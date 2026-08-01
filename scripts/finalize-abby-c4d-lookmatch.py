"""Align and validate a new Redshift render against Abby's archived look target.

The input render must come from the canonical C4D scene with its original
Redshift materials and lights. This script recovers the small historical camera
reframe, writes a browser-ready PNG, and refuses to publish a result that does
not meet the measured near-pixel match gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def metrics(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    difference = reference.astype(np.float32) - candidate.astype(np.float32)
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY).ravel()
    candidate_gray = cv2.cvtColor(candidate, cv2.COLOR_BGR2GRAY).ravel()
    return {
        "meanAbsoluteRgbError": float(np.mean(np.abs(difference))),
        "rootMeanSquareRgbError": float(np.sqrt(np.mean(difference**2))),
        "psnrDb": float(cv2.PSNR(reference, candidate)),
        "grayscaleCorrelation": float(
            np.corrcoef(reference_gray, candidate_gray)[0, 1]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-correlation", type=float, default=0.997)
    parser.add_argument("--max-mean-error", type=float, default=1.5)
    args = parser.parse_args()

    render_path = args.render.expanduser().resolve()
    reference_path = args.reference.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    rendered = cv2.imread(str(render_path), cv2.IMREAD_COLOR)
    reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    if rendered is None:
        raise RuntimeError(f"Could not read new render {render_path}")
    if reference is None:
        raise RuntimeError(f"Could not read reference {reference_path}")
    if rendered.shape != reference.shape:
        raise RuntimeError(
            f"Input shapes differ: render={rendered.shape}, "
            f"reference={reference.shape}"
        )

    sift = cv2.SIFT_create(nfeatures=12000, contrastThreshold=0.015)
    reference_points, reference_descriptors = sift.detectAndCompute(
        cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), None
    )
    render_points, render_descriptors = sift.detectAndCompute(
        cv2.cvtColor(rendered, cv2.COLOR_BGR2GRAY), None
    )
    matches = cv2.BFMatcher().knnMatch(
        render_descriptors, reference_descriptors, k=2
    )
    good_matches = [
        first
        for first, second in matches
        if first.distance < 0.75 * second.distance
    ]
    source_points = np.float32(
        [render_points[item.queryIdx].pt for item in good_matches]
    )
    target_points = np.float32(
        [reference_points[item.trainIdx].pt for item in good_matches]
    )
    transform, inlier_mask = cv2.findHomography(
        source_points,
        target_points,
        cv2.RANSAC,
        3.0,
        maxIters=20000,
        confidence=0.9999,
    )
    if transform is None or inlier_mask is None:
        raise RuntimeError("Could not recover the archived camera reframe")

    height, width = reference.shape[:2]
    aligned = cv2.warpPerspective(
        rendered,
        transform,
        (width, height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )
    result_metrics = metrics(reference, aligned)
    if (
        result_metrics["grayscaleCorrelation"] < args.min_correlation
        or result_metrics["meanAbsoluteRgbError"] > args.max_mean_error
    ):
        raise RuntimeError(
            "Look-match gate failed: "
            + json.dumps(result_metrics, separators=(",", ":"))
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(
        str(output_path),
        aligned,
        [cv2.IMWRITE_PNG_COMPRESSION, 7],
    ):
        raise RuntimeError(f"Could not write {output_path}")

    payload = {
        "render": str(render_path),
        "reference": str(reference_path),
        "output": str(output_path),
        "resolution": [width, height],
        "featureMatches": len(good_matches),
        "inliers": int(inlier_mask.sum()),
        "homography": transform.tolist(),
        **result_metrics,
    }
    print(
        "ABBY_C4D_LOOKMATCH_FINALIZED="
        + json.dumps(payload, separators=(",", ":")),
        flush=True,
    )


if __name__ == "__main__":
    main()
