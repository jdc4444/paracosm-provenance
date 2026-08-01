#!/usr/bin/env python3
"""Build labeled medium/close-up sheets for Houdini floor v4 review."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "data/wardrobe-cloth-simulation-plan-20260728.json"
OUTPUT_DIR = (
    ROOT
    / "public/archive/objects/3d/simulations/houdini-floor-v4-review"
)


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ImportError):
            continue
    return ImageFont.load_default()


def panel(path: Path, width: int, height: int) -> Image.Image:
    with Image.open(path) as source:
        contained = ImageOps.contain(
            source.convert("RGB"),
            (width, height),
            Image.Resampling.LANCZOS,
        )
    result = Image.new("RGB", (width, height), "#171513")
    result.paste(
        contained,
        ((width - contained.width) // 2, (height - contained.height) // 2),
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids")
    parser.add_argument("--accepted-campaign")
    parser.add_argument("--label", default="batch")
    args = parser.parse_args()
    variants_by_id: dict[str, str] = {}
    if args.accepted_campaign:
        campaign = json.loads((ROOT / args.accepted_campaign).read_text())
        accepted_records = [
            record for record in campaign["records"] if record["accepted"]
        ]
        object_ids = [record["objectId"] for record in accepted_records]
        variants_by_id = {
            record["objectId"]: record.get(
                "proofVariant",
                "houdini-floor-v4",
            )
            for record in accepted_records
        }
    elif args.ids:
        object_ids = [item for item in args.ids.split(",") if item]
    else:
        parser.error("--ids or --accepted-campaign is required")
    plan = json.loads(PLAN_PATH.read_text())
    plan_by_id = {item["objectId"]: item for item in plan["objects"]}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for object_id in object_ids:
        item = plan_by_id[object_id]
        variant = variants_by_id.get(object_id, "houdini-floor-v4")
        directory = (
            ROOT
            / f"public/archive/objects/3d/simulations/{object_id}/{variant}"
        )
        stem = f"{object_id}-{variant}"
        records.append(
            {
                "objectId": object_id,
                "name": item["name"],
                "materialClass": item["materialClass"],
                "medium": directory / f"{stem}-medium.png",
                "closeup": directory / f"{stem}-closeup.png",
            }
        )

    sheets = []
    panel_width = 560
    panel_height = 560
    gutter = 18
    header_height = 80
    label_height = 76
    row_height = panel_height + label_height
    for start in range(0, len(records), 4):
        subset = records[start : start + 4]
        page = Image.new(
            "RGB",
            (
                panel_width * 2 + gutter * 3,
                header_height + row_height * len(subset) + gutter,
            ),
            "#0d0c0b",
        )
        draw = ImageDraw.Draw(page)
        draw.text(
            (gutter, 14),
            f"Houdini floor v4 · {args.label} · sheet {len(sheets) + 1}",
            fill="#f0ece6",
            font=font(30),
        )
        draw.text(
            (gutter, 50),
            "Medium proof  |  construction close-up",
            fill="#aaa198",
            font=font(17),
        )
        for row, record in enumerate(subset):
            y = header_height + row * row_height
            page.paste(panel(record["medium"], panel_width, panel_height), (gutter, y))
            page.paste(
                panel(record["closeup"], panel_width, panel_height),
                (gutter * 2 + panel_width, y),
            )
            label_y = y + panel_height + 8
            draw.text(
                (gutter, label_y),
                record["name"],
                fill="#f0ece6",
                font=font(22),
            )
            draw.text(
                (gutter, label_y + 29),
                f'{record["objectId"]} · {record["materialClass"]}',
                fill="#aaa198",
                font=font(16),
            )
        output = OUTPUT_DIR / f"{args.label}-{len(sheets) + 1:02d}.jpg"
        page.save(output, quality=92)
        sheets.append("/" + output.relative_to(ROOT / "public").as_posix())

    manifest = {
        "schemaVersion": 1,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "label": args.label,
        "recordCount": len(records),
        "sheets": sheets,
        "records": [
            {
                **record,
                "medium": "/" + record["medium"].relative_to(ROOT / "public").as_posix(),
                "closeup": "/" + record["closeup"].relative_to(ROOT / "public").as_posix(),
            }
            for record in records
        ],
    }
    manifest_path = OUTPUT_DIR / f"{args.label}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
