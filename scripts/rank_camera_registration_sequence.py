#!/usr/bin/env python3
"""Rank a render sequence by geometric registration to one camera proof.

This intentionally ignores color similarity.  It detects local SIFT features,
solves a RANSAC homography from every sequence frame into the proof, and ranks
frames by inlier support plus how closely the solved transform resembles the
expected resolution-only scale.  It is useful when a grey C4D proof omits an
offline character but still contains enough static scene geometry to identify
the camera/time used by a retained production render.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def image_paths(directory: Path) -> list[Path]:
    suffixes = {".exr", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.casefold() in suffixes
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--sequence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--ratio-threshold", type=float, default=0.78)
    parser.add_argument("--ransac-threshold", type=float, default=3.0)
    args = parser.parse_args()

    proof_path = args.proof.expanduser().resolve()
    sequence_dir = args.sequence_dir.expanduser().resolve()
    proof = cv2.imread(str(proof_path), cv2.IMREAD_COLOR)
    if proof is None:
        raise FileNotFoundError(proof_path)
    proof_gray = cv2.cvtColor(proof, cv2.COLOR_BGR2GRAY)
    sift = cv2.SIFT_create(nfeatures=3000)
    proof_points, proof_descriptors = sift.detectAndCompute(proof_gray, None)
    if proof_descriptors is None:
        raise RuntimeError("proof has no usable SIFT descriptors")
    matcher = cv2.BFMatcher()
    records: list[dict[str, object]] = []

    for path in image_paths(sequence_dir):
        image = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_4)
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        points, descriptors = sift.detectAndCompute(gray, None)
        if descriptors is None:
            continue
        pairs = matcher.knnMatch(descriptors, proof_descriptors, k=2)
        good = [
            first
            for first, second in pairs
            if first.distance < args.ratio_threshold * second.distance
        ]
        record: dict[str, object] = {
            "path": str(path),
            "reliableMatches": len(good),
            "ransacInliers": 0,
            "ransacInlierRatio": 0.0,
            "maximumScaleError": None,
            "maximumPerspectiveTerm": None,
            "score": 0.0,
        }
        if len(good) >= 4:
            source = np.float32(
                [points[item.queryIdx].pt for item in good]
            ).reshape(-1, 1, 2)
            target = np.float32(
                [proof_points[item.trainIdx].pt for item in good]
            ).reshape(-1, 1, 2)
            homography, inlier_mask = cv2.findHomography(
                source,
                target,
                cv2.RANSAC,
                args.ransac_threshold,
            )
            if homography is not None and inlier_mask is not None:
                inliers = int(inlier_mask.sum())
                inlier_ratio = inliers / len(good)
                # IMREAD_REDUCED_COLOR_4 makes the sequence candidate one
                # quarter size.  The expected candidate-to-proof scale must
                # therefore use that decoded size, not the on-disk image size.
                expected_scale_x = proof.shape[1] / image.shape[1]
                expected_scale_y = proof.shape[0] / image.shape[0]
                scale_x = float(np.linalg.norm(homography[:2, 0]))
                scale_y = float(np.linalg.norm(homography[:2, 1]))
                scale_error = max(
                    abs(scale_x - expected_scale_x),
                    abs(scale_y - expected_scale_y),
                )
                perspective = max(
                    abs(float(homography[2, 0])),
                    abs(float(homography[2, 1])),
                )
                geometric_penalty = (
                    min(scale_error / 0.2, 3.0)
                    + min(perspective / 0.001, 3.0)
                )
                score = (
                    inliers
                    * (0.35 + 0.65 * inlier_ratio)
                    / (1.0 + geometric_penalty)
                )
                record.update(
                    {
                        "ransacInliers": inliers,
                        "ransacInlierRatio": round(inlier_ratio, 6),
                        "maximumScaleError": round(scale_error, 8),
                        "maximumPerspectiveTerm": round(perspective, 10),
                        "score": round(float(score), 6),
                        "homography": [
                            [round(float(value), 9) for value in row]
                            for row in homography
                        ],
                    }
                )
        records.append(record)

    records.sort(
        key=lambda item: (
            float(item["score"]),
            int(item["ransacInliers"]),
            float(item["ransacInlierRatio"]),
        ),
        reverse=True,
    )
    payload = {
        "schemaVersion": 1,
        "proof": str(proof_path),
        "sequenceDirectory": str(sequence_dir),
        "candidateCount": len(records),
        "ranking": records[: max(1, args.limit)],
    }
    rendered = json.dumps(payload, indent=2) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
