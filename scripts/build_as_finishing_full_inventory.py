#!/usr/bin/env python3
"""Build a complete, read-only inventory of AS/0 Finishing.

The existing AS chronology is intentionally project-centric. This companion
inventory covers every file and also collapses the two legacy render trees into
image-sequence records with trustworthy frame and filesystem date ranges.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AS_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
    "Absolutely/AS/0 Finishing"
)
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".exr",
    ".tga",
}
SEQUENCE_PATTERN = re.compile(
    r"^(?P<prefix>.*?)(?P<frame>-?\d{3,8})(?P<suffix>\.[^.]+)$"
)
BACKUP_PATTERN = re.compile(
    r"^(?P<source>.+\.c4d)@(?P<timestamp>\d{8}_\d{6})$",
    re.IGNORECASE,
)
CHAPTER_ALIASES = {
    "01 ND": "ND",
    "02 NTH": "NTH",
    "03 TH": "TH",
    "04 NA": "NA",
    "05 GG": "GG",
    "06 IJDKYY": "IJDKYY",
    "ND": "ND",
    "NTH": "NTH",
    "TH": "TH",
    "NA": "NA",
    "GG": "GG",
    "IJDKYY": "IJDKYY",
}
PREFIX_CHAPTERS = {
    "1": "ND",
    "2": "NTH",
    "3": "TH",
    "4": "NA",
    "5": "GG",
    "6": "IJDKYY",
}
RELEVANT_WINDOWS = (
    ("ND final CU revision era", "ND", "2026-02-24", "2026-03-01"),
    ("NTH February source era", "NTH", "2026-02-12", "2026-02-19"),
    ("NTH walk/run render era", "NTH", "2026-03-19", "2026-03-22"),
    ("NTH late finishing era", "NTH", "2026-04-28", "2026-05-08"),
    ("TH final horses/freezer era", "TH", "2026-04-16", "2026-05-10"),
    ("NA March render era", "NA", "2026-03-01", "2026-03-17"),
    ("NA April/May LayDown era", "NA", "2026-04-16", "2026-05-02"),
    ("GG later SG render era", "GG", "2026-01-29", "2026-02-15"),
    ("IJDKYY carousel revision era", "IJDKYY", "2026-03-11", "2026-03-15"),
    ("IJDKYY final finishing era", "IJDKYY", "2026-04-06", "2026-04-22"),
)


def local_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat()


def utc_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def extension_for(path: Path) -> str:
    if BACKUP_PATTERN.match(path.name):
        return ".c4d@timestamp"
    return path.suffix.casefold() or "[no extension]"


def area_for(relative: Path) -> str:
    return relative.parts[0] if relative.parts else "[root]"


def infer_chapter(relative: Path) -> str | None:
    for part in relative.parts:
        if part in CHAPTER_ALIASES:
            return CHAPTER_ALIASES[part]
    name = relative.name.lstrip().casefold()
    if name.startswith("log_"):
        name = name[4:].lstrip()
    match = re.match(r"([1-6])(?:[a-z_ ]|$)", name)
    return PREFIX_CHAPTERS.get(match.group(1)) if match else None


def windows_for(chapter: str | None, modified_date: str) -> list[str]:
    return [
        label
        for label, window_chapter, start, end in RELEVANT_WINDOWS
        if chapter == window_chapter and start <= modified_date < end
    ]


def sequence_key(path: Path) -> tuple[Path, str, str, int] | None:
    if path.suffix.casefold() not in IMAGE_EXTENSIONS:
        return None
    match = SEQUENCE_PATTERN.match(path.name)
    if not match:
        return None
    return (
        path.parent,
        match.group("prefix"),
        match.group("suffix").casefold(),
        int(match.group("frame")),
    )


def add_counts(
    target: dict[str, Counter[str]], key: str, value: str, amount: int = 1
) -> None:
    target[key][value] += amount


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--chronology",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "as-finishing-chronology-20260726.json",
    )
    args = parser.parse_args()

    root = AS_ROOT.resolve()
    chronology = json.loads(args.chronology.read_text(encoding="utf-8"))

    files: list[dict[str, Any]] = []
    sequence_files: dict[
        tuple[str, str, str], list[tuple[int, dict[str, Any]]]
    ] = defaultdict(list)
    extension_counts: Counter[str] = Counter()
    extension_bytes: Counter[str] = Counter()
    area_counts: Counter[str] = Counter()
    area_bytes: Counter[str] = Counter()
    chapter_counts: Counter[str] = Counter()
    chapter_bytes: Counter[str] = Counter()
    month_counts: Counter[str] = Counter()
    month_bytes: Counter[str] = Counter()
    day_counts: Counter[str] = Counter()
    day_bytes: Counter[str] = Counter()
    area_extension_counts: dict[str, Counter[str]] = defaultdict(Counter)
    chapter_extension_counts: dict[str, Counter[str]] = defaultdict(Counter)
    window_counts: Counter[str] = Counter()
    window_bytes: Counter[str] = Counter()
    total_allocated = 0

    for directory, child_directories, filenames in os.walk(root):
        child_directories.sort(key=str.casefold)
        filenames.sort(key=str.casefold)
        for filename in filenames:
            path = Path(directory) / filename
            relative = path.relative_to(root)
            stat = path.stat()
            modified_at = local_timestamp(stat.st_mtime)
            created_at = local_timestamp(stat.st_birthtime)
            modified_date = modified_at[:10]
            modified_month = modified_at[:7]
            extension = extension_for(path)
            area = area_for(relative)
            chapter = infer_chapter(relative)
            window_labels = windows_for(chapter, modified_date)
            allocated = stat.st_blocks * 512
            total_allocated += allocated

            record = {
                "path": str(path.resolve()),
                "relativePath": str(relative),
                "name": filename,
                "area": area,
                "chapter": chapter,
                "extension": extension,
                "sizeBytes": stat.st_size,
                "allocatedBytes": allocated,
                "modifiedAt": modified_at,
                "modifiedAtUtc": utc_timestamp(stat.st_mtime),
                "createdAt": created_at,
                "createdAtUtc": utc_timestamp(stat.st_birthtime),
                "relevantWindowLabels": window_labels,
                "readable": os.access(path, os.R_OK),
                "empty": stat.st_size == 0,
                "codexGenerated": "_codex_" in str(relative).casefold(),
            }
            files.append(record)

            extension_counts[extension] += 1
            extension_bytes[extension] += stat.st_size
            area_counts[area] += 1
            area_bytes[area] += stat.st_size
            month_counts[modified_month] += 1
            month_bytes[modified_month] += stat.st_size
            day_counts[modified_date] += 1
            day_bytes[modified_date] += stat.st_size
            area_extension_counts[area][extension] += 1
            if chapter:
                chapter_counts[chapter] += 1
                chapter_bytes[chapter] += stat.st_size
                chapter_extension_counts[chapter][extension] += 1
            for label in window_labels:
                window_counts[label] += 1
                window_bytes[label] += stat.st_size

            if area in {"03 Renders", "04 Renders"}:
                parsed = sequence_key(path)
                if parsed:
                    parent, prefix, suffix, frame = parsed
                    key = (str(parent.resolve()), prefix, suffix)
                    sequence_files[key].append((frame, record))

    files.sort(key=lambda item: item["relativePath"].casefold())

    sequences: list[dict[str, Any]] = []
    for (directory, prefix, suffix), entries in sequence_files.items():
        entries.sort(key=lambda item: item[0])
        frames = [item[0] for item in entries]
        records = [item[1] for item in entries]
        unique_frames = sorted(set(frames))
        missing_frames: list[int] = []
        if unique_frames:
            expected_count = unique_frames[-1] - unique_frames[0] + 1
            if expected_count <= 100_000:
                present = set(unique_frames)
                missing_frames = [
                    frame
                    for frame in range(unique_frames[0], unique_frames[-1] + 1)
                    if frame not in present
                ]
        relative_directory = str(Path(directory).relative_to(root))
        chapter = infer_chapter(Path(relative_directory))
        modified_values = [item["modifiedAt"] for item in records]
        created_values = [item["createdAt"] for item in records]
        sequences.append(
            {
                "directory": directory,
                "relativeDirectory": relative_directory,
                "chapter": chapter,
                "prefix": prefix,
                "extension": suffix,
                "fileCount": len(entries),
                "uniqueFrameCount": len(unique_frames),
                "duplicateFrameCount": len(entries) - len(unique_frames),
                "firstFrame": unique_frames[0] if unique_frames else None,
                "lastFrame": unique_frames[-1] if unique_frames else None,
                "missingFrameCount": len(missing_frames),
                "missingFrames": missing_frames[:500],
                "missingFramesTruncated": len(missing_frames) > 500,
                "sizeBytes": sum(item["sizeBytes"] for item in records),
                "modifiedAtMin": min(modified_values),
                "modifiedAtMax": max(modified_values),
                "createdAtMin": min(created_values),
                "createdAtMax": max(created_values),
                "firstPath": records[0]["path"],
                "lastPath": records[-1]["path"],
            }
        )
    sequences.sort(
        key=lambda item: (
            item["relativeDirectory"].casefold(),
            item["prefix"].casefold(),
            item["extension"],
        )
    )

    relevant_windows: list[dict[str, Any]] = []
    for label, chapter, start, end in RELEVANT_WINDOWS:
        projects = [
            item
            for item in chronology.get("projects", [])
            if (
                CHAPTER_ALIASES.get(item.get("chapter", ""), item.get("chapter"))
                == chapter
                and start <= item["modifiedDate"] < end
                and not item["codexGenerated"]
            )
        ]
        logs = [
            item
            for item in chronology.get("renderLogs", [])
            if (
                CHAPTER_ALIASES.get(item.get("chapter", ""), item.get("chapter"))
                == chapter
                and start <= item["modifiedDate"] < end
            )
        ]
        sequences_in_window = [
            item
            for item in sequences
            if item["chapter"] == chapter
            and not (
                item["modifiedAtMax"][:10] < start
                or item["modifiedAtMin"][:10] >= end
            )
        ]
        relevant_windows.append(
            {
                "label": label,
                "chapter": chapter,
                "startInclusive": start,
                "endExclusive": end,
                "allFileCount": window_counts[label],
                "allFileBytes": window_bytes[label],
                "authoredProjectStateCount": len(projects),
                "renderLogCount": len(logs),
                "legacyRenderSequenceCount": len(sequences_in_window),
                "projectPaths": [item["path"] for item in projects],
                "renderLogPaths": [item["path"] for item in logs],
                "legacyRenderSequenceDirectories": sorted(
                    {item["directory"] for item in sequences_in_window},
                    key=str.casefold,
                ),
            }
        )

    def counter_rows(
        counts: Counter[str], sizes: Counter[str]
    ) -> list[dict[str, Any]]:
        return [
            {"key": key, "fileCount": counts[key], "sizeBytes": sizes[key]}
            for key in sorted(counts, key=str.casefold)
        ]

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Read-only live filesystem walk of every regular file in "
            "AS/0 Finishing. File modification and birth times are native "
            "filesystem metadata; c4d@timestamp names and image frame suffixes "
            "are preserved without reinterpretation."
        ),
        "root": str(root),
        "chronology": str(args.chronology.resolve()),
        "summary": {
            "totalFiles": len(files),
            "logicalBytes": sum(item["sizeBytes"] for item in files),
            "allocatedBytes": total_allocated,
            "readableFiles": sum(item["readable"] for item in files),
            "unreadableFiles": sum(not item["readable"] for item in files),
            "emptyFiles": sum(item["empty"] for item in files),
            "codexGeneratedFiles": sum(item["codexGenerated"] for item in files),
            "legacyRenderSequences": len(sequences),
            "legacyRenderSequenceFiles": sum(
                item["fileCount"] for item in sequences
            ),
            "legacyRenderSequencesWithGaps": sum(
                item["missingFrameCount"] > 0 for item in sequences
            ),
            "projectStates": chronology["summary"]["projectStates"],
            "primaryProjects": chronology["summary"]["primaryProjects"],
            "backupSnapshots": chronology["summary"]["backupSnapshots"],
            "parsedRedshiftLogs": chronology["summary"][
                "redshiftBatchRenderLogs"
            ],
        },
        "byExtension": counter_rows(extension_counts, extension_bytes),
        "byArea": counter_rows(area_counts, area_bytes),
        "byChapter": counter_rows(chapter_counts, chapter_bytes),
        "byModifiedMonth": counter_rows(month_counts, month_bytes),
        "byModifiedDay": counter_rows(day_counts, day_bytes),
        "extensionCountsByArea": {
            key: dict(sorted(value.items()))
            for key, value in sorted(area_extension_counts.items())
        },
        "extensionCountsByChapter": {
            key: dict(sorted(value.items()))
            for key, value in sorted(chapter_extension_counts.items())
        },
        "relevantDateWindows": relevant_windows,
        "legacyRenderSequences": sequences,
        "files": files,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
