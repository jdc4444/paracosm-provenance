#!/usr/bin/env python3
"""Build source-render versus C4D camera-proof comparison sheets."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from render_c4d_camera_candidate_sweep import image_metrics


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FRAMES = ROOT / "data" / "c4d-source-frame-archive-20260726.json"
SOURCE_EXPORT_FRAMES = (
    ROOT / "data" / "c4d-source-export-frames-20260726.json"
)
PRIMARY_PROOFS = (
    ROOT / "data" / "c4d-camera-proof-renders-corrected-20260726.json"
)
STATE_PATH = ROOT / "public" / "data" / "state.json"
OUTPUT_DIR = (
    ROOT / "public" / "archive" / "c4d-source-camera-comparisons-20260726"
)
MANIFEST = (
    ROOT / "data" / "c4d-source-camera-comparisons-20260726.json"
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def public_path(path: Path) -> str:
    return "/" + path.resolve().relative_to(ROOT / "public").as_posix()


def pair_sheet(
    cut_id: str,
    thumbnail: Path | None,
    source: Path,
    proof: Path | None,
    camera_label: str,
    output: Path,
) -> None:
    width, height, header = 480, 270, 26
    page = Image.new("RGB", (width * 3, height + header), "#090909")
    font = ImageFont.load_default()
    entries = [
        (thumbnail, f"{cut_id} · FINAL CUT"),
        (source, f"{cut_id} · SOURCE RENDER"),
        (
            proof,
            f"{cut_id} · {camera_label}"
            if proof
            else f"{cut_id} · NO CAMERA PROOF",
        ),
    ]
    for index, (path, label) in enumerate(entries):
        if path is not None and path.exists():
            with Image.open(path) as image:
                panel = ImageOps.fit(
                    image.convert("RGB"),
                    (width, height),
                    Image.Resampling.LANCZOS,
                )
        else:
            panel = Image.new("RGB", (width, height), "#111111")
        x = index * width
        page.paste(panel, (x, 0))
        draw = ImageDraw.Draw(page)
        draw.text(
            (x + 7, height + 8),
            label[:72],
            fill="#d7d2c8",
            font=font,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    page.save(output, quality=90)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-frames", type=Path, default=SOURCE_FRAMES)
    parser.add_argument(
        "--source-export-frames",
        type=Path,
        default=SOURCE_EXPORT_FRAMES,
    )
    parser.add_argument("--primary-proofs", type=Path, default=PRIMARY_PROOFS)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()

    sources = {
        str(item["cutId"]): item
        for item in load(args.source_frames).get("records", [])
    }
    if args.source_export_frames.exists():
        for item in load(args.source_export_frames).get("records", []):
            if (
                item.get("archiveStatus") == "archived"
                and Path(str(item.get("outputPath") or "")).exists()
            ):
                sources[str(item["cutId"])] = {
                    **item,
                    "status": "archived",
                    "sourceFramePath": item.get("exportPath"),
                    "referenceKind": "source_export_frame",
                }
    proofs = {
        str(cut_id): item
        for item in load(args.primary_proofs).get("proofs", [])
        for cut_id in item.get("cutIds", [])
    }
    thumbnails = {
        str(item["id"]): (
            ROOT / "public" / str(item.get("thumbnail") or "").lstrip("/")
        )
        for item in load(args.state).get("cuts", [])
        if not item.get("isGap")
    }
    records: list[dict[str, Any]] = []
    for cut_id in sorted(sources):
        source = sources[cut_id]
        proof = proofs.get(cut_id) or {}
        source_path = Path(str(source.get("outputPath") or ""))
        proof_path = Path(str(proof.get("outputPath") or ""))
        source_ready = (
            source.get("status") == "archived" and source_path.exists()
        )
        proof_ready = (
            proof.get("status") == "rendered" and proof_path.exists()
        )
        comparison = (
            args.output_dir.expanduser().resolve() / f"{cut_id}.jpg"
        )
        metrics: dict[str, Any] | None = None
        if source_ready and proof_ready:
            try:
                metrics = image_metrics(source_path, proof_path)
            except Exception as error:
                metrics = {"error": f"{type(error).__name__}: {error}"}
        if source_ready:
            pair_sheet(
                cut_id,
                thumbnails.get(cut_id),
                source_path,
                proof_path if proof_ready else None,
                str(
                    proof.get("cameraObjectPath")
                    or proof.get("cameraName")
                    or "C4D CAMERA PROOF"
                ),
                comparison,
            )
        status = (
            "comparison_ready"
            if source_ready and proof_ready
            else "camera_proof_missing"
            if source_ready
            else "source_frame_unresolved"
        )
        records.append(
            {
                "cutId": cut_id,
                "status": status,
                "sourceFramePath": source.get("sourceFramePath"),
                "sourceReferenceKind": source.get(
                    "referenceKind", "raw_render_frame"
                ),
                "sourceReferenceEvidence": source.get("evidence"),
                "sourceImage": (
                    source.get("publicPath") if source_ready else None
                ),
                "canonicalThumbnail": (
                    public_path(thumbnails[cut_id])
                    if cut_id in thumbnails
                    and thumbnails[cut_id].exists()
                    else None
                ),
                "projectPath": proof.get("projectPath"),
                "cameraName": proof.get("cameraName"),
                "cameraObjectPath": proof.get("cameraObjectPath"),
                "cameraProofImage": (
                    proof.get("publicPath") if proof_ready else None
                ),
                "comparisonImage": (
                    public_path(comparison) if source_ready else None
                ),
                "metrics": metrics,
                "manualReviewRequired": True,
            }
        )

    comparison_records = [
        item
        for item in records
        if item.get("status") == "comparison_ready"
        and item.get("comparisonImage")
    ]
    sheets = []
    sheet_width, sheet_height = 1440, 296
    for page_index in range(0, len(comparison_records), 6):
        page_records = comparison_records[page_index : page_index + 6]
        page = Image.new(
            "RGB",
            (sheet_width * 2, sheet_height * 3),
            "#050505",
        )
        for index, record in enumerate(page_records):
            source = (
                ROOT
                / "public"
                / str(record["comparisonImage"]).lstrip("/")
            )
            with Image.open(source) as image:
                panel = ImageOps.fit(
                    image.convert("RGB"),
                    (sheet_width, sheet_height),
                    Image.Resampling.LANCZOS,
                )
            page.paste(
                panel,
                (
                    (index % 2) * sheet_width,
                    (index // 2) * sheet_height,
                ),
            )
        sheet = (
            args.output_dir.expanduser().resolve()
            / f"sheet-{page_index // 6 + 1:02d}.jpg"
        )
        page.save(sheet, quality=88)
        sheets.append(
            {
                "cuts": [item["cutId"] for item in page_records],
                "image": public_path(sheet),
            }
        )

    statuses: dict[str, int] = defaultdict(int)
    for record in records:
        statuses[str(record["status"])] += 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Direct canonical source-render frames compared to read-only C4D "
            "camera proofs. Metrics are triage only; visual confirmation of "
            "camera and assets remains mandatory."
        ),
        "summary": {
            "records": len(records),
            "statuses": dict(statuses),
            "sheets": len(sheets),
        },
        "records": records,
        "sheets": sheets,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
