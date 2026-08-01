#!/usr/bin/env python3
"""Merge an isolated c4dpy dependency result into the main audit archive."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from probe_c4d_dependencies import summarize_collection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "c4d-dependency-export.json",
    )
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    project_path = str(Path(source["project"]).expanduser().resolve())
    take = source.get("take") or "Main"
    collection = {
        "collectorResult": source.get("collectorResult"),
        "assets": source.get("dependencies", []),
    }
    summary = summarize_collection(collection)
    project = {
        "projectPath": project_path,
        "document": Path(project_path).name,
        "documentPath": str(Path(project_path).parent),
        "activeTake": take,
        "requestedTakes": [take],
        "fullScene": summary,
        "takes": {take: {**summary, "found": True}},
        "objectInventory": {
            "total": 0,
            "renderEnabled": 0,
            "characterSignals": 0,
            "characterExamples": [],
            "note": (
                "Object inventory is recorded separately in "
                "c4d-scene-state-audit.json."
            ),
        },
        "open": False,
        "temporaryFullLoad": True,
        "auditSource": str(args.input),
    }

    archive = (
        json.loads(args.archive.read_text(encoding="utf-8"))
        if args.archive.exists()
        else {"schemaVersion": 1, "projects": []}
    )
    previous = next(
        (
            item
            for item in archive.get("projects", [])
            if str(item.get("projectPath") or "") == project_path
            and not item.get("error")
        ),
        None,
    )
    if previous:
        project["takes"] = {
            **previous.get("takes", {}),
            take: {**summary, "found": True},
        }
        project["requestedTakes"] = sorted(project["takes"])
        project["fullScene"] = previous.get("fullScene") or summary
        project["objectInventory"] = (
            previous.get("objectInventory") or project["objectInventory"]
        )
    projects = [
        item
        for item in archive.get("projects", [])
        if str(item.get("projectPath") or "") != project_path
    ]
    projects.append(project)
    projects.sort(key=lambda item: str(item.get("projectPath") or ""))
    archive.update(
        {
            "schemaVersion": 1,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "method": (
                "Cinema 4D GetAllAssetsNew audits; GUI bridge records plus "
                "isolated c4dpy take-evaluated fallbacks"
            ),
            "projects": projects,
        }
    )
    args.archive.write_text(json.dumps(archive, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "project": project_path,
                "take": take,
                "status": summary["status"],
                "dependencies": summary["dependencyCount"],
                "linked": summary["linkedCount"],
                "missing": summary["missingCount"],
                "renderCriticalMissing": summary[
                    "renderCriticalMissingCount"
                ],
                "archive": str(args.archive),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
