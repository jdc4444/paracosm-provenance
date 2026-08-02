#!/usr/bin/env python3
"""Apply a measured integer center crop and optional reference-sized resize."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--crop-width", required=True, type=int)
    parser.add_argument("--crop-height", required=True, type=int)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()

    with Image.open(args.input) as source_image:
        source = source_image.convert("RGB")
        source_width, source_height = source.size

        if args.crop_width > source_width or args.crop_height > source_height:
            parser.error(
                f"crop {args.crop_width}x{args.crop_height} exceeds "
                f"source {source_width}x{source_height}"
            )

        left = (source_width - args.crop_width) // 2
        top = (source_height - args.crop_height) // 2
        crop_box = (
            left,
            top,
            left + args.crop_width,
            top + args.crop_height,
        )
        result = source.crop(crop_box)

    reference_size = None
    if args.reference:
        with Image.open(args.reference) as reference_image:
            reference_size = reference_image.size
        if result.size != reference_size:
            result = result.resize(reference_size, Image.Resampling.LANCZOS)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.save(args.output)

    payload = {
        "status": "created",
        "input": str(args.input.resolve()),
        "sourceSize": [source_width, source_height],
        "cropBox": list(crop_box),
        "cropSize": [args.crop_width, args.crop_height],
        "operation": "integer_center_crop",
        "reference": str(args.reference.resolve()) if args.reference else None,
        "referenceSize": list(reference_size) if reference_size else None,
        "resize": "Pillow Image.Resampling.LANCZOS" if reference_size else None,
        "output": str(args.output.resolve()),
        "outputSize": list(result.size),
    }

    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(json.dumps(payload, indent=2) + "\n")

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
