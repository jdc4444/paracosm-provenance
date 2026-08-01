#!/usr/bin/env python3
"""Build labeled Blender-versus-Houdini static cloth proof review sheets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
REVIEW_PATH = ROOT / "data" / "wardrobe-reviewed-cloth-proofs-20260728.json"
BATCH_PATH = ROOT / "data" / "houdini-wardrobe-rescue-batch-20260728.json"
OUTPUT_DIR = (
    ROOT
    / "public"
    / "archive"
    / "objects"
    / "3d"
    / "simulations"
    / "houdini-rescue-review"
)
MANIFEST_PATH = OUTPUT_DIR / "review-sheets.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def public_file(public_path: str) -> Path:
    return ROOT / "public" / public_path.lstrip("/")


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, ImportError):
            continue
    return ImageFont.load_default()


def image_panel(path: Path, width: int, height: int) -> Image.Image:
    if not path.exists():
        panel = Image.new("RGB", (width, height), "#201d1a")
        ImageDraw.Draw(panel).text(
            (18, 18),
            "MISSING",
            fill="#ff8e78",
            font=font(24),
        )
        return panel
    with Image.open(path) as source:
        return ImageOps.contain(
            source.convert("RGB"),
            (width, height),
            Image.Resampling.LANCZOS,
        )


def build_sheet(
    sheet_index: int,
    records: list[dict[str, Any]],
) -> Path:
    panel_width = 440
    panel_height = 440
    gutter = 16
    label_height = 82
    header_height = 86
    row_height = panel_height + label_height
    page_width = gutter * 4 + panel_width * 3
    page_height = header_height + gutter + row_height * len(records)
    page = Image.new("RGB", (page_width, page_height), "#0d0c0b")
    draw = ImageDraw.Draw(page)
    title_font = font(32)
    label_font = font(22)
    small_font = font(17)
    draw.text(
        (gutter, 14),
        f"Houdini Vellum rescue review · sheet {sheet_index}",
        fill="#f0ece6",
        font=title_font,
    )
    draw.text(
        (gutter, 55),
        "Original Blender proof  |  Houdini medium  |  Houdini closeup",
        fill="#a9a198",
        font=small_font,
    )

    for row, record in enumerate(records):
        y = header_height + gutter + row * row_height
        paths = (
            public_file(record["blenderMedium"]),
            public_file(record["houdiniMedium"]),
            public_file(record["houdiniCloseup"]),
        )
        for column, path in enumerate(paths):
            x = gutter + column * (panel_width + gutter)
            panel = image_panel(path, panel_width, panel_height)
            paste_x = x + (panel_width - panel.width) // 2
            paste_y = y + (panel_height - panel.height) // 2
            page.paste(panel, (paste_x, paste_y))
        label_y = y + panel_height + 10
        draw.text(
            (gutter, label_y),
            record["name"],
            fill="#f0ece6",
            font=label_font,
        )
        draw.text(
            (gutter, label_y + 30),
            f'{record["objectId"]} · {record["materialClass"]}',
            fill="#a9a198",
            font=small_font,
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"houdini-rescue-review-{sheet_index:02d}.jpg"
    page.save(output, quality=92)
    return output


def main() -> None:
    review = load(REVIEW_PATH)
    batch = load(BATCH_PATH)
    rescue_by_id = {
        item["objectId"]: item
        for item in review["proofs"]
        if item["status"] == "needs-prep"
    }
    records: list[dict[str, Any]] = []
    for item in batch["objects"]:
        if item["status"] != "succeeded":
            continue
        object_id = item["objectId"]
        old = rescue_by_id[object_id]
        directory = (
            f"/archive/objects/3d/simulations/{object_id}/houdini-vellum-v1"
        )
        stem = f"{object_id}-houdini-vellum-v1"
        records.append(
            {
                "objectId": object_id,
                "name": item["name"],
                "materialClass": item["materialClass"],
                "blenderMedium": old["image"],
                "houdiniMedium": f"{directory}/{stem}-medium.png",
                "houdiniCloseup": f"{directory}/{stem}-closeup.png",
            }
        )

    sheets = []
    for start in range(0, len(records), 4):
        output = build_sheet(len(sheets) + 1, records[start : start + 4])
        sheets.append(
            "/" + output.relative_to(ROOT / "public").as_posix()
        )

    manifest = {
        "schemaVersion": 1,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "reviewMethod": (
            "Labeled side-by-side manual review of the previous Blender "
            "medium proof and the Houdini Vellum medium and closeup proofs."
        ),
        "recordCount": len(records),
        "sheetCount": len(sheets),
        "generatedVideoCount": 0,
        "sheets": sheets,
        "records": records,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
