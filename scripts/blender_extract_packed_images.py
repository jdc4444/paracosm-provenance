#!/usr/bin/env python3
"""Extract selected packed Blender image datablocks without re-encoding them.

Run with Blender so ``bpy`` is available, for example::

    blender --background scene.blend --python scripts/blender_extract_packed_images.py -- \
      --output-dir recovered --map Image_0.001=_baseColorTexture_1.jpg
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence

import bpy


def _script_args(argv: Sequence[str]) -> list[str]:
    if "--" not in argv:
        return []
    return list(argv[argv.index("--") + 1 :])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--map",
        action="append",
        required=True,
        metavar="DATABLOCK=FILENAME",
        help="Packed image datablock and exact output filename.",
    )
    parser.add_argument("--receipt-json")
    args = parser.parse_args(_script_args(sys.argv))

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    for mapping in args.map:
        if "=" not in mapping:
            raise ValueError(f"invalid --map value: {mapping!r}")
        datablock_name, filename = mapping.split("=", 1)
        if not datablock_name or not filename or Path(filename).name != filename:
            raise ValueError(f"unsafe --map value: {mapping!r}")

        image = bpy.data.images.get(datablock_name)
        if image is None:
            raise KeyError(f"image datablock not found: {datablock_name}")
        if image.packed_file is None:
            raise ValueError(f"image datablock is not packed: {datablock_name}")

        data = bytes(image.packed_file.data)
        destination = output_dir / filename
        if destination.exists() and _sha256(destination.read_bytes()) != _sha256(data):
            raise FileExistsError(f"different bytes already exist: {destination}")
        destination.write_bytes(data)
        rows.append(
            {
                "datablock": datablock_name,
                "filename": filename,
                "path": str(destination),
                "bytes": len(data),
                "sha256": _sha256(data),
                "magicHex": data[:12].hex(),
                "dimensions": list(image.size),
            }
        )

    receipt = {
        "schemaVersion": 1,
        "sourceBlend": bpy.data.filepath,
        "blenderVersion": bpy.app.version_string,
        "method": "raw bpy PackedFile bytes; no image decode or re-encode",
        "outputDirectory": str(output_dir),
        "images": rows,
    }
    if args.receipt_json:
        receipt_path = Path(args.receipt_json).expanduser().resolve()
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("PARACOSM_PACKED_IMAGE_EXTRACTION=" + json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
