#!/usr/bin/env python3
"""Measure background registration between two retained render frames.

This is useful when the character/cache state changes between renders but the
question is whether the saved C4D camera changed.  A caller can mask the
character and compare the remaining static scene.  The result is evidence,
not a substitute for a C4D/Redshift proof.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def parse_rect(value: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("mask must be X1,Y1,X2,Y2")
    return tuple(parts)  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--mask", action="append", type=parse_rect, default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ratio-threshold", type=float, default=0.72)
    parser.add_argument("--ransac-threshold", type=float, default=2.0)
    args = parser.parse_args()

    reference = cv2.imread(str(args.reference.expanduser().resolve()))
    comparison = cv2.imread(str(args.comparison.expanduser().resolve()))
    if reference is None:
        raise FileNotFoundError(args.reference)
    if comparison is None:
        raise FileNotFoundError(args.comparison)

    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    comparison_gray = cv2.cvtColor(comparison, cv2.COLOR_BGR2GRAY)
    mask = np.full(reference_gray.shape, 255, dtype=np.uint8)
    for x1, y1, x2, y2 in args.mask:
        cv2.rectangle(mask, (x1, y1), (x2, y2), 0, -1)

    sift = cv2.SIFT_create(nfeatures=4000)
    reference_points, reference_descriptors = sift.detectAndCompute(
        reference_gray, mask
    )
    comparison_points, comparison_descriptors = sift.detectAndCompute(
        comparison_gray, None
    )
    if reference_descriptors is None or comparison_descriptors is None:
        raise RuntimeError("not enough image features for registration")

    matches = cv2.BFMatcher().knnMatch(
        reference_descriptors, comparison_descriptors, k=2
    )
    good = [
        first
        for first, second in matches
        if first.distance < args.ratio_threshold * second.distance
    ]
    if len(good) < 4:
        raise RuntimeError("fewer than four reliable feature matches")

    source = np.float32(
        [reference_points[item.queryIdx].pt for item in good]
    ).reshape(-1, 1, 2)
    target = np.float32(
        [comparison_points[item.trainIdx].pt for item in good]
    ).reshape(-1, 1, 2)
    homography, inlier_mask = cv2.findHomography(
        source, target, cv2.RANSAC, args.ransac_threshold
    )
    if homography is None or inlier_mask is None:
        raise RuntimeError("homography solve failed")

    scale_x = float(np.linalg.norm(homography[:2, 0]))
    scale_y = float(np.linalg.norm(homography[:2, 1]))
    expected_scale_x = comparison.shape[1] / reference.shape[1]
    expected_scale_y = comparison.shape[0] / reference.shape[0]
    inliers = int(inlier_mask.sum())
    inlier_ratio = inliers / len(good)
    scale_error = max(
        abs(scale_x - expected_scale_x),
        abs(scale_y - expected_scale_y),
    )
    perspective_terms = [
        float(homography[2, 0]),
        float(homography[2, 1]),
    ]
    consistent = (
        inliers >= 30
        and inlier_ratio >= 0.65
        and scale_error <= 0.02
        and max(abs(item) for item in perspective_terms) <= 0.00005
    )
    payload = {
        "schemaVersion": 1,
        "reference": str(args.reference.expanduser().resolve()),
        "comparison": str(args.comparison.expanduser().resolve()),
        "referenceSize": {
            "width": reference.shape[1],
            "height": reference.shape[0],
        },
        "comparisonSize": {
            "width": comparison.shape[1],
            "height": comparison.shape[0],
        },
        "excludedReferenceRectangles": [list(item) for item in args.mask],
        "referenceKeypoints": len(reference_points),
        "comparisonKeypoints": len(comparison_points),
        "reliableMatches": len(good),
        "ransacInliers": inliers,
        "ransacInlierRatio": round(inlier_ratio, 6),
        "homography": [
            [round(float(value), 9) for value in row]
            for row in homography
        ],
        "measuredScale": {
            "x": round(scale_x, 9),
            "y": round(scale_y, 9),
        },
        "expectedResolutionScale": {
            "x": round(expected_scale_x, 9),
            "y": round(expected_scale_y, 9),
        },
        "maximumScaleError": round(scale_error, 9),
        "perspectiveTerms": perspective_terms,
        "backgroundCameraRegistration": (
            "consistent" if consistent else "not_confirmed"
        ),
        "interpretation": (
            "Static-background features register as resolution-only scaling; "
            "the camera is consistent even though character/cache state may "
            "differ."
            if consistent
            else "Registration does not prove an unchanged camera."
        ),
    }
    rendered = json.dumps(payload, indent=2) + "\n"
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
