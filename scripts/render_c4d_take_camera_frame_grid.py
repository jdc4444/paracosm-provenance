#!/usr/bin/env python3
"""Render a saved take's exact effective camera across candidate frames."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from render_c4d_camera_proofs import render_project_c4dpy


ROOT = Path(__file__).resolve().parents[1]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def public_path(path: Path) -> str:
    return "/" + path.resolve().relative_to(ROOT / "public").as_posix()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cut-id", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--take", required=True)
    parser.add_argument("--frame", type=int, action="append", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_dir = (
        ROOT
        / "public"
        / "archive"
        / "camera-take-frame-grids-20260726"
        / args.cut_id
        / slug(args.take)
    )
    records = []
    for frame in args.frame:
        output = output_dir / f"f{frame:06d}.png"
        records.append(
            {
                "sourceId": (
                    f"{args.cut_id}__take_{slug(args.take)}__f{frame:06d}"
                ),
                "cutId": args.cut_id,
                "targetFrame": frame,
                "projectPath": str(project),
                # Blank requested camera deliberately invokes the exact
                # effective camera saved in the requested take.
                "cameraName": "",
                "cameraTake": args.take,
                "cameraObject": {},
                "outputPath": str(output),
                "publicPath": public_path(output),
                "status": "pending",
            }
        )
    results = render_project_c4dpy(
        project,
        records,
        width=480,
        height=270,
        timeout=args.timeout,
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Read-only render of the exact effective camera and visibility "
            "state saved in one C4D take across candidate source frames."
        ),
        "cutId": args.cut_id,
        "projectPath": str(project),
        "take": args.take,
        "records": results,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "records": len(results),
                "rendered": sum(
                    item.get("status") == "rendered" for item in results
                ),
            },
            indent=2,
        )
    )
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
