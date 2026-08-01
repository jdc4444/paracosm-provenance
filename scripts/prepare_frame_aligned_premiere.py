#!/usr/bin/env python3
"""Build one-frame-per-timeline-frame adapters for proven conform corrections.

The user-cleaned Premiere project remains the base.  Only intervals listed in
``clean-conform-visual-alignment.json`` are replaced.  Each replacement image
sequence is made from symlinks to the original render frames; direct structural
comparison against the final reference determines the monotonic source-frame
cadence, including 30-to-23.976 conversions and held frames.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


APP_ROOT = Path(__file__).resolve().parents[1]
CLEAN_EXPORT = APP_ROOT / "data" / "premiere" / "clean-conform-export.json"
ALIGNMENT_ARCHIVE = APP_ROOT / "data" / "clean-conform-visual-alignment.json"
REFERENCE_MOVIE = Path(
    "/Users/alphaone/Desktop/desktop 0705/Paracosm Full Copy 01.mov"
)
MEDIA_ROOT = APP_ROOT / "data" / "premiere" / "frame-aligned-media"
OUTPUT_PATH = APP_ROOT / "data" / "premiere" / "frame-aligned-manifest.json"
IMAGE_EXTENSIONS = {".png", ".tif", ".tiff", ".jpg", ".jpeg", ".exr"}
REFERENCE_FPS = 24000 / 1001


def numbered_frame(path: Path) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    if not match:
        return None, None
    return int(match.group(1)), len(match.group(1))


def frame_path(path_value: str, frame: int) -> Path:
    path = Path(path_value)
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    if not match:
        return path
    return path.with_name(
        path.name[: match.start()]
        + f"{frame:0{len(match.group(1))}d}"
        + path.name[match.end() :]
    )


def source_frame_path(
    source: dict[str, Any],
    correction: dict[str, Any],
    frame: int,
) -> Path:
    prefix_change = correction.get("framePrefixChangesAt")
    if prefix_change is not None and frame >= int(prefix_change):
        suffix = Path(str(source["path"])).suffix
        return Path(str(source["renderDirectory"])) / (
            f"{correction['framePrefix']}{frame:04d}{suffix}"
        )
    return frame_path(str(source["path"]), frame)


def normalized_feature(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if image.ndim == 2:
        gray = cv2.resize(
            image,
            (160, 90),
            interpolation=cv2.INTER_AREA,
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
    return gray.reshape(-1), edges.reshape(-1)


def reference_features(
    capture: cv2.VideoCapture,
    start_frame: int,
    end_frame: int,
) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    features = []
    for frame in range(start_frame, end_frame):
        ok, image = capture.read()
        if not ok:
            raise RuntimeError(f"Could not decode final reference frame {frame}")
        gray, edges = normalized_feature(image)
        features.append(np.concatenate((gray * 0.7, edges * 0.3)))
    return np.asarray(features, dtype=np.float32)


def source_features(paths: list[Path]) -> np.ndarray:
    features = []
    for path in paths:
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise RuntimeError(f"Could not read source frame {path}")
        gray, edges = normalized_feature(image)
        features.append(np.concatenate((gray * 0.7, edges * 0.3)))
    return np.asarray(features, dtype=np.float32)


def monotonic_mapping(
    final_features: np.ndarray,
    render_features: np.ndarray,
) -> tuple[list[int], list[float]]:
    """Return a non-decreasing render index for every final frame."""

    similarities = final_features @ render_features.T
    feature_size = final_features.shape[1]
    similarities /= max(1.0, feature_size * (0.7**2 + 0.3**2))
    target_count, source_count = similarities.shape
    expected_step = (
        (source_count - 1) / (target_count - 1)
        if target_count > 1
        else 0.0
    )
    max_step = max(3, int(math.ceil(expected_step)) + 2)
    transition_penalty = 0.015

    scores = np.full((target_count, source_count), -1e9, dtype=np.float32)
    previous = np.full((target_count, source_count), -1, dtype=np.int16)
    scores[0] = similarities[0]
    for target_index in range(1, target_count):
        for source_index in range(source_count):
            best_score = -1e9
            best_previous = -1
            for step in range(max_step + 1):
                previous_index = source_index - step
                if previous_index < 0:
                    break
                score = float(scores[target_index - 1, previous_index])
                score -= transition_penalty * abs(step - expected_step)
                if score > best_score:
                    best_score = score
                    best_previous = previous_index
            scores[target_index, source_index] = (
                best_score + similarities[target_index, source_index]
            )
            previous[target_index, source_index] = best_previous

    cursor = int(np.argmax(scores[-1]))
    mapping = [cursor]
    for target_index in range(target_count - 1, 0, -1):
        cursor = int(previous[target_index, cursor])
        mapping.append(cursor)
    mapping.reverse()
    chosen_scores = [
        float(similarities[target_index, source_index])
        for target_index, source_index in enumerate(mapping)
    ]
    return mapping, chosen_scores


def reset_adapter(directory: Path, stem: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.glob(f"{stem}_*"):
        if path.is_symlink():
            path.unlink()


def main() -> None:
    clean = json.loads(CLEAN_EXPORT.read_text(encoding="utf-8"))
    archive = json.loads(ALIGNMENT_ARCHIVE.read_text(encoding="utf-8"))
    sources = list(clean["sources"])
    corrections = [
        correction
        for correction in archive.get("corrections", [])
        if not correction.get("remove")
    ]
    corrected_sources = []
    for correction in corrections:
        source = next(
            (
                item
                for item in sources
                if str(correction["pathContains"]) in str(item.get("path") or "")
            ),
            None,
        )
        if source is None:
            raise RuntimeError(
                f"No clean source matches {correction['pathContains']}"
            )
        corrected_sources.append((source, correction))

    capture = cv2.VideoCapture(str(REFERENCE_MOVIE))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {REFERENCE_MOVIE}")
    records = []
    try:
        for source, correction in corrected_sources:
            start_frame = int(correction["timelineStartFrame"])
            end_frame = int(correction["timelineEndFrame"])
            first_source = int(source["selectedFirstFrame"])
            last_source = int(source["selectedLastFrame"])
            candidate_numbers = list(range(first_source, last_source + 1))
            candidate_paths = [
                source_frame_path(source, correction, frame)
                for frame in candidate_numbers
            ]
            missing = [str(path) for path in candidate_paths if not path.exists()]
            if missing:
                raise RuntimeError(
                    f"{source['id']} has {len(missing)} missing candidate frames; "
                    f"first: {missing[0]}"
                )

            final = reference_features(capture, start_frame, end_frame)
            render = source_features(candidate_paths)
            mapping, scores = monotonic_mapping(final, render)
            chosen_paths = [candidate_paths[index] for index in mapping]
            chosen_numbers = [candidate_numbers[index] for index in mapping]

            adapter_dir = MEDIA_ROOT / str(source["id"])
            adapter_stem = f"FRAME-ALIGNED-{source['id']}"
            reset_adapter(adapter_dir, adapter_stem)
            extension = chosen_paths[0].suffix.lower()
            for index, original in enumerate(chosen_paths):
                link = adapter_dir / f"{adapter_stem}_{index:06d}{extension}"
                link.symlink_to(original)

            steps = [
                chosen_numbers[index] - chosen_numbers[index - 1]
                for index in range(1, len(chosen_numbers))
            ]
            step_histogram = {
                str(step): steps.count(step) for step in sorted(set(steps))
            }
            record = {
                "sourceId": source["id"],
                "track": int(source["track"]),
                "pathContains": correction["pathContains"],
                "originalMediaPath": source["path"],
                "importPath": str(
                    adapter_dir / f"{adapter_stem}_000000{extension}"
                ),
                "timelineStartFrame": start_frame,
                "timelineEndFrame": end_frame,
                "timelineStart": start_frame / REFERENCE_FPS,
                "timelineEnd": end_frame / REFERENCE_FPS,
                "timelineStartTicks": str(start_frame * int(clean["timelineTimebaseTicksPerFrame"])),
                "timelineEndTicks": str(end_frame * int(clean["timelineTimebaseTicksPerFrame"])),
                "timelineFrameCount": end_frame - start_frame,
                "adapterFrameRate": REFERENCE_FPS,
                "candidateFirstFrame": first_source,
                "candidateLastFrame": last_source,
                "chosenFirstFrame": chosen_numbers[0],
                "chosenLastFrame": chosen_numbers[-1],
                "chosenSourceFrames": chosen_numbers,
                "chosenSourcePaths": [str(path) for path in chosen_paths],
                "stepHistogram": step_histogram,
                "similarity": {
                    "minimum": round(min(scores), 6),
                    "median": round(float(np.median(scores)), 6),
                    "mean": round(float(np.mean(scores)), 6),
                    "maximum": round(max(scores), 6),
                },
                "evidence": correction.get("evidence") or "confirmed",
                "detail": correction.get("detail") or "",
            }
            records.append(record)
            print(
                f"{source['id']} V{source['track']} "
                f"{start_frame}-{end_frame} -> "
                f"{chosen_numbers[0]}-{chosen_numbers[-1]} "
                f"median={record['similarity']['median']:.4f} "
                f"steps={step_histogram}",
                flush=True,
            )
    finally:
        capture.release()

    removed = [
        correction
        for correction in archive.get("corrections", [])
        if correction.get("remove")
    ]
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Direct monotonic frame matching against Paracosm Full Copy 01.mov; "
            "only proven correction intervals replace the recovered user conform."
        ),
        "baseProject": clean["workingProjectPath"],
        "baseSequence": clean["sequence"],
        "outputSequence": "Paracosm Conform Codex FRAME ALIGNED",
        "referenceMovie": str(REFERENCE_MOVIE),
        "timelineFrameRate": REFERENCE_FPS,
        "timebaseTicksPerFrame": int(clean["timelineTimebaseTicksPerFrame"]),
        "records": records,
        "removedSources": removed,
        "summary": {
            "replacementClips": len(records),
            "removedFalseSources": len(removed),
            "adapterFrames": sum(
                int(record["timelineFrameCount"]) for record in records
            ),
            "missingAdapterFrames": 0,
        },
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
