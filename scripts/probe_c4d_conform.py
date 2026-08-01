#!/usr/bin/env python3
"""Probe active cameras for every C4D project linked to the source conform."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import scan
from probe_c4d_camera import EXPORT_PATH, archive_result, probe_project

MANIFEST_PATH = scan.DATA_DIR / "conform-manifest.json"


def conform_project_paths() -> list[Path]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assets, renders, _ = scan.inventory_assets()
    camera_archive = (
        json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
        if EXPORT_PATH.exists()
        else {"projects": []}
    )
    render_matches, _ = scan.match_render_projects(
        assets, renders, camera_archive
    )
    render_by_path = {
        str(Path(item["path"]).expanduser().resolve()): item for item in renders
    }
    asset_by_id = {item["id"]: item for item in assets}
    paths: set[Path] = set()
    for segment in manifest.get("segments", []):
        source_path = Path(
            str(segment.get("sourceFirstFramePath") or segment.get("sourcePath") or "")
        )
        render = render_by_path.get(str(source_path.expanduser().resolve().parent))
        linked = render_matches.get(render["id"], []) if render else []
        if not linked:
            continue
        asset = asset_by_id.get(linked[0]["assetId"])
        if asset:
            paths.add(Path(asset["path"]).expanduser().resolve())
    return sorted(paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="Reprobe projects already present in the camera archive.",
    )
    args = parser.parse_args()
    archived: set[str] = set()
    if EXPORT_PATH.exists():
        payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
        archived = {
            str(Path(item["projectPath"]).expanduser().resolve())
            for item in payload.get("projects", [])
            if item.get("projectPath")
        }

    paths = conform_project_paths()
    queue = paths if args.all else [path for path in paths if str(path) not in archived]
    failures = []
    for index, project in enumerate(queue, start=1):
        print(f"[{index}/{len(queue)}] {project}", flush=True)
        try:
            result = probe_project(project)
            archive_result(result)
            print(
                f"  camera={result.get('activeCamera')!r} "
                f"take={result.get('activeTake')!r} "
                f"render={result.get('activeRenderData')!r}",
                flush=True,
            )
        except Exception as error:
            failures.append({"projectPath": str(project), "error": str(error)})
            print(f"  ERROR: {error}", flush=True)

    print(
        json.dumps(
            {
                "linkedProjects": len(paths),
                "alreadyArchived": len(paths) - len(queue),
                "probed": len(queue) - len(failures),
                "failed": len(failures),
                "failures": failures,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
