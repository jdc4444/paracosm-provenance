#!/usr/bin/env python3
"""Rank source frames after one exact integer center-crop transform."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def comparison(candidate: np.ndarray, reference: np.ndarray) -> dict[str, object]:
    delta = candidate - reference
    correlations: list[float | None] = []
    for channel in range(3):
        left = candidate[..., channel].reshape(-1)
        right = reference[..., channel].reshape(-1)
        if np.std(left) == 0 or np.std(right) == 0:
            correlations.append(None)
        else:
            correlations.append(float(np.corrcoef(left, right)[0, 1]))
    return {
        "meanAbsoluteError": float(np.mean(np.abs(delta))),
        "rootMeanSquareError": float(np.sqrt(np.mean(np.square(delta)))),
        "perChannelCorrelation": correlations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-pattern", required=True)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--first-frame", required=True, type=int)
    parser.add_argument("--last-frame", required=True, type=int)
    parser.add_argument("--crop-width", required=True, type=int)
    parser.add_argument("--crop-height", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.last_frame < args.first_frame:
        parser.error("--last-frame must be at least --first-frame")

    with Image.open(args.reference) as reference_image:
        reference_rgb = reference_image.convert("RGB")
    reference_pixels = np.asarray(reference_rgb, dtype=np.float32) / 255.0

    records = []
    crop_box = None
    for frame in range(args.first_frame, args.last_frame + 1):
        candidate_path = Path(args.candidate_pattern.format(frame=frame))
        with Image.open(candidate_path) as candidate_image:
            source = candidate_image.convert("RGB")
        source_width, source_height = source.size
        if args.crop_width > source_width or args.crop_height > source_height:
            parser.error(
                f"crop exceeds frame {frame} source size {source.size}"
            )
        left = (source_width - args.crop_width) // 2
        top = (source_height - args.crop_height) // 2
        current_crop_box = (
            left,
            top,
            left + args.crop_width,
            top + args.crop_height,
        )
        if crop_box is None:
            crop_box = current_crop_box
        elif crop_box != current_crop_box:
            raise RuntimeError("candidate source sizes changed across frames")
        candidate = source.crop(current_crop_box).resize(
            reference_rgb.size, Image.Resampling.LANCZOS
        )
        candidate_pixels = np.asarray(candidate, dtype=np.float32) / 255.0
        records.append(
            {
                "frame": frame,
                "path": str(candidate_path.resolve()),
                **comparison(candidate_pixels, reference_pixels),
            }
        )

    records.sort(key=lambda item: (item["meanAbsoluteError"], item["frame"]))
    payload = {
        "schemaVersion": 1,
        "reference": str(args.reference.resolve()),
        "candidatePattern": args.candidate_pattern,
        "frameRange": [args.first_frame, args.last_frame],
        "sourceSize": [source_width, source_height],
        "cropBox": list(crop_box) if crop_box else None,
        "cropSize": [args.crop_width, args.crop_height],
        "outputSize": list(reference_rgb.size),
        "resize": "Pillow Image.Resampling.LANCZOS",
        "selectionMetric": "minimum meanAbsoluteError",
        "selectedFrame": records[0]["frame"],
        "selectedComparison": records[0],
        "rankedComparisons": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
