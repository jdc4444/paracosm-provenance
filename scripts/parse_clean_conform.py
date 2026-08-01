#!/usr/bin/env python3
"""Normalize the user-cleaned V1/V2 Premiere conform for the atlas.

The exported Premiere inventory is authoritative. V1 and V2 contain the
canonical visible source-render clip instances. Audio 1 contains six contiguous
clips whose edit points are the chapter boundaries. Timeline and source ticks
are retained verbatim; frame indices are derived from the exported tick rates,
not from rounded wall-clock seconds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = APP_ROOT / "data" / "premiere" / "clean-conform-latest.json"
DEFAULT_OUTPUT = APP_ROOT / "data" / "premiere" / "clean-conform-export.json"
CONFORM_MANIFEST = APP_ROOT / "data" / "conform-manifest.json"
VISUAL_ALIGNMENT = APP_ROOT / "data" / "clean-conform-visual-alignment.json"
FRAME_ALIGNED_MANIFEST = (
    APP_ROOT / "data" / "premiere" / "frame-aligned-manifest.json"
)
FRAME_ALIGNED_STATUS = (
    APP_ROOT / "data" / "premiere" / "frame-aligned-premiere-status.json"
)
FRAME_ALIGNED_VERIFICATION = (
    APP_ROOT / "data" / "premiere" / "frame-aligned-verification.json"
)

SECTION_ORDER = [
    ("ND", "Natural Disaster"),
    ("NTH", "Nothing to Hide"),
    ("TH", "Teardrop"),
    ("NA", "New Again"),
    ("GG", "Goodbye Glitter"),
    ("IJDKYY", "If You Don't Know Yourself Yet"),
]


def _frame_number(path: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)(?=\.[^.]+$)", Path(path).name)
    if not match:
        return None, None
    return int(match.group(1)), len(match.group(1))


def _ticks(value: dict[str, Any] | None) -> int:
    if not value:
        return 0
    return int(str(value.get("ticks") or 0))


def _seconds(value: dict[str, Any] | None) -> float:
    if not value:
        return 0.0
    return float(value.get("seconds") or 0.0)


def _frame_from_ticks(ticks: int, ticks_per_frame: int) -> int:
    return int(round(ticks / ticks_per_frame))


def _source_frame_offset(
    ticks: int,
    ticks_per_second: int,
    source_fps: float,
) -> int:
    return int(round((ticks / ticks_per_second) * source_fps))


def _section_for(
    start: float,
    end: float,
    chapters: list[dict[str, Any]],
) -> dict[str, Any]:
    midpoint = (start + end) / 2
    return next(
        (
            chapter
            for chapter in chapters
            if float(chapter["start"]) - 1e-7
            <= midpoint
            < float(chapter["end"]) + 1e-7
        ),
        chapters[-1],
    )


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_source_id(name: str, media_path: str) -> str | None:
    for value in (name, Path(media_path).name, Path(media_path).parent.name):
        match = re.search(r"\bSRC-(\d{3})\b", value, flags=re.IGNORECASE)
        if match:
            return f"SRC-{match.group(1)}"
    return None


def _resolved_reverse_frame(
    media_path: str,
    local_frame: int,
) -> tuple[str | None, int | None]:
    path = Path(media_path)
    number, padding = _frame_number(media_path)
    if number is None or padding is None:
        return None, None
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    if not match:
        return None, None
    target = path.with_name(
        path.name[: match.start()]
        + f"{number + local_frame:0{padding}d}"
        + path.name[match.end() :]
    )
    try:
        resolved = target.resolve(strict=True)
    except OSError:
        return None, None
    resolved_frame, _ = _frame_number(str(resolved))
    return str(resolved), resolved_frame


def _selected_media_health(
    source_path: str,
    selected_first: int | None,
    selected_last: int | None,
) -> dict[str, Any]:
    path = Path(source_path)
    if selected_first is None or selected_last is None:
        exists = path.exists()
        return {
            "status": "complete" if exists else "missing",
            "expectedFrames": 1,
            "availableFrames": int(exists),
            "missingFrames": 0 if exists else 1,
            "selectedFirstFrame": selected_first,
            "selectedLastFrame": selected_last,
        }
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    if not match:
        exists = path.exists()
        return {
            "status": "complete" if exists else "missing",
            "expectedFrames": 1,
            "availableFrames": int(exists),
            "missingFrames": 0 if exists else 1,
            "selectedFirstFrame": selected_first,
            "selectedLastFrame": selected_last,
        }
    low = min(int(selected_first), int(selected_last))
    high = max(int(selected_first), int(selected_last))
    missing = []
    for frame in range(low, high + 1):
        frame_path = path.with_name(
            path.name[: match.start()]
            + f"{frame:0{len(match.group(1))}d}"
            + path.name[match.end() :]
        )
        if not frame_path.exists():
            missing.append(frame)
    expected = high - low + 1
    return {
        "status": "complete" if not missing else "incomplete",
        "expectedFrames": expected,
        "availableFrames": expected - len(missing),
        "missingFrames": len(missing),
        "missingFirstFrame": missing[0] if missing else None,
        "missingLastFrame": missing[-1] if missing else None,
        "selectedFirstFrame": selected_first,
        "selectedLastFrame": selected_last,
    }


def _frame_path(path_value: str, frame: int) -> str:
    path = Path(path_value)
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    if not match:
        return path_value
    return str(
        path.with_name(
            path.name[: match.start()]
            + f"{frame:0{len(match.group(1))}d}"
            + path.name[match.end() :]
        )
    )


def _aligned_media_health(
    source: dict[str, Any],
    correction: dict[str, Any],
) -> dict[str, Any]:
    first = int(source["selectedFirstFrame"])
    last = int(source["selectedLastFrame"])
    prefix_change = correction.get("framePrefixChangesAt")
    prefix = str(correction.get("framePrefix") or "")
    available = 0
    missing = []
    for frame in range(first, last + 1):
        if prefix_change is not None and frame >= int(prefix_change):
            candidate = Path(source["renderDirectory"]) / (
                f"{prefix}{frame:04d}{Path(source['path']).suffix}"
            )
        else:
            candidate = Path(_frame_path(str(source["path"]), frame))
        if candidate.exists():
            available += 1
        else:
            missing.append(frame)
    expected = last - first + 1
    return {
        "status": "complete" if not missing else "incomplete",
        "expectedFrames": expected,
        "availableFrames": available,
        "missingFrames": len(missing),
        "missingFirstFrame": missing[0] if missing else None,
        "missingLastFrame": missing[-1] if missing else None,
        "selectedFirstFrame": first,
        "selectedLastFrame": last,
        "framePrefixChange": (
            {
                "atFrame": int(prefix_change),
                "prefix": prefix,
            }
            if prefix_change is not None
            else None
        ),
    }


def _apply_visual_alignment(
    sources: list[dict[str, Any]],
    *,
    ticks_per_frame: int,
    ticks_per_second: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not VISUAL_ALIGNMENT.exists():
        return sources, []
    archive = json.loads(VISUAL_ALIGNMENT.read_text(encoding="utf-8"))
    corrections = list(archive.get("corrections", []))
    applied = []
    kept = []
    for source in sources:
        correction = next(
            (
                item
                for item in corrections
                if str(item.get("pathContains") or "") in str(source.get("path") or "")
            ),
            None,
        )
        if not correction:
            kept.append(source)
            continue
        applied.append(
            {
                "sourcePath": source.get("path"),
                **correction,
            }
        )
        if correction.get("remove"):
            continue

        start_frame = int(correction.get("timelineStartFrame", source["startFrame"]))
        end_frame = int(correction.get("timelineEndFrame", source["endFrame"]))
        source["startFrame"] = start_frame
        source["endFrame"] = end_frame
        source["durationFrames"] = end_frame - start_frame
        source["startTicks"] = start_frame * ticks_per_frame
        source["endTicks"] = end_frame * ticks_per_frame
        source["start"] = source["startTicks"] / ticks_per_second
        source["end"] = source["endTicks"] / ticks_per_second
        source["duration"] = source["end"] - source["start"]
        source["visualAlignment"] = {
            "authority": "exact_reference_frame_match",
            "evidence": correction.get("evidence") or "confirmed",
            "detail": correction.get("detail") or "",
            "originalPremiereStartFrame": _frame_from_ticks(
                int(source.get("startTicksOriginal") or source["startTicks"]),
                ticks_per_frame,
            ),
        }

        first = correction.get("selectedFirstFrame")
        last = correction.get("selectedLastFrame")
        if first is not None:
            source["selectedFirstFrame"] = int(first)
        if last is not None:
            source["selectedLastFrame"] = int(last)
            source["selectedEndFrameExclusive"] = int(last) + 1
        if source.get("mediaFirstFrame") is not None:
            media_first = int(source["mediaFirstFrame"])
            source["sourceInFrameOffset"] = (
                int(source["selectedFirstFrame"]) - media_first
            )
            source["sourceOutFrameOffset"] = (
                int(source["selectedLastFrame"]) - media_first + 1
            )
            source["sourceInTicks"] = (
                source["sourceInFrameOffset"] * ticks_per_frame
            )
            source["sourceOutTicks"] = (
                source["sourceOutFrameOffset"] * ticks_per_frame
            )
            source["sourceIn"] = source["sourceInTicks"] / ticks_per_second
            source["sourceOut"] = source["sourceOutTicks"] / ticks_per_second
        if correction.get("selectedLastFramePath"):
            source["selectedLastFramePath"] = correction["selectedLastFramePath"]
        source["sourceMediaHealth"] = _aligned_media_health(source, correction)
        kept.append(source)
    return kept, applied


def _apply_frame_aligned_conform(
    sources: list[dict[str, Any]],
    *,
    ticks_per_frame: int,
    ticks_per_second: int,
) -> dict[str, Any] | None:
    required = (
        FRAME_ALIGNED_MANIFEST,
        FRAME_ALIGNED_STATUS,
        FRAME_ALIGNED_VERIFICATION,
    )
    if not all(path.exists() for path in required):
        return None
    manifest = json.loads(FRAME_ALIGNED_MANIFEST.read_text(encoding="utf-8"))
    status = json.loads(FRAME_ALIGNED_STATUS.read_text(encoding="utf-8"))
    verification = json.loads(
        FRAME_ALIGNED_VERIFICATION.read_text(encoding="utf-8")
    )
    if not status.get("success") or not (
        verification.get("summary") or {}
    ).get("success"):
        return None

    records = {
        str(item["sourceId"]): item for item in manifest.get("records", [])
    }
    proofs_by_source: dict[str, list[dict[str, Any]]] = {}
    for boundary in verification.get("boundaries", []):
        for role, source_key in (
            ("before", "beforeSourceId"),
            ("after", "afterSourceId"),
        ):
            source_id = str(boundary.get(source_key) or "")
            if not source_id:
                continue
            proofs_by_source.setdefault(source_id, []).append(
                {
                    "id": boundary.get("id"),
                    "role": role,
                    "frame": boundary.get("frame"),
                    "detail": boundary.get("detail"),
                    "screenshot": boundary.get("screenshot"),
                    "beforeScore": boundary.get("beforeScore"),
                    "afterScore": boundary.get("afterScore"),
                    "verified": boundary.get("verified"),
                }
            )

    for source in sources:
        record = records.get(str(source["id"]))
        if not record:
            continue
        source["selectedFirstFrame"] = int(record["chosenFirstFrame"])
        source["selectedLastFrame"] = int(record["chosenLastFrame"])
        source["selectedEndFrameExclusive"] = (
            int(record["chosenLastFrame"]) + 1
        )
        chosen_paths = list(record.get("chosenSourcePaths") or [])
        if chosen_paths:
            source["selectedFirstFramePath"] = chosen_paths[0]
            source["selectedLastFramePath"] = chosen_paths[-1]
        duration_ticks = int(source["endTicks"]) - int(source["startTicks"])
        source["premiereMediaPath"] = record["importPath"]
        source["sourceInTicks"] = 0
        source["sourceOutTicks"] = duration_ticks
        source["sourceIn"] = 0.0
        source["sourceOut"] = duration_ticks / ticks_per_second
        source["sourceInFrameOffset"] = 0
        source["sourceOutFrameOffset"] = int(record["timelineFrameCount"])
        source["sourceFrameRate"] = float(record["adapterFrameRate"])
        source["sourceFrameRateOverridden"] = True
        source["sourceMediaHealth"] = {
            "status": "complete",
            "expectedFrames": int(record["timelineFrameCount"]),
            "availableFrames": int(record["timelineFrameCount"]),
            "missingFrames": 0,
            "selectedFirstFrame": int(record["chosenFirstFrame"]),
            "selectedLastFrame": int(record["chosenLastFrame"]),
            "adapterFrames": int(record["timelineFrameCount"]),
            "adapterPath": record["importPath"],
        }
        source["frameAlignedConform"] = {
            "authority": "direct_monotonic_reference_frame_matching",
            "project": status["projectExport"],
            "sequence": manifest["outputSequence"],
            "adapterPath": record["importPath"],
            "adapterFrameRate": record["adapterFrameRate"],
            "adapterFrames": record["timelineFrameCount"],
            "chosenFirstFrame": record["chosenFirstFrame"],
            "chosenLastFrame": record["chosenLastFrame"],
            "stepHistogram": record["stepHistogram"],
            "similarity": record["similarity"],
            "proofs": proofs_by_source.get(str(source["id"]), []),
            "verified": True,
        }

    return {
        "manifestPath": str(FRAME_ALIGNED_MANIFEST),
        "verificationPath": str(FRAME_ALIGNED_VERIFICATION),
        "projectPath": status["projectExport"],
        "fcpXmlPath": status.get("fcpXml"),
        "sequence": manifest["outputSequence"],
        "summary": verification["summary"],
    }


def _source_record(
    clip: dict[str, Any],
    *,
    source_index: int,
    track_number: int,
    chapters: list[dict[str, Any]],
    ticks_per_frame: int,
    ticks_per_second: int,
    reverse_sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    start_ticks = _ticks(clip.get("start"))
    end_ticks = _ticks(clip.get("end"))
    in_ticks = _ticks(clip.get("inPoint"))
    out_ticks = _ticks(clip.get("outPoint"))
    start = _seconds(clip.get("start"))
    end = _seconds(clip.get("end"))
    media_path = str((clip.get("projectItem") or {}).get("mediaPath") or "")
    source_fps = float(
        (
            (clip.get("projectItem") or {})
            .get("footageInterpretation", {})
            .get("frameRate")
        )
        or 24.0
    )
    if source_fps < 1:
        source_fps = 24.0
    legacy_id = _legacy_source_id(str(clip.get("name") or ""), media_path)
    reverse_manifest = reverse_sources.get(legacy_id or "")
    play_backwards = bool(reverse_manifest and "/data/premiere/media/" in media_path)
    source_path = (
        str(reverse_manifest.get("sourcePath") or media_path)
        if reverse_manifest
        else media_path
    )
    is_image_sequence = Path(source_path).suffix.lower() in {
        ".tif",
        ".tiff",
        ".exr",
        ".png",
        ".jpg",
        ".jpeg",
    }
    media_first_frame, frame_padding = (
        _frame_number(source_path)
        if is_image_sequence
        else (None, None)
    )
    in_offset = _source_frame_offset(
        in_ticks,
        ticks_per_second,
        source_fps,
    )
    out_offset = _source_frame_offset(
        out_ticks,
        ticks_per_second,
        source_fps,
    )
    selected_first = (
        media_first_frame + in_offset
        if media_first_frame is not None
        else None
    )
    selected_last = (
        media_first_frame + out_offset - 1
        if media_first_frame is not None
        else None
    )
    selected_first_path = None
    selected_last_path = None
    if play_backwards:
        selected_first_path, selected_first = _resolved_reverse_frame(
            media_path,
            in_offset,
        )
        selected_last_path, selected_last = _resolved_reverse_frame(
            media_path,
            max(in_offset, out_offset - 1),
        )
        media_first_frame, frame_padding = _frame_number(source_path)

    chapter = _section_for(start, end, chapters)
    start_frame = _frame_from_ticks(start_ticks, ticks_per_frame)
    end_frame = _frame_from_ticks(end_ticks, ticks_per_frame)
    record = {
        "id": f"CLEAN-SRC-{source_index:03d}",
        "legacySourceId": legacy_id,
        "origin": "clean_v1_v2",
        "canonicalLayer": f"V{track_number}",
        "track": track_number,
        "role": "exact_match",
        "name": str(clip.get("name") or ""),
        "path": source_path,
        "premiereMediaPath": media_path,
        "renderDirectory": str(Path(source_path).parent) if source_path else "",
        "sectionCode": chapter["sectionCode"],
        "sectionName": chapter["sectionName"],
        "startTicks": start_ticks,
        "endTicks": end_ticks,
        "start": start,
        "end": end,
        "duration": end - start,
        "startFrame": start_frame,
        "endFrame": end_frame,
        "durationFrames": end_frame - start_frame,
        "sourceInTicks": in_ticks,
        "sourceOutTicks": out_ticks,
        "sourceIn": _seconds(clip.get("inPoint")),
        "sourceOut": _seconds(clip.get("outPoint")),
        "sourceInFrameOffset": in_offset,
        "sourceOutFrameOffset": out_offset,
        "mediaFirstFrame": media_first_frame,
        "mediaFramePadding": frame_padding,
        "selectedFirstFrame": selected_first,
        "selectedEndFrameExclusive": (
            selected_last + (-1 if play_backwards else 1)
            if selected_last is not None
            else None
        ),
        "selectedLastFrame": selected_last,
        "selectedFirstFramePath": selected_first_path,
        "selectedLastFramePath": selected_last_path,
        "playBackwards": play_backwards,
        "sourceFrameRate": source_fps,
        "sourceFrameRateOverridden": True,
        "premiereLabel": None,
        "premiereLabelExpected": f"Canonical V{track_number}",
        "premiereLabelExpectedIndex": None,
        "manualTrimAuthority": True,
        "projectItemNodeId": str(
            (clip.get("projectItem") or {}).get("nodeId") or ""
        ),
        "clipNodeId": str(clip.get("nodeId") or ""),
    }
    record["sourceMediaHealth"] = _selected_media_health(
        source_path,
        selected_first,
        selected_last,
    )
    return record


def _chapter_records(
    audio_clips: list[dict[str, Any]],
    ticks_per_frame: int,
) -> list[dict[str, Any]]:
    # The current user-saved Clean sequence has one internal Audio 1 edit
    # inside ND: the first clip plays source audio 00:00:00:00–00:00:05:02,
    # then the next clip resumes after the removed slate.  It is not a
    # chapter boundary.  Preserve the saved edit as evidence, but merge those
    # two contiguous timeline pieces into one logical ND chapter before
    # applying the user's six-chapter contract.
    ignored_internal_edits: list[dict[str, Any]] = []
    if len(audio_clips) == len(SECTION_ORDER) + 1:
        first, second = audio_clips[:2]
        first_path = str((first.get("projectItem") or {}).get("mediaPath") or "")
        second_path = str((second.get("projectItem") or {}).get("mediaPath") or "")
        if (
            _ticks(first.get("end")) == _ticks(second.get("start"))
            and first_path
            and first_path == second_path
        ):
            merged = dict(first)
            merged["end"] = second.get("end")
            merged["duration"] = {
                "ticks": str(
                    _ticks(second.get("end")) - _ticks(first.get("start"))
                ),
                "seconds": (
                    _seconds(second.get("end")) - _seconds(first.get("start"))
                ),
            }
            ignored_internal_edits.append(
                {
                    "timelineTicks": _ticks(first.get("end")),
                    "timelineSeconds": _seconds(first.get("end")),
                    "leftAudioClipIndex": int(first.get("clipIndex") or 0),
                    "rightAudioClipIndex": int(second.get("clipIndex") or 1),
                    "reason": "internal_slate_removal_not_chapter_boundary",
                }
            )
            audio_clips = [merged, *audio_clips[2:]]
    if len(audio_clips) != len(SECTION_ORDER):
        raise ValueError(
            "Expected six Audio 1 clips for chapter boundaries; "
            f"found {len(audio_clips)}."
        )
    chapters = []
    for index, (clip, (code, name)) in enumerate(
        zip(audio_clips, SECTION_ORDER, strict=True),
        start=1,
    ):
        start_ticks = _ticks(clip.get("start"))
        end_ticks = _ticks(clip.get("end"))
        chapters.append(
            {
                "id": f"chapter-{index}",
                "sectionCode": code,
                "sectionName": name,
                "audioTrack": 1,
                "audioClipIndex": index - 1,
                "audioClipName": str(clip.get("name") or ""),
                "audioMediaPath": str(
                    (clip.get("projectItem") or {}).get("mediaPath") or ""
                ),
                "startTicks": start_ticks,
                "endTicks": end_ticks,
                "start": _seconds(clip.get("start")),
                "end": _seconds(clip.get("end")),
                "startFrame": _frame_from_ticks(start_ticks, ticks_per_frame),
                "endFrame": _frame_from_ticks(end_ticks, ticks_per_frame),
                "boundaryAuthority": "saved_audio_track_edit_points",
                "evidence": "confirmed",
                "ignoredInternalEditPoints": (
                    ignored_internal_edits if index == 1 else []
                ),
            }
        )
    for previous, current in zip(chapters, chapters[1:]):
        if previous["endTicks"] != current["startTicks"]:
            raise ValueError(
                "Audio chapter clips are not contiguous at "
                f"{previous['sectionCode']}→{current['sectionCode']}."
            )
    return chapters


def _gap_records(
    sources: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
    ticks_per_frame: int,
) -> list[dict[str, Any]]:
    boundaries = sorted(
        {
            int(chapter["startTicks"]) for chapter in chapters
        }
        | {int(chapter["endTicks"]) for chapter in chapters}
        | {int(source["startTicks"]) for source in sources}
        | {int(source["endTicks"]) for source in sources}
    )
    gaps = []
    for start_ticks, end_ticks in zip(boundaries, boundaries[1:]):
        if end_ticks <= start_ticks:
            continue
        covered = any(
            int(source["startTicks"]) <= start_ticks
            and int(source["endTicks"]) >= end_ticks
            for source in sources
        )
        if covered:
            continue
        start = start_ticks / chapters[0].get("ticksPerSecond", 254_016_000_000)
        end = end_ticks / chapters[0].get("ticksPerSecond", 254_016_000_000)
        chapter = _section_for(start, end, chapters)
        gaps.append(
            {
                "role": "intentional_blank",
                "track": 0,
                "name": "Premiere V1/V2 intentional black",
                "path": "",
                "renderDirectory": None,
                "sectionCode": chapter["sectionCode"],
                "sectionName": chapter["sectionName"],
                "startTicks": start_ticks,
                "endTicks": end_ticks,
                "start": start,
                "end": end,
                "duration": end - start,
                "startFrame": _frame_from_ticks(start_ticks, ticks_per_frame),
                "endFrame": _frame_from_ticks(end_ticks, ticks_per_frame),
                "durationFrames": (
                    _frame_from_ticks(end_ticks, ticks_per_frame)
                    - _frame_from_ticks(start_ticks, ticks_per_frame)
                ),
                "sourceCoverage": {
                    "status": "intentional_blank",
                    "roles": [],
                    "sourceIds": [],
                    "overlaps": [],
                    "coveredFrames": 0,
                    "exactFrames": 0,
                    "totalFrames": (
                        _frame_from_ticks(end_ticks, ticks_per_frame)
                        - _frame_from_ticks(start_ticks, ticks_per_frame)
                    ),
                    "coverage": 0.0,
                    "exactCoverage": 0.0,
                    "fullyTracked": False,
                    "fullyExact": False,
                },
            }
        )
    return gaps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    exported = json.loads(args.input.read_text(encoding="utf-8"))
    if not exported.get("success"):
        raise SystemExit("The Clean conform export did not report success.")
    sequence = exported["sequence"]
    if sequence.get("name") != "Paracosm Conform Codex JD Clean":
        raise SystemExit(f"Unexpected sequence: {sequence.get('name')}")

    ticks_per_second = int(sequence.get("ticksPerSecond") or 254_016_000_000)
    ticks_per_frame = int(sequence["timebaseTicksPerFrame"])
    timeline_fps = ticks_per_second / ticks_per_frame
    audio_track = next(
        (
            track
            for track in sequence.get("audioTracks", [])
            if int(track.get("trackIndex") or 0) == 0
        ),
        None,
    )
    if audio_track is None:
        raise SystemExit("Audio 1 was not found.")
    chapters = _chapter_records(audio_track.get("clips", []), ticks_per_frame)
    for chapter in chapters:
        chapter["ticksPerSecond"] = ticks_per_second

    conform_manifest = (
        json.loads(CONFORM_MANIFEST.read_text(encoding="utf-8"))
        if CONFORM_MANIFEST.exists()
        else {}
    )
    reverse_sources = {
        str(item.get("id")): item
        for item in conform_manifest.get("segments", [])
        if item.get("playBackwards")
    }

    sources = []
    for track in sequence.get("videoTracks", [])[:2]:
        track_number = int(track.get("trackIndex") or 0) + 1
        for clip in track.get("clips", []):
            sources.append(
                _source_record(
                    clip,
                    source_index=len(sources) + 1,
                    track_number=track_number,
                    chapters=chapters,
                    ticks_per_frame=ticks_per_frame,
                    ticks_per_second=ticks_per_second,
                    reverse_sources=reverse_sources,
                )
            )
    for source in sources:
        source["startTicksOriginal"] = source["startTicks"]
        source["endTicksOriginal"] = source["endTicks"]
        source["startFrameOriginal"] = source["startFrame"]
        source["endFrameOriginal"] = source["endFrame"]
    sources, visual_alignment = _apply_visual_alignment(
        sources,
        ticks_per_frame=ticks_per_frame,
        ticks_per_second=ticks_per_second,
    )
    sources.sort(key=lambda item: (item["startTicks"], item["track"]))
    for index, source in enumerate(sources, start=1):
        source["id"] = f"CLEAN-SRC-{index:03d}"
    frame_aligned = _apply_frame_aligned_conform(
        sources,
        ticks_per_frame=ticks_per_frame,
        ticks_per_second=ticks_per_second,
    )

    for previous, current in zip(sources, sources[1:]):
        if int(current["startTicks"]) < int(previous["endTicks"]):
            raise SystemExit(
                "Canonical V1/V2 clips overlap: "
                f"{previous['name']} and {current['name']}."
            )

    gaps = _gap_records(sources, chapters, ticks_per_frame)
    inventory = [
        {
            **source,
            "sourceCoverage": {
                "status": "exact_match",
                "roles": ["exact_match"],
                "sourceIds": [source["id"]],
                "overlaps": [
                    {
                        "sourceId": source["id"],
                        "role": "exact_match",
                        "track": source["track"],
                        "overlapStartFrame": source["startFrame"],
                        "overlapEndFrame": source["endFrame"],
                        "overlapFrames": source["durationFrames"],
                    }
                ],
                "coveredFrames": source["durationFrames"],
                "exactFrames": source["durationFrames"],
                "totalFrames": source["durationFrames"],
                "coverage": 1.0,
                "exactCoverage": 1.0,
                "fullyTracked": True,
                "fullyExact": True,
            },
        }
        for source in sources
    ]
    inventory.extend(gaps)
    inventory.sort(key=lambda item: (item["startTicks"], item["track"]))
    for index, item in enumerate(inventory, start=1):
        item["canonicalId"] = f"CUT-{index:03d}"
        item["canonicalIndex"] = index

    project_export = Path(
        str(
            (frame_aligned or {}).get("projectPath")
            or exported.get("projectExport")
            or ""
        )
    )
    chapter_duration = float(chapters[-1]["end"])
    visible_duration = sum(float(item["duration"]) for item in sources)
    blank_duration = sum(float(item["duration"]) for item in gaps)
    incomplete_sources = [
        item
        for item in sources
        if (item.get("sourceMediaHealth") or {}).get("status") != "complete"
    ]
    output = {
        "schemaVersion": 2,
        "authorityKind": "clean_v1_v2",
        "authority": (
            "User-cleaned Premiere V1/V2 source clips plus exact reference-frame "
            "alignment are the canonical visible conform; Audio 1 edit points "
            "are chapter boundaries."
        ),
        "projectPath": str(project_export),
        "workingProjectPath": str(
            (frame_aligned or {}).get("projectPath")
            or exported.get("projectPath")
            or ""
        ),
        "projectSha256": _sha256(project_export),
        "fcpXmlPath": str(
            (frame_aligned or {}).get("fcpXmlPath")
            or exported.get("fcpXml")
            or ""
        ),
        "premiereInventoryPath": str(args.input),
        "sequence": (
            (frame_aligned or {}).get("sequence") or sequence["name"]
        ),
        "sequenceId": sequence.get("sequenceId"),
        "timelineFrameRate": timeline_fps,
        "timelineFrameDuration": 1 / timeline_fps,
        "timelineTimebaseTicksPerFrame": ticks_per_frame,
        "ticksPerSecond": ticks_per_second,
        "sourceImageFrameRate": 24.0,
        "canonicalTracks": [1, 2],
        "chapterBoundaryTrack": 1,
        "chapterCuts": chapters,
        "visualAlignment": {
            "path": str(VISUAL_ALIGNMENT),
            "appliedCorrections": visual_alignment,
        },
        "frameAlignedConform": frame_aligned,
        "sources": sources,
        "inventory": inventory,
        "summary": {
            "pictureClips": len(sources),
            "intentionalBlanks": len(gaps),
            "inventoryIntervals": len(inventory),
            "canonicalSources": len(sources),
            "v1CanonicalSources": sum(
                int(item["track"]) == 1 for item in sources
            ),
            "v2CanonicalSources": sum(
                int(item["track"]) == 2 for item in sources
            ),
            "chapterCuts": len(chapters),
            "visibleDuration": visible_duration,
            "intentionalBlankDuration": blank_duration,
            "chapterDuration": chapter_duration,
            "allClipInstancesLinked": all(
                bool(item.get("path")) for item in sources
            ),
            "allSelectedRenderFramesPresent": not incomplete_sources,
            "completeSourceClips": len(sources) - len(incomplete_sources),
            "incompleteSourceClips": len(incomplete_sources),
            "missingSelectedRenderFrames": sum(
                int(
                    (item.get("sourceMediaHealth") or {}).get(
                        "missingFrames"
                    )
                    or 0
                )
                for item in incomplete_sources
            ),
            "statuses": {
                "exact_match": len(sources),
                "intentional_blank": len(gaps),
            },
        },
    }
    args.output.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(output["summary"], indent=2))


if __name__ == "__main__":
    main()
