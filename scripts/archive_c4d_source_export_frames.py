#!/usr/bin/env python3
"""Archive exact export frames when the canonical raw-render link is false."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "public" / "archive" / "c4d-source-export-frames-20260726"
MANIFEST = ROOT / "data" / "c4d-source-export-frames-20260726.json"

OVERRIDES = [
    {
        "cutId": "CUT-011",
        "exportPath": (
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
            "JD/11 Color/underwatercloseups.mov"
        ),
        "exportFrame": 240,
        "exportFrameRate": 24,
        "resolveTimeline": "Natural Disaster 4 copy 1",
        "resolveTimelineIndex": 12,
        "resolveTrack": 2,
        "resolveSourceInterval": [219, 270],
        "sourceProjectCandidates": [
            (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/SG/C4D/ND_Underwater_01_v001.c4d"
            ),
            (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/SG/C4D/ND_Underwater_01_v001 - Copy.c4d"
            ),
        ],
        "sourceProjectTargetFrame": 382,
        "status": "export_frame_authoritative_raw_render_link_false",
        "evidence": (
            "Natural Disaster 4 copy 1 uses frames 219-270 of "
            "underwatercloseups.mov on its upper picture track, and final "
            "CUT-011 matches frame 240 inside that exact interval. "
            "The linked 0126 ND_Underwater_01_v001 image sequence contains "
            "the CUT-010 top-down pass and does not contain this close-up."
        ),
    }
]


def public_path(path: Path) -> str:
    return "/" + path.resolve().relative_to(ROOT / "public").as_posix()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for item in OVERRIDES:
        source = Path(item["exportPath"]).expanduser().resolve()
        output = output_dir / f"{item['cutId']}.png"
        record = {
            **item,
            "exportPath": str(source),
            "outputPath": str(output),
            "publicPath": public_path(output),
        }
        if not source.exists():
            record["archiveStatus"] = "export_missing"
            records.append(record)
            continue
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"select=eq(n\\,{int(item['exportFrame'])})",
            "-frames:v",
            "1",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        record["archiveStatus"] = (
            "archived"
            if result.returncode == 0 and output.exists()
            else "archive_failed"
        )
        if result.returncode != 0:
            record["error"] = result.stderr.strip()
        records.append(record)

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Exact read-only export frames used only where the current "
            "canonical raw-render link is proven false or incomplete."
        ),
        "records": records,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"records": len(records)}, indent=2))
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
