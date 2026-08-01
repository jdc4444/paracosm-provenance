#!/usr/bin/env python3
"""Build an exact C4D file inventory for the two production Dropbox roots."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOTS = (
    (
        "AS Finishing",
        Path(
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
            "Absolutely/AS/0 Finishing"
        ),
    ),
    (
        "SG",
        Path(
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
            "Absolutely/SG"
        ),
    ),
)

EXCLUDED_DIRECTORIES = {".git", ".cache", "node_modules", "__pycache__"}

RELEVANT_WINDOWS = (
    ("ND final CU revision era", "01 ND", "2026-02-24", "2026-03-01"),
    ("NTH February source era", "02 NTH", "2026-02-12", "2026-02-19"),
    ("NTH walk/run revision era", "02 NTH", "2026-03-19", "2026-03-22"),
    ("NTH late finishing era", "02 NTH", "2026-04-28", "2026-05-08"),
    ("TH final horses/freezer era", "03 TH", "2026-04-16", "2026-05-10"),
    ("NA March render era", "04 NA", "2026-03-01", "2026-03-17"),
    ("NA April/May LayDown era", "04 NA", "2026-04-16", "2026-05-02"),
    (
        "IJDKYY carousel revision era",
        "06 IJDKYY",
        "2026-03-11",
        "2026-03-15",
    ),
    (
        "IJDKYY final finishing era",
        "06 IJDKYY",
        "2026-04-06",
        "2026-04-22",
    ),
)


def local_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat()


def utc_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def iter_c4d(root: Path):
    for directory, child_directories, filenames in os.walk(root):
        child_directories[:] = [
            item
            for item in child_directories
            if item not in EXCLUDED_DIRECTORIES
        ]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.casefold() == ".c4d":
                yield path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "public"
        / "data"
        / "state.json",
    )
    args = parser.parse_args()

    state = json.loads(args.state.read_text(encoding="utf-8"))
    indexed_paths = {
        str(Path(item["path"]).expanduser().resolve())
        for item in state.get("assets", [])
        if item.get("kind") == "cinema4d"
    }

    records = []
    for label, root in ROOTS:
        root = root.expanduser().resolve()
        for path in iter_c4d(root):
            resolved = path.resolve()
            stat = resolved.stat()
            relative = resolved.relative_to(root)
            chapter = (
                relative.parts[1]
                if label == "AS Finishing"
                and len(relative.parts) > 1
                and relative.parts[0] == "02 Projects"
                else None
            )
            modified_local = local_timestamp(stat.st_mtime)
            records.append(
                {
                    "root": label,
                    "rootPath": str(root),
                    "chapter": chapter,
                    "relativePath": str(relative),
                    "name": resolved.name,
                    "path": str(resolved),
                    "sizeBytes": stat.st_size,
                    "allocatedBytes": stat.st_blocks * 512,
                    "modifiedAt": modified_local,
                    "modifiedAtUtc": utc_timestamp(stat.st_mtime),
                    "modifiedDate": modified_local[:10],
                    "modifiedMonth": modified_local[:7],
                    "codexGenerated": "_codex_" in str(relative).casefold(),
                    "indexedInAtlas": str(resolved) in indexed_paths,
                    "readable": os.access(resolved, os.R_OK),
                }
            )
    records.sort(
        key=lambda item: (
            item["root"],
            item["relativePath"].casefold(),
        )
    )
    live_paths = {item["path"] for item in records}
    indexed_under_roots = {
        path
        for path in indexed_paths
        if any(
            path == str(root.resolve())
            or path.startswith(str(root.resolve()) + os.sep)
            for _label, root in ROOTS
        )
    }

    root_counts = Counter(item["root"] for item in records)
    chapter_counts = Counter(
        item["chapter"] for item in records if item["chapter"]
    )
    month_counts = Counter(item["modifiedMonth"] for item in records)
    relevant_windows = []
    for label, chapter, start, end in RELEVANT_WINDOWS:
        matching = [
            item["path"]
            for item in records
            if item["root"] == "AS Finishing"
            and item["chapter"] == chapter
            and start <= item["modifiedDate"] < end
            and not item["codexGenerated"]
        ]
        relevant_windows.append(
            {
                "label": label,
                "root": "AS Finishing",
                "chapter": chapter,
                "startInclusive": start,
                "endExclusive": end,
                "count": len(matching),
                "paths": matching,
            }
        )

    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Live filesystem walk of both production Dropbox roots; no source "
            "file was opened, hydrated, modified, or saved."
        ),
        "stateGeneratedAt": state.get("generatedAt"),
        "roots": [
            {"label": label, "path": str(root.resolve())}
            for label, root in ROOTS
        ],
        "summary": {
            "c4dFiles": len(records),
            "byRoot": dict(sorted(root_counts.items())),
            "byChapter": dict(sorted(chapter_counts.items())),
            "byModifiedMonth": dict(sorted(month_counts.items())),
            "codexGenerated": sum(
                item["codexGenerated"] for item in records
            ),
            "unreadable": sum(not item["readable"] for item in records),
            "indexedInAtlas": sum(
                item["indexedInAtlas"] for item in records
            ),
            "missingFromAtlas": len(live_paths - indexed_under_roots),
            "staleAtlasEntries": len(indexed_under_roots - live_paths),
        },
        "missingFromAtlas": sorted(live_paths - indexed_under_roots),
        "staleAtlasEntries": sorted(indexed_under_roots - live_paths),
        "relevantDateWindows": relevant_windows,
        "files": records,
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(records[0]) if records else []
    with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
