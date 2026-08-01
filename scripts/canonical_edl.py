#!/usr/bin/env python3
"""Synchronize the atlas to one canonical CMX3600 picture EDL.

The EDL owns current shot order and record boundaries.  A persistent registry
owns shot identity.  Display labels such as CUT-019 are deliberately derived
from the current order and are never used as durable foreign keys.

Feedback records store registry shot IDs.  Pipeline records are reconciled by
the same source identity before their current display ordinal is updated.  A
removed source therefore becomes a retired shot instead of silently donating
its work to the next CUT number.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = APP_ROOT / "data" / "canonical"
DEFAULT_EDL = CANONICAL_DIR / "paracosm-current.edl"
REGISTRY_PATH = CANONICAL_DIR / "shot-registry.json"
SOURCE_CORRECTIONS_PATH = CANONICAL_DIR / "source-corrections.json"
STATE_PATH = APP_ROOT / "public" / "data" / "state.json"
FEEDBACK_PATH = APP_ROOT / "data" / "feedback.json"
CLEAN_CONFORM_PATH = (
    APP_ROOT / "data" / "premiere" / "clean-conform-export.json"
)
CLEAN_INVENTORY_PATH = (
    APP_ROOT / "data" / "premiere" / "clean-conform-latest.json"
)
SHOT_MEDIA_DIR = APP_ROOT / "public" / "archive" / "shots"

FPS = 24
SECTION_ORDER = [
    ("ND", "Natural Disaster"),
    ("NTH", "Nothing to Hide"),
    ("TH", "Teardrop"),
    ("NA", "New Again"),
    ("GG", "Goodbye Glitter"),
    ("IJDKYY", "If You Don't Know Yourself Yet"),
]


@dataclass
class EdlEvent:
    event_number: int
    reel: str
    track: str
    source_in: int
    source_out: int
    record_in: int
    record_out: int
    clip_name: str = ""
    speed: float | None = None
    section_code: str = ""
    section_name: str = ""
    media_key: str = ""
    source_key: str = ""
    shot_id: str = ""

    @property
    def is_gap(self) -> bool:
        return self.reel.upper() == "BL"

    @property
    def duration_frames(self) -> int:
        return self.record_out - self.record_in


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(fallback)
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os_process_id()}.tmp")
    temporary.write_text(
        f"{json.dumps(value, indent=2, default=str)}\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def os_process_id() -> int:
    # Kept behind a function so imports of this module stay side-effect free.
    import os

    return os.getpid()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_timecode(value: str, fps: int = FPS) -> int:
    hour, minute, second, frame = (int(part) for part in value.split(":"))
    if frame >= fps:
        raise ValueError(f"Invalid {fps} fps timecode: {value}")
    return (((hour * 60) + minute) * 60 + second) * fps + frame


def timecode(frame: int, fps: int = FPS) -> str:
    frame = max(0, int(frame))
    remainder = frame % fps
    seconds = frame // fps
    second = seconds % 60
    minute = (seconds // 60) % 60
    hour = seconds // 3600
    return f"{hour:02d}:{minute:02d}:{second:02d}:{remainder:02d}"


def _strip_source_prefix(name: str) -> str:
    value = re.sub(
        r"^\s*(?:SRC|CLEAN-SRC)-\d{3}\s*(?:¬∑|[-:])?\s*",
        "",
        name,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^\s*YELLOW-(?:CONFIRMED|CANDIDATE)-CUT-\d{3}\s*"
        r"(?:¬∑|[-:])?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value.strip()


def media_key(name: str) -> str:
    """Return a source-media identity that ignores display-only frame suffixes."""

    value = _strip_source_prefix(Path(name).name)
    value = re.sub(r"\.[^.]+$", "", value)
    value = re.sub(r"_Sub_\d+$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:_|(?<=\D))\d{3,6}$", "", value)
    value = re.sub(r"[\s_]+", " ", value).strip().casefold()
    return value


def _source_key(event: EdlEvent) -> str:
    speed = "" if event.speed is None else f"{event.speed:.4f}"
    return "|".join(
        [
            "gap" if event.is_gap else event.media_key,
            str(event.source_in),
            str(event.source_out),
            speed,
            str(event.duration_frames),
        ]
    )


def parse_edl(path: Path) -> tuple[list[EdlEvent], list[EdlEvent]]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    fcm = next((line for line in lines if line.startswith("FCM:")), "")
    if "NON-DROP FRAME" not in fcm:
        raise ValueError("The canonical EDL must be NON-DROP FRAME.")

    event_pattern = re.compile(
        r"^(\d+)\s+(\S+)\s+(V|AA)\s+C\s+"
        r"(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)\s+"
        r"(\d\d:\d\d:\d\d:\d\d)\s+(\d\d:\d\d:\d\d:\d\d)"
    )
    clip_pattern = re.compile(r"^\* FROM CLIP NAME:\s*(.+)$")
    speed_pattern = re.compile(
        r"^M2\s+\S+\s+([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
    )
    events: list[EdlEvent] = []
    current: EdlEvent | None = None
    for line in lines:
        match = event_pattern.match(line)
        if match:
            current = EdlEvent(
                event_number=int(match.group(1)),
                reel=match.group(2),
                track=match.group(3),
                source_in=parse_timecode(match.group(4)),
                source_out=parse_timecode(match.group(5)),
                record_in=parse_timecode(match.group(6)),
                record_out=parse_timecode(match.group(7)),
            )
            if current.record_out <= current.record_in:
                raise ValueError(
                    f"EDL event {current.event_number} has no record duration."
                )
            events.append(current)
            continue
        if current is None:
            continue
        clip = clip_pattern.match(line)
        if clip:
            current.clip_name = clip.group(1).strip()
            continue
        speed = speed_pattern.match(line)
        if speed:
            current.speed = float(speed.group(1))

    picture = [event for event in events if event.track == "V"]
    audio = [event for event in events if event.track == "AA"]
    if not picture:
        raise ValueError("The canonical EDL contains no V events.")
    for previous, current_event in zip(picture, picture[1:]):
        if previous.record_out != current_event.record_in:
            raise ValueError(
                "The canonical V track has an unexpressed gap between "
                f"{timecode(previous.record_out)} and "
                f"{timecode(current_event.record_in)}. Add an explicit BL event."
            )
    if picture[0].record_in != 0:
        raise ValueError("The canonical V track must start at 00:00:00:00.")
    for event in picture:
        if not event.is_gap and not event.clip_name:
            raise ValueError(
                f"EDL event {event.event_number} has no FROM CLIP NAME."
            )
        event.media_key = "__gap__" if event.is_gap else media_key(event.clip_name)
        event.source_key = _source_key(event)
    return picture, audio


def _chapter_ranges(
    picture: list[EdlEvent],
    audio: list[EdlEvent],
) -> list[dict[str, Any]]:
    audio = sorted(audio, key=lambda event: event.record_in)
    boundaries = [0]
    for event in audio:
        if event.record_in not in boundaries:
            boundaries.append(event.record_in)
    picture_end = picture[-1].record_out
    boundaries = [value for value in sorted(boundaries) if value < picture_end]

    # Premiere split the first song block at 00:00:05:02 in this EDL.  It is
    # not a chapter boundary.  Only collapse short same-source lead-ins, and
    # fail loudly if the EDL still cannot describe exactly six chapters.
    while len(boundaries) > len(SECTION_ORDER):
        removable = next(
            (
                boundary
                for boundary in boundaries[1:]
                if boundary < 10 * FPS
            ),
            None,
        )
        if removable is None:
            break
        boundaries.remove(removable)
    if len(boundaries) != len(SECTION_ORDER):
        raise ValueError(
            "Expected six chapter starts after merging short audio lead-ins; "
            f"found {len(boundaries)} ({', '.join(timecode(x) for x in boundaries)})."
        )

    chapters = []
    for index, (code, name) in enumerate(SECTION_ORDER):
        start = boundaries[index]
        end = (
            boundaries[index + 1]
            if index + 1 < len(boundaries)
            else picture_end
        )
        chapters.append(
            {
                "id": f"chapter-{index + 1}",
                "sectionCode": code,
                "sectionName": name,
                "startFrame": start,
                "endFrame": end,
                "start": start / FPS,
                "end": end / FPS,
                "recordIn": timecode(start),
                "recordOut": timecode(end),
                "boundaryAuthority": "canonical_edl_audio_edit",
                "evidence": "confirmed",
            }
        )
    for event in picture:
        midpoint = event.record_in + event.duration_frames / 2
        chapter = next(
            item
            for item in chapters
            if item["startFrame"] <= midpoint < item["endFrame"]
        )
        event.section_code = chapter["sectionCode"]
        event.section_name = chapter["sectionName"]

    # Intentional blanks are editorial tail space, not standalone chapters.
    # Keep their durable GAP shot identity, but group them with the last
    # picture chapter so every consumer sees one shared chapter taxonomy.
    previous_chapter: tuple[str, str] | None = None
    for event in picture:
        if event.is_gap and previous_chapter:
            event.section_code, event.section_name = previous_chapter
        elif not event.is_gap:
            previous_chapter = (event.section_code, event.section_name)
    return chapters


def _new_shot_id(event: EdlEvent, used: set[str]) -> str:
    prefix = "GAP" if event.is_gap else "SHOT"
    digest = hashlib.sha1(event.source_key.encode("utf-8")).hexdigest()[:12].upper()
    base = f"{prefix}-{digest}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _assign_registry_ids(
    events: list[EdlEvent],
    registry: dict[str, Any],
    preferred_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    old_records = list(registry.get("shots", []))
    preferred_ids = preferred_ids or set()
    unused = set(range(len(old_records)))
    used_ids = {str(record["shotId"]) for record in old_records}
    by_shot: dict[str, dict[str, Any]] = {}

    for event in events:
        candidates = [
            index
            for index in unused
            if str(old_records[index].get("mediaKey")) == event.media_key
        ]
        if candidates:
            def registry_match_key(candidate: int) -> tuple[int, int, int, int]:
                distance = (
                    abs(
                        int(old_records[candidate].get("sourceInFrame") or 0)
                        - event.source_in
                    )
                    + abs(
                        int(old_records[candidate].get("sourceOutFrame") or 0)
                        - event.source_out
                    )
                )
                return (
                    0 if distance <= 2 else distance,
                    0
                    if str(old_records[candidate].get("shotId")) in preferred_ids
                    else 1,
                    distance,
                    abs(
                        int(old_records[candidate].get("lastRecordInFrame") or 0)
                        - event.record_in
                    ),
                )

            index = min(
                candidates,
                key=registry_match_key,
            )
            unused.remove(index)
            shot_id = str(old_records[index]["shotId"])
            record = copy.deepcopy(old_records[index])
        else:
            shot_id = _new_shot_id(event, used_ids)
            used_ids.add(shot_id)
            record = {
                "shotId": shot_id,
                "createdAt": _utc_now(),
            }
        event.shot_id = shot_id
        record.update(
            {
                "mediaKey": event.media_key,
                "sourceKey": event.source_key,
                "clipName": event.clip_name or "Editorial gap",
                "sourceInFrame": event.source_in,
                "sourceOutFrame": event.source_out,
                "speed": event.speed,
                "isGap": event.is_gap,
                "active": True,
                "lastRecordInFrame": event.record_in,
                "lastRecordOutFrame": event.record_out,
                "sectionCode": event.section_code,
                "lastSeenAt": _utc_now(),
            }
        )
        by_shot[shot_id] = record

    for index in unused:
        retired = copy.deepcopy(old_records[index])
        retired["active"] = False
        retired["retiredAt"] = retired.get("retiredAt") or _utc_now()
        by_shot[str(retired["shotId"])] = retired

    registry = {
        "schemaVersion": 1,
        "identityRule": (
            "Persistent shotId reconciled by source media; CUT-### is current "
            "display order only."
        ),
        "updatedAt": _utc_now(),
        "currentOrder": [event.shot_id for event in events],
        "shots": list(by_shot.values()),
    }
    return registry, by_shot


def _normalize_registry_media_keys(registry: dict[str, Any]) -> dict[str, Any]:
    clean = _read_json(CLEAN_CONFORM_PATH, {})
    inventory_by_cut = {
        str(item.get("canonicalId")): item
        for item in clean.get("inventory", [])
        if item.get("canonicalId")
    }
    normalized = copy.deepcopy(registry)
    for record in normalized.get("shots", []):
        legacy = inventory_by_cut.get(str(record.get("legacyCutId") or ""))
        alias = (
            str(legacy.get("name") or legacy.get("path") or "")
            if legacy
            else str(record.get("clipName") or record.get("mediaKey") or "")
        )
        if alias and alias != "Editorial gap":
            record["mediaKey"] = media_key(alias)
        if legacy:
            record["sourceInFrame"] = round(
                float(legacy.get("sourceIn") or 0) * FPS
            )
            record["sourceOutFrame"] = round(
                float(legacy.get("sourceOut") or 0) * FPS
            )
    return normalized


def _prune_duplicate_registry_records(
    registry: dict[str, Any],
    referenced_ids: set[str],
) -> dict[str, Any]:
    records = list(registry.get("shots", []))
    protected = [
        record
        for record in records
        if record.get("active") or str(record.get("shotId")) in referenced_ids
    ]
    kept = list(protected)
    for record in records:
        if record in protected:
            continue
        duplicate = next(
            (
                candidate
                for candidate in kept
                if candidate.get("mediaKey") == record.get("mediaKey")
                and abs(
                    int(candidate.get("sourceInFrame") or 0)
                    - int(record.get("sourceInFrame") or 0)
                )
                <= 2
                and abs(
                    int(candidate.get("sourceOutFrame") or 0)
                    - int(record.get("sourceOutFrame") or 0)
                )
                <= 2
            ),
            None,
        )
        if duplicate is None:
            kept.append(record)
    registry = copy.deepcopy(registry)
    registry["shots"] = kept
    valid_ids = {str(record.get("shotId")) for record in kept}
    registry["currentOrder"] = [
        shot_id
        for shot_id in registry.get("currentOrder", [])
        if shot_id in valid_ids
    ]
    return registry


def _clean_source_alias(source: dict[str, Any]) -> str:
    return _strip_source_prefix(str(source.get("name") or Path(str(source.get("path") or "")).name))


def _source_indexes(
    state: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    clean = _read_json(CLEAN_CONFORM_PATH, {})
    sources = list(clean.get("sources", []))
    source_by_id = {str(source.get("id")): source for source in sources}
    source_by_alias = {
        _clean_source_alias(source).casefold(): source
        for source in sources
    }

    latest = _read_json(CLEAN_INVENTORY_PATH, {})
    for track in (latest.get("sequence") or {}).get("videoTracks", []):
        for clip in track.get("clips", []):
            project_item = clip.get("projectItem") or {}
            path = str(project_item.get("mediaPath") or "")
            if not path:
                continue
            alias = str(clip.get("name") or Path(path).name)
            source_by_alias.setdefault(
                alias.casefold(),
                {
                    "id": f"LIVE-{clip.get('nodeId') or hashlib.sha1(path.encode()).hexdigest()[:10]}",
                    "name": alias,
                    "path": path,
                    "renderDirectory": str(Path(path).parent),
                    "sourceFrameRate": FPS,
                },
            )
    return source_by_id, source_by_alias


def _cut_media(
    cut: dict[str, Any],
    source_by_id: dict[str, dict[str, Any]],
) -> tuple[str, int]:
    source_ids = list((cut.get("manualConform") or {}).get("sources", []))
    source = next(
        (source_by_id[source_id] for source_id in source_ids if source_id in source_by_id),
        None,
    )
    if source:
        name = _clean_source_alias(source)
    else:
        segment = next(iter(cut.get("sourceSegments", [])), {})
        name = str(
            segment.get("clipName")
            or Path(str(segment.get("sourcePath") or "")).name
        )
    source_in = (cut.get("manualConform") or {}).get("sourceIn")
    return media_key(name), round(float(source_in or 0) * FPS)


def _match_pipeline_cuts(
    old_cuts: list[dict[str, Any]],
    events: list[EdlEvent],
    source_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    old_by_shot = {
        str(cut.get("shotId")): cut for cut in old_cuts if cut.get("shotId")
    }
    unmatched = [
        cut for cut in old_cuts if not cut.get("isGap") and not cut.get("shotId")
    ]
    old_info = {
        str(cut["id"]): _cut_media(cut, source_by_id)
        for cut in unmatched
    }
    base_by_shot: dict[str, dict[str, Any]] = {}
    old_to_shot: dict[str, str] = {}

    for event in events:
        direct = old_by_shot.get(event.shot_id)
        if direct:
            base_by_shot[event.shot_id] = direct
            old_to_shot[str(direct["id"])] = event.shot_id
            continue
        if event.is_gap:
            gaps = [cut for cut in old_cuts if cut.get("isGap")]
            direct_gap = min(
                gaps,
                key=lambda cut: abs(
                    round(float(cut.get("start") or 0) * FPS) - event.record_in
                ),
                default=None,
            )
            if direct_gap:
                base_by_shot[event.shot_id] = direct_gap
                old_to_shot[str(direct_gap["id"])] = event.shot_id
            continue
        candidates = [
            cut
            for cut in unmatched
            if old_info[str(cut["id"])][0] == event.media_key
        ]
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda cut: (
                abs(old_info[str(cut["id"])][1] - event.source_in),
                abs(round(float(cut.get("start") or 0) * FPS) - event.record_in),
            ),
        )
        unmatched.remove(chosen)
        base_by_shot[event.shot_id] = chosen
        old_to_shot[str(chosen["id"])] = event.shot_id

    retired = [
        cut
        for cut in old_cuts
        if not cut.get("isGap")
        and str(cut.get("id")) not in old_to_shot
        and not (
            cut.get("shotId")
            and str(cut.get("shotId")) in {event.shot_id for event in events}
        )
    ]
    return base_by_shot, old_to_shot, retired


def _resolve_source(
    event: EdlEvent,
    state: dict[str, Any],
    source_by_alias: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    source = source_by_alias.get(event.clip_name.casefold())
    if source and Path(str(source.get("path") or "")).exists():
        return source

    wanted = media_key(event.clip_name)
    renders = list(state.get("renderSequences", []))
    exact = [
        render
        for render in renders
        if media_key(str(render.get("name") or "")) == wanted
        and Path(str(render.get("firstFrame") or "")).exists()
    ]
    if not exact:
        exact = [
            render
            for render in renders
            if (
                wanted.startswith(media_key(str(render.get("name") or "")))
                or media_key(str(render.get("name") or "")).startswith(wanted)
            )
            and Path(str(render.get("firstFrame") or "")).exists()
        ]
    if not exact:
        return None
    render = max(
        exact,
        key=lambda item: (
            len(media_key(str(item.get("name") or ""))),
            int(item.get("frameCount") or 0),
        ),
    )
    return {
        "id": str(render.get("id") or f"RENDER-{event.shot_id}"),
        "name": event.clip_name,
        "path": str(render["firstFrame"]),
        "renderDirectory": str(render.get("path") or Path(render["firstFrame"]).parent),
        "sourceFrameRate": FPS,
    }


def _sequence_files(source: dict[str, Any]) -> list[Path]:
    first = Path(str(source.get("path") or ""))
    directory = Path(str(source.get("renderDirectory") or first.parent))
    if not first.exists() or first.suffix.lower() in {".mov", ".mp4", ".m4v"}:
        return []
    match = re.search(r"(\d+)(?=\.[^.]+$)", first.name)
    if not match:
        return [first]
    prefix = first.name[: match.start()]
    suffix = first.name[match.end() :]
    candidates = []
    for path in directory.glob(f"{prefix}*{first.suffix}"):
        number = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
        if number and path.name[number.end() :] == suffix:
            candidates.append((int(number.group(1)), path))
    return [path for _, path in sorted(candidates)] or [first]


def _source_positions(event: EdlEvent) -> list[int]:
    speed = FPS if event.speed is None else event.speed
    ratio = speed / FPS
    positions = []
    for output_frame in range(event.duration_frames):
        position = event.source_in + round(output_frame * ratio)
        positions.append(max(0, position))
    return positions


def _ffconcat_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace("'", "\\'")


def _render_image_proxy(
    event: EdlEvent,
    source: dict[str, Any],
    proxy_path: Path,
    thumbnail_path: Path,
) -> bool:
    frames = _sequence_files(source)
    if not frames:
        return False
    positions = _source_positions(event)
    selected = [frames[min(position, len(frames) - 1)] for position in positions]
    midpoint = selected[len(selected) // 2]
    scale = (
        "scale=640:360:force_original_aspect_ratio=decrease,"
        "pad=640:360:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(midpoint),
            "-vf",
            scale,
            "-frames:v",
            "1",
            str(thumbnail_path),
        ],
        check=True,
    )
    with tempfile.TemporaryDirectory(prefix="paracosm-edl-") as directory:
        concat_path = Path(directory) / "frames.ffconcat"
        entries = ["ffconcat version 1.0"]
        for frame in selected:
            entries.append(f"file '{_ffconcat_path(frame)}'")
            entries.append(f"duration {1 / FPS:.12f}")
        entries.append(f"file '{_ffconcat_path(selected[-1])}'")
        concat_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-vf",
                scale,
                "-r",
                str(FPS),
                "-frames:v",
                str(event.duration_frames),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "25",
                "-movflags",
                "+faststart",
                str(proxy_path),
            ],
            check=True,
        )
    return True


def _render_movie_proxy(
    event: EdlEvent,
    source: dict[str, Any],
    proxy_path: Path,
    thumbnail_path: Path,
) -> bool:
    path = Path(str(source.get("path") or ""))
    if not path.exists():
        return False
    speed = FPS if event.speed is None else event.speed
    source_span = max(1, round(event.duration_frames * abs(speed) / FPS))
    if speed < 0:
        source_start = max(0, event.source_in - source_span + 1)
        reverse = ",reverse"
    else:
        source_start = event.source_in
        reverse = ""
    rate = abs(speed) / FPS if speed else 1 / FPS
    filter_chain = (
        f"trim=start_frame={source_start}:end_frame={source_start + source_span},"
        f"setpts=PTS-STARTPTS{reverse},setpts={1 / max(rate, 1e-6):.9f}*PTS,"
        "fps=24,scale=640:360:force_original_aspect_ratio=decrease,"
        "pad=640:360:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vf",
            filter_chain,
            "-frames:v",
            str(event.duration_frames),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "25",
            "-movflags",
            "+faststart",
            str(proxy_path),
        ],
        check=True,
    )
    midpoint = max(0, (event.duration_frames // 2) / FPS)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{midpoint:.6f}",
            "-i",
            str(proxy_path),
            "-frames:v",
            "1",
            str(thumbnail_path),
        ],
        check=True,
    )
    return True


def _ensure_local_media(
    event: EdlEvent,
    source: dict[str, Any] | None,
    *,
    force: bool,
) -> tuple[str | None, str | None]:
    if event.is_gap or not source:
        return None, None
    SHOT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    proxy = SHOT_MEDIA_DIR / f"{event.shot_id}.mp4"
    thumbnail = SHOT_MEDIA_DIR / f"{event.shot_id}.jpg"
    if not force and proxy.exists() and thumbnail.exists():
        return (
            f"/archive/shots/{proxy.name}",
            f"/archive/shots/{thumbnail.name}",
        )
    try:
        if Path(str(source.get("path") or "")).suffix.lower() in {
            ".mov",
            ".mp4",
            ".m4v",
        }:
            built = _render_movie_proxy(event, source, proxy, thumbnail)
        else:
            built = _render_image_proxy(event, source, proxy, thumbnail)
    except (OSError, subprocess.CalledProcessError):
        built = False
    if not built:
        proxy.unlink(missing_ok=True)
        thumbnail.unlink(missing_ok=True)
        return None, None
    return (
        f"/archive/shots/{proxy.name}",
        f"/archive/shots/{thumbnail.name}",
    )


def _source_segment(
    event: EdlEvent,
    source: dict[str, Any] | None,
) -> dict[str, Any]:
    path = str((source or {}).get("path") or "")
    render_directory = str(
        (source or {}).get("renderDirectory") or (Path(path).parent if path else "")
    )
    positions = _source_positions(event)
    files = _sequence_files(source or {})
    first_path = (
        str(files[min(positions[0], len(files) - 1)])
        if files
        else path
    )
    last_path = (
        str(files[min(positions[-1], len(files) - 1)])
        if files
        else path
    )
    return {
        "id": event.shot_id,
        "shotId": event.shot_id,
        "clipName": event.clip_name,
        "sectionCode": event.section_code,
        "finalStart": event.record_in / FPS,
        "finalEnd": event.record_out / FPS,
        "finalStartFrame": event.record_in,
        "finalEndFrame": event.record_out,
        "sourceSystem": "Canonical EDL V1",
        "sourceEdit": "Canonical source media",
        "sourcePath": path,
        "renderDirectory": render_directory,
        "sourceFirstFramePath": first_path,
        "sourceLastFramePath": last_path,
        "sourceStartFrame": positions[0],
        "sourceEndFrame": positions[-1],
        "sourceFrameRate": FPS,
        "sourceTrack": 1,
        "playBackwards": bool(event.speed is not None and event.speed < 0),
        "evidence": "confirmed" if path else "candidate",
        "role": "exact_match",
        "canonical": True,
        "sourceInTicks": event.source_in,
        "sourceOutTicks": event.source_out,
        "selectedFirstFrame": positions[0],
        "selectedLastFrame": positions[-1],
        "manualTrimAuthority": True,
        "sourceMediaHealth": {
            "status": "complete" if path and Path(path).exists() else "missing",
            "expectedFrames": event.duration_frames,
            "availableFrames": event.duration_frames if path and Path(path).exists() else 0,
            "missingFrames": 0 if path and Path(path).exists() else event.duration_frames,
        },
    }


def _apply_source_correction(
    cut: dict[str, Any],
    correction: dict[str, Any] | None,
) -> dict[str, Any]:
    """Overlay visually confirmed source corrections after EDL synchronization.

    The EDL remains the record-boundary authority. A correction may replace
    only the media lineage and source in/out when distributed final-film frame
    comparisons prove that editorial points at an older or misidentified
    render family.
    """

    if not correction or cut.get("isGap"):
        return cut
    existing_manual = copy.deepcopy(cut.get("manualConform") or {})
    record_start_frame = int(
        existing_manual.get("startFrame")
        if existing_manual.get("startFrame") is not None
        else round(float(cut.get("start") or 0) * FPS)
    )
    record_end_frame = int(
        existing_manual.get("endFrame")
        if existing_manual.get("endFrame") is not None
        else round(float(cut.get("end") or 0) * FPS)
    )
    correction_authority = (
        "canonical_edl_plus_visual_source_correction"
        if existing_manual.get("authority") in {None, "canonical_edl"}
        else "canonical_v1_v2_plus_visual_source_correction"
    )
    segment_override = copy.deepcopy(correction.get("sourceSegment") or {})
    if segment_override:
        segment = copy.deepcopy((cut.get("sourceSegments") or [{}])[0])
        segment.update(segment_override)
        segment.update(
            {
                "id": cut.get("shotId"),
                "shotId": cut.get("shotId"),
                "sectionCode": cut.get("sectionCode"),
                "finalStart": cut.get("start"),
                "finalEnd": cut.get("end"),
                "finalStartFrame": record_start_frame,
                "finalEndFrame": record_end_frame,
                "canonical": True,
                "manualTrimAuthority": True,
            }
        )
        cut["sourceSegments"] = [segment]

    manual_override = copy.deepcopy(correction.get("manualConform") or {})
    if manual_override:
        cut["manualConform"] = {
            **existing_manual,
            **manual_override,
            "authority": correction_authority,
            "startFrame": record_start_frame,
            "endFrame": record_end_frame,
            "sources": [cut.get("shotId")],
            "canonicalSources": [cut.get("shotId")],
            "coverage": 1,
            "exactCoverage": 1,
        }

    replacement_kinds = set(correction.get("replaceLineageKinds") or [])
    replacement_nodes = copy.deepcopy(correction.get("lineageNodes") or [])
    if replacement_kinds or replacement_nodes:
        lineage = [
            node
            for node in cut.get("lineage", [])
            if node.get("kind") not in replacement_kinds
        ]
        insertion = next(
            (
                index
                for index, node in enumerate(lineage)
                if node.get("kind") == "resolve"
            ),
            len(lineage),
        )
        cut["lineage"] = [
            *lineage[:insertion],
            *replacement_nodes,
            *lineage[insertion:],
        ]

    for key, value in (correction.get("pipelineFields") or {}).items():
        cut[key] = copy.deepcopy(value)
    cut["sourceCorrection"] = {
        key: copy.deepcopy(value)
        for key, value in correction.items()
        if key
        not in {
            "sourceSegment",
            "manualConform",
            "lineageNodes",
            "replaceLineageKinds",
            "pipelineFields",
        }
    }
    return cut


def apply_source_corrections(state: dict[str, Any]) -> dict[str, Any]:
    """Apply confirmed media-lineage corrections without changing cut order.

    Clean V1/V2 source intervals remain authoritative when present.  The
    correction archive can address them by durable shot id or by the audited
    canonical CUT label recorded when the evidence was produced.
    """

    archive = _read_json(SOURCE_CORRECTIONS_PATH, {"corrections": []})
    by_shot = {
        str(record.get("shotId")): record
        for record in archive.get("corrections", [])
        if record.get("shotId")
    }
    by_cut = {
        str(record.get("auditedCutId")): record
        for record in archive.get("corrections", [])
        if record.get("auditedCutId")
    }
    for cut in state.get("cuts", []):
        correction = by_shot.get(str(cut.get("shotId"))) or by_cut.get(
            str(cut.get("id"))
        )
        _apply_source_correction(cut, correction)
    return state


def sync_clean_conform_registry(state: dict[str, Any]) -> dict[str, Any]:
    """Publish the authoritative Clean V1/V2 order to shared shot identity.

    The canonical EDL remains useful as an editorial identity seed, but the
    saved Clean Premiere V1/V2 conform can contain flattened nested clips and
    confirmed source corrections that are not individual EDL events.  Once
    those records are published, keep the registry and feedback retirement
    state aligned with that actual authoritative order.
    """

    cuts = list(state.get("cuts", []))
    if not cuts:
        return state

    registry = _read_json(REGISTRY_PATH, {"shots": []})
    records = list(registry.get("shots", []))
    by_id = {
        str(record.get("shotId")): record
        for record in records
        if record.get("shotId")
    }
    published_ids = [
        str(cut.get("shotId"))
        for cut in cuts
        if cut.get("shotId")
    ]
    published_set = set(published_ids)
    updated_at = datetime.now(timezone.utc).isoformat()

    for cut in cuts:
        shot_id = str(cut.get("shotId") or "")
        if not shot_id:
            continue
        record = by_id.get(shot_id)
        if record is None:
            segment = next(iter(cut.get("sourceSegments") or []), {})
            source_path = str(segment.get("sourcePath") or "")
            clip_name = (
                str(segment.get("clipName") or "")
                or Path(source_path).name
                or str(cut.get("id") or shot_id)
            )
            record = {
                "shotId": shot_id,
                "createdAt": updated_at,
                "mediaKey": media_key(clip_name) if not cut.get("isGap") else "",
                "clipName": clip_name,
                "isGap": bool(cut.get("isGap")),
            }
            records.append(record)
            by_id[shot_id] = record
        record.update(
            {
                "active": True,
                "lastRecordInFrame": int(
                    round(float(cut.get("start") or 0) * FPS)
                ),
                "lastRecordOutFrame": int(
                    round(float(cut.get("end") or 0) * FPS)
                ),
                "sectionCode": cut.get("sectionCode"),
                "lastSeenAt": updated_at,
            }
        )
        record.pop("retiredAt", None)

    for record in records:
        shot_id = str(record.get("shotId") or "")
        if shot_id and shot_id not in published_set:
            record["active"] = False
            record.setdefault("retiredAt", updated_at)

    registry.update(
        {
            "currentOrder": published_ids,
            "pictureEvents": len(cuts),
            "pictureShots": sum(1 for cut in cuts if not cut.get("isGap")),
            "intentionalBlanks": sum(1 for cut in cuts if cut.get("isGap")),
            "updatedAt": updated_at,
            "shots": records,
        }
    )
    _atomic_json(REGISTRY_PATH, registry)

    feedback = _read_json(FEEDBACK_PATH, {})
    feedback_changed = False
    for collection in ("generalNotes", "parents", "notes"):
        for record in feedback.get(collection, []):
            retired = list(record.get("retiredShotIds") or [])
            filtered = [
                shot_id
                for shot_id in retired
                if str(shot_id) not in published_set
            ]
            if filtered != retired:
                record["retiredShotIds"] = filtered
                feedback_changed = True
    if feedback_changed:
        _atomic_json(FEEDBACK_PATH, feedback)

    return state


def assign_clean_shot_identities(state: dict[str, Any]) -> dict[str, Any]:
    """Attach unique durable shot ids to Clean V1/V2 cut records.

    The Clean conform predates the persistent registry and therefore carries
    canonical CUT/source ids but no ``shotId``.  Reuse registry identities by
    normalized media plus source trim wherever possible; create a deterministic
    identity only for flattened nested-source shots that never existed as
    top-level EDL events.
    """

    registry = _read_json(REGISTRY_PATH, {"shots": []})
    records = [
        record
        for record in registry.get("shots", [])
        if record.get("shotId") and record.get("mediaKey")
    ]
    used: set[str] = set()

    def source_numbers(record: dict[str, Any]) -> tuple[int, int, int]:
        parts = str(record.get("sourceKey") or "").split("|")
        try:
            return int(parts[1]), int(parts[2]), int(parts[4])
        except (IndexError, TypeError, ValueError):
            return 0, 0, 0

    for cut in state.get("cuts", []):
        if cut.get("shotId"):
            used.add(str(cut["shotId"]))
            continue
        manual = cut.get("manualConform") or {}
        segment = next(iter(cut.get("sourceSegments") or []), {})
        name = str(
            segment.get("clipName")
            or Path(str(segment.get("sourcePath") or "")).name
            or cut.get("id")
            or ""
        )
        wanted_media = "__gap__" if cut.get("isGap") else media_key(name)
        wanted_in = int(manual.get("sourceInFrameOffset") or 0)
        wanted_out = int(manual.get("sourceOutFrameOffset") or 0)
        wanted_duration = int(manual.get("endFrame") or 0) - int(
            manual.get("startFrame") or 0
        )
        candidates = [
            record
            for record in records
            if str(record.get("shotId")) not in used
            and str(record.get("mediaKey")) == wanted_media
        ]
        chosen = min(
            candidates,
            key=lambda record: sum(
                abs(left - right)
                for left, right in zip(
                    source_numbers(record),
                    (wanted_in, wanted_out, wanted_duration),
                    strict=True,
                )
            ),
            default=None,
        )
        if chosen:
            shot_id = str(chosen["shotId"])
        else:
            identity = "|".join(
                [
                    "clean_v1_v2",
                    wanted_media,
                    str(wanted_in),
                    str(wanted_out),
                    str(manual.get("startFrame") or ""),
                    str(manual.get("endFrame") or ""),
                    str(cut.get("id") or ""),
                ]
            )
            shot_id = f"SHOT-{hashlib.sha256(identity.encode()).hexdigest()[:12].upper()}"
        used.add(shot_id)
        cut["shotId"] = shot_id
        cut["pipelineAttachmentId"] = shot_id
    return state


def _chapter_tag(chapter: dict[str, Any], edl_path: Path) -> dict[str, Any]:
    return {
        "type": "chapter_edit",
        "label": chapter["sectionName"],
        "detail": (
            f"Canonical EDL chapter · {chapter['recordIn']}–"
            f"{timecode(int(chapter['endFrame']) - 1)} inclusive"
        ),
        "path": str(edl_path),
        "evidence": "confirmed",
    }


def _canonical_cut(
    event: EdlEvent,
    index: int,
    base: dict[str, Any] | None,
    source: dict[str, Any] | None,
    chapter: dict[str, Any],
    edl_path: Path,
    previous_source_key: str | None,
    generate_media: bool,
) -> dict[str, Any]:
    cut = copy.deepcopy(base) if base else {}
    display_id = f"CUT-{index:03d}"
    old_id = str(base.get("id")) if base else None
    old_start = float(base.get("start") or 0) if base else 0
    old_end = float(base.get("end") or 0) if base else 0
    stable_thumbnail = f"/archive/shots/{event.shot_id}.jpg"
    stable_thumbnail_path = SHOT_MEDIA_DIR / f"{event.shot_id}.jpg"

    media_changed = previous_source_key not in {None, event.source_key}
    local_proxy = None
    local_thumbnail = None
    if generate_media and (not base or media_changed):
        local_proxy, local_thumbnail = _ensure_local_media(
            event,
            source,
            force=media_changed,
        )
    if base and not event.is_gap and not stable_thumbnail_path.exists():
        base_thumb = APP_ROOT / "public" / str(base.get("thumbnail") or "").lstrip("/")
        if base_thumb.exists():
            SHOT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base_thumb, stable_thumbnail_path)
    if stable_thumbnail_path.exists():
        local_thumbnail = stable_thumbnail

    start = event.record_in / FPS
    end = event.record_out / FPS
    cut.update(
        {
            "id": display_id,
            "shotId": event.shot_id,
            "pipelineAttachmentId": event.shot_id,
            "legacyCutId": (
                str(base.get("legacyCutId") or old_id) if base else None
            ),
            "index": index,
            "start": start,
            "end": end,
            "duration": end - start,
            "timecode": timecode(event.record_in),
            # User-facing ranges are inclusive. recordOutTimecode remains
            # available for EDL/export math.
            "endTimecode": timecode(event.record_out - 1),
            "recordOutTimecode": timecode(event.record_out),
            "thumbnail": (
                local_thumbnail
                or (base.get("thumbnail") if base else stable_thumbnail)
            ),
            "scrubProxy": (
                local_proxy
                or (base.get("scrubProxy") if base else None)
                or (
                    "/archive/reference/paracosm-hover.mp4"
                    if base and not event.is_gap
                    else None
                )
            ),
            "scrubStart": (
                0
                if local_proxy
                else float(base.get("scrubStart", old_start))
                if base
                else 0
            ),
            "scrubEnd": (
                end - start
                if local_proxy
                else float(base.get("scrubEnd", old_end))
                if base
                else end - start
            ),
            "boundaryEvidence": "canonical_edl_record_boundary",
            "boundaryDetail": (
                f"CMX3600 event {event.event_number:03d} record In/Out; "
                "CUT number derived from current EDL order."
            ),
            "verification": "canonical_edl_confirmed",
            "blockId": chapter["id"],
            "sectionCode": event.section_code,
            "sectionName": event.section_name,
            "isGap": event.is_gap,
            "confidence": "confirmed",
            "sourceIdentity": {
                "mediaKey": event.media_key,
                "sourceKey": event.source_key,
                "clipName": event.clip_name or "Editorial gap",
                "sourceInFrame": event.source_in,
                "sourceOutFrame": event.source_out,
                "speed": event.speed,
                "recordInFrame": event.record_in,
                "recordOutFrame": event.record_out,
                "edlEvent": event.event_number,
            },
        }
    )
    if event.is_gap:
        cut["plannedShotId"] = None
        cut["sourceSegments"] = []
        cut["manualConform"] = {
            "authority": "canonical_edl",
            "startFrame": event.record_in,
            "endFrame": event.record_out,
            "status": "intentional_blank",
            "sources": [],
        }
        cut["lineage"] = [
            {
                "kind": "reference",
                "label": display_id,
                "detail": (
                    f"Canonical EDL intentional BL · "
                    f"{timecode(event.record_in)}–{timecode(event.record_out - 1)}"
                ),
                "path": str(edl_path),
                "evidence": "confirmed",
                "tags": [_chapter_tag(chapter, edl_path)],
            }
        ]
        cut["exportScreenshots"] = []
        for key in [
            "comparison",
            "c4dLinkStatus",
            "c4dVerification",
            "c4dSceneState",
            "c4dProxyAudit",
            "c4dStructuralRecovery",
            "c4dCameraCandidateAudit",
        ]:
            cut.pop(key, None)
        return cut

    segment = _source_segment(event, source)
    cut["sourceSegments"] = [segment]
    cut["manualConform"] = {
        **copy.deepcopy(cut.get("manualConform") or {}),
        "authority": "canonical_edl",
        "timelineTrack": 1,
        "startFrame": event.record_in,
        "endFrame": event.record_out,
        "sourceIn": event.source_in / FPS,
        "sourceOut": event.source_out / FPS,
        "sourceInFrameOffset": event.source_in,
        "sourceOutFrameOffset": event.source_out,
        "status": "exact_match" if segment["sourcePath"] else "untracked",
        "sources": [event.shot_id],
        "canonicalSources": [event.shot_id] if segment["sourcePath"] else [],
        "coverage": 1 if segment["sourcePath"] else 0,
        "exactCoverage": 1 if segment["sourcePath"] else 0,
    }
    lineage = list(cut.get("lineage") or [])
    if lineage:
        lineage[0] = {
            **lineage[0],
            "kind": "reference",
            "label": display_id,
            "detail": (
                f"Canonical EDL event {event.event_number:03d} · "
                f"{timecode(event.record_in)}–{timecode(event.record_out - 1)} "
                f"inclusive · {event.clip_name}"
            ),
            "path": str(edl_path),
            "evidence": "confirmed",
            "tags": [
                tag
                for tag in lineage[0].get("tags", [])
                if tag.get("type") != "chapter_edit"
            ]
            + [_chapter_tag(chapter, edl_path)],
        }
    else:
        lineage = [
            {
                "kind": "reference",
                "label": display_id,
                "detail": (
                    f"Canonical EDL event {event.event_number:03d} · "
                    f"{event.clip_name}"
                ),
                "path": str(edl_path),
                "evidence": "confirmed",
                "tags": [_chapter_tag(chapter, edl_path)],
            },
            {
                "kind": "render_sequence",
                "label": event.clip_name,
                "detail": "Source media resolved from the canonical EDL.",
                "path": segment["sourcePath"],
                "evidence": "confirmed" if segment["sourcePath"] else "candidate",
                "sourceId": event.shot_id,
                "tags": [
                    {
                        "type": "source_render",
                        "label": event.clip_name,
                        "detail": segment["renderDirectory"],
                    }
                ],
            },
        ]
    cut["lineage"] = lineage
    if not cut.get("exportScreenshots") and cut.get("thumbnail"):
        cut["exportScreenshots"] = [
            {
                "id": f"{event.shot_id}-canonical-frame",
                "role": "canonical_edl_frame",
                "label": "Canonical EDL source frame",
                "image": cut["thumbnail"],
                "exportPath": segment["sourceFirstFramePath"],
                "producers": [],
            }
        ]
    return cut


def _retired_shot_id(
    cut: dict[str, Any],
    source_by_id: dict[str, dict[str, Any]],
    used: set[str],
) -> tuple[str, str]:
    key, source_in = _cut_media(cut, source_by_id)
    material = f"{key}|{source_in}|retired"
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:12].upper()
    candidate = f"SHOT-{digest}"
    suffix = 2
    while candidate in used:
        candidate = f"SHOT-{digest}-{suffix}"
        suffix += 1
    return candidate, key


def _migrate_feedback(
    feedback: dict[str, Any],
    old_to_shot: dict[str, str],
    retired: list[dict[str, Any]],
    source_by_id: dict[str, dict[str, Any]],
    registry: dict[str, Any],
) -> dict[str, Any]:
    used = {str(record["shotId"]) for record in registry.get("shots", [])}
    referenced_ids = {
        str(shot_id)
        for record in [
            *feedback.get("generalNotes", []),
            *feedback.get("parents", []),
            *feedback.get("notes", []),
        ]
        for shot_id in record.get("shotIds", [])
    }
    retired_map: dict[str, str] = {}
    for cut in retired:
        existing = str(cut.get("shotId") or "")
        key, _ = _cut_media(cut, source_by_id)
        if existing:
            shot_id = existing
        else:
            candidates = [
                record
                for record in registry.get("shots", [])
                if str(record.get("legacyCutId") or "") == str(cut["id"])
                and str(record.get("mediaKey") or "") == key
            ]
            if candidates:
                chosen = min(
                    candidates,
                    key=lambda record: (
                        0
                        if str(record.get("shotId")) in referenced_ids
                        else 1,
                        str(record.get("createdAt") or ""),
                    ),
                )
                shot_id = str(chosen["shotId"])
            else:
                shot_id, key = _retired_shot_id(cut, source_by_id, used)
                used.add(shot_id)
        retired_map[str(cut["id"])] = shot_id
        if not any(
            str(record.get("shotId")) == shot_id
            for record in registry.get("shots", [])
        ):
            registry["shots"].append(
                {
                    "shotId": shot_id,
                    "mediaKey": key,
                    "clipName": key or str(cut.get("id")),
                    "active": False,
                    "createdAt": _utc_now(),
                    "retiredAt": _utc_now(),
                    "legacyCutId": cut.get("id"),
                }
            )
    legacy_map = {**retired_map, **old_to_shot}
    active = set(registry.get("currentOrder", []))
    for record in [
        *feedback.get("generalNotes", []),
        *feedback.get("parents", []),
        *feedback.get("notes", []),
    ]:
        if "shotIds" in record:
            shot_ids = list(record.get("shotIds") or [])
        else:
            shot_ids = [
                legacy_map[cut_id]
                for cut_id in record.get("cutIds", [])
                if cut_id in legacy_map
            ]
        record["shotIds"] = list(dict.fromkeys(shot_ids))
        record["retiredShotIds"] = [
            shot_id for shot_id in record["shotIds"] if shot_id not in active
        ]
        record.pop("cutIds", None)
    feedback["schemaVersion"] = max(4, int(feedback.get("schemaVersion") or 1))
    feedback["assignmentIdentity"] = "shotId"
    feedback["updatedAt"] = _utc_now()
    return feedback


def _recount_summary(state: dict[str, Any], cuts: list[dict[str, Any]]) -> None:
    summary = state.setdefault("summary", {})
    picture = [cut for cut in cuts if not cut.get("isGap")]
    summary["editCuts"] = len(cuts)
    summary["pictureCuts"] = len(picture)
    summary["manualConformPictureClips"] = len(picture)
    summary["manualConformIntentionalBlanks"] = len(cuts) - len(picture)
    summary["manualConformCanonicalSources"] = len(picture)
    summary["sourceConformSegments"] = len(picture)
    summary["sourceConformConfirmed"] = sum(
        1
        for cut in picture
        if (cut.get("manualConform") or {}).get("status") == "exact_match"
    )
    summary["lineageExportScreenshots"] = sum(
        len(cut.get("exportScreenshots", [])) for cut in cuts
    )
    summary["chapterEditTaggedCuts"] = len(picture)
    summary["sourceMediaCompleteClips"] = sum(
        1
        for cut in picture
        if (cut.get("sourceSegments") or [{}])[0]
        .get("sourceMediaHealth", {})
        .get("status")
        == "complete"
    )
    summary["sourceMediaIncompleteClips"] = len(picture) - summary[
        "sourceMediaCompleteClips"
    ]
    summary["sourceMediaMissingSelectedFrames"] = sum(
        int(
            (cut.get("sourceSegments") or [{}])[0]
            .get("sourceMediaHealth", {})
            .get("missingFrames")
            or 0
        )
        for cut in picture
    )


def sync_state(
    state: dict[str, Any],
    *,
    edl_path: Path = DEFAULT_EDL,
    feedback: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
    generate_media: bool = True,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    picture_events, audio_events = parse_edl(edl_path)
    chapters = _chapter_ranges(picture_events, audio_events)
    registry = _normalize_registry_media_keys(
        registry or _read_json(REGISTRY_PATH, {})
    )
    preferred_ids = {
        str(shot_id)
        for record in [
            *(feedback or {}).get("generalNotes", []),
            *(feedback or {}).get("parents", []),
            *(feedback or {}).get("notes", []),
        ]
        for shot_id in record.get("shotIds", [])
    }
    registry = _prune_duplicate_registry_records(registry, preferred_ids)
    previous_source_keys = {
        str(record.get("shotId")): str(record.get("sourceKey") or "")
        for record in registry.get("shots", [])
    }
    registry, _ = _assign_registry_ids(
        picture_events,
        registry,
        preferred_ids,
    )
    registry = _prune_duplicate_registry_records(registry, preferred_ids)
    registry.update(
        {
            "canonicalEdl": str(edl_path),
            "canonicalEdlSha256": _sha256(edl_path),
            "fps": FPS,
            "pictureEvents": len(picture_events),
            "pictureShots": sum(1 for event in picture_events if not event.is_gap),
            "intentionalBlanks": sum(1 for event in picture_events if event.is_gap),
        }
    )

    source_by_id, source_by_alias = _source_indexes(state)
    source_corrections = {
        str(record.get("shotId")): record
        for record in _read_json(
            SOURCE_CORRECTIONS_PATH, {"corrections": []}
        ).get("corrections", [])
        if record.get("shotId")
    }
    old_cuts = list(state.get("cuts", []))
    base_by_shot, old_to_shot, retired = _match_pipeline_cuts(
        old_cuts,
        picture_events,
        source_by_id,
    )
    new_cuts = []
    for index, event in enumerate(picture_events, start=1):
        chapter = next(
            item
            for item in chapters
            if item["startFrame"]
            <= event.record_in + event.duration_frames / 2
            < item["endFrame"]
        )
        source = (
            None
            if event.is_gap
            else _resolve_source(event, state, source_by_alias)
        )
        canonical_cut = _canonical_cut(
                event,
                index,
                base_by_shot.get(event.shot_id),
                source,
                chapter,
                edl_path,
                previous_source_keys.get(event.shot_id),
                generate_media,
            )
        new_cuts.append(
            _apply_source_correction(
                canonical_cut,
                source_corrections.get(event.shot_id),
            )
        )

    duration_frames = picture_events[-1].record_out
    blocks = [
        {
            "id": chapter["id"],
            "name": chapter["sectionName"],
            "path": str(edl_path),
            "track": 1,
            "start": chapter["start"],
            "end": chapter["end"],
            "duration": chapter["end"] - chapter["start"],
            "sectionCode": chapter["sectionCode"],
            "sectionName": chapter["sectionName"],
            "evidence": "confirmed",
            "boundaryAuthority": "canonical_edl_audio_edit",
            "manualTrimAuthority": True,
        }
        for chapter in chapters
    ]
    conform_segments = [
        copy.deepcopy(cut["sourceSegments"][0])
        for cut in new_cuts
        if not cut.get("isGap") and cut.get("sourceSegments")
    ]
    section_counts = Counter(
        segment["sectionCode"] for segment in conform_segments
    )
    state["cuts"] = new_cuts
    state["generatedAt"] = _utc_now()
    state["canonicalShotList"] = {
        "authority": "CMX3600 one-track picture EDL",
        "path": str(edl_path),
        "sha256": registry["canonicalEdlSha256"],
        "registryPath": str(REGISTRY_PATH),
        "fps": FPS,
        "pictureEvents": len(picture_events),
        "pictureShots": registry["pictureShots"],
        "intentionalBlanks": registry["intentionalBlanks"],
        "identityField": "shotId",
        "displayOrdinalField": "id",
        "recordOutSemantics": "exclusive; endTimecode is inclusive for display",
    }
    state["groundTruth"].update(
        {
            "title": "Paracosm canonical EDL",
            "duration": duration_frames / FPS,
            "durationTimecode": timecode(duration_frames),
            "fps": FPS,
        }
    )
    state["premiere"].update(
        {
            "project": str(edl_path),
            "sequence": "Paracosm Conform Codex JD Clean",
            "blocks": blocks,
            "primaryBlocks": blocks,
        }
    )
    state["premiereConform"].update(
        {
            "success": True,
            "authority": "Canonical CMX3600 EDL",
            "verifiedSegments": len(picture_events),
            "expectedSegments": len(picture_events),
            "sourceClipCount": registry["pictureShots"],
            "exactSourceClipCount": registry["pictureShots"],
            "canonicalSourceClipCount": registry["pictureShots"],
            "projectExport": str(edl_path),
            "fcpXml": "",
        }
    )
    state["conform"] = {
        "baseSequence": "Paracosm Conform Codex JD Clean",
        "project": str(edl_path),
        "authority": (
            "Canonical EDL record boundaries plus persistent source-media shot IDs"
        ),
        "timelineFrameRate": FPS,
        "sourceFrameRate": FPS,
        "segments": conform_segments,
        "omittedSubframeEvents": [],
        "summary": {
            "segments": len(conform_segments),
            "omittedSubframeEvents": 0,
            "confirmed": sum(
                1 for segment in conform_segments if segment["evidence"] == "confirmed"
            ),
            "strongInference": 0,
            "sections": dict(section_counts),
            "roles": {"exact_match": len(conform_segments)},
        },
    }
    state["revisedConform"].update(
        {
            "active": True,
            "authorityKind": "clean_v1_v2",
            "authority": (
                "Canonical one-track EDL owns shot order and record boundaries; "
                "persistent shotId owns Pipeline and Feedback attachments."
            ),
            "projectPath": str(edl_path),
            "projectSha256": registry["canonicalEdlSha256"],
            "sequence": "Paracosm Conform Codex JD Clean",
            "timelineFrameRate": FPS,
            "sourceImageFrameRate": FPS,
            "canonicalTracks": [1],
            "chapterBoundaryTrack": 1,
            "chapterCuts": chapters,
            "manualTrimPolicy": (
                "EDL record/source In/Out retained exactly at 24 fps; "
                "displayed shot ends are inclusive."
            ),
            "summary": {
                "pictureClips": registry["pictureShots"],
                "intentionalBlanks": registry["intentionalBlanks"],
                "inventoryIntervals": len(picture_events),
                "canonicalSources": registry["pictureShots"],
                "chapterCuts": len(chapters),
                "visibleDuration": duration_frames / FPS,
                "allClipInstancesLinked": all(
                    bool(segment.get("sourcePath")) for segment in conform_segments
                ),
                "statuses": {
                    "exact_match": sum(
                        1
                        for segment in conform_segments
                        if segment.get("sourcePath")
                    ),
                    "untracked": sum(
                        1
                        for segment in conform_segments
                        if not segment.get("sourcePath")
                    ),
                    "intentional_blank": registry["intentionalBlanks"],
                },
            },
        }
    )
    state["chapterEdits"] = [
        {
            "sectionCode": chapter["sectionCode"],
            "sectionName": chapter["sectionName"],
            "system": "canonical_edl",
            "projectLabel": "Paracosm Conform Codex JD Clean",
            "projectPath": str(edl_path),
            "editName": chapter["sectionName"],
            "editKind": "audio_record_boundary",
            "exportPath": str(edl_path),
            "finalSectionStart": chapter["start"],
            "evidence": "confirmed",
            "detail": (
                f"Canonical EDL chapter starts at {chapter['recordIn']}."
            ),
            "taggedCuts": sum(
                1
                for cut in new_cuts
                if cut["sectionCode"] == chapter["sectionCode"]
                and not cut.get("isGap")
            ),
        }
        for chapter in chapters
    ]
    state.setdefault("method", {})["boundaryStatus"] = "canonical_edl_record_in_out"
    notes = list(state.setdefault("method", {}).get("notes", []))
    notes = [
        note
        for note in notes
        if "Canonical CUT ids" not in note
        and "Visible CUT ids" not in note
    ]
    state["method"]["notes"] = [
        (
            "The canonical EDL is the only shot-order authority. Pipeline and "
            "Feedback both join through persistent shotId; CUT-### is display "
            "order and may change on every import."
        ),
        (
            "A removed or replaced source is retired. Its work is never "
            "silently reassigned to a new source occupying the same time range."
        ),
        *notes,
    ]
    _recount_summary(state, new_cuts)

    if feedback is not None:
        feedback = _migrate_feedback(
            feedback,
            old_to_shot,
            retired,
            source_by_id,
            registry,
        )
    return state, feedback, registry


def sync_files(
    *,
    edl_path: Path,
    import_edl: bool,
    generate_media: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    if import_edl:
        if edl_path.resolve() != DEFAULT_EDL.resolve():
            shutil.copy2(edl_path, DEFAULT_EDL)
        edl_path = DEFAULT_EDL
    state = _read_json(STATE_PATH, {})
    feedback = _read_json(FEEDBACK_PATH, {})
    registry = _read_json(REGISTRY_PATH, {})
    state, migrated_feedback, registry = sync_state(
        state,
        edl_path=edl_path,
        feedback=feedback,
        registry=registry,
        generate_media=generate_media,
    )
    assert migrated_feedback is not None
    _atomic_json(STATE_PATH, state)
    _atomic_json(FEEDBACK_PATH, migrated_feedback)
    _atomic_json(REGISTRY_PATH, registry)
    return state, migrated_feedback, registry


def sync_generated_state(
    state: dict[str, Any],
    *,
    generate_media: bool = True,
) -> dict[str, Any]:
    """Apply the canonical EDL before a newly scanned state is published."""

    if not DEFAULT_EDL.exists():
        return state
    feedback = _read_json(FEEDBACK_PATH, {})
    registry = _read_json(REGISTRY_PATH, {})
    state, feedback, registry = sync_state(
        state,
        edl_path=DEFAULT_EDL,
        feedback=feedback,
        registry=registry,
        generate_media=generate_media,
    )
    assert feedback is not None
    _atomic_json(FEEDBACK_PATH, feedback)
    _atomic_json(REGISTRY_PATH, registry)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--edl",
        type=Path,
        default=DEFAULT_EDL,
        help="Canonical CMX3600 EDL to import or synchronize.",
    )
    parser.add_argument(
        "--no-import",
        action="store_true",
        help="Read the supplied EDL in place instead of copying it into data/canonical.",
    )
    parser.add_argument(
        "--skip-media",
        action="store_true",
        help="Skip generation of local proxies for newly introduced shots.",
    )
    args = parser.parse_args()
    if not args.edl.exists():
        parser.error(f"EDL does not exist: {args.edl}")
    state, feedback, registry = sync_files(
        edl_path=args.edl,
        import_edl=not args.no_import,
        generate_media=not args.skip_media,
    )
    print(
        "Canonical shot list synchronized: "
        f"{len(state['cuts'])} events, "
        f"{sum(1 for cut in state['cuts'] if not cut.get('isGap'))} picture, "
        f"{sum(1 for cut in state['cuts'] if cut.get('isGap'))} gaps, "
        f"{sum(len(record.get('shotIds', [])) for record in [*feedback.get('generalNotes', []), *feedback['parents'], *feedback['notes']])} "
        "feedback assignments."
    )
    print(f"Registry: {registry['canonicalEdlSha256']}")


if __name__ == "__main__":
    main()
