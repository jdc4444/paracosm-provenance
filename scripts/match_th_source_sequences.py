#!/usr/bin/env python3
"""Match the final TH intervals to the exact terminal image-sequence frames."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

APP_ROOT = Path(__file__).resolve().parents[1]
AE_ARCHIVE = APP_ROOT / "data" / "after-effects-export.json"
SCENE_BOUNDARIES = APP_ROOT / "data" / "scene-boundaries.json"
OUTPUT_PATH = APP_ROOT / "data" / "th-visual-source-matches.json"
SOURCE_EDIT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
    "SG/C4D/_renders/AS/TH/TH_0427.mp4"
)
TH_ROOT = SOURCE_EDIT.parent
PREVIS_ROOTS = [
    Path(
        "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
        "JD/AS/previs 3/TH"
    ),
    Path(
        "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
        "JD/AS/Previs renders/freezer/2 horses gallop"
    ),
]
IMAGE_EXTENSIONS = {".png", ".tif", ".tiff", ".jpg", ".jpeg", ".exr"}
TH_START = 138.80533333333332
TH_END = 205.78891666666667
# Direct final ↔ TH_0427 frame matching produces an alternating 23.976/29.97
# cadence around this center. It is used only to request the corresponding
# baked-edit frame; terminal image frames are then independently searched.
FINAL_TO_SOURCE_OFFSET = 131.6440125
# These are real edit points in the baked source edit that the 0.30 reference
# detector misses because adjacent horse compositions are structurally similar.
# The times below are the exact matching 23.976 reference frames.
SOURCE_ONLY_CUT = 196.946809
FINAL_WIDE_CUT = 201.326125


def image_files(directory: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ),
        key=lambda path: [
            int(value) if value.isdigit() else value.lower()
            for value in re.split(r"(\d+)", path.name)
        ],
    )


def feature(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(
        cv2.resize(image, (160, 90), interpolation=cv2.INTER_AREA),
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
    return 0.7 * luminance + 0.3 * edges


def video_reference(
    capture: cv2.VideoCapture, source_time: float
) -> dict[str, Any]:
    capture.set(cv2.CAP_PROP_POS_MSEC, source_time * 1000)
    ok, image = capture.read()
    if not ok:
        raise RuntimeError(f"Could not decode {SOURCE_EDIT.name} at {source_time:.3f}s")
    gray = cv2.cvtColor(
        cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA),
        cv2.COLOR_BGR2GRAY,
    )
    return {"feature": feature(image), "gray": gray}


def numbered_frame(path: Path) -> int | None:
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    return int(match.group(1)) if match else None


def sequence_identity(path: Path) -> tuple[str, str]:
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    return (
        path.name[: match.start()] if match else path.stem,
        path.suffix.lower(),
    )


def candidate_directories() -> list[Path]:
    candidates = set()
    for root in [TH_ROOT, *PREVIS_ROOTS]:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir() and any(
                item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS
                for item in path.iterdir()
            ):
                candidates.add(path)

    if AE_ARCHIVE.exists():
        archive = json.loads(AE_ARCHIVE.read_text(encoding="utf-8"))
        for project in archive.get("projects", []):
            project_path = str(project.get("path") or "").lower()
            if "paracosm (converted)" not in project_path and "th_edit" not in project_path:
                continue
            for comp in project.get("compositions", []):
                for layer in comp.get("layers", []):
                    source_path = Path(str(layer.get("sourcePath") or ""))
                    if source_path.suffix.lower() in IMAGE_EXTENSIONS and source_path.parent.exists():
                        candidates.add(source_path.parent)
    return sorted(candidates)


def main() -> None:
    scene = json.loads(SCENE_BOUNDARIES.read_text(encoding="utf-8"))
    boundaries = [
        TH_START,
        *[
            float(value)
            for value in scene.get("visualBoundaries", [])
            if TH_START + 0.1 < float(value) < 191.5
        ],
        SOURCE_ONLY_CUT,
        FINAL_WIDE_CUT,
        TH_END,
    ]
    boundaries = sorted(
        value
        for index, value in enumerate(sorted(boundaries))
        if index == 0 or value - sorted(boundaries)[index - 1] > 0.1
    )
    intervals = [
        {
            "finalStart": boundaries[index],
            "finalEnd": boundaries[index + 1],
            "finalMidpoint": (
                boundaries[index] + boundaries[index + 1]
            )
            / 2,
        }
        for index in range(len(boundaries) - 1)
    ]

    capture = cv2.VideoCapture(str(SOURCE_EDIT))
    references = []
    for interval in intervals:
        source_time = interval["finalMidpoint"] - FINAL_TO_SOURCE_OFFSET
        references.append(video_reference(capture, source_time))
        interval["sourceEditTime"] = source_time
    capture.release()

    directories = candidate_directories()
    directory_files = {directory: image_files(directory) for directory in directories}
    coarse: dict[int, list[tuple[float, Path]]] = defaultdict(list)
    for directory, files in directory_files.items():
        if not files:
            continue
        indexes = np.linspace(0, len(files) - 1, min(16, len(files)), dtype=int)
        best_scores = [-2.0] * len(references)
        for index in sorted(set(int(value) for value in indexes)):
            image = cv2.imread(str(files[index]), cv2.IMREAD_COLOR)
            if image is None:
                continue
            candidate = feature(image)
            for reference_index, reference in enumerate(references):
                best_scores[reference_index] = max(
                    best_scores[reference_index],
                    similarity(reference["feature"], candidate),
                )
        for reference_index, score in enumerate(best_scores):
            coarse[reference_index].append((score, directory))

    shortlisted: dict[int, set[Path]] = {}
    for index in range(len(references)):
        shortlisted[index] = {
            directory
            for _, directory in sorted(coarse[index], reverse=True)[:6]
        }

    detailed: dict[int, list[tuple[float, Path]]] = defaultdict(list)
    union = sorted(set().union(*shortlisted.values()))
    for directory in union:
        interested = [
            index
            for index, values in shortlisted.items()
            if directory in values
        ]
        for path in directory_files[directory]:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            candidate = feature(image)
            for index in interested:
                detailed[index].append(
                    (similarity(references[index]["feature"], candidate), path)
                )

    for index, interval in enumerate(intervals):
        matches = []
        seen_directories = set()
        for score, path in sorted(detailed[index], reverse=True):
            if path.parent in seen_directories:
                continue
            seen_directories.add(path.parent)
            matches.append(
                {
                    "score": round(score, 6),
                    "framePath": str(path),
                    "directory": str(path.parent),
                }
            )
            if len(matches) == 6:
                break
        interval["matches"] = matches

    sift = cv2.SIFT_create(nfeatures=1200)
    matcher = cv2.BFMatcher()
    reference_sift = []
    for reference in references:
        keypoints, descriptors = sift.detectAndCompute(reference["gray"], None)
        reference_sift.append((keypoints, descriptors))
    best_directories = {
        index: Path(interval["matches"][0]["directory"])
        for index, interval in enumerate(intervals)
        if interval.get("matches")
    }
    for directory in sorted(set(best_directories.values())):
        interested = [
            index
            for index, value in best_directories.items()
            if value == directory
        ]
        best: dict[int, tuple[int, int, float, Path]] = {}
        files = directory_files[directory]
        candidate_indexes = set()
        for index in interested:
            coarse_path = Path(intervals[index]["matches"][0]["framePath"])
            try:
                coarse_index = files.index(coarse_path)
            except ValueError:
                continue
            candidate_indexes.update(
                range(
                    max(0, coarse_index - 60),
                    min(len(files), coarse_index + 61),
                )
            )
        for file_index in sorted(candidate_indexes):
            path = files[file_index]
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            image = cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA)
            candidate_keypoints, candidate_descriptors = sift.detectAndCompute(
                image, None
            )
            if candidate_descriptors is None:
                continue
            for index in interested:
                reference_keypoints, reference_descriptors = reference_sift[index]
                if reference_descriptors is None:
                    continue
                pairs = matcher.knnMatch(
                    reference_descriptors, candidate_descriptors, k=2
                )
                good = [
                    match
                    for match, alternative in pairs
                    if match.distance < 0.70 * alternative.distance
                ]
                inliers = 0
                if len(good) >= 4:
                    source_points = np.float32(
                        [
                            reference_keypoints[match.queryIdx].pt
                            for match in good
                        ]
                    )
                    candidate_points = np.float32(
                        [
                            candidate_keypoints[match.trainIdx].pt
                            for match in good
                        ]
                    )
                    _, mask = cv2.findHomography(
                        source_points,
                        candidate_points,
                        cv2.RANSAC,
                        4,
                    )
                    if mask is not None:
                        inliers = int(mask.sum())
                mean_distance = (
                    sum(match.distance for match in good) / len(good)
                    if good
                    else 9999.0
                )
                score = (inliers, len(good), -mean_distance, path)
                if index not in best or score[:3] > best[index][:3]:
                    best[index] = score
        for index, score in best.items():
            inliers, good_matches, negative_distance, path = score
            interval = intervals[index]
            midpoint_frame = numbered_frame(path)
            files = [
                item
                for item in directory_files[path.parent]
                if sequence_identity(item) == sequence_identity(path)
            ]
            first_frame = numbered_frame(files[0])
            last_frame = numbered_frame(files[-1])
            if midpoint_frame is None or first_frame is None:
                continue
            source_rate = 24.0
            source_start = max(
                first_frame,
                int(
                    round(
                        midpoint_frame
                        - (
                            float(interval["finalMidpoint"])
                            - float(interval["finalStart"])
                        )
                        * source_rate
                    )
                ),
            )
            source_duration = max(
                1,
                int(
                    round(
                        (
                            float(interval["finalEnd"])
                            - float(interval["finalStart"])
                        )
                        * source_rate
                    )
                ),
            )
            source_end = min(
                last_frame if last_frame is not None else source_start + source_duration - 1,
                source_start + source_duration - 1,
            )
            frame_width = len(
                re.search(r"(\d+)(?=\.[^.]+$)", files[0].name).group(1)
            )
            prefix = files[0].name[: re.search(r"(\d+)(?=\.[^.]+$)", files[0].name).start()]
            suffix = files[0].suffix
            start_path = path.parent / (
                prefix + str(source_start).zfill(frame_width) + suffix
            )
            interval["terminalSource"] = {
                "sourcePath": str(files[0]),
                "sourceFirstFramePath": str(start_path),
                "sourceStartFrame": source_start,
                "sourceEndFrame": source_end,
                "sourceFrameRate": source_rate,
                "midpointFramePath": str(path),
                "midpointFrame": midpoint_frame,
                "siftInliers": inliers,
                "siftGoodMatches": good_matches,
                "siftMeanDistance": round(-negative_distance, 4),
            }

    for index, interval in enumerate(intervals):
        matches = interval.get("matches", [])
        best = matches[0] if matches else None
        terminal = interval.get("terminalSource")
        matched_path = (
            Path(terminal["midpointFramePath"])
            if terminal
            else Path(best["framePath"])
            if best
            else None
        )
        print(
            f"TH-{index + 1:02d} "
            f"{interval['finalStart']:.3f}-{interval['finalEnd']:.3f} "
            + (
                f"{best['score']:.4f} {matched_path.name}"
                + (
                    f" · {terminal['siftInliers']} SIFT inliers"
                    if terminal
                    else ""
                )
                if best
                else "NO MATCH"
            ),
            flush=True,
        )

    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceEditPath": str(SOURCE_EDIT),
        "finalToSourceOffset": FINAL_TO_SOURCE_OFFSET,
        "sourceOnlyCut": SOURCE_ONLY_CUT,
        "finalWideCut": FINAL_WIDE_CUT,
        "candidateDirectories": len(directories),
        "intervals": intervals,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(intervals)} TH matches to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
