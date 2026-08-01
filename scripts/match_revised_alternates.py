#!/usr/bin/env python3
"""Search render archives for exact alternatives to user-marked old/new sources."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps


APP_ROOT = Path(__file__).resolve().parents[1]
REVISED_PATH = (
    APP_ROOT / "data" / "premiere" / "revised-conform-export.json"
)
STATE_PATH = APP_ROOT / "public" / "data" / "state.json"
OUTPUT_PATH = APP_ROOT / "data" / "premiere" / "alternate-search.json"
ARCHIVE_DIR = APP_ROOT / "public" / "archive" / "alternate-search"
REFERENCE_MOV = Path(
    "/Users/alphaone/Desktop/desktop 0705/Paracosm Full Copy 01.mov"
)
IMAGE_EXTENSIONS = {".png", ".tif", ".tiff", ".jpg", ".jpeg", ".exr"}


def natural_key(path: Path) -> list[Any]:
    return [
        int(value) if value.isdigit() else value.lower()
        for value in re.split(r"(\d+)", path.name)
    ]


def image_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=natural_key,
    )
    auxiliary = re.compile(
        r"(?i)(?:aov_(?!beauty)|puzzlematte|cryptomatte|volumez|"
        r"\bdepth\b|motionvectors?|worldposition|normals?|diffusefilter|"
        r"specularfilter|reflectionfilter|refractionfilter)"
    )
    primary = [path for path in files if not auxiliary.search(path.name)]
    return primary or files


def clean_name(value: str) -> str:
    value = re.sub(r"^SRC-\d+\s*¬∑\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\d+(?=\.[^.]+$)", "", value)
    value = re.sub(r"(?i)(?:_|-)?i\d+", "", value)
    value = re.sub(r"(?i)(?:_|-)?v\d+(?:-\d+)?", "", value)
    value = re.sub(r"(?i)(?:_|-)?\d{4}", "", value)
    return re.sub(r"[^a-z0-9]", "", value.lower())


def directory_identity(directory: Path) -> str:
    return clean_name(directory.name)


def feature(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if image.ndim == 2:
        gray = cv2.resize(
            image, (160, 90), interpolation=cv2.INTER_AREA
        ).astype(np.float32)
    else:
        bgr = image[:, :, :3]
        gray = cv2.cvtColor(
            cv2.resize(bgr, (160, 90), interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2GRAY,
        ).astype(np.float32)
    gray = (gray - gray.mean()) / (gray.std() + 1e-6)
    edges = cv2.Laplacian(gray, cv2.CV_32F)
    edges = (edges - edges.mean()) / (edges.std() + 1e-6)
    return gray, edges


def similarity(
    first: tuple[np.ndarray, np.ndarray],
    second: tuple[np.ndarray, np.ndarray],
) -> float:
    luminance = float((first[0] * second[0]).mean())
    edges = float((first[1] * second[1]).mean())
    return max(
        0.0,
        min(
            1.0,
            0.65 * ((luminance + 1) / 2)
            + 0.35 * ((edges + 1) / 2),
        ),
    )


def video_image(
    capture: cv2.VideoCapture,
    time_value: float,
) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, time_value) * 1000)
    ok, image = capture.read()
    if not ok:
        raise RuntimeError(
            f"Could not decode final reference at {time_value:.6f}s"
        )
    return image


def concrete_frame(path: str, frame_number: int) -> Path:
    match = re.search(r"(\d+)(?=\.[^.]+$)", Path(path).name)
    if not match:
        return Path(path)
    name = Path(path).name
    return Path(path).with_name(
        name[: match.start()]
        + str(frame_number).zfill(len(match.group(1)))
        + name[match.end() :]
    )


def current_midpoint_frame(source: dict[str, Any]) -> Path | None:
    first = source.get("mediaFirstFrame")
    if first is None:
        return None
    duration = int(source["durationFrames"])
    if source.get("playBackwards"):
        frame = (
            first
            + int(source["sourceOutFrameOffset"])
            - 1
            - duration // 2
        )
    else:
        frame = (
            first
            + int(source["sourceInFrameOffset"])
            + duration // 2
        )
    path = concrete_frame(str(source["path"]), frame)
    return path if path.exists() else None


def candidate_name_score(source_names: list[str], directory: Path) -> float:
    candidate = directory_identity(directory)
    if not candidate:
        return 0
    result = 0.0
    for source_name in source_names:
        query = clean_name(source_name)
        if not query:
            continue
        score = SequenceMatcher(None, query, candidate).ratio()
        if query in candidate or candidate in query:
            score = max(score, 0.94)
        result = max(result, score)
    return result


def candidate_directories(
    source: dict[str, Any],
    all_directories: list[Path],
    source_names: list[str],
) -> list[Path]:
    known_directory = Path(
        str(source.get("renderDirectory") or "")
    ).resolve()
    scored = []
    for directory in all_directories:
        if directory.resolve() == known_directory:
            continue
        name_score = candidate_name_score(source_names, directory)
        section_bonus = 0.0
        path_lower = str(directory).lower()
        if (
            source["sectionCode"] == "TH"
            and (
                "/as/th/" in path_lower
                or directory.name.lower().startswith("3")
            )
        ):
            section_bonus = 0.18
        elif (
            source["sectionCode"] == "NTH"
            and (
                "/nth/" in path_lower
                or directory.name.lower().startswith("2")
            )
        ):
            section_bonus = 0.08
        elif (
            source["sectionCode"] == "GG"
            and (
                "/gg" in path_lower
                or directory.name.lower().startswith("5")
            )
        ):
            section_bonus = 0.08
        elif (
            source["sectionCode"] == "ND"
            and directory.name.lower().startswith("1")
        ):
            section_bonus = 0.08
        elif (
            source["sectionCode"] == "NA"
            and (
                "/na/" in path_lower
                or directory.name.lower().startswith("4")
            )
        ):
            section_bonus = 0.08
        score = min(1.0, name_score + section_bonus)
        threshold = (
            0.05
            if source.get("role") == "missing_exact_source"
            else 0.48
        )
        if score >= threshold:
            scored.append((score, directory))
    return [
        directory
        for _, directory in sorted(
            scored, key=lambda item: (item[0], str(item[1])), reverse=True
        )[:80 if source.get("role") == "missing_exact_source" else 32]
    ]


def comparison_sheet(
    final_image: np.ndarray,
    known_path: Path | None,
    candidate_path: Path,
    target: Path,
    title: str,
) -> None:
    panels = []
    labels = ["FINAL CUT", "USER-MARKED ALT", "SEARCH CANDIDATE"]
    final_rgb = cv2.cvtColor(final_image, cv2.COLOR_BGR2RGB)
    panels.append(Image.fromarray(final_rgb))
    for path in (known_path, candidate_path):
        if path is not None and path.exists():
            with Image.open(path) as image:
                panels.append(image.convert("RGB").copy())
        else:
            panels.append(Image.new("RGB", (640, 360), "#161616"))
    fitted = [
        ImageOps.fit(
            image, (540, 304), method=Image.Resampling.LANCZOS
        )
        for image in panels
    ]
    sheet = Image.new("RGB", (1620, 352), "#0c0c0c")
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(fitted):
        x = index * 540
        sheet.paste(image, (x, 48))
        draw.text((x + 12, 12), labels[index], fill="#d7f452")
    draw.text((810, 12), title, anchor="ma", fill="#f4f4f4")
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, quality=90)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Refresh only the four V1 intervals with no aligned source",
    )
    args = parser.parse_args()
    revised = json.loads(REVISED_PATH.read_text(encoding="utf-8"))
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    unresolved = (
        []
        if args.missing_only
        else [
            source
            for source in revised["sources"]
            if source["role"] in {"older_than_cut", "newer_than_cut"}
        ]
    )
    for edit in revised["inventory"]:
        coverage = edit.get("sourceCoverage") or {}
        if (
            edit.get("role") == "final_cut"
            and coverage.get("status") == "untracked"
        ):
            unresolved.append(
                {
                    "id": f"MISSING-{edit['canonicalId']}",
                    "targetCutId": edit["canonicalId"],
                    "track": None,
                    "role": "missing_exact_source",
                    "name": edit["name"],
                    "path": "",
                    "renderDirectory": "",
                    "sectionCode": edit["sectionCode"],
                    "sectionName": edit["sectionName"],
                    "start": edit["start"],
                    "end": edit["end"],
                    "startFrame": edit["startFrame"],
                    "endFrame": edit["endFrame"],
                    "durationFrames": edit["durationFrames"],
                    "sourceInFrameOffset": 0,
                    "sourceOutFrameOffset": edit["durationFrames"],
                    "mediaFirstFrame": None,
                    "playBackwards": False,
                }
            )
    all_directories = sorted(
        {
            Path(item["path"])
            for item in state["renderSequences"]
            if Path(item["path"]).is_dir()
        }
    )
    sources_by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in unresolved:
        for other in revised["sources"]:
            if (
                source["sectionCode"] == other["sectionCode"]
                and source["start"] < other["end"] + 15
                and source["end"] > other["start"] - 15
            ):
                sources_by_time[source["id"]].append(other)

    capture = cv2.VideoCapture(str(REFERENCE_MOV))
    references: dict[str, dict[str, Any]] = {}
    for source in unresolved:
        midpoint = (source["start"] + source["end"]) / 2
        image = video_image(capture, midpoint)
        known_path = current_midpoint_frame(source)
        known_score = None
        if known_path is not None:
            known_image = cv2.imread(str(known_path), cv2.IMREAD_UNCHANGED)
            if known_image is not None:
                known_score = similarity(feature(image), feature(known_image))
        references[source["id"]] = {
            "image": image,
            "feature": feature(image),
            "midpoint": midpoint,
            "knownPath": known_path,
            "knownScore": known_score,
        }

    candidates: dict[str, list[Path]] = {}
    directory_interests: dict[Path, list[str]] = defaultdict(list)
    directory_files: dict[Path, list[Path]] = {}
    for source in unresolved:
        names = [
            item["name"] for item in sources_by_time[source["id"]]
        ]
        names.append(source["name"])
        selected = candidate_directories(
            source, all_directories, names
        )
        candidates[source["id"]] = selected
        for directory in selected:
            directory_interests[directory].append(source["id"])

    coarse: dict[str, list[tuple[float, Path, Path]]] = defaultdict(list)
    for directory, interests in directory_interests.items():
        files = image_files(directory)
        directory_files[directory] = files
        if not files:
            continue
        indexes = sorted(
            {
                round(value)
                for value in np.linspace(
                    0, len(files) - 1, min(14, len(files))
                )
            }
        )
        best = {source_id: (-1.0, files[0]) for source_id in interests}
        for index in indexes:
            path = files[index]
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None:
                continue
            candidate_feature = feature(image)
            for source_id in interests:
                score = similarity(
                    references[source_id]["feature"],
                    candidate_feature,
                )
                if score > best[source_id][0]:
                    best[source_id] = (score, path)
        for source_id, (score, path) in best.items():
            coarse[source_id].append((score, directory, path))

    shortlisted: dict[str, set[Path]] = {}
    detailed_interests: dict[Path, list[str]] = defaultdict(list)
    for source in unresolved:
        source_id = source["id"]
        shortlisted[source_id] = {
            directory
            for _, directory, _ in sorted(
                coarse[source_id],
                key=lambda item: item[0],
                reverse=True,
            )[:6]
        }
        for directory in shortlisted[source_id]:
            detailed_interests[directory].append(source_id)

    detailed: dict[str, list[tuple[float, Path, Path, int]]] = defaultdict(
        list
    )
    for directory, interests in detailed_interests.items():
        files = directory_files.get(directory) or image_files(directory)
        best: dict[str, list[tuple[float, Path, int]]] = {
            source_id: [] for source_id in interests
        }
        for index, path in enumerate(files):
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None:
                continue
            candidate_feature = feature(image)
            for source_id in interests:
                score = similarity(
                    references[source_id]["feature"],
                    candidate_feature,
                )
                values = best[source_id]
                if len(values) < 3 or score > values[-1][0]:
                    values.append((score, path, index))
                    values.sort(key=lambda item: item[0], reverse=True)
                    del values[3:]
        for source_id, values in best.items():
            if values:
                score, path, index = values[0]
                detailed[source_id].append(
                    (score, directory, path, index)
                )

    results = []
    timeline_fps = float(revised["timelineFrameRate"])
    for source in unresolved:
        source_id = source["id"]
        ranking = []
        for score, directory, path, index in sorted(
            detailed[source_id],
            key=lambda item: item[0],
            reverse=True,
        )[:6]:
            ranking.append(
                {
                    "score": round(score, 6),
                    "renderDirectory": str(directory),
                    "framePath": str(path),
                    "frameIndex": index,
                }
            )
        if not ranking:
            continue
        best = ranking[0]
        best_directory = Path(best["renderDirectory"])
        files = directory_files.get(best_directory) or image_files(
            best_directory
        )
        anchor = int(best["frameIndex"])
        step = min(
            24,
            max(3, int(source["durationFrames"]) // 4),
            anchor,
            max(0, len(files) - anchor - 1),
        )
        temporal_scores = []
        direction_scores = {}
        if step >= 1:
            before_image = video_image(
                capture,
                references[source_id]["midpoint"] - step / timeline_fps,
            )
            after_image = video_image(
                capture,
                references[source_id]["midpoint"] + step / timeline_fps,
            )
            before_feature = feature(before_image)
            after_feature = feature(after_image)
            for direction in (1, -1):
                first = cv2.imread(
                    str(files[anchor - direction * step]),
                    cv2.IMREAD_UNCHANGED,
                )
                second = cv2.imread(
                    str(files[anchor + direction * step]),
                    cv2.IMREAD_UNCHANGED,
                )
                if first is None or second is None:
                    continue
                values = [
                    float(best["score"]),
                    similarity(before_feature, feature(first)),
                    similarity(after_feature, feature(second)),
                ]
                direction_scores[direction] = values
            if direction_scores:
                direction, temporal_scores = max(
                    direction_scores.items(),
                    key=lambda item: sum(item[1]) / len(item[1]),
                )
            else:
                direction = 1
                temporal_scores = [float(best["score"])]
        else:
            direction = 1
            temporal_scores = [float(best["score"])]
        temporal_score = sum(temporal_scores) / len(temporal_scores)
        baseline = references[source_id]["knownScore"]
        improvement = (
            temporal_score - baseline if baseline is not None else None
        )
        evidence = (
            "visually_confirmed_candidate"
            if temporal_score >= 0.88
            and min(temporal_scores) >= 0.82
            and (improvement is None or improvement >= 0.015)
            else "strong_candidate"
            if temporal_score >= 0.8
            else "candidate"
        )
        anchor_number_match = re.search(
            r"(\d+)(?=\.[^.]+$)", Path(best["framePath"]).name
        )
        anchor_frame_number = (
            int(anchor_number_match.group(1))
            if anchor_number_match
            else anchor
        )
        midpoint_offset = int(source["durationFrames"]) // 2
        if direction == 1:
            proposed_first_frame = anchor_frame_number - midpoint_offset
            proposed_last_frame = (
                proposed_first_frame + int(source["durationFrames"]) - 1
            )
        else:
            proposed_first_frame = anchor_frame_number + midpoint_offset
            proposed_last_frame = (
                proposed_first_frame - int(source["durationFrames"]) + 1
            )
        archive_path = ARCHIVE_DIR / f"{source_id}-candidate.jpg"
        comparison_sheet(
            references[source_id]["image"],
            references[source_id]["knownPath"],
            Path(best["framePath"]),
            archive_path,
            (
                f"{source_id} · {source['role']} · "
                f"{temporal_score:.3f}"
            ),
        )
        results.append(
            {
                "sourceId": source_id,
                "targetCutId": source.get("targetCutId"),
                "role": source["role"],
                "sectionCode": source["sectionCode"],
                "finalStart": source["start"],
                "finalEnd": source["end"],
                "finalStartFrame": source["startFrame"],
                "finalEndFrame": source["endFrame"],
                "knownSourcePath": source.get("path"),
                "knownMidpointFrame": (
                    str(references[source_id]["knownPath"])
                    if references[source_id]["knownPath"] is not None
                    else None
                ),
                "knownMidpointScore": (
                    round(baseline, 6) if baseline is not None else None
                ),
                "candidateRenderDirectory": best["renderDirectory"],
                "candidateMidpointFrame": best["framePath"],
                "candidateMidpointScore": best["score"],
                "temporalScore": round(temporal_score, 6),
                "temporalScores": [
                    round(value, 6) for value in temporal_scores
                ],
                "improvement": (
                    round(improvement, 6)
                    if improvement is not None
                    else None
                ),
                "playBackwards": direction == -1,
                "proposedFirstFrame": proposed_first_frame,
                "proposedLastFrame": proposed_last_frame,
                "evidence": evidence,
                "comparisonImage": (
                    f"/archive/alternate-search/{archive_path.name}"
                ),
                "ranking": ranking,
            }
        )
        print(
            f"{source_id} {source['role']} "
            f"known={baseline if baseline is not None else -1:.3f} "
            f"candidate={temporal_score:.3f} "
            f"{Path(best['renderDirectory']).name} {evidence}",
            flush=True,
        )

    capture.release()
    if args.missing_only and OUTPUT_PATH.exists():
        previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        results = [
            item
            for item in previous.get("results", [])
            if item.get("role") != "missing_exact_source"
        ] + results
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Direct final-reference structural and temporal frame comparison; "
            "user V5/V7 classification and all saved trims remain "
            "authoritative. Missing-source results are candidates only."
        ),
        "results": results,
        "summary": {
            "searched": len(results),
            "ranked": len(results),
            "visuallyConfirmedCandidates": sum(
                item["evidence"] == "visually_confirmed_candidate"
                for item in results
            ),
            "strongCandidates": sum(
                item["evidence"] == "strong_candidate"
                for item in results
            ),
            "candidates": sum(
                item["evidence"] == "candidate" for item in results
            ),
        },
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
