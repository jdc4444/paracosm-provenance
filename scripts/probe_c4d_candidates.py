#!/usr/bin/env python3
"""Probe every unique Cinema 4D project currently linked by the atlas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from probe_c4d_camera import archive_result, probe_project

APP_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = APP_ROOT / "public" / "data" / "state.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--section",
        action="append",
        help="Limit probing to one or more section codes, such as NA or GG.",
    )
    args = parser.parse_args()
    sections = {value.upper() for value in args.section or []}

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    paths = {
        edge["path"]
        for cut in state.get("cuts", [])
        if not sections or cut.get("sectionCode") in sections
        for edge in cut.get("lineage", [])
        if edge.get("kind") == "cinema4d" and edge.get("path")
    }

    failures = []
    for index, value in enumerate(sorted(paths), start=1):
        project = Path(value)
        print(f"[{index}/{len(paths)}] {project}", flush=True)
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
                "probed": len(paths) - len(failures),
                "failed": len(failures),
                "failures": failures,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
