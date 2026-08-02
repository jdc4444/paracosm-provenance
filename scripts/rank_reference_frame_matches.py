#!/usr/bin/env python3
"""Rank archived render frames against one reference image.

This is a read-only triage helper for finding likely frame offsets and older
render sources. It downsamples candidates before comparison and reports paths;
visual confirmation is still required before a source/camera is promoted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


IMAGE_SUFFIXES = {".exr", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def normalized_correlation(first: np.ndarray, second: np.ndarray) -> float:
    a = first.astype(np.float32).reshape(-1)
    b = second.astype(np.float32).reshape(-1)
    a -= float(a.mean())
    b -= float(b.mean())
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denominator == 0:
        return 1.0 if np.array_equal(a, b) else 0.0
    return float(np.dot(a, b) / denominator)


def load_feature(path: Path, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    image = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_8)
    if image is None:
        raise ValueError(f"Unreadable image: {path}")
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    grey = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    edges = cv2.Laplacian(grey, cv2.CV_32F)
    return grey, edges


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--directory", type=Path, action="append", required=True)
    parser.add_argument(
        "--include-term",
        action="append",
        default=[],
        help="Require at least one case-insensitive term in the full path.",
    )
    parser.add_argument("--exclude-term", action="append", default=[])
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search every image below each supplied directory.",
    )
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--width", type=int, default=160)
    parser.add_argument("--height", type=int, default=90)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    reference = args.reference.expanduser().resolve()
    reference_grey, reference_edges = load_feature(
        reference, args.width, args.height
    )
    exclude_terms = tuple(term.casefold() for term in args.exclude_term)
    include_terms = tuple(term.casefold() for term in args.include_term)
    candidates: list[Path] = []
    for directory in args.directory:
        root = directory.expanduser().resolve()
        paths = root.rglob("*") if args.recursive else root.iterdir()
        candidates.extend(
            path
            for path in paths
            if path.is_file()
            and path.suffix.casefold() in IMAGE_SUFFIXES
            and (
                not include_terms
                or any(term in str(path).casefold() for term in include_terms)
            )
            and not any(
                term in path.name.casefold() for term in exclude_terms
            )
        )

    results = []
    unreadable = []
    for path in sorted(set(candidates)):
        try:
            grey, edges = load_feature(path, args.width, args.height)
        except Exception as error:
            unreadable.append(
                {"path": str(path), "error": f"{type(error).__name__}: {error}"}
            )
            continue
        luminance = normalized_correlation(reference_grey, grey)
        edge = normalized_correlation(reference_edges, edges)
        results.append(
            {
                "path": str(path),
                "luminanceCorrelation": round(luminance, 6),
                "edgeCorrelation": round(edge, 6),
                "score": round((luminance * 0.65) + (edge * 0.35), 6),
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    report = {
        "reference": str(reference),
        "candidateCount": len(candidates),
        "readableCount": len(results),
        "unreadableCount": len(unreadable),
        "top": results[: args.top],
        "unreadable": unreadable[:20],
    }
    output = json.dumps(report, indent=2) + "\n"
    if args.output:
        destination = args.output.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
