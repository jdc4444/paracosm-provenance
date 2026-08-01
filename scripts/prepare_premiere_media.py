#!/usr/bin/env python3
"""Prepare a Premiere import plan, including reversed symlink image sequences."""

from __future__ import annotations

import json
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "data" / "conform-manifest.json"
OUTPUT_PATH = APP_ROOT / "data" / "premiere" / "import-manifest.json"
MEDIA_ROOT = APP_ROOT / "data" / "premiere" / "media"


def concrete_frame(source_path: str, frame: int) -> Path:
    range_match = re.search(r"\[(\d+)-(\d+)\](\.[^.]+)$", source_path)
    if range_match:
        return Path(
            source_path[: range_match.start()]
            + str(frame).zfill(len(range_match.group(1)))
            + range_match.group(3)
        )
    match = re.search(r"(\d+)(\.[^.]+)$", source_path)
    if not match:
        return Path(source_path)
    return Path(
        source_path[: match.start(1)]
        + str(frame).zfill(len(match.group(1)))
        + match.group(2)
    )


def import_start(source_path: str) -> tuple[Path, int]:
    range_match = re.search(r"\[(\d+)-(\d+)\](\.[^.]+)$", source_path)
    if range_match:
        first = int(range_match.group(1))
        return (
            Path(
                source_path[: range_match.start()]
                + range_match.group(1)
                + range_match.group(3)
            ),
            first,
        )
    match = re.search(r"(\d+)(\.[^.]+)$", source_path)
    if not match:
        return Path(source_path), 0
    return Path(source_path), int(match.group(1))


def assign_lanes(segments: list[dict]) -> dict[str, int]:
    lane_ends: list[float] = []
    result = {}
    for segment in sorted(
        segments, key=lambda item: (float(item["finalStart"]), float(item["finalEnd"]))
    ):
        start = float(segment["finalStart"])
        lane = next(
            (index for index, end in enumerate(lane_ends) if end <= start + 1e-5),
            None,
        )
        if lane is None:
            lane = len(lane_ends)
            lane_ends.append(0.0)
        lane_ends[lane] = float(segment["finalEnd"])
        result[segment["id"]] = lane
    return result


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    segments = manifest["segments"]
    lanes = assign_lanes(segments)
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    records = []
    missing = []

    for segment in segments:
        fps = float(segment.get("sourceFrameRate") or manifest.get("frameRate") or 24)
        start_frame = int(segment["sourceStartFrame"])
        end_frame = int(segment["sourceEndFrame"])
        duration = float(segment["finalEnd"]) - float(segment["finalStart"])
        reversed_media = bool(segment.get("playBackwards"))

        if reversed_media:
            target_dir = MEDIA_ROOT / segment["id"]
            target_dir.mkdir(parents=True, exist_ok=True)
            # These directories are generated media adapters. Rebuild their
            # symlinks so a conform-ID shift cannot leave a previous segment's
            # reversed frames under the newly assigned ID.
            for old_link in target_dir.glob(f"{segment['id']}_*"):
                if old_link.is_symlink():
                    old_link.unlink()
            frames = list(
                range(
                    start_frame,
                    end_frame + (-1 if end_frame < start_frame else 1),
                    -1 if end_frame < start_frame else 1,
                )
            )
            extension = Path(str(segment["sourcePath"])).suffix.lower()
            for index, frame in enumerate(frames):
                original = concrete_frame(str(segment["sourcePath"]), frame)
                link = target_dir / f"{segment['id']}_{index:06d}{extension}"
                if not original.exists():
                    missing.append(f"{segment['id']} frame {frame}: {original}")
                    continue
                if not link.exists():
                    link.symlink_to(original)
            import_path = target_dir / f"{segment['id']}_000000{extension}"
            in_point = 0.0
        else:
            import_path, first_frame = import_start(str(segment["sourcePath"]))
            in_point = max(0.0, (start_frame - first_frame) / fps)

        records.append(
            {
                "segmentId": segment["id"],
                "importPath": str(import_path),
                "inPoint": round(in_point, 9),
                "outPoint": round(in_point + duration, 9),
                "lane": lanes[segment["id"]],
                "reversedMedia": reversed_media,
            }
        )

    payload = {
        "schemaVersion": 1,
        "sourceManifest": str(MANIFEST_PATH),
        "segments": records,
        "summary": {
            "segments": len(records),
            "lanes": max(lanes.values(), default=0) + 1,
            "reversedSequences": sum(
                1 for record in records if record["reversedMedia"]
            ),
            "missingFrames": len(missing),
        },
        "missingFrames": missing,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    if missing:
        raise SystemExit(f"{len(missing)} reverse source frames are missing")


if __name__ == "__main__":
    main()
