#!/usr/bin/env python3
"""Compare two archived render frames without modifying either source file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def correlation(first: np.ndarray, second: np.ndarray) -> float:
    first_values = first.astype(np.float32).reshape(-1)
    second_values = second.astype(np.float32).reshape(-1)
    first_values -= float(first_values.mean())
    second_values -= float(second_values.mean())
    denominator = float(
        np.linalg.norm(first_values) * np.linalg.norm(second_values)
    )
    if denominator == 0:
        return 1.0 if np.array_equal(first, second) else 0.0
    return float(np.dot(first_values, second_values) / denominator)


def compare(first_path: Path, second_path: Path) -> dict[str, object]:
    first = cv2.imread(str(first_path), cv2.IMREAD_UNCHANGED)
    second = cv2.imread(str(second_path), cv2.IMREAD_UNCHANGED)
    if first is None or second is None:
        raise ValueError("Both inputs must be readable image files")
    first_bgr = first[:, :, :3] if first.ndim == 3 else first
    second_bgr = second[:, :, :3] if second.ndim == 3 else second
    height = min(first_bgr.shape[0], second_bgr.shape[0], 720)
    width = min(first_bgr.shape[1], second_bgr.shape[1], 1280)
    first_resized = cv2.resize(
        first_bgr, (width, height), interpolation=cv2.INTER_AREA
    )
    second_resized = cv2.resize(
        second_bgr, (width, height), interpolation=cv2.INTER_AREA
    )
    first_gray = (
        cv2.cvtColor(first_resized, cv2.COLOR_BGR2GRAY)
        if first_resized.ndim == 3
        else first_resized
    )
    second_gray = (
        cv2.cvtColor(second_resized, cv2.COLOR_BGR2GRAY)
        if second_resized.ndim == 3
        else second_resized
    )
    first_edges = cv2.Laplacian(first_gray, cv2.CV_32F)
    second_edges = cv2.Laplacian(second_gray, cv2.CV_32F)
    dynamic_range = max(
        float(np.max(first_gray)),
        float(np.max(second_gray)),
        1.0,
    )
    return {
        "first": str(first_path),
        "second": str(second_path),
        "firstShape": list(first.shape),
        "secondShape": list(second.shape),
        "pixelExact": bool(
            first.shape == second.shape and np.array_equal(first, second)
        ),
        "luminanceCorrelation": round(
            correlation(first_gray, second_gray), 6
        ),
        "edgeCorrelation": round(correlation(first_edges, second_edges), 6),
        "normalizedMeanAbsoluteError": round(
            float(
                np.mean(
                    np.abs(
                        first_gray.astype(np.float32)
                        - second_gray.astype(np.float32)
                    )
                )
                / dynamic_range
            ),
            6,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.first, args.second), indent=2))


if __name__ == "__main__":
    main()
