#!/usr/bin/env python3
"""Independently verify the saved frame-aligned Premiere deliverable."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "data" / "premiere" / "frame-aligned-manifest.json"
INVENTORY_PATH = APP_ROOT / "data" / "premiere" / "frame-aligned-latest.json"
STATUS_PATH = (
    APP_ROOT / "data" / "premiere" / "frame-aligned-premiere-status.json"
)
OUTPUT_PATH = (
    APP_ROOT / "data" / "premiere" / "frame-aligned-verification.json"
)
ARCHIVE_DIR = APP_ROOT / "public" / "archive" / "frame-aligned"


def feature(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    bgr = image[:, :, :3] if image.ndim == 3 else image
    gray = (
        cv2.cvtColor(
            cv2.resize(bgr, (320, 180), interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2GRAY,
        )
        if bgr.ndim == 3
        else cv2.resize(bgr, (320, 180), interpolation=cv2.INTER_AREA)
    ).astype(np.float32)
    gray = (gray - gray.mean()) / (gray.std() + 1e-6)
    edges = cv2.Laplacian(gray, cv2.CV_32F)
    edges = (edges - edges.mean()) / (edges.std() + 1e-6)
    return gray, edges


def similarity(first: np.ndarray, second: np.ndarray) -> dict[str, float]:
    first_gray, first_edges = feature(first)
    second_gray, second_edges = feature(second)
    luminance = float((first_gray * second_gray).mean())
    edges = float((first_edges * second_edges).mean())
    return {
        "luminanceCorrelation": round(luminance, 6),
        "edgeCorrelation": round(edges, 6),
        "structuralScore": round(0.7 * luminance + 0.3 * edges, 6),
    }


def reference_frame(capture: cv2.VideoCapture, frame: int) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, image = capture.read()
    if not ok:
        raise RuntimeError(f"Could not decode final reference frame {frame}")
    return image


def read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Could not read {path}")
    return image


def fit_labelled(
    image: np.ndarray,
    label: str,
    color: tuple[int, int, int],
) -> np.ndarray:
    bgr = image[:, :, :3] if image.ndim == 3 else cv2.cvtColor(
        image,
        cv2.COLOR_GRAY2BGR,
    )
    fitted = cv2.resize(bgr, (640, 360), interpolation=cv2.INTER_AREA)
    panel = np.full((396, 640, 3), 18, dtype=np.uint8)
    panel[36:] = fitted
    cv2.putText(
        panel,
        label,
        (14, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        color,
        1,
        cv2.LINE_AA,
    )
    return panel


def boundary_sheet(
    name: str,
    before_reference: np.ndarray,
    before_source: np.ndarray,
    after_reference: np.ndarray,
    after_source: np.ndarray,
) -> str:
    top = np.hstack(
        (
            fit_labelled(before_reference, "FINAL: frame before cut", (82, 244, 215)),
            fit_labelled(before_source, "SOURCE: frame before cut", (82, 244, 215)),
        )
    )
    bottom = np.hstack(
        (
            fit_labelled(after_reference, "FINAL: first frame after cut", (0, 220, 255)),
            fit_labelled(after_source, "SOURCE: first frame after cut", (0, 220, 255)),
        )
    )
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    output = ARCHIVE_DIR / f"{name}.jpg"
    cv2.imwrite(str(output), np.vstack((top, bottom)), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return f"/archive/frame-aligned/{output.name}"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    sequence = inventory["sequence"]
    failures = []
    clip_checks = []

    if not status.get("success"):
        failures.append("Premiere build status did not report success")
    if sequence.get("name") != manifest.get("outputSequence"):
        failures.append("Saved project sequence name differs from the manifest")
    video_tracks = sequence.get("videoTracks", [])
    audio_tracks = sequence.get("audioTracks", [])
    if len(video_tracks) < 2:
        failures.append("Saved project has fewer than two video tracks")
    if not audio_tracks or len(audio_tracks[0].get("clips", [])) != 6:
        failures.append("Saved project did not preserve six chapter audio clips")

    for record in manifest["records"]:
        track = video_tracks[int(record["track"]) - 1]
        matches = [
            clip
            for clip in track.get("clips", [])
            if str((clip.get("projectItem") or {}).get("mediaPath") or "")
            == str(record["importPath"])
        ]
        if len(matches) != 1:
            failures.append(
                f"{record['sourceId']}: expected one saved clip, found {len(matches)}"
            )
            continue
        clip = matches[0]
        start_ticks = int(clip["start"]["ticks"])
        end_ticks = int(clip["end"]["ticks"])
        adapter_dir = Path(record["importPath"]).parent
        adapter_files = sorted(adapter_dir.glob("FRAME-ALIGNED-*"))
        broken_links = [
            str(path)
            for path in adapter_files
            if path.is_symlink() and not path.exists()
        ]
        valid = (
            start_ticks == int(record["timelineStartTicks"])
            and end_ticks == int(record["timelineEndTicks"])
            and len(adapter_files) == int(record["timelineFrameCount"])
            and not broken_links
        )
        if not valid:
            failures.append(f"{record['sourceId']}: saved clip or adapter mismatch")
        clip_checks.append(
            {
                "sourceId": record["sourceId"],
                "track": record["track"],
                "timelineStartFrame": record["timelineStartFrame"],
                "timelineEndFrame": record["timelineEndFrame"],
                "savedStartTicks": str(start_ticks),
                "savedEndTicks": str(end_ticks),
                "adapterFrames": len(adapter_files),
                "brokenAdapterLinks": len(broken_links),
                "verified": valid,
            }
        )

    records = {item["sourceId"]: item for item in manifest["records"]}
    boundary_specs = [
        (
            "cuts-39-40",
            4340,
            "CLEAN-SRC-038",
            "CLEAN-SRC-039",
            "User-reported previous-shot tail at the wide-to-carousel boundary",
        ),
        (
            "cuts-44-45",
            4827,
            "CLEAN-SRC-043",
            "CLEAN-SRC-044",
            "False horse close-up removed; POV now runs to the true wide cut",
        ),
        (
            "cuts-57-58",
            5927,
            "CLEAN-SRC-055",
            "CLEAN-SRC-056",
            "LayDownRoof continuation retained through the true InsideRip cut",
        ),
    ]
    capture = cv2.VideoCapture(str(manifest["referenceMovie"]))
    if not capture.isOpened():
        raise RuntimeError("Could not open final reference movie")
    boundaries = []
    try:
        for name, frame, before_id, after_id, detail in boundary_specs:
            before_record = records[before_id]
            after_record = records[after_id]
            before_adapter = sorted(
                Path(before_record["importPath"]).parent.glob("FRAME-ALIGNED-*")
            )[-1]
            after_adapter = sorted(
                Path(after_record["importPath"]).parent.glob("FRAME-ALIGNED-*")
            )[0]
            final_before = reference_frame(capture, frame - 1)
            final_after = reference_frame(capture, frame)
            source_before = read_image(before_adapter.resolve())
            source_after = read_image(after_adapter.resolve())
            before_score = similarity(final_before, source_before)
            after_score = similarity(final_after, source_after)
            screenshot = boundary_sheet(
                name,
                final_before,
                source_before,
                final_after,
                source_after,
            )
            verified = (
                int(before_record["timelineEndFrame"]) == frame
                and int(after_record["timelineStartFrame"]) == frame
                and before_score["structuralScore"] >= 0.30
                and after_score["structuralScore"] >= 0.30
            )
            if not verified:
                failures.append(f"{name}: boundary frame comparison failed")
            boundaries.append(
                {
                    "id": name,
                    "frame": frame,
                    "detail": detail,
                    "beforeSourceId": before_id,
                    "afterSourceId": after_id,
                    "beforeAdapterFrame": str(before_adapter.resolve()),
                    "afterAdapterFrame": str(after_adapter.resolve()),
                    "beforeScore": before_score,
                    "afterScore": after_score,
                    "screenshot": screenshot,
                    "verified": verified,
                }
            )
    finally:
        capture.release()

    false_horse_cu_present = any(
        "3m_horse cu" in str((clip.get("projectItem") or {}).get("mediaPath") or "")
        for track in video_tracks[:2]
        for clip in track.get("clips", [])
    )
    if false_horse_cu_present:
        failures.append("The false 3m_horse cu source remains in V1/V2")

    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "project": status.get("projectExport"),
        "sequence": sequence.get("name"),
        "referenceMovie": manifest.get("referenceMovie"),
        "clipChecks": clip_checks,
        "boundaries": boundaries,
        "summary": {
            "success": not failures,
            "savedV1Clips": len(video_tracks[0].get("clips", [])),
            "savedV2Clips": len(video_tracks[1].get("clips", [])),
            "savedCanonicalSourceClips": sum(
                len(track.get("clips", [])) for track in video_tracks[:2]
            ),
            "chapterAudioClips": len(audio_tracks[0].get("clips", [])),
            "verifiedReplacementClips": sum(
                int(item["verified"]) for item in clip_checks
            ),
            "verifiedBoundaries": sum(
                int(item["verified"]) for item in boundaries
            ),
            "falseHorseCloseupPresent": false_horse_cu_present,
            "failures": failures,
        },
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    for boundary in boundaries:
        print(
            f"{boundary['id']} frame={boundary['frame']} "
            f"before={boundary['beforeScore']['structuralScore']:.4f} "
            f"after={boundary['afterScore']['structuralScore']:.4f} "
            f"verified={boundary['verified']}"
        )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
