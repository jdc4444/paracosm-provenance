#!/usr/bin/env python3
"""Shortlist canonical cut frames against every surviving AS render-log output.

The AS finishing folder contains both authored C4D states and Redshift batch
render XMLs. This script groups canonical cuts and render outputs by chapter,
loads every surviving frame once, and keeps the strongest visual candidates
for each cut. Results are triage evidence only; they still require manual
visual confirmation before a source is promoted.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


IMAGE_SUFFIXES = {".exr", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
CHAPTER_KEYS = {
    "ND": "01 ND",
    "NTH": "02 NTH",
    "TH": "03 TH",
    "NA": "04 NA",
    "GG": "05 GG",
    "IJDKYY": "06 IJDKYY",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def image_feature(path: Path, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    image = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_8)
    if image is None:
        raise ValueError(f"Unreadable image: {path}")
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    grey = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32).reshape(-1)
    edges = cv2.Laplacian(
        grey.reshape(height, width), cv2.CV_32F
    ).reshape(-1)
    return normalize(grey), normalize(edges)


def normalize(values: np.ndarray) -> np.ndarray:
    centered = values - float(values.mean())
    norm = float(np.linalg.norm(centered))
    if norm == 0:
        return centered
    return centered / norm


def iter_images(directory: Path):
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES:
            yield path


def insert_top(
    records: list[dict[str, Any]], candidate: dict[str, Any], limit: int
) -> None:
    records.append(candidate)
    records.sort(key=lambda item: item["score"], reverse=True)
    del records[limit:]


def rendered_image_prefix(path: Path) -> str:
    return re.sub(r"-?\d+$", "", path.stem).casefold()


def source_matches_frame(source: dict[str, Any], path: Path) -> bool:
    if source.get("kind") != "redshift_batch_render_log":
        return True
    prefixes = source.get("completedImageBasenamePrefixes") or []
    if not prefixes:
        return True
    actual = rendered_image_prefix(path)
    return any(actual == str(prefix).casefold() for prefix in prefixes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--chronology", type=Path, required=True)
    parser.add_argument("--full-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--width", type=int, default=80)
    parser.add_argument("--height", type=int, default=45)
    parser.add_argument(
        "--render-logs-only",
        action="store_true",
        help="Exclude the legacy 03/04 Renders sequences.",
    )
    args = parser.parse_args()

    state = load_json(args.state)
    chronology = load_json(args.chronology)
    full_inventory = load_json(args.full_inventory)
    state_root = args.state.resolve().parents[2]

    cuts_by_chapter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unreadable_references: list[dict[str, str]] = []
    for cut in state.get("cuts", []):
        chapter = CHAPTER_KEYS.get(cut.get("sectionCode"))
        thumbnail = cut.get("thumbnail")
        if not chapter or not thumbnail or cut.get("isGap"):
            continue
        reference_path = (
            state_root / "public" / thumbnail.lstrip("/")
        ).resolve()
        try:
            grey, edges = image_feature(
                reference_path, args.width, args.height
            )
        except Exception as error:
            unreadable_references.append(
                {
                    "cutId": cut.get("id"),
                    "path": str(reference_path),
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            continue
        cuts_by_chapter[chapter].append(
            {
                "cutId": cut.get("id"),
                "cutIndex": cut.get("index"),
                "timecode": cut.get("timecode"),
                "thumbnail": str(reference_path),
                "grey": grey,
                "edges": edges,
                "top": [],
            }
        )

    directories_by_chapter: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    missing_output_directories: list[dict[str, Any]] = []
    for log in chronology.get("renderLogs", []):
        if log.get("parseStatus") != "parsed":
            continue
        chapter = log.get("chapter")
        output = log.get("outputPathNormalized")
        if not chapter or not output:
            continue
        directory = Path(output)
        if not directory.is_dir():
            missing_output_directories.append(
                {
                    "chapter": chapter,
                    "directory": str(directory),
                    "renderLogPath": log.get("path"),
                    "renderLogModifiedAt": log.get("modifiedAt"),
                }
            )
            continue
        key = str(directory.resolve())
        record = directories_by_chapter[chapter].setdefault(
            key,
            {
                "directory": key,
                "sources": [],
            },
        )
        record["sources"].append(
            {
                "kind": "redshift_batch_render_log",
                "renderLogPath": log.get("path"),
                "renderLogModifiedAt": log.get("modifiedAt"),
                "projectFilename": log.get("projectFilename"),
                "take": log.get("take"),
                "camera": log.get("camera"),
                "renderSettings": log.get("renderSettings"),
                "frameFrom": log.get("frameFrom"),
                "frameTo": log.get("frameTo"),
                "fps": log.get("fps"),
                "completedImageBasenamePrefixes": log.get(
                    "completedImageBasenamePrefixes", []
                ),
                "completedImageBasenameSamples": log.get(
                    "completedImageBasenameSamples", []
                ),
                "renderEngineName": log.get("renderEngineName"),
                "projectCandidatePaths": log.get("projectCandidatePaths", []),
                "nearestProjectStatePath": log.get("nearestProjectStatePath"),
                "nearestProjectStateDeltaSeconds": log.get(
                    "nearestProjectStateDeltaSeconds"
                ),
            }
        )

    if not args.render_logs_only:
        for sequence in full_inventory.get("legacyRenderSequences", []):
            chapter_code = sequence.get("chapter")
            chapter = CHAPTER_KEYS.get(chapter_code)
            directory_value = sequence.get("directory")
            if not chapter or not directory_value:
                continue
            directory = Path(directory_value)
            if not directory.is_dir():
                continue
            key = str(directory.resolve())
            record = directories_by_chapter[chapter].setdefault(
                key,
                {
                    "directory": key,
                    "sources": [],
                },
            )
            record["sources"].append(
                {
                    "kind": "legacy_as_render_sequence",
                    "relativeDirectory": sequence.get("relativeDirectory"),
                    "modifiedAtMin": sequence.get("modifiedAtMin"),
                    "modifiedAtMax": sequence.get("modifiedAtMax"),
                    "firstFrame": sequence.get("firstFrame"),
                    "lastFrame": sequence.get("lastFrame"),
                    "missingFrameCount": sequence.get("missingFrameCount"),
                }
            )

    unreadable_candidates: list[dict[str, str]] = []
    chapter_summaries: dict[str, dict[str, Any]] = {}
    for chapter, cuts in cuts_by_chapter.items():
        directories = list(directories_by_chapter.get(chapter, {}).values())
        candidate_paths = sorted(
            {
                path
                for record in directories
                for path in iter_images(Path(record["directory"]))
            }
        )
        reference_grey = np.stack([cut["grey"] for cut in cuts])
        reference_edges = np.stack([cut["edges"] for cut in cuts])
        readable_count = 0
        for path in candidate_paths:
            try:
                grey, edges = image_feature(path, args.width, args.height)
            except Exception as error:
                unreadable_candidates.append(
                    {
                        "path": str(path),
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            readable_count += 1
            luminance = reference_grey @ grey
            edge = reference_edges @ edges
            score = (luminance * 0.65) + (edge * 0.35)
            parent_record = directories_by_chapter[chapter].get(
                str(path.parent.resolve())
            )
            sources = parent_record["sources"] if parent_record else []
            sources = [
                source
                for source in sources
                if source_matches_frame(source, path)
            ]
            for index, cut in enumerate(cuts):
                insert_top(
                    cut["top"],
                    {
                        "path": str(path),
                        "luminanceCorrelation": round(
                            float(luminance[index]), 6
                        ),
                        "edgeCorrelation": round(float(edge[index]), 6),
                        "score": round(float(score[index]), 6),
                        "sourceEvidence": sources,
                    },
                    args.top,
                )
        chapter_summaries[chapter] = {
            "cutCount": len(cuts),
            "directoryCount": len(directories),
            "candidateFrameCount": len(candidate_paths),
            "readableFrameCount": readable_count,
            "unreadableFrameCount": len(candidate_paths) - readable_count,
        }

    output_cuts = []
    for chapter, cuts in cuts_by_chapter.items():
        for cut in cuts:
            output_cuts.append(
                {
                    key: value
                    for key, value in cut.items()
                    if key not in {"grey", "edges"}
                }
                | {"chapter": chapter}
            )
    output_cuts.sort(key=lambda item: item["cutIndex"])
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Automated visual shortlist across every surviving AS Redshift "
            "batch-render output and legacy AS render sequence, grouped by "
            "chapter. Manual frame confirmation is required."
        ),
        "state": str(args.state.resolve()),
        "chronology": str(args.chronology.resolve()),
        "fullInventory": str(args.full_inventory.resolve()),
        "featureSize": {"width": args.width, "height": args.height},
        "topPerCut": args.top,
        "includedLegacyRenderSequences": not args.render_logs_only,
        "summary": {
            "cutCount": len(output_cuts),
            "chapterCount": len(chapter_summaries),
            "outputDirectoryCount": sum(
                item["directoryCount"] for item in chapter_summaries.values()
            ),
            "candidateFrameCount": sum(
                item["candidateFrameCount"]
                for item in chapter_summaries.values()
            ),
            "unreadableReferenceCount": len(unreadable_references),
            "unreadableCandidateCount": len(unreadable_candidates),
            "missingRenderLogOutputDirectoryCount": len(
                missing_output_directories
            ),
        },
        "byChapter": chapter_summaries,
        "cuts": output_cuts,
        "missingRenderLogOutputDirectories": missing_output_directories,
        "unreadableReferences": unreadable_references,
        "unreadableCandidates": unreadable_candidates[:100],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
