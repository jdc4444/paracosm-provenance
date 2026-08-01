#!/usr/bin/env python3
"""Build the local, read-only Paracosm provenance index.

The creative files are never modified. Generated JSON, SQLite, and thumbnails
live inside this app's own data/archive directories.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canonical_edl import (
    DEFAULT_EDL,
    apply_source_corrections,
    assign_clean_shot_identities,
    sync_clean_conform_registry,
    sync_generated_state,
)
from revised_state import reconcile_revised_conform

APP_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = APP_ROOT / "data"
PUBLIC_DATA_DIR = APP_ROOT / "public" / "data"
CUT_ARCHIVE = APP_ROOT / "public" / "archive" / "cuts"
EXPORT_ARCHIVE = APP_ROOT / "public" / "archive" / "exports"
HOVER_PROXY = (
    APP_ROOT / "public" / "archive" / "reference" / "paracosm-hover.mp4"
)

ABSOLUTELY = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
REFERENCE_MOV = Path(
    "/Users/alphaone/Desktop/desktop 0705/Paracosm Full Copy 01.mov"
)
PREMIERE_PROJECT = ABSOLUTELY / "JD" / "10 Edit" / "Paracosm0226.prproj"
REVISED_CONFORM_EXPORT = (
    APP_ROOT / "data" / "premiere" / "revised-conform-export.json"
)
YELLOW_RECOVERY_CONFORM_EXPORT = (
    APP_ROOT / "data" / "premiere" / "yellow-recovery-conform-export.json"
)
CANONICAL_V6_V7_CONFORM_EXPORT = (
    APP_ROOT
    / "data"
    / "premiere"
    / "canonical-v6-v7-conform-export.json"
)
CLEAN_CONFORM_EXPORT = (
    APP_ROOT / "data" / "premiere" / "clean-conform-export.json"
)
CAMERA_PROOF_RENDER_EXPORT = (
    APP_ROOT / "data" / "c4d-camera-proof-renders.json"
)
ALTERNATE_SEARCH_EXPORT = (
    APP_ROOT / "data" / "premiere" / "alternate-search.json"
)
AUTHORITATIVE_CHAPTER_EDITS = (
    APP_ROOT / "data" / "authoritative-chapter-edits.json"
)
SOURCE_CONFIRMATIONS = APP_ROOT / "data" / "source-confirmations.json"
AS_FINISHING_CHRONOLOGY = (
    APP_ROOT / "data" / "as-finishing-chronology-20260727.json"
)
AS_FINISHING_CAMERA_PROOFS = (
    APP_ROOT / "data" / "as-finishing-camera-proofs-20260727.json"
)
AS_FINISHING_CAMERA_PROOF_RECOVERY_OVERRIDES = (
    APP_ROOT
    / "data"
    / "as-finishing-camera-proof-recovery-overrides-20260727.json"
)
C4D_CUT_RELINK_SUMMARY = (
    APP_ROOT / "data" / "c4d-cut-relink-summary-20260728.json"
)
C4D_CUT_DEPENDENCY_AUDIT_DIR = (
    APP_ROOT / "data" / "c4d-cut-dependency-audits-20260728"
)
C4D_FULL_COLOR_RENDER_INVENTORY = (
    APP_ROOT / "data" / "c4d-full-color-camera-render-inventory-20260729.json"
)
AS_FINISHING_REVISION_TARGETS = (
    APP_ROOT / "data" / "as-finishing-revision-targets-20260727.json"
)
C4D_UNRESOLVED_CAMERA_RECOVERIES = (
    APP_ROOT
    / "data"
    / "c4d-unresolved-camera-recoveries-20260727.json"
)
RESOLVE_DB = Path(
    "/Users/alphaone/Library/Application Support/Blackmagic Design/"
    "DaVinci Resolve/Resolve Project Library/Resolve Projects/Users/guest/"
    "Projects/Paracosm/Project.db"
)
TICKS_PER_SECOND = 254_016_000_000
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mxf"}
IMAGE_EXTENSIONS = {".tif", ".tiff", ".exr", ".png", ".jpg", ".jpeg"}
PROJECT_EXTENSIONS = {".c4d", ".aep", ".prproj"}

SECTION_BY_BLOCK = {
    "natural disaster": ("ND", "Natural Disaster", 1),
    "nth": ("NTH", "Nothing to Hide", 2),
    "th_test": ("TH", "Teardrop", 3),
    "na_test": ("NA", "New Again", 4),
    "na_0419": ("NA", "New Again", 4),
    "goodbye glitter": ("GG", "Goodbye Glitter", 5),
    "ijdkyy": ("IJDKYY", "If You Don't Know Yourself Yet", 6),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(message, flush=True)


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def ffprobe(path: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name:stream=index,codec_type,codec_name,"
            "width,height,r_frame_rate,pix_fmt",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def parse_time(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    parts = value.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def timecode(seconds: float, fps: float = 23.976) -> str:
    frames = max(0, round(seconds * fps))
    frame = frames % round(fps)
    whole = frames // round(fps)
    sec = whole % 60
    minute = (whole // 60) % 60
    hour = whole // 3600
    return f"{hour:02d}:{minute:02d}:{sec:02d}:{frame:02d}"


def safe_stat(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        return {
            "exists": True,
            "size": stat.st_size,
            "modifiedAt": datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat(),
        }
    except OSError:
        return {"exists": False, "size": 0, "modifiedAt": None}


def normalize_name(value: str) -> str:
    value = Path(value).stem.lower()
    value = re.sub(r"\b(v|ver|version)[ _-]*0*(\d+)\b", r"v\2", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def parse_aec_render_camera(path: Path) -> dict[str, Any] | None:
    """Read the render-time active camera embedded by Cinema 4D in an AEC."""

    try:
        lines = path.read_text(encoding="latin-1").splitlines()
    except OSError:
        return None
    composition = None
    current_camera = None
    cameras = []
    for raw_line in lines:
        line = raw_line.strip()
        composition_match = re.match(
            r'COMPOSITION\s+\S+\s+\S+\s+"([^"]+)"', line
        )
        if composition_match:
            composition = composition_match.group(1)
            continue
        camera_match = re.match(r'CAMERA\s+"([^"]+)"', line)
        if camera_match:
            current_camera = {
                "name": camera_match.group(1),
                "objectPath": camera_match.group(1),
                "source": "Cinema 4D AEC render metadata",
            }
            cameras.append(current_camera)
            continue
        if current_camera is None or not line.startswith("KEY "):
            continue
        tokens = line.split()
        if len(tokens) < 11:
            continue
        try:
            current_camera.update(
                {
                    "frame": int(float(tokens[1])),
                    "position": {
                        "x": float(tokens[2]),
                        "y": float(tokens[3]),
                        "z": float(tokens[4]),
                    },
                    "rotationDegrees": {
                        "x": float(tokens[5]),
                        "y": float(tokens[6]),
                        "z": float(tokens[7]),
                    },
                    "zoom": float(tokens[8]),
                    "active": bool(int(float(tokens[-1]))),
                }
            )
        except (TypeError, ValueError):
            continue
    active_camera = next(
        (camera for camera in cameras if camera.get("active")),
        None,
    )
    if active_camera is None:
        return None
    return {
        "path": str(path),
        "composition": composition,
        "activeCamera": active_camera["name"],
        "activeCameraObject": active_camera,
        "cameraCount": len(cameras),
    }


def embedded_project_prefix(image_files: list[str]) -> str | None:
    """Recover the C4D project-ish prefix embedded in beauty/AOV filenames."""

    prefixes: Counter[str] = Counter()
    for filename in image_files:
        stem = Path(filename).stem
        # AOV names are immutable render-time evidence and normally encode the
        # complete C4D project stem before `_AOV_`, including version digits.
        # Do not mistake the `001` in `_v001` for a frame number.
        aov_match = re.search(r"_AOV_", stem, flags=re.IGNORECASE)
        if aov_match:
            stem = stem[: aov_match.start()]
        else:
            stem = re.sub(r"_i\d+_\d+$", "", stem, flags=re.IGNORECASE)
            stem = re.sub(r"[_ -]?\d+$", "", stem)
        stem = stem.strip(" _-")
        if stem:
            prefixes[stem] += 1
    if not prefixes:
        return None
    return max(
        prefixes,
        key=lambda prefix: (
            bool(re.search(r"\bv\d+\b", prefix, flags=re.IGNORECASE)),
            len(normalize_name(prefix)),
            prefixes[prefix],
        ),
    )


def section_from_name(name: str) -> tuple[str, str, int]:
    lowered = name.lower()
    for key, section in SECTION_BY_BLOCK.items():
        if key in lowered:
            return section
    return ("UNK", "Unassigned", 0)


def load_shotlist() -> list[dict[str, Any]]:
    archive_path = DATA_DIR / "shotlist.csv"
    log("Reading the archived shotlist reference (Google Drive ignored)")
    if not archive_path.exists():
        raise RuntimeError(f"Archived shotlist is unavailable: {archive_path}")

    rows = []
    with archive_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        for index, row in enumerate(reader, start=1):
            row += [""] * max(0, len(header) - len(row))
            scene, song, shot = row[0].strip(), row[1].strip(), row[2].strip()
            if not (scene and song and shot):
                continue
            planned_id = f"{scene}{song}{shot}".replace(" ", "")
            rows.append(
                {
                    "index": index,
                    "id": planned_id,
                    "scene": scene,
                    "song": song,
                    "shot": shot,
                    "start": parse_time(row[3]),
                    "end": parse_time(row[4]),
                    "length": parse_time(row[5]),
                    "location": row[6].strip(),
                    "framing": row[7].strip(),
                    "description": row[8].strip(),
                    "character": row[9].strip(),
                    "action": row[10].strip(),
                    "simulation": row[11].strip(),
                    "note": row[12].strip(),
                    "fileName": row[13].strip(),
                    "camera": row[14].strip(),
                    "notes": row[15].strip() if len(row) > 15 else "",
                }
            )
    return rows


def resolve_object_graph(root: ET.Element) -> tuple[dict[str, ET.Element], dict[str, ET.Element]]:
    by_id = {}
    by_uid = {}
    for element in root.iter():
        object_id = element.attrib.get("ObjectID")
        object_uid = element.attrib.get("ObjectUID")
        if object_id:
            by_id[object_id] = element
        if object_uid:
            by_uid[object_uid] = element
    return by_id, by_uid


def object_ref(element: ET.Element | None, tag: str) -> str | None:
    if element is None:
        return None
    child = element.find(f".//{tag}")
    return child.attrib.get("ObjectRef") if child is not None else None


def media_path_for_subclip(
    subclip: ET.Element,
    by_id: dict[str, ET.Element],
    by_uid: dict[str, ET.Element],
) -> str:
    clip_ref = object_ref(subclip, "Clip")
    clip = by_id.get(clip_ref or "")
    source_ref = object_ref(clip, "Source")
    source = by_id.get(source_ref or "")
    media_link = source.find(".//Media") if source is not None else None
    media_uid = media_link.attrib.get("ObjectURef") if media_link is not None else None
    media = by_uid.get(media_uid or "")
    if media is None:
        return ""
    return (
        media.findtext("ActualMediaFilePath")
        or media.findtext("FilePath")
        or media.findtext("RelativePath")
        or ""
    )


def normalize_local_media_path(value: str) -> str:
    """Map archived workstation paths onto the local Dropbox mirror."""

    prefix = "/Volumes/Macintosh HD/Users/alphaone/"
    if value.startswith(prefix):
        return "/Users/alphaone/" + value[len(prefix) :]
    archived_dropbox = (
        "/Volumes/WORK/Guassian Dropbox/Steven Guas/Absolutely/"
    )
    if value.startswith(archived_dropbox):
        return (
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/JD/"
            + value[len(archived_dropbox) :]
        )
    archived_aabha_dropbox = "/Users/aabhasewak/Dropbox/Absolutely (1)/"
    if value.startswith(archived_aabha_dropbox):
        return (
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
            + value[len(archived_aabha_dropbox) :]
        )
    return value


def subclip_source_details(
    subclip: ET.Element,
    by_id: dict[str, ET.Element],
    by_uid: dict[str, ET.Element],
) -> dict[str, Any]:
    clip_ref = object_ref(subclip, "Clip")
    clip = by_id.get(clip_ref or "")
    source_ref = object_ref(clip, "Source")
    source = by_id.get(source_ref or "")
    sequence_name = ""
    sequence_uid = ""
    if source is not None and source.tag == "VideoSequenceSource":
        sequence_link = source.find(".//Sequence")
        sequence_uid = (
            sequence_link.attrib.get("ObjectURef", "")
            if sequence_link is not None
            else ""
        )
        nested = by_uid.get(sequence_uid)
        sequence_name = nested.findtext("Name") if nested is not None else ""
    return {
        "sourceIn": (
            int(clip.findtext(".//InPoint") or 0) / TICKS_PER_SECOND
            if clip is not None
            else 0.0
        ),
        "sourceOut": (
            int(clip.findtext(".//OutPoint") or 0) / TICKS_PER_SECOND
            if clip is not None
            else 0.0
        ),
        "playBackwards": (
            (clip.findtext(".//PlayBackwards") or "").lower() == "true"
            if clip is not None
            else False
        ),
        "sourceSequence": sequence_name or "",
        "sourceSequenceUid": sequence_uid,
    }


def premiere_sequence_items(
    sequence: ET.Element,
    by_id: dict[str, ET.Element],
    by_uid: dict[str, ET.Element],
    id_prefix: str,
) -> list[dict[str, Any]]:
    track_group_refs = [
        item.attrib.get("ObjectRef")
        for item in sequence.findall("./TrackGroups/TrackGroup/Second")
        if item.attrib.get("ObjectRef")
    ]
    video_group = next(
        (
            by_id[ref]
            for ref in track_group_refs
            if ref in by_id and by_id[ref].tag == "VideoTrackGroup"
        ),
        None,
    )
    items = []
    if video_group is None:
        return items
    for track_link in video_group.findall("./TrackGroup/Tracks/Track"):
        track_uid = track_link.attrib.get("ObjectURef", "")
        track = by_uid.get(track_uid)
        if track is None:
            continue
        track_index = int(track.findtext(".//Index") or 0)
        track_muted = (track.findtext(".//IsMuted") or "").lower() == "true"
        for item_link in track.findall(".//ClipItems/TrackItems/TrackItem"):
            item = by_id.get(item_link.attrib.get("ObjectRef", ""))
            if item is None or item.tag != "VideoClipTrackItem":
                continue
            subclip_ref = object_ref(item, "SubClip")
            subclip = by_id.get(subclip_ref or "")
            if subclip is None:
                continue
            start_ticks = int(item.findtext(".//TrackItem/Start") or 0)
            end_ticks = int(item.findtext(".//TrackItem/End") or 0)
            name = subclip.findtext("Name") or "Untitled"
            path = normalize_local_media_path(
                media_path_for_subclip(subclip, by_id, by_uid)
            )
            source_details = subclip_source_details(subclip, by_id, by_uid)
            code, section_name, scene = section_from_name(name)
            items.append(
                {
                    "id": f"{id_prefix}-{len(items) + 1:03d}",
                    "name": name,
                    "path": path,
                    "track": track_index + 1,
                    "start": start_ticks / TICKS_PER_SECOND,
                    "end": end_ticks / TICKS_PER_SECOND,
                    "duration": (end_ticks - start_ticks) / TICKS_PER_SECOND,
                    "muted": track_muted,
                    **source_details,
                    "sectionCode": code,
                    "sectionName": section_name,
                    "scene": scene,
                    "evidence": "confirmed",
                }
            )
    items.sort(key=lambda item: (item["start"], item["track"]))
    return items


def parse_premiere() -> dict[str, Any]:
    log("Parsing the final Premiere sequence")
    payload = gzip.open(PREMIERE_PROJECT, "rb").read()
    root = ET.fromstring(payload)
    by_id, by_uid = resolve_object_graph(root)
    sequence = next(
        (
            item
            for item in root.iter("Sequence")
            if item.findtext("Name") == "Paracosm Full Copy 01"
        ),
        None,
    )
    if sequence is None:
        raise RuntimeError("Premiere sequence 'Paracosm Full Copy 01' was not found")

    blocks = premiere_sequence_items(sequence, by_id, by_uid, "premiere")
    primary = [item for item in blocks if item["track"] == 1]
    source_sequences = []
    for index, source_sequence in enumerate(root.iter("Sequence"), start=1):
        source_name = source_sequence.findtext("Name") or f"Sequence {index}"
        if source_name == "Paracosm Full Copy 01":
            continue
        items = premiere_sequence_items(
            source_sequence, by_id, by_uid, f"premiere-source-{index:02d}"
        )
        if not items:
            continue
        source_sequences.append(
            {
                "name": source_name,
                "items": items,
                "duration": max(item["end"] for item in items)
                - min(item["start"] for item in items),
            }
        )
    return {
        "project": str(PREMIERE_PROJECT),
        "sequence": "Paracosm Full Copy 01",
        "blocks": blocks,
        "primaryBlocks": primary,
        "sourceSequences": source_sequences,
        "projectStat": safe_stat(PREMIERE_PROJECT),
    }


def premiere_sequence_by_name(
    premiere: dict[str, Any], name: str
) -> dict[str, Any] | None:
    if name == premiere.get("sequence"):
        return {
            "name": premiere["sequence"],
            "items": premiere.get("blocks", []),
        }
    return next(
        (
            sequence
            for sequence in premiere.get("sourceSequences", [])
            if sequence.get("name") == name
        ),
        None,
    )


def premiere_terminal_source(
    premiere: dict[str, Any],
    sequence_name: str,
    sequence_time: float,
    visited: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """Resolve the visible Premiere item recursively through nested sequences."""

    if sequence_name in visited:
        return None
    sequence = premiere_sequence_by_name(premiere, sequence_name)
    if not sequence:
        return None
    active = [
        item
        for item in sequence.get("items", [])
        if not item.get("muted")
        and float(item.get("start") or 0) - 1e-6
        <= sequence_time
        < float(item.get("end") or 0) - 1e-6
    ]
    if not active:
        return None
    item = max(active, key=lambda candidate: int(candidate.get("track") or 0))
    relative = max(0.0, sequence_time - float(item.get("start") or 0))
    source_in = float(item.get("sourceIn") or 0)
    source_out = float(item.get("sourceOut") or 0)
    source_time = (
        max(source_in, source_out - relative)
        if item.get("playBackwards")
        else source_in + relative
    )
    chain_item = {
        "sequence": sequence_name,
        "name": item.get("name") or "Untitled",
        "track": item.get("track"),
        "start": item.get("start"),
        "end": item.get("end"),
        "sourceTime": source_time,
        "sourceIn": source_in,
        "sourceOut": source_out,
        "playBackwards": bool(item.get("playBackwards")),
    }
    nested_name = str(item.get("sourceSequence") or "")
    if nested_name:
        nested = premiere_terminal_source(
            premiere,
            nested_name,
            source_time,
            (*visited, sequence_name),
        )
        if nested:
            nested["sequenceChain"] = [
                chain_item,
                *nested.get("sequenceChain", []),
            ]
            return nested
    return {
        "item": item,
        "sourceTime": source_time,
        "sequenceChain": [chain_item],
    }


def numbered_sequence_frame(
    source_path: str, source_time: float, frame_rate: float = 24.0
) -> tuple[str, int | None]:
    match = re.search(r"(\d+)(\.[^.]+)$", source_path)
    if not match:
        return source_path, None
    first_frame = int(match.group(1))
    frame_number = first_frame + max(0, round(source_time * frame_rate))
    candidate = (
        source_path[: match.start(1)]
        + str(frame_number).zfill(len(match.group(1)))
        + match.group(2)
    )
    return (candidate if Path(candidate).exists() else source_path), frame_number


def premiere_source_edit_boundaries(
    primary_blocks: list[dict[str, Any]], premiere: dict[str, Any]
) -> list[dict[str, Any]]:
    preferred_sequences = {
        "NTH": "NTH 2",
        "TH": "TH_test 1",
    }
    by_name = {
        item["name"]: item for item in premiere.get("sourceSequences", [])
    }
    boundaries = []
    for block in primary_blocks:
        sequence_name = preferred_sequences.get(block.get("sectionCode"))
        sequence = by_name.get(sequence_name or "")
        if not sequence:
            continue
        primary_items = [
            item
            for item in sequence.get("items", [])
            if item.get("track") == 1 and item.get("path")
        ]
        if not primary_items:
            continue
        sequence_start = min(item["start"] for item in primary_items)
        for item in primary_items:
            mapped = float(block["start"]) + float(item["start"]) - sequence_start
            if block["start"] - 0.05 <= mapped < block["end"] - 0.05:
                boundaries.append(
                    {
                        "time": max(float(block["start"]), mapped),
                        "evidence": "premiere_source_edit",
                        "detail": (
                            f"{sequence_name} · V{item['track']} · {item['name']}"
                        ),
                    }
                )
    return boundaries


def resolve_source_edit_boundaries(
    primary_blocks: list[dict[str, Any]], resolve: dict[str, Any]
) -> list[dict[str, Any]]:
    boundaries = []
    for block in primary_blocks:
        job = render_job_for_block(block, resolve)
        if not job:
            continue
        timeline_name = str(job.get("TimelineName") or job.get("Timeline") or "")
        timeline = next(
            (
                item
                for item in resolve.get("timelines", [])
                if item.get("name") == timeline_name
            ),
            None,
        )
        if not timeline:
            continue
        try:
            fps = float(job.get("FrameRate") or resolve.get("frameRate") or 24)
            mark_in = float(job.get("MarkIn") or timeline.get("startFrame") or 0)
        except (TypeError, ValueError):
            continue
        for track in timeline.get("tracks", []):
            for item in track.get("items", []):
                if not item.get("filePath"):
                    continue
                try:
                    item_start = float(item["start"])
                except (KeyError, TypeError, ValueError):
                    continue
                mapped = float(block["start"]) + (item_start - mark_in) / fps
                if block["start"] - 0.05 <= mapped < block["end"] - 0.05:
                    boundaries.append(
                        {
                            "time": max(float(block["start"]), mapped),
                            "evidence": "resolve_source_edit",
                            "detail": (
                                f"{timeline_name} · V{track.get('index')} · "
                                f"{item.get('name') or Path(item['filePath']).name}"
                            ),
                        }
                    )
    return boundaries


def source_media_edit_boundaries(
    primary_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Recover cuts inside exact baked source-edit exports used by Premiere."""

    cache_path = DATA_DIR / "source-media-boundaries.json"
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}
    boundaries = []
    changed = False
    for block in primary_blocks:
        if "na_0419" not in str(block.get("name") or "").lower():
            continue
        path = Path(str(block.get("path") or ""))
        if not path.exists():
            continue
        stat = safe_stat(path)
        record = cache.get(str(path), {})
        times = (
            record.get("times", [])
            if record.get("size") == stat["size"]
            and record.get("threshold") == 0.08
            else []
        )
        if not times:
            log(f"Detecting source-edit cuts inside {path.name}")
            result = run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    "-i",
                    str(path),
                    "-vf",
                    "scale=320:-2,select='gt(scene,0.08)',showinfo",
                    "-an",
                    "-f",
                    "null",
                    "-",
                ]
            )
            raw_times = [
                float(value)
                for value in re.findall(r"pts_time:([0-9.]+)", result.stderr)
            ]
            times = []
            for value in raw_times:
                if not times or value - times[-1] >= 0.35:
                    times.append(value)
            cache[str(path)] = {
                "size": stat["size"],
                "threshold": 0.08,
                "times": times,
            }
            changed = True
        for value in [0.0, *times]:
            mapped = float(block["start"]) + float(value)
            if mapped < float(block["end"]) - 0.05:
                boundaries.append(
                    {
                        "time": mapped,
                        "evidence": "source_media_edit",
                        "detail": f"{path.name} · exact baked source-edit cut",
                    }
                )
    if changed:
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return boundaries


def scene_boundaries(
    duration: float,
    primary_blocks: list[dict[str, Any]],
    premiere: dict[str, Any],
    resolve: dict[str, Any],
    after_effects_mappings: list[dict[str, Any]],
    conform: dict[str, Any],
) -> tuple[list[float], dict[float, dict[str, Any]]]:
    cache = DATA_DIR / "scene-boundaries.json"
    reference_stat = safe_stat(REFERENCE_MOV)
    visual_times = []
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("referenceSize") == reference_stat["size"]:
            visual_times = [
                float(value)
                for value in cached.get(
                    "visualBoundaries", cached.get("boundaries", [])
                )
            ]

    if not visual_times:
        log("Detecting edit boundaries in the immutable reference film")
        result = run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "info",
                "-i",
                str(REFERENCE_MOV),
                "-vf",
                "scale=320:-2,select='gt(scene,0.30)',showinfo",
                "-an",
                "-f",
                "null",
                "-",
            ]
        )
        visual_times = [
            float(value)
            for value in re.findall(r"pts_time:([0-9.]+)", result.stderr)
        ]

    editorial_boundaries = [
        *premiere_source_edit_boundaries(primary_blocks, premiere),
        *resolve_source_edit_boundaries(primary_blocks, resolve),
        *source_media_edit_boundaries(primary_blocks),
    ]
    ae_boundaries = [
        item
        for item in after_effects_source_edit_boundaries(after_effects_mappings)
    ]
    source_boundaries = [*editorial_boundaries, *ae_boundaries]

    def active_blocks_at(value: float) -> list[dict[str, Any]]:
        return sorted(
            (
                block
                for block in premiere.get("blocks", [])
                if not block.get("muted")
                and float(block["start"]) <= value < float(block["end"])
            ),
            key=lambda block: int(block.get("track") or 0),
        )

    def visible_block_at(value: float) -> dict[str, Any] | None:
        active = active_blocks_at(value)
        return active[-1] if active else None

    def visible_section_at(value: float) -> str:
        active = active_blocks_at(value)
        if not active:
            return "GAP"
        top = active[-1]
        if top.get("sectionCode") != "UNK":
            return str(top.get("sectionCode") or "UNK")
        fallback = next(
            (
                block
                for block in reversed(active[:-1])
                if block.get("sectionCode") != "UNK"
            ),
            top,
        )
        return str(fallback.get("sectionCode") or "UNK")

    visible_block_changes = []
    block_points = sorted(
        {
            float(value)
            for block in premiere.get("blocks", [])
            for value in (block["start"], block["end"])
            if 0 <= float(value) < duration - 0.05
        }
    )
    for value in block_points:
        before = visible_block_at(max(0.0, value - 0.001))
        after = visible_block_at(min(duration - 0.001, value + 0.001))
        if (before or {}).get("id") == (after or {}).get("id"):
            continue
        visible_block_changes.append(
            {
                "time": value,
                "evidence": "premiere_block",
                "detail": (
                    "Visible Premiere layer change · "
                    f"{(after or before or {}).get('name') or 'no active picture'}"
                ),
            }
        )

    confirmed_segments = [
        segment
        for segment in conform.get("segments", [])
        if segment.get("evidence") == "confirmed"
    ]
    conform_boundaries = [
        {
            "time": float(segment["finalStart"]),
            "evidence": "source_conform",
            "detail": (
                f"{segment.get('sourceEdit') or segment.get('sourceSystem')} · "
                f"{Path(str(segment.get('sourcePath') or '')).name}"
            ),
        }
        for segment in confirmed_segments
        if segment.get("sectionCode")
        == visible_section_at(float(segment["finalStart"]) + 0.001)
    ]
    exact_source_media_boundaries = [
        boundary
        for boundary in source_boundaries
        if boundary.get("evidence") == "source_media_edit"
    ]

    def visual_boundary_is_uncovered(value: float) -> bool:
        section = visible_section_at(value)
        return not any(
            segment.get("sectionCode") == section
            and float(segment["finalStart"]) + 0.12
            < value
            < float(segment["finalEnd"]) - 0.12
            for segment in confirmed_segments
        )

    candidates = [
        {"time": 0.0, "evidence": "reference_start", "detail": "Reference start"},
        *[
            {
                "time": float(value),
                "evidence": "visual_boundary",
                "detail": "Reference-film scene score > 0.30",
            }
            for value in visual_times
            if visual_boundary_is_uncovered(float(value))
        ],
        *visible_block_changes,
        *conform_boundaries,
        *exact_source_media_boundaries,
    ]
    priority = {
        "reference_start": 5,
        "source_conform": 4,
        "resolve_source_edit": 3,
        "premiere_source_edit": 3,
        "source_media_edit": 3,
        "after_effects_source_edit": 3,
        "premiere_block": 2,
        "visual_boundary": 1,
    }
    clusters: list[list[dict[str, Any]]] = []
    for candidate in sorted(
        (
            item
            for item in candidates
            if 0 <= float(item["time"]) < duration - 0.05
        ),
        key=lambda item: float(item["time"]),
    ):
        if not clusters or float(candidate["time"]) - float(clusters[-1][-1]["time"]) > 0.12:
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)

    chosen = [
        sorted(
            cluster,
            key=lambda item: (
                priority.get(str(item["evidence"]), 0),
                -abs(float(item["time"]) - float(cluster[0]["time"])),
            ),
            reverse=True,
        )[0]
        for cluster in clusters
    ]
    for item in chosen:
        corroborating = [
            source
            for source in source_boundaries
            if abs(float(source["time"]) - float(item["time"])) <= 0.12
        ]
        if corroborating:
            source = max(
                corroborating,
                key=lambda candidate: priority.get(str(candidate["evidence"]), 0),
            )
            item["evidence"] = source["evidence"]
            item["detail"] = (
                f"{source['detail']} · final-reference boundary corroborated"
            )
    cleaned = [round(float(item["time"]), 6) for item in chosen]
    evidence = {
        round(float(item["time"]), 6): {
            "kind": item["evidence"],
            "detail": item["detail"],
        }
        for item in chosen
    }
    cache.write_text(
        json.dumps(
            {
                "version": 4,
                "threshold": 0.30,
                "visualMinimumGap": 0.45,
                "sourceMergeTolerance": 0.12,
                "canonicalPolicy": (
                    "visible Premiere layer changes plus terminal source-conform "
                    "boundaries; film-only boundaries retained where source coverage "
                    "is absent"
                ),
                "referenceSize": reference_stat["size"],
                "visualBoundaries": visual_times,
                "boundaries": cleaned,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return cleaned, evidence


def generate_thumbnails(cuts: list[dict[str, Any]], quick: bool) -> None:
    index_path = DATA_DIR / "cut-thumbnails-index.json"
    archived = {}
    if index_path.exists():
        try:
            archived = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            archived = {}
    missing = [
        cut
        for cut in cuts
        if not (CUT_ARCHIVE / f"{cut['id']}.jpg").exists()
        or abs(
            float(archived.get(cut["id"], {}).get("start", -9999))
            - float(cut["start"])
        )
        > 0.001
        or abs(
            float(archived.get(cut["id"], {}).get("end", -9999))
            - float(cut["end"])
        )
        > 0.001
    ]
    if not missing:
        return
    if quick:
        log(
            f"Quick scan found {len(missing)} stale reference-cut thumbnails; "
            "refreshing them for canonical accuracy"
        )
    log(f"Archiving {len(missing)} reference-cut thumbnails")
    CUT_ARCHIVE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="paracosm-cuts-") as temp_dir:
        temp = Path(temp_dir)
        for index, cut in enumerate(missing, start=1):
            # A fixed minimum can step beyond very short intervals and sample
            # the following shot. Midpoint sampling is always inside the cut.
            point = cut["start"] + cut["duration"] * 0.5
            target = temp / f"{index:04d}.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{point:.6f}",
                    "-i",
                    str(REFERENCE_MOV),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=720:-2",
                    "-q:v",
                    "3",
                    str(target),
                ],
                check=True,
            )
            shutil.move(target, CUT_ARCHIVE / f"{cut['id']}.jpg")
    index_path.write_text(
        json.dumps(
            {
                cut["id"]: {"start": cut["start"], "end": cut["end"]}
                for cut in cuts
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def normalized_export_name(value: str) -> str:
    """Normalize an export filename, including Finder's duplicate suffix."""

    stem = Path(value).stem.lower()
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", stem)


def after_effects_export_producer(
    export_path: str,
    cut: dict[str, Any],
    archives: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the AE project/comp that rendered an export already in lineage."""

    target = normalized_export_name(export_path)
    if not target:
        return None
    lineage_projects = {
        str(Path(str(node.get("path") or "")).expanduser().resolve())
        for node in cut.get("lineage", [])
        if node.get("kind") == "after_effects"
        and str(node.get("path") or "").lower().endswith(".aep")
    }
    matches = []
    for archive in archives:
        for project in archive.get("projects", []):
            project_path = str(project.get("path") or "")
            if not project_path:
                continue
            resolved_project = str(Path(project_path).expanduser().resolve())
            if lineage_projects and resolved_project not in lineage_projects:
                continue
            for queue_item in project.get("renderQueue", []):
                for output in queue_item.get("outputs", []):
                    output_path = str(output.get("file") or "")
                    if normalized_export_name(output_path) != target:
                        continue
                    matches.append(
                        {
                            "kind": "after_effects",
                            "label": Path(project_path).name,
                            "projectPath": project_path,
                            "sequence": queue_item.get("compName") or "AE composition",
                            "detail": "Render Queue output filename matches this export",
                            "evidence": next(
                                (
                                    node.get("evidence") or "strong_inference"
                                    for node in cut.get("lineage", [])
                                    if node.get("kind") == "after_effects"
                                    and str(
                                        Path(str(node.get("path") or ""))
                                        .expanduser()
                                        .resolve()
                                    )
                                    == resolved_project
                                ),
                                "strong_inference",
                            ),
                        }
                    )
    return matches[-1] if matches else None


def video_duration(path: Path, cache: dict[str, float]) -> float | None:
    key = str(path)
    if key in cache:
        return cache[key]
    try:
        duration = float(ffprobe(path)["format"]["duration"])
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
        return None
    cache[key] = duration
    return duration


def archive_export_frame(
    path: Path,
    point: float,
    target: Path,
    duration_cache: dict[str, float],
) -> bool:
    """Archive one concrete frame from a lineage export without touching it."""

    duration = video_duration(path, duration_cache)
    if duration is None or duration <= 0:
        return False
    safe_point = min(max(0.0, point), max(0.0, duration - 0.05))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.png")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{safe_point:.6f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=720:-2",
                "-compression_level",
                "5",
                "-y",
                str(temporary),
            ],
            check=True,
        )
        temporary.replace(target)
        return True
    except (OSError, subprocess.SubprocessError):
        temporary.unlink(missing_ok=True)
        return False


def archive_lineage_export_screenshots(
    cuts: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    premiere: dict[str, Any],
    after_effects_archives: list[dict[str, Any]],
) -> int:
    """Attach shot-specific frames from concrete exports in each lineage."""

    block_by_id = {str(block["id"]): block for block in blocks}
    index_path = DATA_DIR / "lineage-export-screenshots.json"
    previous = {}
    if index_path.exists():
        try:
            previous = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    previous_records = {
        str(item.get("id")): item for item in previous.get("screenshots", [])
    }
    duration_cache: dict[str, float] = {}
    archive_records = []
    screenshot_count = 0

    for cut in cuts:
        # The frame-aligned Premiere verifier contributes saved-project
        # boundary sheets before this concrete-export archive pass. Preserve
        # those shot-specific proofs while refreshing the ordinary export
        # frames so they cannot become stale.
        cut["exportScreenshots"] = [
            item
            for item in cut.get("exportScreenshots", [])
            if item.get("role") == "frame_aligned_boundary"
        ]
        if cut.get("isGap"):
            continue
        midpoint = float(cut["start"]) + float(cut["duration"]) / 2
        candidates: list[dict[str, Any]] = []
        block = block_by_id.get(str(cut.get("blockId") or ""))
        screenshot_block = block
        if (
            screenshot_block is None
            or Path(str(screenshot_block.get("path") or "")).suffix.lower()
            not in VIDEO_EXTENSIONS
        ):
            screenshot_block = block_by_id.get(
                str(cut.get("supportingPremiereExportBlockId") or "")
            )

        if screenshot_block:
            block_path = Path(
                normalize_local_media_path(
                    str(screenshot_block.get("path") or "")
                )
            )
            if block_path.suffix.lower() in VIDEO_EXTENSIONS and block_path.exists():
                elapsed = midpoint - float(screenshot_block["start"])
                if screenshot_block.get("playBackwards"):
                    source_time = (
                        float(screenshot_block.get("sourceOut") or 0)
                        - elapsed
                    )
                else:
                    source_time = (
                        float(screenshot_block.get("sourceIn") or 0)
                        + elapsed
                    )
                producers = [
                    {
                        "kind": "premiere",
                        "label": Path(str(premiere.get("project") or "")).name,
                        "projectPath": premiere.get("project"),
                        "sequence": premiere.get("sequence"),
                        "detail": (
                            f"V{screenshot_block.get('track')} source block in "
                            "the final Premiere sequence"
                        ),
                        "evidence": "confirmed",
                    }
                ]
                resolve_node = next(
                    (
                        node
                        for node in cut.get("lineage", [])
                        if node.get("kind") == "resolve"
                    ),
                    None,
                )
                if resolve_node:
                    producers.append(
                        {
                            "kind": "resolve",
                            "label": "Paracosm",
                            "projectPath": resolve_node.get("path"),
                            "sequence": resolve_node.get("label"),
                            "detail": resolve_node.get("detail"),
                            "evidence": resolve_node.get("evidence") or "confirmed",
                        }
                    )
                ae_producer = after_effects_export_producer(
                    str(block_path), cut, after_effects_archives
                )
                if ae_producer:
                    producers.append(ae_producer)
                candidates.append(
                    {
                        "role": (
                            "supporting-edit-export"
                            if block
                            and screenshot_block.get("id") != block.get("id")
                            else "edit-block"
                        ),
                        "label": (
                            screenshot_block.get("name") or block_path.name
                        ),
                        "exportPath": str(block_path),
                        "sourceTime": source_time,
                        "detail": (
                            "Shot midpoint in the concrete section export "
                            f"used on V{screenshot_block.get('track')}"
                        ),
                        "evidence": "confirmed",
                        "producers": producers,
                    }
                )

        resolve_media = cut.get("resolveMediaExport")
        if resolve_media:
            media_path = Path(
                normalize_local_media_path(
                    str(resolve_media.get("exportPath") or "")
                )
            )
            if media_path.suffix.lower() in VIDEO_EXTENSIONS and media_path.exists():
                producers = [
                    {
                        "kind": "resolve",
                        "label": "Paracosm",
                        "projectPath": str(RESOLVE_DB),
                        "sequence": resolve_media.get("timeline"),
                        "detail": "Visible source media on the Resolve timeline",
                        "evidence": "confirmed",
                    }
                ]
                ae_producer = after_effects_export_producer(
                    str(media_path), cut, after_effects_archives
                )
                if ae_producer:
                    producers.append(ae_producer)
                candidates.append(
                    {
                        "role": "resolve-source",
                        "label": media_path.name,
                        "exportPath": str(media_path),
                        "sourceTime": float(resolve_media.get("sourceTime") or 0),
                        "detail": "Shot-specific frame from the Resolve source export",
                        "evidence": "confirmed",
                        "producers": producers,
                    }
                )

        canonical_edit = cut.get("canonicalChapterEdit") or {}
        canonical_export = Path(
            normalize_local_media_path(
                str(canonical_edit.get("exportPath") or "")
            )
        )
        if (
            canonical_edit
            and canonical_export.suffix.lower() in VIDEO_EXTENSIONS
            and canonical_export.exists()
        ):
            if canonical_edit.get("finalToExportOffset") is not None:
                canonical_source_time = midpoint - float(
                    canonical_edit["finalToExportOffset"]
                )
            else:
                canonical_source_time = midpoint - float(
                    canonical_edit.get("finalSectionStart") or 0
                )
            if canonical_source_time >= 0:
                candidates.append(
                    {
                        "role": "chapter-edit-export",
                        "label": canonical_export.name,
                        "exportPath": str(canonical_export),
                        "sourceTime": canonical_source_time,
                        "detail": (
                            "Shot-specific frame from the verified chapter "
                            f"edit export for {cut.get('sectionCode')}"
                        ),
                        "evidence": str(
                            canonical_edit.get("evidence") or "confirmed"
                        ),
                        "producers": [
                            {
                                "kind": canonical_edit.get("system"),
                                "label": canonical_edit.get("projectLabel"),
                                "projectPath": canonical_edit.get(
                                    "projectPath"
                                ),
                                "sequence": canonical_edit.get("editName"),
                                "detail": canonical_edit.get("detail"),
                                "evidence": canonical_edit.get("evidence")
                                or "confirmed",
                            }
                        ],
                    }
                )

        for node in cut.get("lineage", []):
            node_path = Path(
                normalize_local_media_path(str(node.get("path") or ""))
            )
            if (
                node.get("kind") != "after_effects_comp"
                or node_path.suffix.lower() not in VIDEO_EXTENSIONS
                or not node_path.exists()
                or any(
                    candidate["exportPath"] == str(node_path)
                    for candidate in candidates
                )
            ):
                continue
            source_time = None
            for segment in cut.get("sourceSegments", []):
                visual_match = segment.get("visualMatch") or {}
                if (
                    str(visual_match.get("sourceEditPath") or "") == str(node_path)
                    and visual_match.get("sourceEditTime") is not None
                ):
                    segment_midpoint = (
                        float(segment["finalStart"]) + float(segment["finalEnd"])
                    ) / 2
                    source_time = float(visual_match["sourceEditTime"]) + (
                        midpoint - segment_midpoint
                    )
                    break
            if source_time is None:
                source_time = float(
                    (cut.get("afterEffectsConform") or {}).get("sourceTime") or 0
                )
            ae_node = next(
                (
                    candidate
                    for candidate in cut.get("lineage", [])
                    if candidate.get("kind") == "after_effects"
                ),
                None,
            )
            candidates.append(
                {
                    "role": "ae-source-edit",
                    "label": node.get("label") or node_path.name,
                    "exportPath": str(node_path),
                    "sourceTime": source_time,
                    "detail": "Shot-specific frame from the consolidated AE source edit",
                    "evidence": node.get("evidence") or "confirmed",
                    "producers": [
                        {
                            "kind": "after_effects",
                            "label": (
                                ae_node.get("label")
                                if ae_node
                                else node_path.name
                            ),
                            "projectPath": (
                                ae_node.get("path") if ae_node else str(node_path)
                            ),
                            "sequence": node.get("label"),
                            "detail": node.get("detail"),
                            "evidence": node.get("evidence") or "confirmed",
                        }
                    ],
                }
            )

        unique_candidates = {}
        for candidate in candidates:
            identity = (
                candidate["exportPath"],
                round(float(candidate["sourceTime"]), 3),
            )
            if identity not in unique_candidates:
                unique_candidates[identity] = candidate
                continue
            existing_kinds = {
                producer["kind"]
                for producer in unique_candidates[identity]["producers"]
            }
            unique_candidates[identity]["producers"].extend(
                producer
                for producer in candidate["producers"]
                if producer["kind"] not in existing_kinds
            )

        for ordinal, candidate in enumerate(unique_candidates.values(), start=1):
            screenshot_id = f"{cut['id']}-export-{ordinal:02d}"
            target = EXPORT_ARCHIVE / f"{screenshot_id}.png"
            source_path = Path(candidate["exportPath"])
            source_stat = safe_stat(source_path)
            signature = {
                "exportPath": str(source_path),
                "sourceTime": round(float(candidate["sourceTime"]), 6),
                "sourceSize": source_stat.get("size"),
                "sourceModifiedAt": source_stat.get("modifiedAt"),
            }
            previous_record = previous_records.get(screenshot_id) or {}
            needs_archive = (
                not target.exists()
                or any(
                    previous_record.get(key) != value
                    for key, value in signature.items()
                )
            )
            if needs_archive and not archive_export_frame(
                source_path,
                float(candidate["sourceTime"]),
                target,
                duration_cache,
            ):
                continue
            record = {
                "id": screenshot_id,
                "image": f"/archive/exports/{target.name}",
                **candidate,
                **signature,
            }
            cut["exportScreenshots"].append(record)
            archive_records.append({"cutId": cut["id"], **record})
            screenshot_count += 1

    EXPORT_ARCHIVE.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "generatedAt": now_iso(),
                "screenshots": archive_records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return screenshot_count


def append_lineage_tag(
    node: dict[str, Any],
    tag_type: str,
    detail: str,
    evidence: str,
) -> None:
    tags = node.setdefault("tags", [])
    if any(tag.get("type") == tag_type for tag in tags):
        return
    tags.append(
        {
            "type": tag_type,
            "label": tag_type.replace("_", " ").title(),
            "detail": detail,
            "evidence": evidence,
        }
    )


def apply_authoritative_chapter_edits(
    cuts: list[dict[str, Any]],
    *,
    tag_nodes: bool,
) -> dict[str, Any]:
    """Attach the verified chapter edit for every section.

    These assignments supersede producer-order heuristics. In particular,
    After Effects auto-saves can remain useful layer evidence without being
    mislabeled as the canonical chapter edit.
    """

    archive = load_creative_app_archive("authoritative-chapter-edits.json")
    sections = archive.get("sections", {})
    tagged_cuts = 0
    chapter_records = []

    for section_code, spec in sections.items():
        edit_kind = str(spec.get("editKind") or spec.get("system") or "")
        project_path = str(spec.get("projectPath") or "")
        edit_name = str(spec.get("editName") or "Chapter edit")
        section_cuts = [
            cut
            for cut in cuts
            if cut.get("sectionCode") == section_code
            and not cut.get("isGap")
        ]
        for cut in section_cuts:
            cut["canonicalChapterEdit"] = {
                "sectionCode": section_code,
                **spec,
            }
            if tag_nodes:
                for node in cut.get("lineage", []):
                    tags = [
                        tag
                        for tag in node.get("tags", [])
                        if tag.get("type") != "chapter_edit"
                    ]
                    if tags:
                        node["tags"] = tags
                    else:
                        node.pop("tags", None)

            project_kind = str(spec.get("system") or "")
            project_node = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if str(node.get("path") or "") == project_path
                    and node.get("kind")
                    in {
                        project_kind,
                        "premiere",
                        "resolve",
                        "after_effects",
                    }
                ),
                None,
            )
            if project_node is None and edit_kind != project_kind:
                project_node = {
                    "kind": project_kind,
                    "label": str(spec.get("projectLabel") or Path(project_path).name),
                    "detail": (
                        f"Verified {spec.get('sectionName') or section_code} "
                        "chapter project"
                    ),
                    "path": project_path,
                    "projectPath": project_path,
                    "evidence": str(spec.get("evidence") or "confirmed"),
                }
                insert_at = next(
                    (
                        index
                        for index, node in enumerate(cut.get("lineage", []))
                        if node.get("kind")
                        in {
                            "resolve_media",
                            "after_effects_layer",
                            "render_sequence",
                            "cinema4d",
                            "camera",
                        }
                    ),
                    len(cut.get("lineage", [])),
                )
                cut["lineage"].insert(insert_at, project_node)

            edit_node = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if node.get("kind") == edit_kind
                    and node.get("label") == edit_name
                    and (
                        str(node.get("path") or "") == project_path
                        or (
                            edit_kind == "resolve"
                            and str(node.get("path") or "") == project_path
                        )
                    )
                ),
                None,
            )
            if edit_node is None:
                edit_node = {
                    "kind": edit_kind,
                    "label": edit_name,
                    "detail": str(spec.get("detail") or "Verified chapter edit"),
                    "path": project_path,
                    "projectPath": project_path,
                    "evidence": str(spec.get("evidence") or "confirmed"),
                }
                if spec.get("editAlias"):
                    edit_node["detail"] += f" · Alias: {spec['editAlias']}"
                insert_at = (
                    cut["lineage"].index(project_node) + 1
                    if project_node in cut.get("lineage", [])
                    else len(cut.get("lineage", []))
                )
                cut["lineage"].insert(insert_at, edit_node)
            else:
                edit_node["detail"] = str(
                    spec.get("detail") or edit_node.get("detail") or ""
                )
                edit_node["projectPath"] = project_path
                edit_node["evidence"] = str(
                    spec.get("evidence") or "confirmed"
                )

            if tag_nodes:
                append_lineage_tag(
                    edit_node,
                    "chapter_edit",
                    (
                        f"{spec.get('projectLabel') or Path(project_path).name} · "
                        f"{edit_name} is the verified "
                        f"{spec.get('sectionName') or section_code} chapter edit"
                    ),
                    str(spec.get("evidence") or "confirmed"),
                )
                tagged_cuts += 1

        chapter_records.append(
            {
                "sectionCode": section_code,
                **spec,
                "taggedCuts": len(section_cuts),
            }
        )

    return {
        "chapterEditTaggedCuts": tagged_cuts,
        "chapterEdits": chapter_records,
    }


def apply_source_confirmations(
    cuts: list[dict[str, Any]],
) -> dict[str, int]:
    """Apply user-named, frame-checked source recoveries without moving V1."""

    archive = load_creative_app_archive("source-confirmations.json")
    cuts_by_id = {str(cut.get("id")): cut for cut in cuts}
    confirmed = 0
    candidates = 0

    for record in archive.get("confirmations", []):
        record_source_path = str(record.get("sourcePath") or "")
        record_render_directory = str(record.get("renderDirectory") or "")
        cut = next(
            (
                candidate
                for candidate in cuts
                if not candidate.get("isGap")
                and any(
                    str(segment.get("sourcePath") or "")
                    == record_source_path
                    or str(segment.get("renderDirectory") or "")
                    == record_render_directory
                    for segment in candidate.get("sourceSegments", [])
                )
            ),
            cuts_by_id.get(str(record.get("cutId") or "")),
        )
        if cut is None or cut.get("isGap"):
            continue
        status = str(record.get("status") or "candidate")
        render_directory = str(record.get("renderDirectory") or "")
        source_path = str(record.get("sourcePath") or "")
        first_frame = int(record.get("sourceStartFrame") or 0)
        last_frame = int(record.get("sourceEndFrame") or first_frame)
        evidence = "confirmed" if status == "confirmed" else "candidate"
        comparison_scores = [
            float(value)
            for value in (
                record.get("comparisonScores", [])
                or [
                    item.get("luminanceCorrelation")
                    for item in record.get("frameChecks", [])
                ]
            )
            if isinstance(value, (int, float))
        ]
        target_track = int(record.get("conformTrack") or 0)
        matching_segment = next(
            (
                segment
                for segment in cut.get("sourceSegments", [])
                if (
                    str(segment.get("sourcePath") or "") == source_path
                    or str(segment.get("renderDirectory") or "")
                    == render_directory
                )
            ),
            None,
        )
        inserted_in_premiere = matching_segment is not None

        if status == "confirmed":
            segment_id = f"RECOVERED-{cut['id']}"
            cut["sourceSegments"] = [
                segment
                for segment in cut.get("sourceSegments", [])
                if segment.get("id") != segment_id
            ]
            if matching_segment is None:
                cut["sourceSegments"].append(
                    {
                    "id": segment_id,
                    "sectionCode": cut["sectionCode"],
                    "finalStart": cut["start"],
                    "finalEnd": cut["end"],
                    "finalStartFrame": round(float(cut["start"]) * 23.976023976),
                    "finalEndFrame": round(float(cut["end"]) * 23.976023976),
                    "sourceSystem": "Recovered exact source",
                    "sourceEdit": (
                        "Exact source render · user-named chapter evidence"
                    ),
                    "sourcePath": source_path,
                    "renderDirectory": render_directory,
                    "sourceFirstFramePath": concrete_sequence_frame(
                        source_path, first_frame
                    ),
                    "sourceLastFramePath": concrete_sequence_frame(
                        source_path, last_frame
                    ),
                    "sourceStartFrame": first_frame,
                    "sourceEndFrame": last_frame,
                    "sourceFrameRate": float(
                        record.get("sourceFrameRate") or 24
                    ),
                    "sourceTrack": None,
                    "playBackwards": last_frame < first_frame,
                    "evidence": "confirmed",
                    "role": "exact_match",
                    "manualTrimAuthority": False,
                    "confirmationMethod": record.get("confirmationMethod"),
                    "comparisonScores": comparison_scores,
                    }
                )
            else:
                matching_segment["evidence"] = "confirmed"
                matching_segment["confirmationMethod"] = record.get(
                    "confirmationMethod"
                )
                matching_segment["comparisonScores"] = comparison_scores
            matching_render = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if node.get("kind") == "render_sequence"
                    and str(node.get("path") or "") == render_directory
                ),
                None,
            )
            if matching_render is None:
                matching_render = {
                    "kind": "render_sequence",
                    "label": Path(render_directory).name,
                    "detail": str(record.get("confirmationMethod") or ""),
                    "path": render_directory,
                    "evidence": "confirmed",
                }
                insert_at = next(
                    (
                        index
                        for index, node in enumerate(cut.get("lineage", []))
                        if node.get("kind") in {"cinema4d", "camera"}
                    ),
                    len(cut.get("lineage", [])),
                )
                cut["lineage"].insert(insert_at, matching_render)
            else:
                matching_render["evidence"] = "confirmed"
                matching_render["detail"] = str(
                    record.get("confirmationMethod")
                    or matching_render.get("detail")
                    or ""
                )

            project_path = str(record.get("projectPath") or "")
            project_node = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if node.get("kind") == "cinema4d"
                    and str(node.get("path") or "") == project_path
                ),
                None,
            )
            camera = record.get("camera") or {}
            if project_path and project_node is None:
                project_node = {
                    "kind": "cinema4d",
                    "label": Path(project_path).name,
                    "detail": (
                        "Recovered source project; render output "
                        + (
                            "matches the confirmed sequence"
                            if camera.get("outputPath")
                            else "camera probe still pending"
                        )
                    ),
                    "path": project_path,
                    "projectPath": project_path,
                    "evidence": (
                        "confirmed"
                        if camera.get("outputPath")
                        else "candidate"
                    ),
                }
                cut["lineage"].append(project_node)
            elif project_node is not None and camera.get("outputPath"):
                project_node["evidence"] = "confirmed"
                project_node["detail"] = (
                    "C4D render setting output matches the recovered "
                    "source sequence exactly"
                )

            if project_path and camera:
                cut["lineage"] = [
                    node
                    for node in cut.get("lineage", [])
                    if not (
                        node.get("kind") == "camera"
                        and str(node.get("path") or "") == project_path
                    )
                ]
                cut["lineage"].append(
                    {
                        "kind": "camera",
                        "label": camera.get("name") or "Camera",
                        "detail": (
                            f"Take: {camera.get('take') or 'Main'} · "
                            f"Render data: {camera.get('renderData') or 'unnamed'} · "
                            "Render-output alignment: exact path · "
                            f"GUID: {camera.get('guid') or 'unavailable'} · "
                            f"Output: {camera.get('outputPath')} · "
                            f"C4D project fps currently {camera.get('projectFps')} "
                            "(source sequence interpreted at 24 fps)"
                        ),
                        "path": project_path,
                        "projectPath": project_path,
                        "evidence": "confirmed",
                        "confirmationMethod": (
                            "user-identified first frame + six-point final "
                            "comparison + exact C4D render-output path"
                        ),
                    }
                )
            upstream_edit = record.get("upstreamEdit") or {}
            if upstream_edit.get("projectPath"):
                cut["lineage"] = [
                    node
                    for node in cut.get("lineage", [])
                    if not (
                        node.get("kind") == "after_effects"
                        and str(node.get("path") or "")
                        == str(upstream_edit["projectPath"])
                    )
                ]
                cut["lineage"].append(
                    {
                        "kind": "after_effects",
                        "label": Path(str(upstream_edit["projectPath"])).name,
                        "detail": (
                            f"{upstream_edit.get('compName') or 'composition'} · "
                            f"{upstream_edit.get('layerName') or 'source layer'} · "
                            "user-traced chapter lineage"
                        ),
                        "path": upstream_edit["projectPath"],
                        "projectPath": upstream_edit["projectPath"],
                        "sequence": upstream_edit.get("compName"),
                        "evidence": str(
                            upstream_edit.get("evidence") or "confirmed"
                        ),
                    }
                )
            project_candidate = record.get("projectCandidate") or {}
            if project_candidate.get("path") and not project_path:
                cut["lineage"] = [
                    node
                    for node in cut.get("lineage", [])
                    if not (
                        node.get("kind") == "cinema4d"
                        and node.get("evidence") != "confirmed"
                    )
                ]
                cut["lineage"].append(
                    {
                        "kind": "cinema4d",
                        "label": Path(str(project_candidate["path"])).name,
                        "detail": str(
                            project_candidate.get("detail")
                            or "Candidate source project"
                        ),
                        "path": project_candidate["path"],
                        "projectPath": project_candidate["path"],
                        "evidence": str(
                            project_candidate.get("evidence") or "candidate"
                        ),
                    }
                )
            if camera and not project_path and camera.get("aecPath"):
                cut["lineage"] = [
                    node
                    for node in cut.get("lineage", [])
                    if not (
                        node.get("kind") == "camera"
                        and str(node.get("path") or "")
                        == str(camera["aecPath"])
                    )
                ]
                cut["lineage"].append(
                    {
                        "kind": "camera",
                        "label": camera.get("name") or "AEC active camera",
                        "detail": (
                            "Render-time active camera from Cinema 4D AEC "
                            f"metadata · {camera.get('cameraCount') or 0} "
                            "cameras archived · source project remains candidate"
                        ),
                        "path": camera["aecPath"],
                        "evidence": str(
                            camera.get("evidence") or "confirmed"
                        ),
                        "confirmationMethod": (
                            camera.get("source")
                            or "Cinema 4D AEC render metadata"
                        ),
                    }
                )
            cut["sourceRecovery"] = {
                "status": "confirmed",
                "detail": record.get("confirmationMethod"),
                "sourcePath": source_path,
                "sourceStartFrame": first_frame,
                "sourceEndFrame": last_frame,
                "comparisonScores": comparison_scores,
                "insertedInPremiere": inserted_in_premiere,
                "premiereTrack": target_track or None,
                "premiereLabel": (
                    matching_segment.get("premiereLabel")
                    if matching_segment
                    else record.get("conformLabel")
                ),
            }
            cut["confidence"] = "confirmed"
            confirmed += 1
        else:
            cut["lineage"].append(
                {
                    "kind": "visual_match",
                    "label": f"{Path(render_directory).name} · chapter candidate",
                    "detail": str(record.get("confirmationMethod") or ""),
                    "path": render_directory,
                    "projectPath": record.get("projectPath"),
                    "evidence": "candidate",
                    "confirmationMethod": (
                        "user-named chapter project + direct frame comparison"
                    ),
                }
            )
            cut["sourceRecovery"] = {
                "status": "candidate",
                "detail": record.get("confirmationMethod"),
                "sourcePath": source_path,
                "sourceStartFrame": first_frame,
                "sourceEndFrame": last_frame,
                "comparisonScores": comparison_scores,
                "insertedInPremiere": inserted_in_premiere,
                "premiereTrack": target_track or None,
                "premiereLabel": (
                    matching_segment.get("premiereLabel")
                    if matching_segment
                    else record.get("conformLabel")
                ),
            }
            candidates += 1

    return {
        "recoveredSourceRenders": confirmed,
        "recoveredSourceCandidates": candidates,
    }


def tag_lineage_roles(cuts: list[dict[str, Any]]) -> dict[str, int]:
    """Tag the exact chapter edit and directly resolved terminal renders."""

    chapter_edit_cuts = 0
    source_render_cuts = 0
    source_render_nodes = 0

    for cut in cuts:
        for node in cut.get("lineage", []):
            node.pop("tags", None)
        if cut.get("isGap"):
            continue

        direct_chapter_export = (
            next(
                (
                    item
                    for item in cut.get("exportScreenshots", [])
                    if item.get("role") == "ae-source-edit"
                    and item.get("evidence") == "confirmed"
                ),
                None,
            )
            if cut.get("sectionCode") == "TH"
            else None
        )
        export_record = direct_chapter_export or next(
            (
                item
                for item in cut.get("exportScreenshots", [])
                if item.get("role")
                in {"edit-block", "supporting-edit-export"}
            ),
            None,
        )
        if export_record:
            producer = next(
                (
                    producer
                    for kind in ("resolve", "after_effects", "premiere")
                    for producer in export_record.get("producers", [])
                    if producer.get("kind") == kind
                ),
                None,
            )
            target_node = None
            if producer and producer.get("kind") == "resolve":
                target_node = next(
                    (
                        node
                        for node in cut.get("lineage", [])
                        if node.get("kind") == "resolve"
                        and (
                            not producer.get("sequence")
                            or node.get("label") == producer.get("sequence")
                        )
                    ),
                    None,
                )
            elif producer and producer.get("kind") == "after_effects":
                project_path = str(producer.get("projectPath") or "")
                project_index = next(
                    (
                        index
                        for index, node in enumerate(cut.get("lineage", []))
                        if node.get("kind") == "after_effects"
                        and str(node.get("path") or "") == project_path
                    ),
                    None,
                )
                if project_index is not None:
                    target_node = next(
                        (
                            node
                            for node in cut["lineage"][project_index + 1 :]
                            if node.get("kind") == "after_effects_comp"
                        ),
                        None,
                    )
                    if target_node is None:
                        target_node = cut["lineage"][project_index]
            elif producer and producer.get("kind") == "premiere":
                target_node = next(
                    (
                        node
                        for node in cut.get("lineage", [])
                        if node.get("kind") == "premiere"
                        and (
                            str(node.get("path") or "").lower().endswith(
                                ".prproj"
                            )
                            or "sequence" in str(node.get("label") or "").lower()
                        )
                    ),
                    None,
                ) or next(
                    (
                        node
                        for node in cut.get("lineage", [])
                        if node.get("kind") == "premiere"
                    ),
                    None,
                )
            if producer and target_node:
                if (
                    producer.get("kind") == "premiere"
                    and export_record.get("role")
                    == "supporting-edit-export"
                ):
                    chapter_detail = (
                        f"{producer.get('label') or 'Premiere project'} · "
                        f"{target_node.get('label') or 'nested sequence'} is "
                        "the active chapter edit; "
                        f"{export_record.get('label')} is the corresponding "
                        "concrete section export"
                    )
                elif export_record.get("role") == "ae-source-edit":
                    chapter_detail = (
                        f"{producer.get('label') or 'After Effects project'} · "
                        f"{target_node.get('label') or 'chapter comp'} is the "
                        "confirmed chapter edit matching "
                        f"{Path(str(export_record.get('exportPath') or '')).name}"
                    )
                else:
                    chapter_detail = (
                        f"{producer.get('label') or producer.get('kind')} · "
                        f"{producer.get('sequence') or 'chapter sequence'} "
                        f"produces {export_record.get('label')}"
                    )
                append_lineage_tag(
                    target_node,
                    "chapter_edit",
                    chapter_detail,
                    str(producer.get("evidence") or "confirmed"),
                )
                chapter_edit_cuts += 1

        terminal_directories = set()
        terminal_segments_by_directory: dict[str, list[str]] = defaultdict(list)
        for segment in cut.get("sourceSegments", []):
            if segment.get("evidence") != "confirmed":
                continue
            for source_key in ("sourcePath", "sourceFirstFramePath"):
                source_path = str(segment.get(source_key) or "")
                if not source_path:
                    continue
                directory = str(Path(source_path).expanduser().resolve().parent)
                terminal_directories.add(directory)
                segment_id = str(segment.get("id") or "terminal source")
                if segment_id not in terminal_segments_by_directory[directory]:
                    terminal_segments_by_directory[directory].append(segment_id)

        for render_directory in sorted(terminal_directories):
            matching_node = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if node.get("kind") == "render_sequence"
                    and node.get("path")
                    and str(
                        Path(str(node["path"])).expanduser().resolve()
                    )
                    == render_directory
                ),
                None,
            )
            if matching_node is not None or not Path(render_directory).exists():
                continue
            segment_ids = ", ".join(
                terminal_segments_by_directory.get(render_directory, [])
            )
            terminal_render_node = {
                "kind": "render_sequence",
                "label": Path(render_directory).name,
                "detail": (
                    f"{segment_ids or 'Terminal conform'} · confirmed terminal "
                    "source directory for this cut"
                ),
                "path": render_directory,
                "evidence": "confirmed",
            }
            insert_index = next(
                (
                    index
                    for index, node in enumerate(cut.get("lineage", []))
                    if node.get("kind") in {"cinema4d", "camera"}
                ),
                len(cut.get("lineage", [])),
            )
            cut["lineage"].insert(insert_index, terminal_render_node)

        tagged_render = False
        for node in cut.get("lineage", []):
            if (
                node.get("kind") != "render_sequence"
                or not node.get("path")
            ):
                continue
            render_directory = str(
                Path(str(node["path"])).expanduser().resolve()
            )
            if render_directory not in terminal_directories:
                continue
            node["evidence"] = "confirmed"
            segment_ids = ", ".join(
                terminal_segments_by_directory.get(render_directory, [])
            )
            append_lineage_tag(
                node,
                "source_render",
                (
                    f"{segment_ids or 'Terminal conform'} resolves directly "
                    "into this render directory"
                ),
                "confirmed",
            )
            source_render_nodes += 1
            tagged_render = True
        if tagged_render:
            source_render_cuts += 1

    return {
        "chapterEditTaggedCuts": chapter_edit_cuts,
        "sourceRenderTaggedCuts": source_render_cuts,
        "sourceRenderTaggedNodes": source_render_nodes,
    }


def apply_camera_confirmations(
    cuts: list[dict[str, Any]],
    c4d_cameras: dict[str, Any],
) -> int:
    """Apply archived visual/manual confirmations for irreducible legacy copies."""

    path = DATA_DIR / "camera-confirmations.json"
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        log(f"Ignoring unreadable camera confirmation archive ({error})")
        return 0
    cuts_by_id = {str(cut.get("id")): cut for cut in cuts}
    cameras_by_path = {
        str(Path(str(item.get("projectPath") or "")).expanduser().resolve()): item
        for item in c4d_cameras.get("projects", [])
        if item.get("projectPath")
    }
    applied = 0
    for confirmation in payload.get("confirmations", []):
        cut = cuts_by_id.get(str(confirmation.get("cutId") or ""))
        if cut is None:
            continue
        render_path = str(
            Path(str(confirmation.get("renderPath") or ""))
            .expanduser()
            .resolve()
        )
        project_path = str(
            Path(str(confirmation.get("projectPath") or ""))
            .expanduser()
            .resolve()
        )
        camera = cameras_by_path.get(project_path) or {}
        for segment in cut.get("sourceSegments", []):
            source_directory = str(
                Path(str(segment.get("sourcePath") or ""))
                .expanduser()
                .resolve()
                .parent
            )
            if source_directory == render_path:
                segment["evidence"] = "confirmed"
                segment["cameraConfirmation"] = confirmation
        render_node = next(
            (
                node
                for node in cut.get("lineage", [])
                if node.get("kind") == "render_sequence"
                and str(
                    Path(str(node.get("path") or "")).expanduser().resolve()
                )
                == render_path
            ),
            None,
        )
        if render_node is None:
            render_node = {
                "kind": "render_sequence",
                "label": Path(render_path).name,
                "detail": "Terminal render confirmed by camera audit",
                "path": render_path,
                "evidence": "confirmed",
            }
            cut["lineage"].append(render_node)
        else:
            render_node["evidence"] = "confirmed"
            render_node["detail"] = (
                f"{render_node.get('detail') or 'Terminal render'} · "
                f"camera audit: {confirmation.get('method')}"
            )
        cut["lineage"] = [
            node
            for node in cut.get("lineage", [])
            if not (
                node.get("kind") in {"cinema4d", "camera"}
                and node.get("evidence") != "confirmed"
            )
        ]
        camera_object = camera.get("activeCameraObject") or {}
        cut["lineage"].append(
            {
                "kind": "cinema4d",
                "label": Path(project_path).name,
                "detail": (
                    f"Render-aligned project confirmed by "
                    f"{confirmation.get('method')}"
                ),
                "path": project_path,
                "evidence": "confirmed",
            }
        )
        metrics = confirmation.get("metrics") or {}
        detail_parts = [
            str(confirmation.get("detail") or ""),
            f"Take: {confirmation.get('cameraTake') or camera.get('activeTake') or 'Main'}",
            (
                "Render data: "
                f"{confirmation.get('cameraRenderData') or camera.get('activeRenderData') or 'unnamed'}"
            ),
        ]
        if camera_object.get("objectPath"):
            detail_parts.append(f"Object: {camera_object['objectPath']}")
        if camera_object.get("guid"):
            detail_parts.append(f"GUID: {camera_object['guid']}")
        if camera_object.get("focalLength") is not None:
            detail_parts.append(f"Lens: {camera_object['focalLength']} mm")
        if metrics:
            detail_parts.append(
                "Audit metrics: "
                f"luma {float(metrics.get('meanLuminanceCorrelation') or 0):.3f}, "
                f"edges {float(metrics.get('meanEdgeCorrelation') or 0):.3f}"
            )
        if confirmation.get("comparisonImage"):
            detail_parts.append(
                f"Comparison: {confirmation['comparisonImage']}"
            )
        cut["lineage"].append(
            {
                "kind": "camera",
                "label": (
                    confirmation.get("cameraName")
                    or camera.get("activeCamera")
                    or "Camera"
                ),
                "detail": " · ".join(part for part in detail_parts if part),
                "path": project_path,
                "evidence": "confirmed",
                "comparisonImage": confirmation.get("comparisonImage"),
                "confirmationMethod": confirmation.get("method"),
            }
        )
        cut["confidence"] = "confirmed"
        applied += 1
    return applied


def apply_camera_proof_renders(
    cuts: list[dict[str, Any]],
    proof_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach canonical source-camera test renders to shot lineage."""

    cuts_by_id = {str(cut.get("id")): cut for cut in cuts}
    rendered = 0
    failed = 0
    isolated_rendered = 0
    unresolved = 0
    tagged_cuts: set[str] = set()
    for proof in proof_archive.get("proofs", []):
        status = str(proof.get("status") or "unresolved")
        if status == "rendered":
            rendered += 1
        elif status == "failed":
            failed += 1
        else:
            unresolved += 1
        mapping_evidence = str(proof.get("mappingEvidence") or "")
        evidence = (
            "confirmed"
            if mapping_evidence
            in {
                "confirmed",
                "confirmed_camera_audit",
                "confirmed_user_lineage",
            }
            else "strong_inference"
            if mapping_evidence == "strong_inference"
            else "candidate"
            if mapping_evidence == "candidate"
            else "missing"
        )
        if status != "rendered":
            evidence = "missing"
        if proof.get("cameraFallbackToTake") and status == "rendered":
            evidence = "candidate"
        camera_name = str(proof.get("cameraName") or "Camera unresolved")
        source_id = str(proof.get("sourceId") or "source")
        track = proof.get("track")
        take = str(proof.get("cameraTake") or "Main")
        frame = proof.get("targetFrame")
        renderer = str(
            proof.get("renderer") or "Cinema 4D Hardware Preview"
        )
        visual = str(proof.get("visualStatus") or "not rendered").replace(
            "_", " "
        )
        detail_parts = [
            f"Canonical V{track} source {source_id}",
            f"source frame {frame}",
            f"take {take}",
            renderer,
            f"visual result: {visual}",
        ]
        if proof.get("cameraObjectPath"):
            detail_parts.append(f"object {proof['cameraObjectPath']}")
        if proof.get("cameraReconstructedFromArchive"):
            detail_parts.append("camera rebuilt from archived transform/lens")
        if proof.get("cameraFallbackToTake"):
            detail_parts.append(
                "requested archived camera absent on disk; rendered effective "
                "take camera as a visual candidate"
            )
        if proof.get("mappingMethod"):
            detail_parts.append(f"mapping: {proof['mappingMethod']}")
        if proof.get("error"):
            detail_parts.append(f"render failure: {proof['error']}")
        if status == "unresolved":
            detail_parts.append(
                "project/camera mapping is not identified; no proof was fabricated"
            )
        comparison_image = (
            proof.get("publicPath")
            if status == "rendered"
            and Path(str(proof.get("outputPath") or "")).exists()
            else None
        )
        if proof.get("confirmationMethod"):
            confirmation_method = proof["confirmationMethod"]
        elif status == "rendered" and proof.get("cameraFallbackToTake"):
            confirmation_method = (
                "C4D hardware camera proof · effective take camera candidate"
            )
        elif status == "rendered":
            confirmation_method = "C4D hardware camera proof"
        else:
            confirmation_method = "C4D camera proof attempt"
        node = {
            "kind": "camera_proof",
            "label": (
                f"{camera_name} · frame {frame}"
                if frame is not None
                else camera_name
            ),
            "detail": " · ".join(detail_parts),
            "path": proof.get("projectPath") or proof.get("renderPath"),
            "projectPath": proof.get("projectPath"),
            "comparisonImage": comparison_image,
            "confirmationMethod": confirmation_method,
            "evidence": evidence,
            "proofStatus": status,
            "sourceId": source_id,
            "sourceTrack": track,
            "targetFrame": frame,
            "cameraFallbackToTake": bool(
                proof.get("cameraFallbackToTake")
            ),
            "redshiftProof": bool(proof.get("redshiftProof")),
            "fullColorProof": bool(proof.get("fullColorProof")),
            "redshiftSourceImage": proof.get("redshiftSourcePublicPath"),
        }
        for cut_id in proof.get("cutIds", []):
            cut = cuts_by_id.get(str(cut_id))
            if cut is None:
                continue
            cut["lineage"].append(dict(node))
            tagged_cuts.add(str(cut_id))
    return {
        "cameraProofTargets": len(proof_archive.get("proofs", [])),
        "cameraProofRendered": rendered,
        "cameraProofFailed": failed,
        "cameraProofUnresolved": unresolved,
        "cameraProofTaggedCuts": len(tagged_cuts),
    }


def merge_camera_proof_recovery_overrides(
    proof_archive: dict[str, Any],
    override_archive: dict[str, Any],
) -> dict[str, Any]:
    """Overlay retained clean-copy evidence without rewriting prior proofs."""

    def merge_dict(
        base: dict[str, Any], override: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(base)
        for key, value in override.items():
            if (
                isinstance(value, dict)
                and isinstance(merged.get(key), dict)
            ):
                merged[key] = merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    override_records = [
        item
        for item in override_archive.get("proofOverrides", [])
        if item.get("cutId") and not item.get("legacyFinalReferenceOnly")
    ]
    overrides = {
        str(item.get("cutId")): item
        for item in override_records
    }
    base_proofs = list(proof_archive.get("proofs", []))
    base_cut_ids = {
        str(proof.get("cutId"))
        for proof in base_proofs
        if proof.get("cutId")
    }
    return {
        **proof_archive,
        "proofs": [
            merge_dict(proof, overrides.get(str(proof.get("cutId")), {}))
            for proof in base_proofs
        ]
        + [
            dict(override)
            for override in override_records
            if str(override.get("cutId")) not in base_cut_ids
        ],
        "recoveryOverrideAuthority": override_archive.get("authority"),
    }


def attach_fresh_full_color_render_inventory(
    cuts: list[dict[str, Any]],
) -> dict[str, int]:
    """Attach every fresh audit-rendered full-color frame as process evidence.

    A rendered frame is never promoted to a camera proof here. Manual visual
    comparison and the strict dependency gate remain authoritative for the
    green/yellow/black/grey card state.
    """

    result_dirs = [
        DATA_DIR / "c4d-mainframe-recovery-20260730",
        DATA_DIR / "c4d-clean-recoveries",
    ]
    cuts_by_id = {
        str(cut.get("id") or ""): cut
        for cut in cuts
        if not cut.get("isGap")
    }
    manual_audits = {
        str(item.get("cutId") or ""): (
            item.get("materialCompatibilityAudit") or {}
        )
        for item in load_creative_app_archive(
            AS_FINISHING_CAMERA_PROOF_RECOVERY_OVERRIDES.relative_to(
                DATA_DIR
            ).as_posix()
        ).get("proofOverrides", [])
        if item.get("cutId") and not item.get("legacyFinalReferenceOnly")
    }

    def as_public_path(value: Any) -> str:
        candidate = str(value or "")
        if not candidate:
            return ""
        if candidate.startswith("/archive/"):
            return candidate
        try:
            relative = Path(candidate).resolve().relative_to(
                (APP_ROOT / "public").resolve()
            )
        except (OSError, ValueError):
            return ""
        return f"/{relative.as_posix()}"

    def unsafe_relink_reason(target_path: Any) -> str | None:
        parts = [
            part.casefold().replace("-", "_")
            for part in str(target_path or "").replace("\\", "/").split("/")
            if part
        ]
        for part in parts:
            if (
                part == "quarantine"
                or part.startswith("quarantine_")
                or part.endswith("_quarantine")
            ):
                return "quarantined_target"
            if "rejected" in part and "unproven" in part:
                return "rejected_unproven_target"
        return None

    records: list[dict[str, Any]] = []
    attached_paths: set[tuple[str, str]] = set()
    rendered_shots: set[str] = set()
    for result_dir in result_dirs:
        if not result_dir.exists():
            continue
        for result_path in sorted(result_dir.glob("*-result.json")):
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(result, dict):
                continue
            if result.get("status") != "rendered":
                continue
            output_value = str(result.get("output") or "")
            if not output_value:
                continue
            output_path = Path(output_value)
            if not output_path.exists() or not output_path.is_file():
                continue
            output_name = output_path.name.casefold()
            if (
                result.get("greyOverride")
                or re.search(
                    r"(?:grey|hardware|contact|comparison|smoke)",
                    output_name,
                )
                or not (
                    result.get("fullColor") is True
                    or re.search(
                        r"(?:redshift|material|full[-_ ]?color|denoiser)",
                        output_name,
                    )
                )
            ):
                continue
            match = re.search(r"CUT[-_](\d{3})", result_path.name)
            if not match:
                continue
            cut_id = f"CUT-{match.group(1)}"
            cut = cuts_by_id.get(cut_id)
            if cut is None:
                continue
            try:
                relative_output = output_path.resolve().relative_to(
                    (APP_ROOT / "public").resolve()
                )
            except (OSError, ValueError):
                continue
            public_path = f"/{relative_output.as_posix()}"
            attachment_key = (cut_id, public_path)
            if attachment_key in attached_paths:
                continue
            attached_paths.add(attachment_key)
            rendered_shots.add(cut_id)
            camera_name = str(
                result.get("camera")
                or result.get("cameraPath")
                or "saved render camera"
            )
            frame = result.get("frame")
            frame_label = (
                f"frame {int(frame)}"
                if isinstance(frame, (int, float))
                else "saved target frame"
            )
            audit = manual_audits.get(cut_id) or {}
            audit_image_paths = {
                as_public_path(value)
                for key, value in audit.items()
                if isinstance(value, str)
                and (
                    re.search(r"(?:output|comparison)path$", key, re.I)
                    or key in {"publicPath", "diagnosticImage"}
                )
            }
            matching_audit = audit if public_path in audit_image_paths else {}
            audit_status = str(
                matching_audit.get("status") or "rendered_process_evidence"
            )
            if (
                result.get("visualMatch") is True
                and result.get("activeFrameStrictDependencyRenderSafe")
                is True
                and result.get("projectWideStrictDependencyRenderSafe")
                is True
            ):
                audit_status = "rendered_match"
            unsafe_result_relinks = []
            for relink_key in (
                "temporaryExactDependencyRelinks",
                "temporaryExactMaterialRelinks",
                "temporaryExactSceneMaterialRelinks",
                "postEvaluationExactMaterialRelinks",
                "postEvaluationExactSceneMaterialRelinks",
            ):
                for mapping in result.get(relink_key) or []:
                    reason = unsafe_relink_reason(
                        mapping.get("targetPath")
                    )
                    if reason:
                        unsafe_result_relinks.append(
                            {
                                "relinkGroup": relink_key,
                                "requiredPath": mapping.get(
                                    "requiredPath"
                                ),
                                "targetPath": mapping.get("targetPath"),
                                "reason": reason,
                            }
                        )
            if unsafe_result_relinks:
                audit_status = "rejected_unsafe_cross_shot_relink"
            rejected = bool(
                re.search(
                    (
                        r"mismatch|black|missing|runtime_required|"
                        r"cache_required|incomplete|unresolved"
                    ),
                    audit_status,
                    re.I,
                )
            )
            accepted = audit_status == "rendered_match"
            label_prefix = (
                "Validated full-color Redshift render"
                if accepted
                else "Rejected full-color Redshift diagnostic"
                if rejected
                else "Full-color Redshift attempt"
            )
            detail = str(
                (
                    "This fresh render used a quarantined or explicitly "
                    "rejected/unproven relink target and is retained only to "
                    "document the failed audit path. It cannot support camera, "
                    "character, hair, wardrobe, asset-linkage, or material "
                    "verification. The source C4D was not modified."
                    if unsafe_result_relinks
                    else matching_audit.get("runtimeDetail")
                )
                or (
                    "Fresh material-enabled Redshift audit frame from "
                    f"{Path(str(result.get('project') or '')).name or 'the mapped C4D project'}"
                    f" · {camera_name} · {frame_label}. It remains process "
                    "evidence until visually accepted against the canonical cut."
                )
            )
            record = {
                "cutId": cut_id,
                "resultPath": str(result_path.relative_to(APP_ROOT)),
                "outputPath": str(output_path),
                "publicPath": public_path,
                "projectPath": result.get("project"),
                "camera": camera_name,
                "cameraPath": result.get("cameraPath"),
                "take": result.get("take"),
                "renderData": result.get("renderData"),
                "frame": frame,
                "seconds": result.get("seconds"),
                "status": audit_status,
                "proofEligible": False,
                "fullColor": True,
                "freshAuditRender": True,
                "unsafeRelinkTargets": unsafe_result_relinks,
            }
            records.append(record)
            if any(
                node.get("comparisonImage") == public_path
                for node in cut.get("lineage", [])
            ):
                continue
            cut.setdefault("lineage", []).append(
                {
                    "kind": "process_image",
                    "label": (
                        f"{label_prefix} · {camera_name} · "
                        f"{frame_label}"
                    ),
                    "detail": detail,
                    "path": result.get("project"),
                    "projectPath": result.get("project"),
                    "comparisonImage": public_path,
                    "confirmationMethod": (
                        (
                            "Rejected fresh full-color render"
                            if rejected
                            else "Validated fresh full-color render"
                            if accepted
                            else "Fresh full-color render awaiting comparison"
                        )
                        + f" · {audit_status.replace('_', ' ')}"
                    ),
                    "evidence": "candidate",
                    "proofStatus": (
                        "rejected_unsafe_relink"
                        if unsafe_result_relinks
                        else "process_only"
                    ),
                    "fullColorRender": True,
                    "freshAuditRender": True,
                    "resultPath": str(result_path.relative_to(APP_ROOT)),
                    "targetFrame": frame,
                    "unsafeRelinkTargets": unsafe_result_relinks,
                }
            )

    payload = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "authority": (
            "Fresh material-enabled single-frame Redshift audit outputs only. "
            "Historical stills and composites are excluded. Inventory presence "
            "does not promote a frame to camera proof."
        ),
        "summary": {
            "renderedFrames": len(records),
            "renderedShots": len(rendered_shots),
        },
        "records": records,
    }
    C4D_FULL_COLOR_RENDER_INVENTORY.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    (PUBLIC_DATA_DIR / C4D_FULL_COLOR_RENDER_INVENTORY.name).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return {
        "c4dFreshFullColorRenderFrames": len(records),
        "c4dFreshFullColorRenderShots": len(rendered_shots),
    }


def is_historical_production_reference(proof: dict[str, Any]) -> bool:
    """Return True for retained production frames, never fresh camera tests."""

    public_path = str(proof.get("publicPath") or "").casefold()
    return bool(
        proof.get("historicalProductionReference")
        or "historical-redshift" in Path(public_path).name
    )


def apply_as_finishing_chronology(
    state: dict[str, Any],
    chronology: dict[str, Any],
    proof_archive: dict[str, Any],
    revision_targets: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Attach exact AS render-log lineage without weakening visual gates.

    A log is accepted when either its normalized output directory is already
    the cut's confirmed source-render directory or the chronology audit matched
    its exact emitted filename prefix inside one of the cut's canonical render
    directories (covering render folders that were renamed after completion).
    It must report Redshift, at least one completed frame, and zero errors.
    This makes the active project/take/camera authoritative for lineage while
    leaving strict linkage dependent on the separate dependency audit and
    visual proof.
    """

    cuts_by_id = {
        str(cut.get("id")): cut
        for cut in state.get("cuts", [])
        if cut.get("id") and not cut.get("isGap")
    }
    logs_by_path = {
        str(item.get("path")): item
        for item in chronology.get("renderLogs", [])
        if item.get("path")
    }
    applied_logs = 0
    corrected_projects = 0
    corrected_cameras = 0
    exact_cut_ids: set[str] = set()

    for cut_id, leads in chronology.get("cutLineageLeads", {}).items():
        cut = cuts_by_id.get(str(cut_id))
        if not cut:
            continue
        render_paths = {
            os.path.normpath(str(node.get("path") or ""))
            for node in cut.get("lineage", [])
            if node.get("kind") == "render_sequence" and node.get("path")
        }
        canonical_frame_prefixes = {
            re.sub(
                r"-?\d+$",
                "",
                Path(str(frame_path)).stem,
            ).casefold()
            for segment in cut.get("sourceSegments", [])
            for frame_path in (
                segment.get("sourceFirstFramePath"),
                segment.get("sourceLastFramePath"),
            )
            if frame_path
        }
        comparison_frame_path = (cut.get("comparison") or {}).get(
            "sourceFramePath"
        )
        if comparison_frame_path:
            canonical_frame_prefixes.add(
                re.sub(
                    r"-?\d+$",
                    "",
                    Path(str(comparison_frame_path)).stem,
                ).casefold()
            )
        exact_leads = []
        for lead in leads:
            output_path = os.path.normpath(str(lead.get("outputPath") or ""))
            log_record = logs_by_path.get(str(lead.get("renderLogPath"))) or lead
            exact_relocated_prefix_match = (
                str(cut_id)
                in {
                    str(item)
                    for item in log_record.get("matchingCutIds", [])
                }
                and log_record.get("cutMatchingRule")
                == (
                    "exact_emitted_filename_prefix_across_canonical_"
                    "render_directories"
                )
                and bool(log_record.get("renderOutputRelocated"))
            )
            if (
                output_path not in render_paths
                and not exact_relocated_prefix_match
            ):
                continue
            if str(log_record.get("renderEngineName") or "") != "Redshift":
                continue
            if int(log_record.get("completedFrameCount") or 0) <= 0:
                continue
            if int(log_record.get("errorCount") or 0) != 0:
                continue
            log_frame_prefixes = {
                str(prefix).casefold()
                for prefix in log_record.get(
                    "completedImageBasenamePrefixes", []
                )
                if prefix
            }
            if (
                canonical_frame_prefixes
                and log_frame_prefixes
                and canonical_frame_prefixes.isdisjoint(log_frame_prefixes)
            ):
                continue
            exact_leads.append((lead, log_record))
        if not exact_leads:
            continue
        lead, log_record = max(
            exact_leads,
            key=lambda pair: str(
                pair[0].get("renderLogModifiedAt")
                or pair[1].get("modifiedAt")
                or ""
            ),
        )
        exact_cut_ids.add(str(cut_id))
        project_candidates = [
            str(path)
            for path in lead.get("projectCandidatePaths", [])
            if path and Path(str(path)).is_file()
        ]
        project_path = (
            project_candidates[0]
            if project_candidates
            else str(lead.get("nearestProjectStatePath") or "")
        )
        camera_name = str(lead.get("camera") or "")
        take = str(lead.get("take") or "Main")
        log_path = str(lead.get("renderLogPath") or "")
        log_date = str(
            lead.get("renderLogModifiedAt")
            or log_record.get("modifiedAt")
            or ""
        )
        render_settings = str(log_record.get("renderSettings") or "")

        if project_path and not any(
            node.get("kind") == "cinema4d"
            and str(node.get("path") or node.get("projectPath") or "")
            == project_path
            for node in cut.get("lineage", [])
        ):
            cut.setdefault("lineage", []).append(
                {
                    "kind": "cinema4d",
                    "label": Path(project_path).name,
                    "detail": (
                        "Source project named by the completed AS Redshift "
                        f"batch-render log on {log_date}"
                    ),
                    "path": project_path,
                    "projectPath": project_path,
                    "evidence": "confirmed",
                    "sourceProjectFromRenderLog": True,
                    "strictLinked": False,
                }
            )
            corrected_projects += 1
        else:
            for node in cut.get("lineage", []):
                if (
                    node.get("kind") == "cinema4d"
                    and str(node.get("path") or node.get("projectPath") or "")
                    == project_path
                ):
                    node["sourceProjectFromRenderLog"] = True
                    node["renderLogPath"] = log_path

        stale_camera_count = len(cut.get("lineage", []))
        cut["lineage"] = [
            node
            for node in cut.get("lineage", [])
            if not (
                node.get("kind") == "camera"
                and project_path
                and str(node.get("path") or node.get("projectPath") or "")
                == project_path
                and str(node.get("label") or "") != camera_name
                and "Render-output alignment: exact path"
                in str(node.get("detail") or "")
            )
        ]
        if len(cut["lineage"]) != stale_camera_count:
            corrected_cameras += 1

        if camera_name and not any(
            node.get("kind") == "camera"
            and node.get("label") == camera_name
            and str(node.get("projectPath") or node.get("path") or "")
            == project_path
            for node in cut.get("lineage", [])
        ):
            cut["lineage"].append(
                {
                    "kind": "camera",
                    "label": camera_name,
                    "detail": (
                        f"Completed Redshift log · take {take}"
                        + (
                            f" · render data {render_settings}"
                            if render_settings
                            else ""
                        )
                        + f" · frames {lead.get('frameFrom')}–"
                        f"{lead.get('frameTo')} at {lead.get('fps')} fps"
                        + f" · {log_date}"
                    ),
                    "path": project_path,
                    "projectPath": project_path,
                    "evidence": "confirmed",
                    "confirmationMethod": (
                        (
                            "Exact emitted filename prefix inside the "
                            "canonical render directory plus completed "
                            "zero-error Redshift batch-render log; the "
                            "output directory was renamed after render"
                            if exact_relocated_prefix_match
                            else (
                                "Exact source-render output path plus "
                                "completed zero-error Redshift batch-render "
                                "log"
                            )
                        )
                    ),
                    "renderLogPath": log_path,
                    "take": take,
                    "renderData": render_settings,
                }
            )
            corrected_cameras += 1

        if not any(
            node.get("kind") == "redshift_render_log"
            and node.get("path") == log_path
            for node in cut.get("lineage", [])
        ):
            cut["lineage"].append(
                {
                    "kind": "redshift_render_log",
                    "label": Path(log_path).name,
                    "detail": (
                        f"{lead.get('completedFrameCount')} completed frames · "
                        f"0 errors · {lead.get('width')}×{lead.get('height')} · "
                        f"{lead.get('fps')} fps · take {take} · camera "
                        f"{camera_name}"
                    ),
                    "path": log_path,
                    "projectPath": project_path,
                    "evidence": "confirmed",
                    "sourceRenderPath": lead.get("outputPath"),
                    "renderOutputRelocated": exact_relocated_prefix_match,
                }
            )
            applied_logs += 1

    applied_proofs = 0
    applied_references = 0
    for proof in proof_archive.get("proofs", []):
        cut = cuts_by_id.get(str(proof.get("cutId")))
        if not cut:
            continue
        # Process evidence is useful even when it proves only a related scene
        # family and cannot qualify as a camera proof. Publish it before the
        # rendered-proof gate so unresolved cuts such as CUT-001 retain the
        # fresh camera-search frames and their exact source-project lineage.
        for process_image in proof.get("processImages") or []:
            process_public_path = str(
                process_image.get("publicPath")
                or process_image.get("comparisonImage")
                or ""
            )
            fresh_full_color_process = bool(
                (
                    process_image.get("fullColorRender") is True
                    and process_image.get("freshAuditRender") is True
                )
                or re.search(
                    r"/archive/redshift-full-color-final-\d{8}/",
                    process_public_path,
                    flags=re.IGNORECASE,
                )
            )
            if not process_public_path or any(
                node.get("kind") == "process_image"
                and node.get("comparisonImage") == process_public_path
                for node in cut.get("lineage", [])
            ):
                continue
            cut.setdefault("lineage", []).append(
                {
                    "kind": "process_image",
                    "label": (
                        process_image.get("label")
                        or Path(process_public_path).name
                    ),
                    "detail": (
                        process_image.get("detail")
                        or "Retained camera-recovery process image."
                    ),
                    "path": proof.get("projectPath"),
                    "projectPath": proof.get("projectPath"),
                    "comparisonImage": process_public_path,
                    "confirmationMethod": process_image.get(
                        "confirmationMethod"
                    ),
                    "evidence": (
                        process_image.get("evidence")
                        or proof.get("proofEvidence")
                        or "candidate"
                    ),
                    "proofStatus": (
                        process_image.get("status") or "process_evidence"
                    ),
                    "redshiftProof": False,
                    "fullColorProof": False,
                    "fullColorRender": fresh_full_color_process,
                    "freshAuditRender": fresh_full_color_process,
                    "recoveryProof": False,
                    "primaryRecoveryProof": False,
                    "visualVerificationStatus": (
                        process_image.get("status")
                        or process_image.get("evidence")
                        or "process_evidence"
                    ),
                }
            )
        if proof.get("status") != "rendered":
            continue
        output_path = Path(str(proof.get("outputPath") or ""))
        if not output_path.is_file():
            continue
        review = dict(proof.get("visualReview") or {})
        elements = dict(review.get("elements") or {})
        historical_reference = is_historical_production_reference(proof)
        proof_project_path = str(proof.get("projectPath") or "")
        superseded_project_paths = {
            os.path.normpath(str(path))
            for path in proof.get("supersededProjectPaths", [])
            if path
        }
        superseded_render_log_paths = {
            os.path.normpath(str(path))
            for path in proof.get("supersededRenderLogPaths", [])
            if path
        }
        if superseded_project_paths or superseded_render_log_paths:
            # A render-name collision can leave a plausible but false camera
            # and log in lineage after the exact pre-render revision is found.
            # Remove only the explicitly enumerated weaker records; never
            # infer exclusions from a similar filename.
            cut["lineage"] = [
                node
                for node in cut.get("lineage", [])
                if not (
                    (
                        node.get("kind")
                        in {"camera", "camera_proof", "cinema4d"}
                        and os.path.normpath(
                            str(
                                node.get("projectPath")
                                or node.get("path")
                                or ""
                            )
                        )
                        in superseded_project_paths
                    )
                    or (
                        node.get("kind")
                        in {"camera", "camera_proof", "redshift_render_log"}
                        and os.path.normpath(
                            str(
                                node.get("renderLogPath")
                                or (
                                    node.get("path")
                                    if node.get("kind")
                                    == "redshift_render_log"
                                    else ""
                                )
                                or ""
                            )
                        )
                        in superseded_render_log_paths
                    )
                )
            ]
        if (
            proof_project_path.lower().endswith(".c4d")
            and Path(proof_project_path).is_file()
        ):
            # A render-era Dropbox revision with a fresh camera proof is
            # stronger source-project evidence than a later project inferred
            # only from a relocated Redshift log. Keep one actionable C4D
            # source node so the card icon opens the exact proven revision.
            cut["lineage"] = [
                node
                for node in cut.get("lineage", [])
                if node.get("kind") != "cinema4d"
            ]
            cut.setdefault("lineage", []).append(
                {
                    "kind": "cinema4d",
                    "label": Path(proof_project_path).name,
                    "detail": (
                        proof.get("projectLineageDetail")
                        or (
                            "Exact render-era Dropbox revision · fresh Redshift "
                            "camera proof · dependency audit attached"
                        )
                    ),
                    "path": proof_project_path,
                    "projectPath": proof_project_path,
                    "evidence": proof.get("projectEvidence") or "confirmed",
                    "projectRevision": proof.get("projectRevision"),
                    "dependencyAuditPath": proof.get(
                        "dependencyAuditPath"
                    ),
                    "linkageAudit": proof.get("linkageAudit"),
                    "materialCompatibilityAudit": proof.get(
                        "materialCompatibilityAudit"
                    ),
                    "visualVerificationStatus": review.get("status"),
                }
            )
        if proof.get("redshiftProof") and not historical_reference:
            cut["lineage"] = [
                node
                for node in cut.get("lineage", [])
                if not (
                    node.get("kind") == "camera_proof"
                    and not node.get("redshiftProof")
                )
            ]
            # The render-era archive proof is the newest strict authority.
            # Retain older Redshift diagnostics in backward lineage, but do
            # not let an earlier reconstruction remain the card's primary
            # camera proof after an exact pre-render revision is audited.
            for node in cut.get("lineage", []):
                if node.get("kind") == "camera_proof":
                    node["primaryRecoveryProof"] = False
        primary_proof_frame = (
            proof.get("productionRedshiftProofFrame")
            if proof.get("productionRedshiftProofPath")
            else proof.get("targetFrame")
        )
        primary_proof_image = (
            proof.get("productionRedshiftProofPath")
            or proof.get("publicPath")
            or proof.get("comparisonPath")
        )
        cut.setdefault("lineage", []).append(
            {
                "kind": (
                    "render_reference"
                    if historical_reference
                    else "camera_proof"
                ),
                "label": (
                    (
                        f"{proof.get('cameraName')} · retained production "
                        "Redshift reference · frame "
                        f"{primary_proof_frame}"
                    )
                    if historical_reference
                    else (
                        f"{proof.get('cameraName')} · frame "
                        f"{primary_proof_frame}"
                    )
                ),
                "detail": (
                    proof.get("proofLineageDetail")
                    or (
                        "AS render-log-selected camera · read-only grey proof · "
                        + (
                            "Dropbox revision "
                            + str(
                                (proof.get("projectRevision") or {}).get(
                                    "revisionModifiedAt"
                                )
                            )
                            + " · "
                            if (proof.get("projectRevision") or {}).get(
                                "revisionModifiedAt"
                            )
                            else ""
                        )
                        + str(review.get("notes") or "")
                    )
                ),
                "path": proof.get("projectPath"),
                "projectPath": proof.get("projectPath"),
                "comparisonImage": primary_proof_image,
                "confirmationMethod": (
                    (
                        "Retained historical production render and completed "
                        "log; reference only, not a newly rendered camera test."
                    )
                    if historical_reference
                    else proof.get("confirmationMethod")
                    or (
                        "Completed zero-error Redshift log selected the exact "
                        "project, take, camera, render data, and source frame"
                    )
                ),
                "evidence": proof.get("proofEvidence") or "confirmed",
                "proofStatus": (
                    "reference_only"
                    if historical_reference
                    else "rendered"
                ),
                "targetFrame": primary_proof_frame,
                "cameraTake": proof.get("cameraTake"),
                "cameraRenderData": proof.get("cameraRenderData"),
                "cameraObjectPath": proof.get("cameraObjectPath"),
                "recoveryProof": not historical_reference,
                "primaryRecoveryProof": not historical_reference,
                "redshiftProof": (
                    bool(proof.get("redshiftProof"))
                    and not historical_reference
                ),
                "fullColorProof": (
                    bool(proof.get("fullColorProof"))
                    and not historical_reference
                ),
                "fullColorRender": (
                    bool(proof.get("fullColorProof"))
                    and not historical_reference
                ),
                "freshAuditRender": (
                    bool(proof.get("redshiftProof"))
                    and bool(proof.get("fullColorProof"))
                    and not historical_reference
                ),
                "productionSourceReference": historical_reference,
                "historicalProductionReference": historical_reference,
                "strictLinked": False,
                "visualVerificationStatus": review.get("status"),
                "visualReview": review,
                "renderLogPath": proof.get("renderLogPath"),
                "projectRevision": proof.get("projectRevision"),
                "dependencyAuditPath": proof.get("dependencyAuditPath"),
                "linkageAudit": proof.get("linkageAudit"),
                "materialCompatibilityAudit": proof.get(
                    "materialCompatibilityAudit"
                ),
                "recoveryPrescription": proof.get("recoveryPrescription"),
            }
        )
        diagnostic_grey_proof = proof.get("diagnosticGreyProofPath")
        if (
            diagnostic_grey_proof
            and not historical_reference
            and diagnostic_grey_proof != primary_proof_image
        ):
            diagnostic_grey_frame = (
                proof.get("diagnosticGreyProofFrame")
                or proof.get("targetFrame")
            )
            cut.setdefault("lineage", []).append(
                {
                    "kind": "camera_proof",
                    "label": (
                        f"{proof.get('cameraName')} · current grey diagnostic · "
                        f"frame {diagnostic_grey_frame}"
                    ),
                    "detail": (
                        "Current-runtime Redshift grey override retained as "
                        "camera, framing, and geometry diagnostic evidence; "
                        "not the production beauty render."
                    ),
                    "path": proof.get("projectPath"),
                    "projectPath": proof.get("projectPath"),
                    "comparisonImage": diagnostic_grey_proof,
                    "confirmationMethod": (
                        "Direct current Redshift diagnostic from the identified "
                        "project, take, and camera."
                    ),
                    "evidence": proof.get("proofEvidence") or "confirmed",
                    "proofStatus": "rendered",
                    "targetFrame": diagnostic_grey_frame,
                    "cameraTake": proof.get("cameraTake"),
                    "cameraRenderData": proof.get("cameraRenderData"),
                    "cameraObjectPath": proof.get("cameraObjectPath"),
                    "recoveryProof": True,
                    "primaryRecoveryProof": False,
                    "redshiftProof": True,
                    "fullColorProof": False,
                    "diagnosticGreyProof": True,
                    "strictLinked": False,
                    "visualVerificationStatus": review.get("status"),
                    "visualReview": review,
                    "dependencyAuditPath": proof.get("dependencyAuditPath"),
                    "linkageAudit": proof.get("linkageAudit"),
                }
            )
        material_diagnostic = proof.get("materialCompatibilityAudit") or {}
        diagnostic_comparison = material_diagnostic.get(
            "diagnosticComparisonPath"
        )
        if diagnostic_comparison:
            cut.setdefault("lineage", []).append(
                {
                    "kind": "material_diagnostic",
                    "label": "Rejected material-runtime diagnostic",
                    "detail": material_diagnostic.get("runtimeDetail")
                    or (
                        "Compatibility render retained as negative evidence; "
                        "it is not a production-material match."
                    ),
                    "path": proof.get("projectPath"),
                    "projectPath": proof.get("projectPath"),
                    "comparisonImage": diagnostic_comparison,
                    "confirmationMethod": (
                        "Canonical source beside the rejected compatibility "
                        "render; camera and geometry align, materials do not."
                    ),
                    "evidence": "candidate",
                    "visualVerificationStatus": "mismatch",
                    "materialCompatibilityAudit": material_diagnostic,
                    "recoveryPrescription": proof.get(
                        "recoveryPrescription"
                    ),
                }
            )
        for process_image in proof.get("processImages") or []:
            process_public_path = str(
                process_image.get("publicPath")
                or process_image.get("comparisonImage")
                or ""
            )
            fresh_full_color_process = bool(
                (
                    process_image.get("fullColorRender") is True
                    and process_image.get("freshAuditRender") is True
                )
                or re.search(
                    r"/archive/redshift-full-color-final-\d{8}/",
                    process_public_path,
                    flags=re.IGNORECASE,
                )
            )
            if not process_public_path or any(
                node.get("kind") == "process_image"
                and node.get("comparisonImage") == process_public_path
                for node in cut.get("lineage", [])
            ):
                continue
            cut.setdefault("lineage", []).append(
                {
                    "kind": "process_image",
                    "label": (
                        process_image.get("label")
                        or Path(process_public_path).name
                    ),
                    "detail": (
                        process_image.get("detail")
                        or "Retained camera-recovery process image."
                    ),
                    "path": proof.get("projectPath"),
                    "projectPath": proof.get("projectPath"),
                    "comparisonImage": process_public_path,
                    "confirmationMethod": process_image.get(
                        "confirmationMethod"
                    ),
                    "evidence": (
                        process_image.get("evidence") or "candidate"
                    ),
                    "proofStatus": (
                        process_image.get("status") or "process_only"
                    ),
                    "redshiftProof": False,
                    "fullColorProof": False,
                    "fullColorRender": fresh_full_color_process,
                    "freshAuditRender": fresh_full_color_process,
                    "recoveryProof": False,
                    "primaryRecoveryProof": False,
                    "visualVerificationStatus": (
                        process_image.get("visualVerificationStatus")
                        or "diagnostic"
                    ),
                }
            )
        verification = cut.setdefault("c4dVerification", {})
        existing_camera_proof = verification.get("cameraProof")
        existing_camera_proof_rendered = bool(
            existing_camera_proof
            and (verification.get("checks") or {}).get(
                "cameraProofRendered"
            )
        )
        verification.update(
            {
                "status": (
                    "partial"
                    if historical_reference
                    else review.get("status") or "partial_match"
                ),
                "label": (
                    "Historical render reference · camera proof missing"
                    if historical_reference
                    else proof.get("verificationLabel")
                    or "Camera matched; assets incomplete"
                ),
                "detail": review.get("notes"),
                "strictLinked": False,
                "reviewedAt": (
                    proof.get("reviewedAt")
                    or verification.get("reviewedAt")
                ),
                "authority": (
                    proof.get("authority")
                    or (
                        "AS completed Redshift log plus canonical-thumbnail "
                        "visual review"
                    )
                ),
                "elements": elements,
                "notes": review.get("notes"),
                "cameraProof": (
                    existing_camera_proof
                    if historical_reference
                    else proof.get("publicPath")
                ),
                "comparisonImage": proof.get("comparisonPath"),
                "renderReference": (
                    proof.get("publicPath")
                    if historical_reference
                    else verification.get("renderReference")
                ),
                "cameraName": proof.get("cameraName"),
                "dependencyAuditPath": proof.get("dependencyAuditPath"),
                "linkageAudit": proof.get("linkageAudit"),
                "materialCompatibilityAudit": proof.get(
                    "materialCompatibilityAudit"
                ),
                "recoveryPrescription": proof.get("recoveryPrescription"),
                "agentReadyChecklist": proof.get("agentReadyChecklist")
                or verification.get("agentReadyChecklist"),
            }
        )
        linkage_audit = proof.get("linkageAudit") or {}
        if linkage_audit:
            render_critical_missing_files = int(
                linkage_audit.get("renderCriticalMissingFiles") or 0
            )
            exact_source_project_missing = bool(
                proof.get("exactSourceProjectMissing")
            )
            missing_exact_files = [
                str(path)
                for path in linkage_audit.get("missingExactFiles", [])
                if path
            ]
            material_compatibility_audit = (
                proof.get("materialCompatibilityAudit") or {}
            )
            material_status = str(
                material_compatibility_audit.get("status") or ""
            )
            material_graph_incomplete = material_status in {
                "asset_missing",
                "rendered_visual_mismatch",
                "runtime_incompatible",
                "source_compatible_runtime_required",
                "source_runtime_required",
            } or material_status.startswith(
                "source_compatible_runtime_"
            )
            cut["c4dLinkStatus"] = {
                "status": (
                    "source_project_derivative_missing"
                    if exact_source_project_missing
                    else
                    "render_safe_material_incomplete"
                    if (
                        render_critical_missing_files == 0
                        and material_graph_incomplete
                    )
                    else
                    "fully_linked_confirmed"
                    if render_critical_missing_files == 0
                    else "render_critical_dependencies_missing"
                ),
                "label": (
                    "Base linked · final project missing"
                    if exact_source_project_missing
                    else
                    "Render-safe · material graph incomplete"
                    if (
                        render_critical_missing_files == 0
                        and material_graph_incomplete
                    )
                    else
                    "Fully linked confirmed"
                    if render_critical_missing_files == 0
                    else (
                        f"{render_critical_missing_files} render-critical "
                        "files missing"
                    )
                ),
                "detail": (
                    proof.get("linkageDetail")
                    or "Exact render-era project dependency audit"
                    if render_critical_missing_files == 0
                    else " · ".join(missing_exact_files)
                ),
                "projectPath": proof_project_path,
                "projectName": (
                    Path(proof_project_path).name
                    if proof_project_path
                    else None
                ),
                "take": proof.get("cameraTake") or "Main",
                "method": (
                    proof.get("linkageMethod")
                    or (
                        "Exact Dropbox revision plus isolated Maxon c4dpy "
                        "dependency audit"
                    )
                ),
                "dependencyReferences": int(
                    linkage_audit.get("dependencyReferences") or 0
                ),
                "linkedReferences": int(
                    linkage_audit.get("linkedReferences") or 0
                ),
                "missingReferences": int(
                    linkage_audit.get("missingReferences") or 0
                ),
                "renderCriticalMissingReferences": int(
                    linkage_audit.get(
                        "renderCriticalMissingReferences"
                    )
                    or 0
                ),
                "renderCriticalMissingFiles": (
                    render_critical_missing_files
                ),
                "renderCriticalExactRecoveries": len(
                    linkage_audit.get("recoveredExactFiles") or []
                ),
                "renderCriticalUnresolvedFiles": len(
                    missing_exact_files
                ),
                "missingExamples": [
                    {
                        "filename": path,
                        "renderCritical": True,
                    }
                    for path in missing_exact_files[:16]
                ],
                "dependencyLabel": (
                    proof.get("dependencyLabel")
                    or "Fully linked confirmed"
                    if render_critical_missing_files == 0
                    else "Render-critical dependencies missing"
                ),
                "components": [],
                "strictLinked": False,
                "visualReview": review,
                "materialCompatibilityAudit": (
                    material_compatibility_audit or None
                ),
            }
            recovered_exact_files = [
                str(path)
                for path in linkage_audit.get("recoveredExactFiles", [])
                if path
            ]
            missing_exact_files = [
                str(path)
                for path in linkage_audit.get("missingExactFiles", [])
                if path
            ]
            camera_element = str(elements.get("camera") or "")
            proof_blockers = []
            if historical_reference:
                proof_blockers.append("camera_proof_missing")
            if exact_source_project_missing:
                proof_blockers.append("exact_source_project_missing")
            elif render_critical_missing_files or missing_exact_files:
                proof_blockers.append(
                    "render_critical_dependencies_missing"
                )
            if str(review.get("status") or "") != "match":
                proof_blockers.append(
                    "camera_or_asset_visual_mismatch"
                    if "mismatch" in camera_element
                    else "asset_visual_incomplete"
                )
            verification["blockers"] = proof_blockers
            remediation = []
            if historical_reference:
                remediation.append(
                    "Render a new camera test from this exact project, take, "
                    "camera, and frame. Keep the historical production frame "
                    "as comparison reference only."
                )
            if proof.get("recoveryPrescription") and (
                exact_source_project_missing
                or material_graph_incomplete
                or render_critical_missing_files
                or missing_exact_files
                or str(review.get("status") or "") != "match"
            ):
                remediation.append(str(proof["recoveryPrescription"]))
            if (
                recovered_exact_files
                and not linkage_audit.get("exactFilesAlreadyRelinked")
            ):
                remediation.append(
                    "Create a dated C4D copy and relink only these exact "
                    "authored dependencies already proven in memory: "
                    + "; ".join(recovered_exact_files)
                    + "."
                )
            for missing_path in missing_exact_files:
                remediation.append(
                    "Recover and relink the exact shot-authored dependency "
                    f"{missing_path}; do not substitute another shot's cache."
                )
            if exact_source_project_missing or (
                render_critical_missing_files or missing_exact_files
            ):
                remediation.append(
                    "Render the exact revision, take, camera, and frame "
                    "through Redshift after every authored render-critical "
                    "cache evaluates."
                )
            elif (
                str(review.get("status") or "") != "match"
                and str(elements.get("materials") or "")
                == "not_verifiable"
            ):
                remediation.append(
                    "Render a material-enabled Redshift proof from the same "
                    "logged project revision, take, camera, and frame."
                )
            verification["remediation"] = remediation
        checks = verification.setdefault("checks", {})
        checks["projectLinked"] = bool(
            proof.get("projectPath")
            and Path(str(proof.get("projectPath"))).exists()
        )
        checks["exactSourceProjectLinked"] = not bool(
            proof.get("exactSourceProjectMissing")
        )
        checks["dependencyAudited"] = bool(linkage_audit)
        checks["dependencyRenderSafe"] = (
            bool(linkage_audit)
            and int(linkage_audit.get("renderCriticalMissingFiles") or 0) == 0
        )
        proxy_gate = proof.get("originalProxyGate") or {}
        proxy_status = str(proxy_gate.get("status") or "not_used")
        checks["proxyRenderSafe"] = (
            proxy_status
            in {
                "not_used",
                "not_applicable",
                "confirmed",
                "verified_rendered",
            }
            and not bool(proof.get("crossShotHairUsed"))
        )
        checks["cameraProofRendered"] = (
            existing_camera_proof_rendered
            if historical_reference
            else True
        )
        checks["visualMatch"] = (
            checks["cameraProofRendered"]
            and str(review.get("status") or "") == "match"
            and all(
                str(elements.get(key) or "") == "match"
                or str(elements.get(key) or "").startswith("not_visible")
                for key in (
                    "location",
                    "camera",
                    "character",
                    "hair",
                    "wardrobe",
                    "materials",
                )
            )
        )
        is_strict_linked = all(
            (
                checks["projectLinked"],
                checks["exactSourceProjectLinked"],
                checks["dependencyAudited"],
                checks["dependencyRenderSafe"],
                checks["proxyRenderSafe"],
                checks["cameraProofRendered"],
                checks["visualMatch"],
                bool(proof.get("redshiftProof"))
                and not historical_reference,
            )
        )
        if is_strict_linked:
            verification.update(
                {
                    "status": "strictly_verified",
                    "label": "Fully linked + camera verified",
                    "strictLinked": True,
                    "blockers": [],
                    "remediation": [],
                }
            )
            for node in cut.get("lineage", []):
                if (
                    node.get("kind") == "camera_proof"
                    and node.get("primaryRecoveryProof")
                    and node.get("projectPath") == proof_project_path
                ):
                    node["strictLinked"] = True
            link_status = cut.get("c4dLinkStatus") or {}
            link_status.update(
                {
                    "status": "fully_linked_confirmed",
                    "label": "Fully linked + camera verified",
                    "strictLinked": True,
                    "verificationStatus": "strictly_verified",
                    "verificationBlockers": [],
                }
            )
            cut["c4dLinkStatus"] = link_status
        if historical_reference:
            applied_references += 1
        else:
            applied_proofs += 1

    state["asFinishingAudit"] = {
        "authority": chronology.get("authority"),
        "root": chronology.get("root"),
        "summary": chronology.get("summary"),
        "relevantDateWindows": chronology.get("relevantDateWindows"),
        "exactSourceRenderCutCount": len(exact_cut_ids),
        "appliedRenderLogs": applied_logs,
        "correctedProjects": corrected_projects,
        "correctedCameras": corrected_cameras,
        "newCameraProofs": applied_proofs,
        "historicalRenderReferences": applied_references,
        "frameMatchAudit": (
            "/data/as-finishing-frame-match-audit-20260727.json"
        ),
        "revisionTargetAudit": (
            "/data/as-finishing-revision-targets-20260727.json"
        ),
        "revisionTargetSummary": (
            (revision_targets or {}).get("summary")
        ),
    }
    return {
        "exactSourceRenderCuts": len(exact_cut_ids),
        "appliedRenderLogs": applied_logs,
        "correctedProjects": corrected_projects,
        "correctedCameras": corrected_cameras,
        "newCameraProofs": applied_proofs,
        "historicalRenderReferences": applied_references,
    }


def apply_unresolved_camera_recoveries(
    state: dict[str, Any],
    archive: dict[str, Any],
) -> dict[str, int]:
    """Publish proven render lineage without promoting a false C4D link."""

    cuts_by_id = {
        str(cut.get("id")): cut
        for cut in state.get("cuts", [])
        if cut.get("id") and not cut.get("isGap")
    }
    applied = 0
    production_render_confirmed = 0
    restored_revisions_tested = 0
    for record in archive.get("records", []):
        if str(record.get("status") or "").startswith("resolved_"):
            # Keep the superseded search ledger as historical evidence, but
            # do not let it overwrite a newer fresh matching camera proof.
            continue
        cut = cuts_by_id.get(str(record.get("cutId")))
        if not cut:
            continue
        candidate = record.get("candidateProject") or {}
        production = record.get("productionRender") or {}
        canonical = record.get("canonical") or {}
        review = record.get("visualReview") or {}
        checks = record.get("checks") or {}
        project_path = str(candidate.get("path") or "")
        comparison_path = str(
            production.get("publicFramePath")
            or record.get("comparisonPath")
            or ""
        )
        rejected_camera_proof_path = str(
            record.get("rejectedCameraProofPath") or ""
        )

        # Preserve the exact project family as a candidate, not as a proven
        # render-time scene. A completed render log proves the output but not
        # that the current saved document still contains its camera state.
        cut["lineage"] = [
            node
            for node in cut.get("lineage", [])
            if not (
                node.get("kind") == "camera_proof"
                and str(node.get("proofStatus") or "") == "unresolved"
            )
        ]
        for node in cut.get("lineage", []):
            if (
                node.get("kind") == "cinema4d"
                and str(node.get("path") or node.get("projectPath") or "")
                == project_path
            ):
                node.update(
                    {
                        "evidence": "candidate",
                        "projectFamilyConfirmed": True,
                        "exactRenderTimeStateConfirmed": False,
                        "sourceApplicationPrimary": True,
                        "detail": str(candidate.get("relationship") or ""),
                    }
                )
        if project_path and not any(
            node.get("kind") == "cinema4d"
            and str(node.get("path") or node.get("projectPath") or "")
            == project_path
            for node in cut.get("lineage", [])
        ):
            cut.setdefault("lineage", []).append(
                {
                    "kind": "cinema4d",
                    "label": Path(project_path).name,
                    "detail": candidate.get("relationship"),
                    "path": project_path,
                    "projectPath": project_path,
                    "evidence": "candidate",
                    "projectFamilyConfirmed": True,
                    "exactRenderTimeStateConfirmed": False,
                    "sourceApplicationPrimary": True,
                }
            )
        render_log_path = str(production.get("renderLogPath") or "")
        if render_log_path and not any(
            node.get("kind") == "redshift_render_log"
            and str(node.get("path") or "") == render_log_path
            for node in cut.get("lineage", [])
        ):
            cut.setdefault("lineage", []).append(
                {
                    "kind": "redshift_render_log",
                    "label": Path(render_log_path).name,
                    "detail": (
                        f"Completed Redshift frames {production.get('frameFrom')}"
                        f"–{production.get('frameTo')} at "
                        f"{production.get('fps')} fps · take "
                        f"{production.get('take')} · logged camera "
                        f"{production.get('camera')} · zero errors"
                    ),
                    "path": render_log_path,
                    "projectPath": project_path,
                    "sourceRenderPath": production.get("path"),
                    "evidence": "confirmed",
                    "productionRenderConfirmed": True,
                    "cameraStateConfirmed": False,
                }
            )
        cut.setdefault("lineage", []).append(
            {
                "kind": "visual_match",
                "label": "Exact archived production render · frame 453",
                "detail": (
                    "Canonical source and archived v003 Redshift output align; "
                    "saved project cameras do not reproduce them."
                ),
                "path": production.get("targetFramePath"),
                "comparisonImage": comparison_path,
                "evidence": "confirmed",
                "productionRenderConfirmed": True,
                "cameraStateConfirmed": False,
                "metrics": production.get("frame453VisualMetrics"),
            }
        )
        for revision in record.get("restoredRevisions", []):
            revision_path = str(revision.get("path") or "")
            cut.setdefault("lineage", []).append(
                {
                    "kind": "cinema4d_recovery",
                    "label": Path(revision_path).name,
                    "detail": (
                        "Restored deleted Dropbox autosave · rendered at "
                        f"frame {canonical.get('targetFrame')} · rejected "
                        "because its saved camera does not match the production "
                        "composition"
                    ),
                    "path": revision_path,
                    "projectPath": revision_path,
                    "comparisonImage": revision.get("proofPath"),
                    "evidence": "missing",
                    "proofStatus": "rejected",
                    "cameraStatePath": revision.get("cameraStatePath"),
                    "sha256": revision.get("sha256"),
                }
            )
            restored_revisions_tested += 1
        cut.setdefault("lineage", []).append(
            {
                "kind": "camera_proof",
                "label": (
                    f"Saved-camera matrix rejected · frame "
                    f"{canonical.get('targetFrame')}"
                ),
                "detail": (
                    "Every saved camera in the current project and both "
                    "recoverable Dropbox autosaves is a different composition."
                ),
                "path": project_path,
                "projectPath": project_path,
                "comparisonImage": rejected_camera_proof_path,
                "evidence": "missing",
                "proofStatus": "rejected",
                "targetFrame": canonical.get("targetFrame"),
                "cameraTake": production.get("take"),
                "cameraRenderData": production.get("renderData"),
                "redshiftProof": True,
                "strictLinked": False,
                "visualVerificationStatus": "mismatch",
                "visualReview": review,
            }
        )

        cut["c4dVerification"] = {
            "status": "mismatch",
            "label": record.get("label"),
            "detail": record.get("detail"),
            "strictLinked": False,
            "reviewedAt": record.get("reviewedAt"),
            "authority": archive.get("authority"),
            "elements": review.get("elements") or {},
            "notes": review.get("notes") or "",
            "blockers": record.get("blockers") or [],
            "remediation": record.get("remediation") or [],
            "checks": {
                "projectLinked": bool(project_path and Path(project_path).is_file()),
                "exactSourceProjectLinked": bool(
                    checks.get("exactRenderTimeProjectLinked")
                ),
                "dependencyAudited": bool(checks.get("dependencyAudited")),
                "dependencyRenderSafe": bool(
                    checks.get("dependencyRenderSafe")
                ),
                "proxyRenderSafe": True,
                "cameraProofRendered": False,
                "rejectedCameraTestRendered": bool(
                    checks.get("cameraProofRendered")
                ),
                "cameraProofMatched": bool(
                    checks.get("cameraProofMatched")
                ),
                "visualMatch": False,
                "productionRenderConfirmed": bool(
                    checks.get("productionRenderConfirmed")
                ),
            },
            "cameraProof": None,
            "cameraName": "Production camera state missing",
            "recoveryEvidencePath": (
                "/data/c4d-unresolved-camera-recoveries-20260727.json"
            ),
            "materialCompatibilityAudit": (
                record.get("materialCompatibilityAudit") or {}
            ),
            "recoveryPrescription": " ".join(
                str(item)
                for item in record.get("remediation") or []
                if item
            ),
            "agentReadyChecklist": [
                str(item)
                for item in record.get("agentReadyChecklist") or []
                if item
            ],
        }
        cut["c4dLinkStatus"] = {
            "status": "source_project_derivative_missing",
            "label": "Render exact · C4D camera unlinked",
            "detail": record.get("detail"),
            "projectPath": project_path,
            "projectName": Path(project_path).name if project_path else None,
            "take": production.get("take") or "Main",
            "method": (
                "Archived output and batch log plus exhaustive current and "
                "restored-revision camera renders"
            ),
            "dependencyReferences": 0,
            "linkedReferences": 0,
            "missingReferences": 0,
            "renderCriticalMissingReferences": 0,
            "renderCriticalMissingFiles": 0,
            "renderCriticalExactRecoveries": 0,
            "renderCriticalUnresolvedFiles": 0,
            "missingExamples": [],
            "dependencyLabel": (
                "Withheld until exact render-time camera state is recovered"
            ),
            "components": [],
            "strictLinked": False,
            "verificationStatus": "mismatch",
            "verificationBlockers": record.get("blockers") or [],
            "visualReview": review,
            "productionRenderConfirmed": bool(
                checks.get("productionRenderConfirmed")
            ),
            "exactRenderTimeProjectLinked": False,
        }
        applied += 1
        production_render_confirmed += int(
            bool(checks.get("productionRenderConfirmed"))
        )
    state["c4dUnresolvedCameraRecoveries"] = {
        "authority": archive.get("authority"),
        "manifest": "/data/c4d-unresolved-camera-recoveries-20260727.json",
        "applied": applied,
        "productionRenderConfirmed": production_render_confirmed,
        "restoredRevisionsTested": restored_revisions_tested,
    }
    return {
        "applied": applied,
        "productionRenderConfirmed": production_render_confirmed,
        "restoredRevisionsTested": restored_revisions_tested,
    }


def apply_manual_lineage_enrichments(
    state: dict[str, Any],
    archive: dict[str, Any],
) -> dict[str, int]:
    """Apply evidence-backed corrections that span multiple source apps."""

    cuts_by_id = {
        str(cut.get("id")): cut
        for cut in state.get("cuts", [])
        if cut.get("id")
    }
    updated_cuts = 0
    removed_nodes = 0
    updated_nodes = 0
    appended_nodes = 0

    for record in archive.get("records", []):
        cut = cuts_by_id.get(str(record.get("cutId") or ""))
        if cut is None:
            continue
        lineage = list(cut.get("lineage", []))

        for removal in record.get("removeNodes", []):
            retained = []
            for node in lineage:
                matches = all(
                    str(node.get(key) or "") == str(value or "")
                    for key, value in removal.items()
                )
                if matches:
                    removed_nodes += 1
                else:
                    retained.append(node)
            lineage = retained

        for update in record.get("updateNodes", []):
            match = update.get("match") or {}
            patch = update.get("patch") or {}
            for node in lineage:
                if all(
                    str(node.get(key) or "") == str(value or "")
                    for key, value in match.items()
                ):
                    node.update(patch)
                    updated_nodes += 1

        for node in record.get("appendNodes", []):
            identity = (
                str(node.get("kind") or ""),
                str(node.get("label") or ""),
                str(node.get("path") or node.get("projectPath") or ""),
                str(node.get("comparisonImage") or ""),
            )
            exists = any(
                (
                    str(existing.get("kind") or ""),
                    str(existing.get("label") or ""),
                    str(
                        existing.get("path")
                        or existing.get("projectPath")
                        or ""
                    ),
                    str(existing.get("comparisonImage") or ""),
                )
                == identity
                for existing in lineage
            )
            if not exists:
                lineage.append(dict(node))
                appended_nodes += 1

        cut["lineage"] = lineage
        updated_cuts += 1

    state["manualLineageEnrichments"] = {
        "authority": archive.get("authority"),
        "generatedAt": archive.get("generatedAt"),
        "manifest": "/data/manual-lineage-enrichments-20260728.json",
        "updatedCuts": updated_cuts,
        "removedNodes": removed_nodes,
        "updatedNodes": updated_nodes,
        "appendedNodes": appended_nodes,
    }
    return {
        "updatedCuts": updated_cuts,
        "removedNodes": removed_nodes,
        "updatedNodes": updated_nodes,
        "appendedNodes": appended_nodes,
    }


def ensure_agent_ready_c4d_prescriptions(
    state: dict[str, Any],
) -> dict[str, int]:
    """Give every picture cut a path-complete recovery or preservation plan."""

    updated = 0
    strict_covered = 0
    non_strict_covered = 0
    custom = 0
    generated = 0
    for cut in state.get("cuts", []):
        if cut.get("isGap"):
            continue
        verification = cut.get("c4dVerification")
        if not isinstance(verification, dict):
            verification = {}
            cut["c4dVerification"] = verification
        strict = bool(verification.get("strictLinked"))
        strict_covered += int(strict)
        non_strict_covered += int(not strict)

        link_status = cut.get("c4dLinkStatus") or {}
        proof_nodes = [
            node
            for node in cut.get("lineage", [])
            if node.get("kind") == "camera_proof"
        ]
        proof = next(
            (
                node
                for node in proof_nodes
                if node.get("primaryRecoveryProof")
            ),
            proof_nodes[-1] if proof_nodes else {},
        )
        project_path = str(
            link_status.get("projectPath")
            or proof.get("projectPath")
            or proof.get("path")
            or ""
        )
        if not project_path:
            c4d_nodes = [
                node
                for node in cut.get("lineage", [])
                if node.get("kind") == "cinema4d"
            ]
            if c4d_nodes:
                project_path = str(
                    c4d_nodes[-1].get("projectPath")
                    or c4d_nodes[-1].get("path")
                    or ""
                )

        source_segments = cut.get("sourceSegments") or []
        source_segment = source_segments[0] if source_segments else {}
        source_frame = str(
            verification.get("renderReference")
            or (cut.get("comparison") or {}).get("sourceFramePath")
            or (cut.get("afterEffectsConform") or {}).get(
                "sourceFramePath"
            )
            or source_segment.get("sourceFirstFramePath")
            or source_segment.get("sourcePath")
            or ""
        )
        source_directory = str(
            source_segment.get("renderDirectory")
            or (
                str(Path(source_frame).parent)
                if source_frame
                else ""
            )
        )
        target_frame = proof.get("targetFrame")
        if target_frame is None:
            camera_frame_match = re.search(
                r"\bframe\s+(\d+)\b",
                str(verification.get("cameraName") or ""),
                flags=re.IGNORECASE,
            )
            if camera_frame_match:
                target_frame = int(camera_frame_match.group(1))
        if target_frame is None and source_frame:
            source_frame_match = re.search(
                r"(\d+)(?=\.[^.]+$)",
                Path(source_frame).name,
            )
            if source_frame_match:
                target_frame = int(source_frame_match.group(1))
        if target_frame is None:
            target_frame = (
                (cut.get("afterEffectsConform") or {}).get("sourceFrame")
                or source_segment.get("selectedFirstFrame")
            )
        take = str(
            proof.get("cameraTake")
            or link_status.get("take")
            or "Main"
        )
        render_data_value = str(
            proof.get("renderData") or proof.get("cameraRenderData") or ""
        )
        if not render_data_value:
            for node in cut.get("lineage", []):
                if node.get("kind") != "camera":
                    continue
                detail = str(node.get("detail") or "")
                render_data_match = re.search(
                    r"(?:render data\s*:?\s*|take\s+[^·]+·\s*)"
                    r"([^·]+?)(?:\s*·|$)",
                    detail,
                    flags=re.IGNORECASE,
                )
                if render_data_match:
                    candidate = render_data_match.group(1).strip()
                    if "render setting" in candidate.casefold():
                        render_data_value = candidate
                        break
        render_data = (
            render_data_value
            or "the exact render-data preset that writes the canonical "
            "source directory"
        )
        camera = str(
            proof.get("cameraObjectPath")
            or verification.get("cameraName")
            or "the take-effective saved render camera"
        )
        camera = re.sub(
            r"\s*[·-]\s*frame\s+\d+\s*$",
            "",
            camera,
            flags=re.IGNORECASE,
        )
        proof_image = str(
            verification.get("cameraProof")
            or proof.get("comparisonImage")
            or ""
        )
        material_audit = (
            verification.get("materialCompatibilityAudit")
            or link_status.get("materialCompatibilityAudit")
            or {}
        )
        render_log_path = ""
        for node in cut.get("lineage", []):
            if node.get("kind") == "redshift_render_log" and node.get("path"):
                render_log_path = str(node["path"])
                break
        if not render_log_path:
            for node in cut.get("lineage", []):
                if node.get("kind") == "camera" and node.get(
                    "renderLogPath"
                ):
                    render_log_path = str(node["renderLogPath"])
                    break
        if not render_log_path:
            render_log_path = str(proof.get("renderLogPath") or "")

        render_log_c4d_version = ""
        if render_log_path and Path(render_log_path).is_file():
            try:
                render_log_text = Path(render_log_path).read_text(
                    errors="replace"
                )
                version_match = re.search(
                    r"<c4dversion>\s*([^<]+?)\s*</c4dversion>",
                    render_log_text,
                    flags=re.IGNORECASE,
                )
                if version_match:
                    render_log_c4d_version = version_match.group(1).strip()
            except OSError:
                pass

        material_runtime = str(
            material_audit.get("productionRuntime")
            or material_audit.get("runtimeDetail")
            or ""
        )
        if material_runtime:
            runtime = material_runtime
        elif render_log_c4d_version:
            runtime = (
                f"Cinema 4D {render_log_c4d_version} with the matching "
                "source-era Redshift node database recorded by "
                f"{render_log_path}"
            )
        elif render_log_path:
            runtime = (
                "the source-compatible Cinema 4D/Redshift runtime after "
                f"reading the exact completed render log {render_log_path}; "
                "do not save a material-bearing recovery until its Cinema "
                "4D and Redshift versions are established"
            )
        else:
            runtime = (
                "the source-compatible Cinema 4D/Redshift runtime only "
                "after recovering a completed render log or render-farm "
                f"package for {source_directory or source_frame or project_path}; "
                "do not save a material-bearing recovery until that runtime "
                "is established"
            )

        missing_files: list[str] = []
        for record in link_status.get("missingExamples") or []:
            if isinstance(record, dict):
                if not record.get("renderCritical"):
                    continue
                missing_path = str(record.get("filename") or "")
            else:
                missing_path = str(record or "")
            if missing_path and missing_path not in missing_files:
                missing_files.append(missing_path)
        linkage_audit = verification.get("linkageAudit") or {}
        for missing_path in linkage_audit.get("missingExactFiles") or []:
            missing_path = str(missing_path or "")
            if missing_path and missing_path not in missing_files:
                missing_files.append(missing_path)

        save_path = ""
        if project_path:
            project_file = Path(project_path)
            if project_file.suffix.casefold() == ".zst":
                project_file = project_file.with_suffix("")
            project_parent = project_file.parent
            if project_parent.name.startswith("_codex_"):
                project_parent = project_parent.parent
            project_stem = re.sub(
                r"_codex_\d{6}$",
                "",
                project_file.stem,
                flags=re.IGNORECASE,
            )
            save_path = str(
                project_parent
                / "_codex_072826"
                / f"{project_stem}_codex_072826.c4d"
            )

        checklist: list[str] = []
        if source_frame or source_directory:
            checklist.append(
                "Lock visual authority to "
                + (source_frame or source_directory)
                + "; preserve the canonical Premiere source interval and "
                "do not retime or substitute a later render."
            )
        if project_path:
            if project_path.casefold().endswith(".zst"):
                checklist.append(
                    f"Restore {project_path} with zstd --keep, open the "
                    "restored C4D read-only first, and never overwrite the "
                    "archive or restored evidence copy."
                )
            else:
                checklist.append(
                    f"Open {project_path} read-only first; make no change to "
                    "the source or any earlier Codex recovery copy."
                )
        else:
            checklist.append(
                "Recover the exact render-time C4D project named by the "
                "canonical render log/output metadata before promoting a "
                "project link."
            )
        if missing_files:
            checklist.append(
                "Recover and identity-check these exact authored files on "
                "their active owner objects; never substitute another "
                "shot's character, hair, wardrobe, proxy, cache, material, "
                "or object: "
                + "; ".join(missing_files)
                + "."
            )
        checklist.append(
            f"Select take {take}, render data {render_data}, camera {camera}"
            + (
                f", and frame {target_frame}."
                if target_frame is not None
                else ". Determine the representative canonical source frame "
                "from the saved source interval before rendering."
            )
        )
        checklist.append(
            "Render both a neutral Redshift camera/geometry proof and a "
            f"production-material proof using {runtime}."
        )
        if proof_image or source_frame:
            checklist.append(
                "Compare camera, location, character, hair, wardrobe, props, "
                "materials, and lighting against "
                + (source_frame or proof_image)
                + "; any visible difference keeps the shot non-strict."
            )
        if save_path:
            checklist.append(
                f"Only after the proof matches, save the new recovery as "
                f"{save_path}; retain the source, archives, and all earlier "
                "dated recovery copies."
            )

        prescription = str(
            verification.get("recoveryPrescription") or ""
        )
        if prescription:
            custom += 1
        else:
            prescription = " ".join(
                f"{index}) {item}"
                for index, item in enumerate(checklist, start=1)
            )
            verification["recoveryPrescription"] = prescription
            generated += 1
        existing_checklist = [
            str(item)
            for item in verification.get("agentReadyChecklist") or []
            if item
        ]
        if len(existing_checklist) >= 4:
            checklist = existing_checklist
        verification["agentReadyChecklist"] = checklist

        remediation = [
            str(item)
            for item in verification.get("remediation") or []
            if item
        ]
        if prescription and prescription not in remediation:
            remediation.insert(0, prescription)
        for item in checklist:
            if item not in remediation:
                remediation.append(item)
        verification["remediation"] = remediation
        link_status["recoveryPrescription"] = prescription
        link_status["agentReadyChecklist"] = checklist
        cut["c4dLinkStatus"] = link_status
        updated += 1

    state.setdefault("c4dVerification", {})[
        "agentReadyRecoveryPrescriptions"
    ] = {
        "pictureCutsCovered": updated,
        "strictCutsCovered": strict_covered,
        "nonStrictCutsCovered": non_strict_covered,
        "customPrescriptions": custom,
        "generatedPrescriptions": generated,
        "savePolicy": (
            "Never overwrite source or prior recovery; use _codex_072826."
        ),
    }
    return {
        "pictureCutsCovered": updated,
        "strictCutsCovered": strict_covered,
        "nonStrictCutsCovered": non_strict_covered,
        "customPrescriptions": custom,
        "generatedPrescriptions": generated,
    }


def apply_c4d_dependency_health(
    cuts: list[dict[str, Any]],
    c4d_dependencies: dict[str, Any],
    dependency_recovery: dict[str, Any] | None = None,
    semantic_recovery: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Attach the current-machine, take-aware C4D asset health to each cut."""

    projects_by_path = {
        str(Path(str(item.get("projectPath") or "")).expanduser().resolve()): item
        for item in c4d_dependencies.get("projects", [])
        if item.get("projectPath")
    }
    recovery_by_project: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        dict
    )
    for item in (dependency_recovery or {}).get(
        "projectDependencies", []
    ):
        project_value = str(item.get("projectPath") or "")
        required_value = str(item.get("requiredPath") or "")
        if project_value and required_value:
            recovery_by_project[project_value][required_value] = item
    semantic_by_required = {
        str(item.get("requiredPath") or ""): item
        for item in (semantic_recovery or {}).get("records", [])
        if item.get("requiredPath")
    }

    def unique_file_count(items: list[dict[str, Any]]) -> int:
        return len(
            {
                str(item.get("filename") or item.get("assetName") or "")
                for item in items
            }
        )

    def component_payload(
        key: str,
        label: str,
        dependencies: list[dict[str, Any]],
        *,
        embedded: bool = False,
        absent_label: str = "Not used",
    ) -> dict[str, Any]:
        linked = [item for item in dependencies if item.get("exists")]
        missing = [item for item in dependencies if not item.get("exists")]
        critical = [
            item
            for item in missing
            if item.get("renderEnabled") is not False
        ]
        if critical:
            status = "missing"
            summary = f"{label} unlinked"
        elif missing:
            status = "warning"
            summary = f"{label} linked for render · inactive links missing"
        elif linked:
            status = "linked"
            summary = f"{label} linked"
        elif embedded:
            status = "embedded"
            summary = f"{label} embedded"
        else:
            status = "not_used"
            summary = absent_label
        return {
            "key": key,
            "label": label,
            "status": status,
            "summary": summary,
            "linkedReferences": len(linked),
            "linkedFiles": unique_file_count(linked),
            "missingReferences": len(missing),
            "missingFiles": unique_file_count(missing),
            "renderCriticalMissingReferences": len(critical),
            "renderCriticalMissingFiles": unique_file_count(critical),
        }

    status_counts: Counter[str] = Counter()
    audited_projects: set[str] = set()
    for cut in cuts:
        if cut.get("isGap"):
            continue
        camera_edge = next(
            (
                edge
                for edge in cut.get("lineage", [])
                if edge.get("kind") == "camera"
                and edge.get("evidence") == "confirmed"
                and edge.get("path")
            ),
            None,
        )
        if camera_edge is None:
            # Dependency linkage is independently useful even before a camera
            # proof succeeds. An immutable render-prefix-confirmed C4D node is
            # sufficient authority for attaching its take-aware asset audit;
            # the later strict-verification gate still requires a rendered,
            # visually matching camera proof.
            camera_edge = next(
                (
                    edge
                    for edge in cut.get("lineage", [])
                    if edge.get("kind") == "cinema4d"
                    and edge.get("evidence") == "confirmed"
                    and str(
                        edge.get("projectPath") or edge.get("path") or ""
                    )
                    .lower()
                    .endswith(".c4d")
                ),
                None,
            )
        if camera_edge is None:
            cut["c4dLinkStatus"] = {
                "status": "audit_unavailable",
                "label": "C4D linkage audit unavailable",
                "detail": "No confirmed render-aligned C4D project is attached.",
                "components": [],
                "missingExamples": [],
            }
            status_counts["audit_unavailable"] += 1
            continue
        camera_project = str(camera_edge.get("projectPath") or "")
        camera_path = str(camera_edge.get("path") or "")
        project_candidate = (
            camera_project
            if camera_project.lower().endswith(".c4d")
            else camera_path
            if camera_path.lower().endswith(".c4d")
            else ""
        )
        if not project_candidate:
            project_node = next(
                (
                    edge
                    for edge in cut.get("lineage", [])
                    if edge.get("kind") == "cinema4d"
                    and str(
                        edge.get("projectPath") or edge.get("path") or ""
                    ).lower().endswith(".c4d")
                ),
                None,
            )
            if project_node:
                project_candidate = str(
                    project_node.get("projectPath")
                    or project_node.get("path")
                    or ""
                )
        if not project_candidate:
            proof_node = next(
                (
                    edge
                    for edge in cut.get("lineage", [])
                    if edge.get("kind") == "camera_proof"
                    and str(edge.get("projectPath") or "")
                    .lower()
                    .endswith(".c4d")
                ),
                None,
            )
            if proof_node:
                project_candidate = str(
                    proof_node.get("projectPath") or ""
                )
        project_path = (
            str(Path(project_candidate).expanduser().resolve())
            if project_candidate
            else ""
        )
        project = projects_by_path.get(project_path)
        if project is None or project.get("error"):
            cut["c4dLinkStatus"] = {
                "status": "audit_unavailable",
                "label": "C4D linkage audit unavailable",
                "detail": (
                    str((project or {}).get("error"))
                    if project
                    else "The confirmed source project has not been dependency-probed."
                ),
                "projectPath": project_path,
                "components": [],
                "missingExamples": [],
            }
            status_counts["audit_unavailable"] += 1
            continue
        take_match = re.search(
            r"(?:^| · )(?:Take:|take) ([^·]+)",
            str(camera_edge.get("detail") or ""),
            re.IGNORECASE,
        )
        take_name = take_match.group(1).strip() if take_match else "Main"
        take_record = project.get("takes", {}).get(take_name)
        collection = (
            take_record
            if take_record and take_record.get("found") is not False
            else project.get("fullScene", {})
        )
        dependencies = collection.get("dependencies", [])
        missing = [item for item in dependencies if not item.get("exists")]
        critical = [
            item
            for item in missing
            if item.get("renderEnabled") is not False
        ]
        project_recovery = recovery_by_project.get(project_path, {})
        critical_recovery_records = list(
            {
                str(record.get("requiredPath") or ""): record
                for record in (
                    project_recovery.get(
                        str(item.get("filename") or "")
                    )
                    for item in critical
                )
                if record
            }.values()
        )
        critical_exact_recoveries = {
            str(item.get("requiredPath") or "")
            for item in critical_recovery_records
            if item.get("status") == "recovered_exact_path"
        }
        critical_candidate_recoveries = {
            str(item.get("requiredPath") or "")
            for item in critical_recovery_records
            if item.get("status")
            in {"candidate_exact_basename", "candidate_normalized_name"}
        }
        critical_unresolved = {
            str(item.get("filename") or "")
            for item in critical
            if (
                project_recovery.get(
                    str(item.get("filename") or ""), {}
                ).get("status")
                in {None, "unresolved"}
            )
        }
        linked = [item for item in dependencies if item.get("exists")]
        object_inventory = project.get("objectInventory", {})
        categories = {
            category: [
                item
                for item in dependencies
                if item.get("category") == category
            ]
            for category in ("object", "texture", "proxy", "cache", "other")
        }
        character_dependencies = [
            item for item in dependencies if item.get("characterRelated")
        ]
        components = [
            component_payload(
                "objects",
                "Objects",
                categories["object"],
                embedded=bool(object_inventory.get("total")),
            ),
            component_payload(
                "character",
                "Character",
                character_dependencies,
                embedded=bool(object_inventory.get("characterSignals")),
                absent_label="Character not detected",
            ),
            component_payload(
                "textures",
                "Textures",
                categories["texture"],
                absent_label="No external textures",
            ),
            component_payload(
                "proxies",
                "Proxies",
                categories["proxy"],
                absent_label="No external proxies",
            ),
            component_payload(
                "caches",
                "Caches",
                categories["cache"],
                absent_label="No external caches",
            ),
        ]
        if critical:
            status = "render_dependencies_missing"
            label = "Render dependencies missing"
        elif missing:
            status = "render_safe_with_warnings"
            label = "Render-safe · inactive links missing"
        else:
            status = "fully_linked_confirmed"
            label = "Fully linked confirmed"
        examples: list[dict[str, Any]] = []
        seen_examples: set[str] = set()
        for item in sorted(
            missing,
            key=lambda value: (
                value.get("renderEnabled") is False,
                str(value.get("category") or ""),
                str(value.get("filename") or ""),
            ),
        ):
            filename = str(
                item.get("filename") or item.get("assetName") or ""
            )
            if filename in seen_examples:
                continue
            seen_examples.add(filename)
            recovery_record = project_recovery.get(filename)
            semantic_record = semantic_by_required.get(filename)
            examples.append(
                {
                    "filename": filename,
                    "owner": str(
                        item.get("ownerPath")
                        or item.get("ownerName")
                        or ""
                    ),
                    "category": item.get("category") or "other",
                    "characterRelated": bool(item.get("characterRelated")),
                    "renderCritical": item.get("renderEnabled") is not False,
                    "recovery": (
                        {
                            "status": (
                                (recovery_record or {}).get("status")
                                or (semantic_record or {}).get("status")
                            ),
                            "candidates": (
                                (recovery_record or {}).get("candidates", [])
                            )[:3],
                            "semanticCandidates": (
                                (semantic_record or {}).get("candidates", [])
                            )[:3],
                            "semanticValidationRequired": (
                                (semantic_record or {}).get(
                                    "validationRequired", []
                                )
                            ),
                        }
                        if recovery_record or semantic_record
                        else None
                    ),
                }
            )
            if len(examples) >= 16:
                break
        component_sentence = " · ".join(
            str(item["summary"]).lower() for item in components
        )
        cut["c4dLinkStatus"] = {
            "status": status,
            "label": label,
            "detail": component_sentence,
            "projectPath": project_path,
            "projectName": Path(project_path).name,
            "take": take_name,
            "auditedAt": c4d_dependencies.get("updatedAt"),
            "method": c4d_dependencies.get("method"),
            "objectCount": int(object_inventory.get("total") or 0),
            "renderEnabledObjectCount": int(
                object_inventory.get("renderEnabled") or 0
            ),
            "dependencyReferences": len(dependencies),
            "linkedReferences": len(linked),
            "linkedFiles": unique_file_count(linked),
            "missingReferences": len(missing),
            "missingFiles": unique_file_count(missing),
            "renderCriticalMissingReferences": len(critical),
            "renderCriticalMissingFiles": unique_file_count(critical),
            "renderCriticalExactRecoveries": len(
                critical_exact_recoveries
            ),
            "renderCriticalCandidateRecoveries": len(
                critical_candidate_recoveries
            ),
            "renderCriticalUnresolvedFiles": len(critical_unresolved),
            "dependencyRecovery": {
                "auditedAt": (dependency_recovery or {}).get(
                    "generatedAt"
                ),
                "method": (dependency_recovery or {}).get("method"),
                "exactPathRecoveries": len(critical_exact_recoveries),
                "candidateRecoveries": len(
                    critical_candidate_recoveries
                ),
                "unresolved": len(critical_unresolved),
                "records": [
                    {
                        "requiredPath": item.get("requiredPath"),
                        "basename": item.get("basename"),
                        "status": item.get("status"),
                        "categories": item.get("categories", []),
                        "characterRelated": bool(
                            item.get("characterRelated")
                        ),
                        "candidates": item.get("candidates", [])[:3],
                        "semanticCandidates": (
                            semantic_by_required.get(
                                str(item.get("requiredPath") or ""), {}
                            ).get("candidates", [])[:3]
                        ),
                    }
                    for item in critical_recovery_records[:16]
                ],
            },
            "components": components,
            "missingExamples": examples,
            "historicalRenderNote": (
                "The archived source render already exists; this reports whether "
                "the C4D project can reproduce it from the current Mac without relinking."
            ),
        }
        for node in cut.get("lineage", []):
            if (
                node.get("kind") == "cinema4d"
                and node.get("path")
                and str(
                    Path(str(node["path"])).expanduser().resolve()
                )
                == project_path
            ):
                node["assetHealth"] = {
                    "status": status,
                    "label": label,
                    "take": take_name,
                }
        audited_projects.add(project_path)
        status_counts[status] += 1
    return {
        "c4dDependencyAuditedProjects": sum(
            1
            for item in c4d_dependencies.get("projects", [])
            if not item.get("error")
        ),
        "c4dDependencyMappedProjects": len(audited_projects),
        "c4dDependencyAuditedCuts": sum(status_counts.values())
        - status_counts["audit_unavailable"],
        "c4dFullyLinkedCuts": status_counts["fully_linked_confirmed"],
        "c4dRenderSafeWarningCuts": status_counts[
            "render_safe_with_warnings"
        ],
        "c4dMissingRenderDependencyCuts": status_counts[
            "render_dependencies_missing"
        ],
        "c4dDependencyUnavailableCuts": status_counts["audit_unavailable"],
    }


def apply_exact_cut_dependency_audits(
    cuts: list[dict[str, Any]],
    archive: dict[str, Any],
) -> dict[str, int]:
    """Overlay the frame-specific, save/reopen-verified dependency ledger.

    The older project audit is useful for component inventory, but this exact
    pass follows each canonical cut's selected project/take/frame, applies only
    unambiguous local relinks in memory, and audits the resulting scene again.
    It therefore owns the render-safety gate without making any camera-match
    claim.
    """

    records = {
        str(record.get("cutId") or ""): record
        for record in archive.get("cuts", [])
        if record.get("cutId")
    }
    counts: Counter[str] = Counter()

    def normalized_project(value: Any) -> str:
        text = str(value or "")
        return (
            str(Path(text).expanduser().resolve())
            if text.lower().endswith(".c4d")
            else ""
        )

    def sequence_label(value: Any) -> str:
        text = str(value or "")
        filename = Path(text).name
        return re.sub(
            r"(?<=\D)\d{3,6}(?=\.[A-Za-z0-9]+$)",
            "####",
            filename,
        )

    for cut in cuts:
        if cut.get("isGap"):
            continue
        cut_id = str(cut.get("id") or "")
        proof_verification = cut.get("c4dVerification") or {}
        current_linkage = (
            proof_verification.get("linkageAudit")
            if isinstance(proof_verification, dict)
            else {}
        )
        current_linkage = (
            current_linkage
            if isinstance(current_linkage, dict)
            else {}
        )
        if current_linkage.get("authoritativeForCurrentRecovery") is True:
            strict_safe = bool(
                current_linkage.get("strictDependencyRenderSafe")
            )
            unresolved_file_count = int(
                current_linkage.get("renderCriticalMissingFiles")
                or current_linkage.get("renderCriticalUnresolvedFiles")
                or 0
            )
            unresolved_reference_count = int(
                current_linkage.get("renderCriticalMissingReferences") or 0
            )
            if strict_safe and (
                unresolved_file_count or unresolved_reference_count
            ):
                strict_safe = False
            project_path = normalized_project(
                current_linkage.get("auditProject")
                or proof_verification.get("projectPath")
            )
            frame = current_linkage.get(
                "auditFrame",
                proof_verification.get("targetFrame"),
            )
            take = str(
                current_linkage.get("auditTake")
                or proof_verification.get("cameraTake")
                or "Main"
            )
            mapped_paths = int(
                current_linkage.get("renderCriticalExactRecoveries")
                or current_linkage.get("mappedPaths")
                or 0
            )
            audit_path = str(
                current_linkage.get("auditPath")
                or proof_verification.get("dependencyAuditPath")
                or ""
            )
            verification_path = (
                APP_ROOT / audit_path if audit_path else APP_ROOT
            )
            source_era_confirmed = current_linkage.get(
                "sourceEraProxyIdentityConfirmed"
            )
            status = (
                str(current_linkage.get("status"))
                if current_linkage.get("status")
                else "fully_linked_confirmed"
                if strict_safe
                else "render_dependencies_missing"
            )
            saved_reopen_verified = bool(
                current_linkage.get("savedReopenVerified")
                or "saved_reopen" in status.lower()
            )
            label = (
                (
                    "Saved/reopened dependency audit passed"
                    if saved_reopen_verified
                    else "Current in-memory dependency audit passed"
                )
                if strict_safe
                else "Current-path render dependencies missing"
            )
            linked_scope_label = (
                "save/reopen dependencies"
                if saved_reopen_verified
                else "active-render dependencies"
            )
            detail = (
                f"Frame {frame} · take {take} · "
                f"{int(current_linkage.get('linkedReferences') or 0)} of "
                f"{int(current_linkage.get('dependencyReferences') or 0)} "
                f"{linked_scope_label} linked · "
                f"{unresolved_file_count} unresolved render-critical "
                f"file{'s' if unresolved_file_count != 1 else ''}"
            )
            if source_era_confirmed is False:
                detail += " · source-era proxy identity not confirmed"

            health = dict(cut.get("c4dLinkStatus") or {})
            health.update(
                {
                    "status": status,
                    "label": label,
                    "detail": detail,
                    "projectPath": project_path,
                    "projectName": (
                        Path(project_path).name if project_path else None
                    ),
                    "take": take,
                    "frame": frame,
                    "auditedAt": proof_verification.get("reviewedAt"),
                    "method": current_linkage.get("authority"),
                    "dependencyReferences": int(
                        current_linkage.get("dependencyReferences") or 0
                    ),
                    "linkedReferences": int(
                        current_linkage.get("linkedReferences") or 0
                    ),
                    "missingReferences": int(
                        current_linkage.get("missingReferences") or 0
                    ),
                    "rawRenderCriticalMissingFiles": int(
                        current_linkage.get(
                            "rawRenderCriticalMissingFiles"
                        )
                        or 0
                    ),
                    "renderCriticalExactRecoveries": mapped_paths,
                    "renderCriticalMissingReferences": (
                        unresolved_reference_count
                    ),
                    "renderCriticalMissingFiles": unresolved_file_count,
                    "renderCriticalUnresolvedFiles": unresolved_file_count,
                    "strictDependencyRenderSafe": strict_safe,
                    "manifestPath": current_linkage.get("manifestPath"),
                    "verificationPath": audit_path or None,
                    "missingExamples": list(
                        current_linkage.get("missingExamples") or []
                    ),
                    "exactCutAudit": {
                        "authority": current_linkage.get("authority"),
                        "rawAuditPath": audit_path or None,
                        "manifestPath": current_linkage.get("manifestPath"),
                        "verificationPath": audit_path or None,
                        "evidencePath": current_linkage.get("evidencePath"),
                        "mappedPaths": mapped_paths,
                        "manifestUnresolvedPaths": unresolved_file_count,
                        "postRelinkUnresolvedFiles": (
                            unresolved_file_count
                        ),
                        "postRelinkUnresolvedReferences": (
                            unresolved_reference_count
                        ),
                        "strictDependencyRenderSafe": strict_safe,
                        "currentPathIdentityConfirmed": (
                            current_linkage.get(
                                "currentPathIdentityConfirmed"
                            )
                        ),
                        "sourceEraProxyIdentityConfirmed": (
                            source_era_confirmed
                        ),
                        "scope": current_linkage.get("scope"),
                    },
                }
            )
            cut["c4dLinkStatus"] = health
            cut["lineage"] = [
                node
                for node in cut.get("lineage", [])
                if node.get("kind") != "c4d_dependency_audit"
            ]
            cut.setdefault("lineage", []).append(
                {
                    "kind": "c4d_dependency_audit",
                    "label": label,
                    "detail": detail,
                    "path": str(verification_path),
                    "projectPath": project_path,
                    "evidence": "confirmed",
                    "take": take,
                    "frame": frame,
                    "strictDependencyRenderSafe": strict_safe,
                    "mappedPaths": mapped_paths,
                    "unresolvedFiles": unresolved_file_count,
                    "currentPathIdentityConfirmed": (
                        current_linkage.get("currentPathIdentityConfirmed")
                    ),
                    "sourceEraProxyIdentityConfirmed": (
                        source_era_confirmed
                    ),
                }
            )
            counts["safe" if strict_safe else "blocked"] += 1
            continue
        record = records.get(cut_id)
        if not record or record.get("status") != "verified":
            counts["unavailable"] += 1
            continue

        project_path = normalized_project(record.get("project"))
        selected_paths = {
            normalized_project(node.get("projectPath") or node.get("path"))
            for node in cut.get("lineage", [])
            if node.get("kind") in {"cinema4d", "camera_proof", "camera"}
        }
        selected_paths.discard("")
        if selected_paths and project_path not in selected_paths:
            counts["project_mismatch"] += 1
            continue

        verification_path = APP_ROOT / str(
            record.get("verificationPath") or ""
        )
        verification: dict[str, Any] = {}
        if verification_path.is_file():
            try:
                verification = json.loads(
                    verification_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                verification = {}
        post = verification.get("postRelinkDependencyAudit") or {}
        post_unresolved_paths = list(
            post.get("renderCriticalUnresolvedPaths")
            or record.get("postRelinkUnresolvedPaths")
            or []
        )
        manifest_unresolved_paths = list(record.get("unresolvedPaths") or [])
        unresolved_paths = post_unresolved_paths or manifest_unresolved_paths
        unresolved_file_count = int(
            post.get("renderCriticalUnresolvedFiles")
            if post.get("renderCriticalUnresolvedFiles") is not None
            else record.get("postRelinkUnresolvedFiles")
            if record.get("postRelinkUnresolvedFiles") is not None
            else len(set(unresolved_paths))
        )
        unresolved_reference_count = int(
            post.get("renderCriticalUnresolvedReferences")
            if post.get("renderCriticalUnresolvedReferences") is not None
            else record.get("postRelinkUnresolvedReferences")
            if record.get("postRelinkUnresolvedReferences") is not None
            else unresolved_file_count
        )
        strict_safe = bool(record.get("strictDependencyRenderSafe"))
        if strict_safe and unresolved_file_count:
            strict_safe = False

        unique_series: list[str] = []
        seen_series: set[str] = set()
        for missing_path in unresolved_paths:
            label = sequence_label(missing_path)
            if label in seen_series:
                continue
            seen_series.add(label)
            unique_series.append(label)
            if len(unique_series) >= 16:
                break

        mapped_paths = int(record.get("mappedPaths") or 0)
        raw_missing = int(record.get("rawRenderCriticalMissingFiles") or 0)
        frame = record.get("frame")
        take = str(record.get("take") or "Main")
        status = (
            "fully_linked_confirmed"
            if strict_safe
            else "render_dependencies_missing"
        )
        label = (
            "Exact dependency audit passed"
            if strict_safe
            else "Exact render dependencies missing"
        )
        detail = (
            f"Frame {frame} · take {take} · {mapped_paths} exact local "
            f"relink{'s' if mapped_paths != 1 else ''} verified · "
            f"{unresolved_file_count} unresolved render-critical "
            f"file{'s' if unresolved_file_count != 1 else ''}"
        )

        health = dict(cut.get("c4dLinkStatus") or {})
        health.update(
            {
                "status": status,
                "label": label,
                "detail": detail,
                "projectPath": project_path,
                "projectName": Path(project_path).name,
                "take": take,
                "frame": frame,
                "auditedAt": archive.get("updatedAt"),
                "method": archive.get("authority"),
                "dependencyReferences": int(
                    post.get("dependencyReferences")
                    or record.get("postRelinkDependencyReferences")
                    or health.get("dependencyReferences")
                    or 0
                ),
                "rawRenderCriticalMissingFiles": raw_missing,
                "renderCriticalExactRecoveries": mapped_paths,
                "renderCriticalMissingReferences": unresolved_reference_count,
                "renderCriticalMissingFiles": unresolved_file_count,
                "renderCriticalUnresolvedFiles": unresolved_file_count,
                "strictDependencyRenderSafe": strict_safe,
                "manifestPath": record.get("manifestPath"),
                "verificationPath": record.get("verificationPath"),
                "missingExamples": [
                    {
                        "filename": item,
                        "owner": "Exact frame-specific dependency audit",
                        "category": (
                            "proxy"
                            if item.lower().endswith(".rs")
                            else "cache"
                            if item.lower().endswith(
                                (".abc", ".vdb", ".bgeo", ".bgeo.sc")
                            )
                            else "texture"
                            if item.lower().endswith(
                                (
                                    ".png",
                                    ".jpg",
                                    ".jpeg",
                                    ".tif",
                                    ".tiff",
                                    ".exr",
                                )
                            )
                            else "other"
                        ),
                        "characterRelated": bool(
                            any(
                                token in item.lower()
                                for token in (
                                    "abby",
                                    "character",
                                    "cloth",
                                    "hair",
                                    "wardrobe",
                                )
                            )
                        ),
                        "renderCritical": True,
                    }
                    for item in unique_series
                ],
                "exactCutAudit": {
                    "authority": archive.get("authority"),
                    "rawAuditPath": record.get("rawAuditPath"),
                    "manifestPath": record.get("manifestPath"),
                    "verificationPath": record.get("verificationPath"),
                    "mappedPaths": mapped_paths,
                    "manifestUnresolvedPaths": len(
                        manifest_unresolved_paths
                    ),
                    "postRelinkUnresolvedFiles": unresolved_file_count,
                    "postRelinkUnresolvedReferences": (
                        unresolved_reference_count
                    ),
                    "strictDependencyRenderSafe": strict_safe,
                },
            }
        )
        cut["c4dLinkStatus"] = health

        for node in cut.get("lineage", []):
            if (
                node.get("kind") == "cinema4d"
                and normalized_project(
                    node.get("projectPath") or node.get("path")
                )
                == project_path
            ):
                node["assetHealth"] = {
                    "status": status,
                    "label": label,
                    "take": take,
                    "frame": frame,
                    "strictDependencyRenderSafe": strict_safe,
                }
        cut["lineage"] = [
            node
            for node in cut.get("lineage", [])
            if node.get("kind") != "c4d_dependency_audit"
        ]
        cut.setdefault("lineage", []).append(
            {
                "kind": "c4d_dependency_audit",
                "label": label,
                "detail": detail,
                "path": str(verification_path),
                "projectPath": project_path,
                "evidence": "confirmed",
                "take": take,
                "frame": frame,
                "strictDependencyRenderSafe": strict_safe,
                "mappedPaths": mapped_paths,
                "unresolvedFiles": unresolved_file_count,
            }
        )
        counts["safe" if strict_safe else "blocked"] += 1

    return {
        "c4dExactCutDependencyAuditedCuts": counts["safe"]
        + counts["blocked"],
        "c4dExactCutDependencySafeCuts": counts["safe"],
        "c4dExactCutDependencyBlockedCuts": counts["blocked"],
        "c4dExactCutDependencyUnavailableCuts": counts["unavailable"],
        "c4dExactCutDependencyProjectMismatches": counts[
            "project_mismatch"
        ],
    }


def integrate_current_c4d_verification_evidence(
    state: dict[str, Any],
) -> dict[str, int]:
    """Link every available audit, camera identity, and active proof together.

    The exact-cut audit archive was produced incrementally, so its summary file
    is not a complete index. This pass reads the per-cut verification records
    directly, records scope differences instead of hiding them, and fills the
    final card-level linkage without changing any camera-match or render-safety
    conclusion.
    """

    cut_audits: dict[str, dict[str, Any]] = {}
    if C4D_CUT_DEPENDENCY_AUDIT_DIR.is_dir():
        for audit_path in sorted(
            C4D_CUT_DEPENDENCY_AUDIT_DIR.glob(
                "CUT-???-relink-verification.json"
            )
        ):
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            cut_id = str(
                audit.get("cutId")
                or audit_path.name.split("-relink-verification", 1)[0]
            )
            audit["_relativePath"] = str(audit_path.relative_to(APP_ROOT))
            cut_audits[cut_id] = audit
    mainframe_recovery_audit_dir = (
        DATA_DIR / "c4d-mainframe-recovery-20260730"
    )
    if mainframe_recovery_audit_dir.is_dir():
        for audit_path in sorted(
            mainframe_recovery_audit_dir.glob(
                "CUT-???-mainframe-exact-relink-verification.json"
            )
        ):
            try:
                audit = json.loads(audit_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if audit.get("status") != "verified":
                continue
            cut_id = audit_path.name.split(
                "-mainframe-exact-relink-verification", 1
            )[0]
            audit["_relativePath"] = str(audit_path.relative_to(APP_ROOT))
            cut_audits[cut_id] = audit

    dependency_path_overrides = {
        "CUT-011": (
            "data/c4d-clean-recoveries/"
            "CUT-011-codex-072726-dependency-audit.json"
        ),
    }
    dependency_links = 0
    linkage_links = 0
    camera_nodes_added = 0
    audit_nodes_added = 0
    superseded_proofs = 0
    scoped_frame_differences = 0

    def normalized_project(value: Any) -> str:
        text = str(value or "")
        if not text.lower().endswith(".c4d"):
            return ""
        try:
            return str(Path(text).expanduser().resolve())
        except OSError:
            return text

    def node_project(node: dict[str, Any]) -> str:
        return normalized_project(node.get("projectPath") or node.get("path"))

    def frame_from_label(value: Any) -> int | None:
        match = re.search(
            r"\bframe\s+(\d+)\b",
            str(value or ""),
            flags=re.IGNORECASE,
        )
        return int(match.group(1)) if match else None

    for cut in state.get("cuts", []):
        if cut.get("isGap"):
            continue
        cut_id = str(cut.get("id") or "")
        verification = cut.get("c4dVerification")
        if not isinstance(verification, dict):
            verification = {}
            cut["c4dVerification"] = verification
        lineage = cut.setdefault("lineage", [])
        link_status = cut.get("c4dLinkStatus") or {}
        audit = cut_audits.get(cut_id) or {}

        active_proof = next(
            (
                node
                for node in lineage
                if node.get("kind") == "camera_proof"
                and node.get("comparisonImage")
                == verification.get("cameraProof")
            ),
            None,
        )
        if active_proof is None:
            active_proof = next(
                (
                    node
                    for node in lineage
                    if node.get("kind") == "camera_proof"
                    and node.get("primaryRecoveryProof")
                ),
                None,
            )
        c4d_nodes = [
            node
            for node in lineage
            if node.get("kind") == "cinema4d"
            and (node.get("projectPath") or node.get("path"))
        ]
        selected_c4d = next(
            (node for node in c4d_nodes if node.get("sourceApplicationPrimary")),
            next(
                (
                    node
                    for node in c4d_nodes
                    if any(
                        tag.get("type") == "chapter_edit"
                        for tag in node.get("tags") or []
                        if isinstance(tag, dict)
                    )
                ),
                next(
                    (node for node in c4d_nodes if node.get("projectPath")),
                    c4d_nodes[0] if c4d_nodes else {},
                ),
            ),
        )
        active_project = normalized_project(
            (active_proof or {}).get("projectPath")
            or (active_proof or {}).get("path")
            or link_status.get("projectPath")
            or selected_c4d.get("projectPath")
            or selected_c4d.get("path")
        )
        if active_proof is not None and active_project:
            active_proof.setdefault("projectPath", active_project)
            active_proof.setdefault("path", active_project)
        active_frame = (active_proof or {}).get("targetFrame")
        if active_frame is None:
            active_frame = frame_from_label(
                (active_proof or {}).get("label")
                or verification.get("cameraName")
            )

        # CUT-008 frame 61 was an earlier diagnosis. Preserve it as history,
        # but remove it from the active camera-proof namespace now that frame
        # 42 is the verified target.
        if cut_id == "CUT-008" and active_frame == 42:
            for node in lineage:
                if node.get("kind") != "camera_proof":
                    continue
                node_frame = node.get("targetFrame")
                if node_frame is None:
                    node_frame = frame_from_label(node.get("label"))
                if node_frame != 61:
                    continue
                node["kind"] = "historical_camera_proof"
                node["evidence"] = "superseded"
                node["proofStatus"] = "superseded"
                node["historicalOnly"] = True
                node["supersededBy"] = verification.get("cameraProof")
                node["detail"] = (
                    f"{node.get('detail') or ''} Superseded by the current "
                    "verified target at frame 42; retained only as process "
                    "history."
                ).strip()
                superseded_proofs += 1

        existing_linkage = verification.get("linkageAudit")
        existing_linkage = (
            dict(existing_linkage)
            if isinstance(existing_linkage, dict)
            else {}
        )
        authoritative_current_recovery = bool(
            existing_linkage.get("authoritativeForCurrentRecovery") is True
        )
        current_mainframe_audit_path = str(
            audit.get("_relativePath") or ""
        )
        current_mainframe_audit_selected = bool(
            current_mainframe_audit_path.startswith(
                "data/c4d-mainframe-recovery-20260730/"
            )
            and audit.get("status") == "verified"
        )
        exact_cut_audit = link_status.get("exactCutAudit") or {}
        if current_mainframe_audit_selected:
            active_post = audit.get("postRelinkDependencyAudit") or {}
            project_wide_post = (
                audit.get("projectWidePostRelinkDependencyAudit") or {}
            )
            strict_active_frame = bool(
                audit.get("strictDependencyRenderSafe")
            )
            exact_cut_audit = {
                "authority": (
                    "Exact Mainframe recovery relinks verified at the "
                    "selected take and frame"
                ),
                "verificationPath": current_mainframe_audit_path,
                "rawAuditPath": current_mainframe_audit_path,
                "manifestPath": audit.get("manifest"),
                "mappedPaths": int(audit.get("mappingCount") or 0),
                "manifestUnresolvedPaths": len(
                    audit.get("manifestUnresolved") or []
                ),
                "postRelinkUnresolvedFiles": int(
                    active_post.get("renderCriticalUnresolvedFiles") or 0
                ),
                "strictDependencyRenderSafe": strict_active_frame,
                "projectWideStrictDependencyRenderSafe": bool(
                    project_wide_post.get("strictDependencyRenderSafe")
                ),
                "projectWideUnresolvedFiles": int(
                    project_wide_post.get("unresolvedPictureFiles") or 0
                ),
                "take": audit.get("take"),
                "frame": audit.get("frame"),
                "project": audit.get("project"),
            }
            link_status = dict(link_status)
            link_status.update(
                {
                    "status": (
                        "active_frame_strict_linked"
                        if exact_cut_audit[
                            "projectWideStrictDependencyRenderSafe"
                        ]
                        else (
                            "active_frame_strict_linked_with_"
                            "dormant_project_residue"
                        )
                    ),
                    "label": (
                        "Active frame fully linked"
                        if exact_cut_audit[
                            "projectWideStrictDependencyRenderSafe"
                        ]
                        else (
                            "Active frame fully linked · dormant project "
                            "residue retained"
                        )
                    ),
                    "detail": (
                        f"{exact_cut_audit['mappedPaths']} exact mappings · "
                        "0 render-critical unresolved files at the selected "
                        f"take/frame · "
                        f"{exact_cut_audit['projectWideUnresolvedFiles']} "
                        "disabled dormant project references retained in the "
                        "forensic audit"
                    ),
                    "renderCriticalMissingReferences": int(
                        active_post.get(
                            "renderCriticalUnresolvedReferences"
                        )
                        or 0
                    ),
                    "renderCriticalMissingFiles": int(
                        active_post.get("renderCriticalUnresolvedFiles") or 0
                    ),
                    "renderCriticalUnresolvedFiles": int(
                        active_post.get("renderCriticalUnresolvedFiles") or 0
                    ),
                    "strictDependencyRenderSafe": strict_active_frame,
                    "strictLinked": strict_active_frame,
                    "exactCutAudit": exact_cut_audit,
                }
            )
            cut["c4dLinkStatus"] = link_status
            verification_checks = dict(
                verification.get("checks") or {}
            )
            verification_checks.update(
                {
                    "projectLinked": True,
                    "dependencyAudited": True,
                    "dependencyRenderSafe": strict_active_frame,
                    "exactSourceProjectLinked": True,
                }
            )
            verification["checks"] = verification_checks
            if cut_id == "CUT-004":
                current_batch_public_path = (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-004/exact-source-zero-missing-480/"
                    "CUT-004-exact-source-zero-missing0168.png"
                )
                current_project = (
                    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                    "Absolutely/SG/C4D/1C_1E_A_Teardrop_Transition_v007_"
                    "codex_exactfull_20260801.c4d"
                )
                current_result_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-004-exact-source-zero-missing-480-result.json"
                )
                current_proof_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-004-strict-full-color-proof-20260801.json"
                )
                current_manifest_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-004-exact-source-full-picture-relink-manifest-"
                    "stage2.json"
                )
                current_reopen_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-004-exact-source-saved-reopen-verification.json"
                )
                current_comparison_path = (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-004/CUT-004-historical-f0168-left-vs-exact-"
                    "source-zero-missing-right.jpg"
                )
                exact_cut_audit = {
                    "authority": (
                        "Exact untouched-source Mainframe recovery, saved "
                        "sibling, and independent reopen verification"
                    ),
                    "verificationPath": current_reopen_path,
                    "rawAuditPath": current_proof_path,
                    "manifestPath": current_manifest_path,
                    "mappedPaths": 1135,
                    "manifestUnresolvedPaths": 0,
                    "postRelinkUnresolvedFiles": 0,
                    "strictDependencyRenderSafe": True,
                    "projectWideStrictDependencyRenderSafe": True,
                    "projectWideUnresolvedFiles": 0,
                    "dependencyReferences": 3659,
                    "projectWidePictureReferences": 3658,
                    "take": "Main",
                    "frame": 168,
                    "project": current_project,
                }
                link_status = dict(link_status)
                link_status.update(
                    {
                        "status": "project_wide_strict_linked",
                        "label": "Project-wide fully linked",
                        "detail": (
                            "1,135 exact mappings · 3,658 project-wide "
                            "picture references · 0 unresolved files after "
                            "save and reopen"
                        ),
                        "projectPath": current_project,
                        "dependencyReferences": 3659,
                        "linkedReferences": 3658,
                        "missingReferences": 0,
                        "renderCriticalMissingReferences": 0,
                        "renderCriticalMissingFiles": 0,
                        "renderCriticalUnresolvedFiles": 0,
                        "missingExamples": [],
                        "dependencyLabel": (
                            "3,658 / 3,658 project-wide picture references "
                            "linked"
                        ),
                        "strictDependencyRenderSafe": True,
                        "strictLinked": True,
                        "exactCutAudit": exact_cut_audit,
                    }
                )
                cut["c4dLinkStatus"] = link_status
                verification.update(
                    {
                        "status": "match",
                        "label": (
                            "Fully linked + fresh full-color exact-source "
                            "match"
                        ),
                        "detail": (
                            "Fresh authored Redshift frame 168 matches the "
                            "retained same-frame production render at MAE "
                            "0.007027 with RGB correlations 0.985862, "
                            "0.996126, and 0.994234."
                        ),
                        "strictLinked": True,
                        "reviewedAt": "2026-08-01T12:08:45+07:00",
                        "cameraProof": current_batch_public_path,
                        "comparisonImage": current_comparison_path,
                        "renderReference": (
                            "/archive/as-finishing-historical-camera-proofs-"
                            "20260727/CUT-004/CUT-004__RS-Camera__v007__"
                            "f0168__historical-redshift.png"
                        ),
                        "dependencyAuditPath": current_proof_path,
                        "linkageAudit": link_status,
                        "blockers": [],
                        "remediation": [],
                    }
                )
                verification_checks = dict(
                    verification.get("checks") or {}
                )
                verification_checks.update(
                    {
                        "projectLinked": True,
                        "dependencyAudited": True,
                        "dependencyRenderSafe": True,
                        "proxyRenderSafe": True,
                        "cameraProofRendered": True,
                        "visualMatch": True,
                        "exactSourceProjectLinked": True,
                    }
                )
                verification["checks"] = verification_checks
                verification["materialCompatibilityAudit"] = {
                    "status": "rendered_match",
                    "outputPath": current_batch_public_path,
                    "publicPath": current_batch_public_path,
                    "resultPath": current_result_path,
                    "fullColor": True,
                    "fullColorProof": True,
                    "freshAuditRender": True,
                    "strictDependencyRenderSafe": True,
                    "unresolvedPictureFiles": 0,
                    "runtimeDetail": (
                        "Fresh normal Cinema batch render from the saved and "
                        "reopened exact-source recovery. No exposure or "
                        "display calibration was applied. The old +1 EV "
                        "workaround is superseded because its darkness came "
                        "from the earlier incomplete recovery copy."
                    ),
                }
                existing_linkage = {
                    "authoritativeForCurrentRecovery": True,
                    "authority": (
                        "Saved and reopened project-wide exact-source "
                        "dependency audit"
                    ),
                    "status": "project_wide_strict_linked",
                    "savedReopenVerified": True,
                    "mappedPaths": 1135,
                    "manifestPath": current_manifest_path,
                    "currentPathIdentityConfirmed": True,
                    "sourceEraProxyIdentityConfirmed": True,
                    "dependencyReferences": 3659,
                    "linkedReferences": 3658,
                    "missingReferences": 0,
                    "renderCriticalMissingReferences": 0,
                    "renderCriticalMissingFiles": 0,
                    "strictDependencyRenderSafe": True,
                    "projectWideStrictDependencyRenderSafe": True,
                    "projectWideUnresolvedFiles": 0,
                    "missingExactFiles": [],
                    "auditPath": current_reopen_path,
                    "auditProject": current_project,
                    "auditTake": "Main",
                    "auditFrame": 168,
                    "activeProofFrame": 168,
                    "scope": "active_project_take_and_frame",
                    "matchesActiveProject": True,
                    "matchesActiveFrame": True,
                }
                active_project = current_project
                active_frame = 168
                authoritative_current_recovery = True
                current_mainframe_audit_path = current_reopen_path
                current_mainframe_audit_selected = False
            if cut_id == "CUT-005":
                current_project = (
                    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                    "Absolutely/SG/C4D/_codex_mainframe_recovery_20260730/"
                    "1C_1E_A_Teardrop_Transition_v008_codex_mainframe_"
                    "exact_donor-materials_ev-plus0p15_20260731.c4d"
                )
                current_batch_public_path = (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-005/batch-denoiser-donor-materials-"
                    "ev-plus0p15-480/CUT-005-mainframe-exact-donor-"
                    "materials-ev-plus0p15_0230.png"
                )
                current_result_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-005-mainframe-exact-donor-materials-"
                    "ev-plus0p15-saved-copy-result.json"
                )
                render_result_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-005-mainframe-exact-donor-materials-"
                    "ev-plus0p15-480-result.json"
                )
                comparison_result_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-005-mainframe-exact-donor-materials-"
                    "ev-plus0p15-vs-historical-comparison.json"
                )
                comparison_public_path = (
                    "/archive/as-finishing-historical-camera-proofs-"
                    "20260727/CUT-005/CUT-005__RS-Camera__v008__"
                    "f0230__historical-redshift.png"
                )
                exact_cut_audit = {
                    "authority": (
                        "Active-frame strict dependency audit after exact "
                        "same-shot source-authored material transplant and "
                        "camera-only exposure calibration"
                    ),
                    "verificationPath": current_result_path,
                    "rawAuditPath": current_result_path,
                    "manifestPath": (
                        "data/c4d-mainframe-recovery-20260730/"
                        "CUT-005-source-authored-sibling-node-relink-"
                        "manifest.json"
                    ),
                    "mappedPaths": 115,
                    "manifestUnresolvedPaths": 0,
                    "postRelinkUnresolvedFiles": 0,
                    "postRelinkUnresolvedReferences": 0,
                    "strictDependencyRenderSafe": True,
                    "projectWideStrictDependencyRenderSafe": False,
                    "projectWideUnresolvedFiles": 1124,
                    "take": "Main",
                    "frame": 230,
                    "project": current_project,
                }
                link_status = dict(link_status)
                link_status.update(
                    {
                        "status": (
                            "active_frame_strict_linked_with_"
                            "dormant_project_residue"
                        ),
                        "label": (
                            "Frame 230 fully linked · dormant project "
                            "residue retained"
                        ),
                        "detail": (
                            "3,408 dependencies evaluated · 0 "
                            "render-critical unresolved files at Main / "
                            "frame 230 · 115 exact material relink mappings "
                            "· 1,124 disabled dormant project files remain"
                        ),
                        "projectPath": current_project,
                        "projectName": Path(current_project).name,
                        "take": "Main",
                        "frame": 230,
                        "dependencyReferences": 3408,
                        "linkedReferences": 2283,
                        "missingReferences": 1125,
                        "renderCriticalMissingReferences": 0,
                        "renderCriticalMissingFiles": 0,
                        "renderCriticalUnresolvedFiles": 0,
                        "missingExamples": [
                            {
                                "filename": (
                                    "Teacup_V1_Proxy_01_0414.rs through "
                                    "Teacup_V1_Proxy_01_1533.rs"
                                ),
                                "renderCritical": False,
                                "activeFrame": False,
                            },
                            {
                                "filename": (
                                    "four dormant source texture identities"
                                ),
                                "renderCritical": False,
                                "activeFrame": False,
                            },
                        ],
                        "dependencyLabel": (
                            "Active frame safe · dormant residue remains"
                        ),
                        "strictDependencyRenderSafe": True,
                        "strictLinked": True,
                        "projectWideStrictDependencyRenderSafe": False,
                        "exactCutAudit": exact_cut_audit,
                    }
                )
                cut["c4dLinkStatus"] = link_status

                for node in c4d_nodes:
                    node["sourceApplicationPrimary"] = False
                current_c4d_node = next(
                    (
                        node
                        for node in lineage
                        if node.get("kind") == "cinema4d"
                        and node_project(node) == current_project
                    ),
                    None,
                )
                if current_c4d_node is None:
                    current_c4d_node = {
                        "kind": "cinema4d",
                        "label": Path(current_project).name,
                    }
                    lineage.append(current_c4d_node)
                current_c4d_node.update(
                    {
                        "detail": (
                            "Canonical Cut 5 frame-230 recovery copy · "
                            "exact target geometry, animation, Main, "
                            "Denoiser and RS Camera · source-authored v008 "
                            "material graphs · +0.15 EV camera-only current-"
                            "runtime calibration"
                        ),
                        "path": current_project,
                        "projectPath": current_project,
                        "evidence": "confirmed",
                        "sourceApplicationPrimary": True,
                        "canonical": True,
                    }
                )

                for node in lineage:
                    if node.get("kind") == "camera_proof":
                        node["primaryRecoveryProof"] = False
                active_proof = next(
                    (
                        node
                        for node in lineage
                        if node.get("kind") == "camera_proof"
                        and node.get("comparisonImage")
                        == current_batch_public_path
                    ),
                    None,
                )
                if active_proof is None:
                    active_proof = {"kind": "camera_proof"}
                    lineage.append(active_proof)
                    camera_nodes_added += 1
                active_proof.update(
                    {
                        "label": (
                            "Fresh full-color Redshift match · RS Camera · "
                            "frame 230"
                        ),
                        "detail": (
                            "Fresh Cinema 4D 2026.1.4 Redshift render from "
                            "the active-frame-strict recovery. Compared "
                            "directly with the retained production frame: "
                            "mean absolute error 0.0161 and RGB correlations "
                            "0.958–0.980."
                        ),
                        "path": current_project,
                        "projectPath": current_project,
                        "comparisonImage": current_batch_public_path,
                        "confirmationMethod": (
                            "Exact same-shot source recovery plus fresh "
                            "Redshift render and numeric 1:1 comparison "
                            f"recorded in {comparison_result_path}"
                        ),
                        "evidence": "confirmed",
                        "proofStatus": "rendered_match",
                        "targetFrame": 230,
                        "cameraTake": "Main",
                        "cameraRenderData": "Denoiser",
                        "cameraObjectPath": (
                            "Camera_Drop_Cup/Camera/RS Camera"
                        ),
                        "recoveryProof": True,
                        "primaryRecoveryProof": True,
                        "redshiftProof": True,
                        "fullColorProof": True,
                        "fullColorRender": True,
                        "freshAuditRender": True,
                        "productionSourceReference": False,
                        "historicalProductionReference": False,
                        "strictLinked": True,
                        "projectWideStrictLinked": False,
                        "visualVerificationStatus": "rendered_match",
                        "resultPath": render_result_path,
                    }
                )
                active_project = current_project
                active_frame = 230

                verification.update(
                    {
                        "status": "rendered_match",
                        "label": (
                            "Fresh full-color Cut 5 recreation · "
                            "0.958–0.980 RGB correlation"
                        ),
                        "detail": (
                            "The exact target geometry, animation, Main, "
                            "Denoiser, RS Camera, and frame 230 now render "
                            "with the verified same-shot source-authored "
                            "material graphs. Character, hair, wardrobe, "
                            "teacup, ocean, palette and lighting match the "
                            "retained production frame."
                        ),
                        "strictLinked": True,
                        "projectWideStrictLinked": False,
                        "reviewedAt": now_iso(),
                        "authority": (
                            "Fresh Cinema 4D 2026.1.4 Redshift render from "
                            "the active-frame-strict saved recovery, "
                            "same-shot material donor identity, frame-230 "
                            "dependency audit and direct numeric comparison "
                            "with the retained production frame"
                        ),
                        "elements": {
                            "location": "match",
                            "camera": "match",
                            "character": "match",
                            "hair": "match",
                            "wardrobe": "match",
                            "teacup": "match",
                            "ocean": "match",
                            "materials": "match",
                            "lighting": "match",
                        },
                        "notes": (
                            "Fresh render and retained production reference "
                            "have mean absolute error 0.0161, RMSE 0.0347, "
                            "and per-channel correlations of 0.9576, 0.9802 "
                            "and 0.9706. The project-wide dormant proxy "
                            "sequence remains separately unresolved."
                        ),
                        "blockers": [],
                        "remediation": [
                            (
                                "Retrieve the exact dormant "
                                "Teacup_V1_Proxy_01_0414.rs through "
                                "Teacup_V1_Proxy_01_1533.rs sequence and four "
                                "unused source texture identities from "
                                "JDC/Mainframe before declaring the entire "
                                "project project-wide strict."
                            )
                        ],
                        "checks": {
                            **(verification.get("checks") or {}),
                            "projectLinked": True,
                            "dependencyAudited": True,
                            "dependencyRenderSafe": True,
                            "proxyRenderSafe": True,
                            "cameraProofRendered": True,
                            "cameraProofMatched": True,
                            "visualMatch": True,
                            "exactSourceProjectLinked": True,
                            "projectWideDependencyRenderSafe": False,
                        },
                        "cameraProof": current_batch_public_path,
                        "cameraName": "RS Camera",
                        "comparisonImage": comparison_public_path,
                        "dependencyAuditPath": current_result_path,
                        "materialCompatibilityAudit": {
                            "status": (
                                "fresh_full_color_source_authored_material_"
                                "graph_match_active_frame_strict"
                            ),
                            "outputPath": current_batch_public_path,
                            "publicPath": current_batch_public_path,
                            "runtimeDetail": (
                                "Fresh full-color Redshift render from the "
                                "saved recovery copy. The target contributes "
                                "geometry, animation, Main, Denoiser, "
                                "RS Camera and frame 230; the same-shot v008 "
                                "sibling contributes only source-authored "
                                "material graphs. All 45 materials and 40 "
                                "assignments verify. The current macOS "
                                "runtime uses a documented +0.15 EV camera-"
                                "only calibration."
                            ),
                        },
                        "recoveryPrescription": (
                            "Retain the exact target, v008 material donor, "
                            "relink manifest, calibrated saved recovery, "
                            "render log, fresh proof and comparison report "
                            "together. Reopen with Cinema 4D 2026.1.4, select "
                            "Main / Denoiser / Camera_Drop_Cup/Camera/"
                            "RS Camera / frame 230, and require zero active-"
                            "frame render-critical unresolved files. "
                            "Retrieve the dormant proxy sequence and four "
                            "texture identities from JDC/Mainframe for "
                            "project-wide closure."
                        ),
                        "agentReadyChecklist": [
                            (
                                "Open the dated +0.15 EV donor-materials "
                                "recovery read-only and preserve both source "
                                "projects."
                            ),
                            (
                                "Select Main, Denoiser, "
                                "Camera_Drop_Cup/Camera/RS Camera and frame "
                                "230."
                            ),
                            (
                                "Require the active-frame audit to report "
                                "3,408 evaluated references and zero "
                                "render-critical unresolved files."
                            ),
                            (
                                "Compare the fresh render to the retained "
                                "production frame using "
                                f"{comparison_result_path}."
                            ),
                            (
                                "Do not report project-wide strict closure "
                                "until the 1,124 dormant files are recovered."
                            ),
                        ],
                    }
                )
                link_status.update(
                    {
                        "visualReview": {
                            "status": "rendered_match",
                            "elements": dict(
                                verification.get("elements") or {}
                            ),
                            "notes": verification.get("notes"),
                        },
                        "materialCompatibilityAudit": dict(
                            verification.get("materialCompatibilityAudit")
                            or {}
                        ),
                        "recoveryPrescription": verification.get(
                            "recoveryPrescription"
                        ),
                        "agentReadyChecklist": list(
                            verification.get("agentReadyChecklist") or []
                        ),
                    }
                )
                cut["c4dLinkStatus"] = link_status
                existing_linkage = {
                    "authoritativeForCurrentRecovery": True,
                    "authority": (
                        "Saved/reopened active-frame strict dependency audit "
                        "after exact same-shot source-authored material "
                        "transplant and exposure calibration"
                    ),
                    "status": (
                        "active_frame_strict_linked_with_"
                        "dormant_project_residue"
                    ),
                    "savedReopenVerified": True,
                    "mappedPaths": 115,
                    "manifestPath": (
                        "data/c4d-mainframe-recovery-20260730/"
                        "CUT-005-source-authored-sibling-node-relink-"
                        "manifest.json"
                    ),
                    "currentPathIdentityConfirmed": True,
                    "sourceEraProxyIdentityConfirmed": True,
                    "dependencyReferences": 3408,
                    "linkedReferences": 2283,
                    "missingReferences": 1125,
                    "renderCriticalMissingReferences": 0,
                    "renderCriticalMissingFiles": 0,
                    "strictDependencyRenderSafe": True,
                    "projectWideStrictDependencyRenderSafe": False,
                    "projectWideUnresolvedFiles": 1124,
                    "missingExactFiles": [],
                    "auditPath": current_result_path,
                    "auditProject": current_project,
                    "auditTake": "Main",
                    "auditFrame": 230,
                    "activeProofFrame": 230,
                    "scope": "active_project_take_and_frame",
                    "matchesActiveProject": True,
                    "matchesActiveFrame": True,
                }
                authoritative_current_recovery = True
                current_mainframe_audit_path = current_result_path
                current_mainframe_audit_selected = False
                source_camera_node = next(
                    (
                        node
                        for node in lineage
                        if node.get("kind") == "camera"
                        and node.get("sourceCameraLineage") is True
                    ),
                    None,
                )
                if source_camera_node is None:
                    source_camera_node = {"kind": "camera"}
                    lineage.append(source_camera_node)
                    camera_nodes_added += 1
                source_camera_node.update(
                    {
                        "label": "RS Camera",
                        "detail": (
                            "Distinct source-camera identity for Main / "
                            "Denoiser at frame 230, verified by the fresh "
                            "full-color production-material match."
                        ),
                        "path": current_project,
                        "projectPath": current_project,
                        "comparisonImage": current_batch_public_path,
                        "evidence": "confirmed",
                        "confirmationMethod": (
                            "fresh full-color Redshift match plus current "
                            "active-frame strict dependency audit"
                        ),
                        "targetFrame": 230,
                        "cameraTake": "Main",
                        "cameraRenderData": "Denoiser",
                        "cameraObjectPath": (
                            "Camera_Drop_Cup/Camera/RS Camera"
                        ),
                        "sourceCameraLineage": True,
                    }
                )
            if cut_id == "CUT-006":
                current_project = (
                    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                    "Absolutely/SG/C4D/_codex_mainframe_recovery_20260730/"
                    "1C_1E_A_CloseUps_v012_codex_mainframe_exact_"
                    "donor-materials_20260731.c4d"
                )
                current_batch_public_path = (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-006/batch-cu-final-donor-materials-480/"
                    "CUT-006-mainframe-exact-donor-materials0166.png"
                )
                current_result_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-006-mainframe-exact-donor-materials-"
                    "saved-copy-result.json"
                )
                comparison_result_path = (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-006-mainframe-exact-donor-materials-vs-"
                    "retained-final-f0166.json"
                )
                comparison_public_path = (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-006/batch-cu-final-donor-materials-480/"
                    "CUT-006-retained-final-f0166-left-vs-mainframe-"
                    "exact-donor-materials-right.jpg"
                )
                exact_cut_audit = {
                    "authority": (
                        "Project-wide strict dependency audit after exact "
                        "same-shot source-authored material transplant"
                    ),
                    "verificationPath": current_result_path,
                    "rawAuditPath": current_result_path,
                    "manifestPath": (
                        "data/c4d-mainframe-recovery-20260730/"
                        "CUT-006-source-authored-sibling-node-relink-"
                        "manifest.json"
                    ),
                    "mappedPaths": 104,
                    "manifestUnresolvedPaths": 0,
                    "postRelinkUnresolvedFiles": 0,
                    "postRelinkUnresolvedReferences": 0,
                    "strictDependencyRenderSafe": True,
                    "projectWideStrictDependencyRenderSafe": True,
                    "projectWideUnresolvedFiles": 0,
                    "take": "CU_01",
                    "frame": 166,
                    "project": current_project,
                }
                link_status = dict(link_status)
                link_status.update(
                    {
                        "status": "fully_linked_confirmed",
                        "label": "Project-wide fully linked",
                        "detail": (
                            "2,379 / 2,379 picture dependencies linked · "
                            "104 exact relink mappings · 30 same-shot "
                            "source-authored materials · 46 target texture "
                            "assignments preserved · 0 unresolved files"
                        ),
                        "projectPath": current_project,
                        "projectName": Path(current_project).name,
                        "take": "CU_01",
                        "frame": 166,
                        "dependencyReferences": 2379,
                        "linkedReferences": 2379,
                        "missingReferences": 0,
                        "renderCriticalMissingReferences": 0,
                        "renderCriticalMissingFiles": 0,
                        "renderCriticalUnresolvedFiles": 0,
                        "missingExamples": [],
                        "dependencyLabel": "All dependencies linked",
                        "strictDependencyRenderSafe": True,
                        "strictLinked": True,
                        "exactCutAudit": exact_cut_audit,
                    }
                )
                cut["c4dLinkStatus"] = link_status

                for node in c4d_nodes:
                    node["sourceApplicationPrimary"] = False
                current_c4d_node = next(
                    (
                        node
                        for node in lineage
                        if node.get("kind") == "cinema4d"
                        and node_project(node) == current_project
                    ),
                    None,
                )
                if current_c4d_node is None:
                    current_c4d_node = {
                        "kind": "cinema4d",
                        "label": Path(current_project).name,
                    }
                    lineage.append(current_c4d_node)
                current_c4d_node.update(
                    {
                        "detail": (
                            "Canonical Cut 6 recovery copy · exact target "
                            "geometry, animation, CU_01, CU_Final, and "
                            "RS Camera.6 · source-authored v012 AS material "
                            "graphs paired by index, name, and type"
                        ),
                        "path": current_project,
                        "projectPath": current_project,
                        "evidence": "confirmed",
                        "sourceApplicationPrimary": True,
                        "canonical": True,
                    }
                )

                for node in lineage:
                    if node.get("kind") == "camera_proof":
                        node["primaryRecoveryProof"] = False
                active_proof = next(
                    (
                        node
                        for node in lineage
                        if node.get("kind") == "camera_proof"
                        and node.get("comparisonImage")
                        == current_batch_public_path
                    ),
                    None,
                )
                if active_proof is None:
                    active_proof = {"kind": "camera_proof"}
                    lineage.append(active_proof)
                    camera_nodes_added += 1
                active_proof.update(
                    {
                        "label": (
                            "Fresh full-color Redshift match · RS Camera.6 "
                            "· frame 166"
                        ),
                        "detail": (
                            "Fresh Cinema 4D 2026.1.4 Redshift render from "
                            "the project-wide fully linked recovery copy. "
                            "Compared directly with the retained production "
                            "frame: mean absolute error 0.0163 and RGB "
                            "correlations 0.991–0.996."
                        ),
                        "path": current_project,
                        "projectPath": current_project,
                        "comparisonImage": current_batch_public_path,
                        "confirmationMethod": (
                            "Exact same-shot source recovery plus fresh "
                            "Redshift render and numeric 1:1 comparison "
                            f"recorded in {comparison_result_path}"
                        ),
                        "evidence": "confirmed",
                        "proofStatus": "rendered_match",
                        "targetFrame": 166,
                        "cameraTake": "CU_01",
                        "cameraRenderData": "CU_Final",
                        "cameraObjectPath": "RS Camera.6",
                        "recoveryProof": True,
                        "primaryRecoveryProof": True,
                        "redshiftProof": True,
                        "fullColorProof": True,
                        "fullColorRender": True,
                        "freshAuditRender": True,
                        "productionSourceReference": False,
                        "historicalProductionReference": False,
                        "strictLinked": True,
                        "visualVerificationStatus": "rendered_match",
                        "resultPath": (
                            "data/c4d-mainframe-recovery-20260730/"
                            "CUT-006-mainframe-exact-donor-materials-"
                            "480-result.json"
                        ),
                    }
                )
                active_project = current_project
                active_frame = 166

                verification.update(
                    {
                        "status": "rendered_match",
                        "label": (
                            "Fresh full-color Cut 6 recreation · "
                            "0.991–0.996 RGB correlation"
                        ),
                        "detail": (
                            "The exact target geometry, animation, CU_01, "
                            "CU_Final, RS Camera.6, and frame 166 now render "
                            "with the verified same-shot source-authored "
                            "material graphs. Character, hair, wardrobe, "
                            "teacup, ocean, palette, and lighting match the "
                            "retained production frame."
                        ),
                        "strictLinked": True,
                        "reviewedAt": now_iso(),
                        "authority": (
                            "Fresh Cinema 4D 2026.1.4 Redshift render from "
                            "the strict saved recovery, same-shot material "
                            "donor identity, project-wide dependency audit, "
                            "and direct numeric comparison with the retained "
                            "production frame"
                        ),
                        "elements": {
                            "location": "match",
                            "camera": "match",
                            "character": "match",
                            "hair": "match",
                            "wardrobe": "match",
                            "teacup": "match",
                            "ocean": "match",
                            "materials": "match",
                            "lighting": "match",
                        },
                        "notes": (
                            "Fresh render and retained production reference "
                            "have mean absolute error 0.0163, RMSE 0.0275, "
                            "and per-channel correlations of 0.9908, 0.9965, "
                            "and 0.9928."
                        ),
                        "blockers": [],
                        "remediation": [],
                        "checks": {
                            **(verification.get("checks") or {}),
                            "projectLinked": True,
                            "dependencyAudited": True,
                            "dependencyRenderSafe": True,
                            "proxyRenderSafe": True,
                            "cameraProofRendered": True,
                            "cameraProofMatched": True,
                            "visualMatch": True,
                            "exactSourceProjectLinked": True,
                        },
                        "cameraProof": current_batch_public_path,
                        "cameraName": "RS Camera.6",
                        "comparisonImage": comparison_public_path,
                        "dependencyAuditPath": current_result_path,
                        "materialCompatibilityAudit": {
                            "status": (
                                "fresh_full_color_source_authored_material_"
                                "graph_match"
                            ),
                            "outputPath": current_batch_public_path,
                            "publicPath": current_batch_public_path,
                            "runtimeDetail": (
                                "Fresh full-color Redshift render from the "
                                "strict saved recovery copy. The target "
                                "contributes geometry, animation, take, "
                                "render data, RS Camera.6 and frame 166; the "
                                "same-shot v012 AS sibling contributes only "
                                "its source-authored material graphs. All 30 "
                                "materials and 46 assignments verify, and "
                                "2,379 / 2,379 picture references resolve."
                            ),
                        },
                        "recoveryPrescription": (
                            "Retain the exact target, v012 AS material donor, "
                            "relink manifest, strict saved recovery copy, "
                            "render log, fresh proof, and comparison report "
                            "together. Reopen with Cinema 4D 2026.1.4, select "
                            "CU_01 / CU_Final / RS Camera.6 / frame 166, and "
                            "require 2,379 / 2,379 dependencies before render."
                        ),
                        "agentReadyChecklist": [
                            (
                                "Open the dated donor-materials recovery copy "
                                "read-only and preserve both source projects."
                            ),
                            (
                                "Select CU_01, CU_Final, RS Camera.6, and "
                                "frame 166."
                            ),
                            (
                                "Require the project-wide strict dependency "
                                "audit to report 2,379 / 2,379 linked."
                            ),
                            (
                                "Compare the fresh render to the retained "
                                "production frame using "
                                f"{comparison_result_path}."
                            ),
                        ],
                    }
                )
                link_status.update(
                    {
                        "visualReview": {
                            "status": "rendered_match",
                            "elements": dict(
                                verification.get("elements") or {}
                            ),
                            "notes": verification.get("notes"),
                        },
                        "materialCompatibilityAudit": dict(
                            verification.get("materialCompatibilityAudit")
                            or {}
                        ),
                        "recoveryPrescription": verification.get(
                            "recoveryPrescription"
                        ),
                        "agentReadyChecklist": list(
                            verification.get("agentReadyChecklist") or []
                        ),
                    }
                )
                cut["c4dLinkStatus"] = link_status
                existing_linkage = {
                    "authoritativeForCurrentRecovery": True,
                    "authority": (
                        "Saved/reopened project-wide strict dependency audit "
                        "after exact same-shot source-authored material "
                        "transplant"
                    ),
                    "status": "fully_linked_confirmed",
                    "savedReopenVerified": True,
                    "mappedPaths": 104,
                    "manifestPath": (
                        "data/c4d-mainframe-recovery-20260730/"
                        "CUT-006-source-authored-sibling-node-relink-"
                        "manifest.json"
                    ),
                    "currentPathIdentityConfirmed": True,
                    "sourceEraProxyIdentityConfirmed": True,
                    "dependencyReferences": 2379,
                    "linkedReferences": 2379,
                    "missingReferences": 0,
                    "renderCriticalMissingReferences": 0,
                    "renderCriticalMissingFiles": 0,
                    "strictDependencyRenderSafe": True,
                    "missingExactFiles": [],
                    "auditPath": current_result_path,
                    "auditProject": current_project,
                    "auditTake": "CU_01",
                    "auditFrame": 166,
                    "activeProofFrame": 166,
                    "scope": "active_project_take_and_frame",
                    "matchesActiveProject": True,
                    "matchesActiveFrame": True,
                }
                authoritative_current_recovery = True
                current_mainframe_audit_path = current_result_path
                current_mainframe_audit_selected = False
                for node in lineage:
                    if node.get("kind") != "camera":
                        continue
                    node.update(
                        {
                            "label": "RS Camera.6",
                            "detail": (
                                "Distinct source-camera identity for CU_01 / "
                                "CU_Final at frame 166, verified by the fresh "
                                "full-color production-material match."
                            ),
                            "path": current_project,
                            "projectPath": current_project,
                            "comparisonImage": current_batch_public_path,
                            "evidence": "confirmed",
                            "confirmationMethod": (
                                "fresh full-color Redshift match plus current "
                                "strict dependency audit"
                            ),
                            "targetFrame": 166,
                            "cameraTake": "CU_01",
                            "sourceCameraLineage": True,
                        }
                    )
        current_na_recoveries = {
            "CUT-056": {
                "take": "InsideRip",
                "renderData": "InsideRip",
                "camera": "Inside_Rip",
                "frame": 1190,
                "ev": 1.5,
                "rmse": 0.06218285486102104,
                "image": (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-056/CUT-056-f1190-saved-exact191-ocio-linear-"
                    "srgb-aces1-sdr-ev1p5-480.png"
                ),
                "result": (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-056-f1190-saved-exact191-render-buffer-"
                    "480-result.json"
                ),
                "detail": (
                    "authored character, long hair, room, InsideRip take, "
                    "and Inside_Rip camera"
                ),
            },
            "CUT-057": {
                "take": "RipReveal",
                "renderData": "RipReveal",
                "camera": "RipReveal",
                "frame": 1350,
                "ev": 1.25,
                "rmse": 0.048534393310546875,
                "image": (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-057/CUT-057-f1350-saved-exact191-ocio-linear-"
                    "srgb-aces1-sdr-ev1p25-480.png"
                ),
                "result": (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-057-f1350-saved-exact191-render-buffer-"
                    "480-result.json"
                ),
                "detail": (
                    "authored character, face, wardrobe, long hair, room, "
                    "RipReveal take, and camera"
                ),
            },
            "CUT-058": {
                "take": "WideRip",
                "renderData": "WideRip",
                "camera": "WideRip",
                "frame": 1376,
                "ev": 1.5,
                "rmse": 0.049713049083948135,
                "image": (
                    "/archive/redshift-mainframe-recovery-20260730/"
                    "CUT-058/CUT-058-f1376-saved-exact191-ocio-linear-"
                    "srgb-aces1-sdr-ev1p5-480.png"
                ),
                "result": (
                    "data/c4d-mainframe-recovery-20260730/"
                    "CUT-058-f1376-saved-exact191-render-buffer-"
                    "480-result.json"
                ),
                "detail": (
                    "authored character, pose, long hair, room geometry, "
                    "WideRip take, and camera"
                ),
            },
        }
        if cut_id in current_na_recoveries:
            recovery = current_na_recoveries[cut_id]
            current_project = (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/AS/0 Finishing/02 Projects/04 NA/"
                "04_NA_SG_tear_v002_codex_073026_exact191-relinked.c4d"
            )
            current_batch_public_path = str(recovery["image"])
            current_result_path = str(recovery["result"])
            active_frame = int(recovery["frame"])
            active_project = current_project
            exact_cut_audit = {
                "authority": (
                    "Saved-and-reopened current recovery dependency audit "
                    "after the complete byte-verified 15-file Mainframe "
                    "recovery"
                ),
                "verificationPath": current_result_path,
                "rawAuditPath": current_result_path,
                "mappedPaths": 191,
                "manifestUnresolvedPaths": 0,
                "postRelinkUnresolvedFiles": 0,
                "postRelinkUnresolvedReferences": 0,
                "strictDependencyRenderSafe": True,
                "projectWideStrictDependencyRenderSafe": True,
                "projectWideUnresolvedFiles": 0,
                "take": recovery["take"],
                "frame": active_frame,
                "project": current_project,
            }
            link_status = dict(link_status)
            link_status.update(
                {
                    "status": "fully_linked_confirmed",
                    "label": "342 / 342 current picture references linked",
                    "detail": (
                        "The complete 15-file Mainframe recovery set is "
                        "local and byte-verified. The saved and reopened "
                        f"{recovery['take']} recovery resolves every current "
                        "picture reference with zero render-critical "
                        "unresolved files."
                    ),
                    "projectPath": current_project,
                    "projectName": Path(current_project).name,
                    "take": recovery["take"],
                    "frame": active_frame,
                    "dependencyReferences": 342,
                    "linkedReferences": 342,
                    "missingReferences": 0,
                    "renderCriticalMissingReferences": 0,
                    "renderCriticalMissingFiles": 0,
                    "renderCriticalUnresolvedFiles": 0,
                    "missingExamples": [],
                    "dependencyLabel": "Current saved recovery fully linked",
                    "strictDependencyRenderSafe": True,
                    "strictLinked": True,
                    "exactCutAudit": exact_cut_audit,
                }
            )

            for node in c4d_nodes:
                node["sourceApplicationPrimary"] = False
            current_c4d_node = next(
                (
                    node
                    for node in lineage
                    if node.get("kind") == "cinema4d"
                    and node_project(node) == current_project
                ),
                None,
            )
            if current_c4d_node is None:
                current_c4d_node = {
                    "kind": "cinema4d",
                    "label": Path(current_project).name,
                }
                lineage.append(current_c4d_node)
            current_c4d_node.update(
                {
                    "detail": (
                        f"Current {cut_id} saved recovery · 191 exact "
                        "mappings · 342 / 342 picture references linked · "
                        f"{recovery['take']} / {recovery['renderData']} / "
                        f"{recovery['camera']} / frame {active_frame}"
                    ),
                    "path": current_project,
                    "projectPath": current_project,
                    "evidence": "confirmed",
                    "sourceApplicationPrimary": True,
                    "canonical": True,
                    "dependencyAuditPath": current_result_path,
                    "visualVerificationStatus": "partial",
                }
            )

            for node in lineage:
                if node.get("kind") == "camera_proof":
                    node["primaryRecoveryProof"] = False
            active_proof = next(
                (
                    node
                    for node in lineage
                    if node.get("kind") == "camera_proof"
                    and node.get("comparisonImage")
                    == current_batch_public_path
                ),
                None,
            )
            if active_proof is None:
                active_proof = {"kind": "camera_proof"}
                lineage.append(active_proof)
                camera_nodes_added += 1
            active_proof.update(
                {
                    "label": (
                        f"Fresh full-color Redshift process proof · "
                        f"{recovery['camera']} · frame {active_frame}"
                    ),
                    "detail": (
                        f"Fresh saved-copy render preserving "
                        f"{recovery['detail']}. The measured "
                        f"sRGB / ACES 1.0 SDR-video display transform at "
                        f"+{recovery['ev']} EV removes the unusably dark "
                        "preview, but the remaining lighting/display "
                        "difference keeps this a yellow process match."
                    ),
                    "path": current_project,
                    "projectPath": current_project,
                    "comparisonImage": current_batch_public_path,
                    "confirmationMethod": (
                        "Fresh Redshift render from a saved-and-reopened "
                        "342 / 342 linked recovery plus direct canonical "
                        "frame comparison"
                    ),
                    "evidence": "confirmed",
                    "proofStatus": "rendered_partial_match",
                    "targetFrame": active_frame,
                    "cameraTake": recovery["take"],
                    "cameraRenderData": recovery["renderData"],
                    "cameraObjectPath": recovery["camera"],
                    "recoveryProof": True,
                    "primaryRecoveryProof": True,
                    "redshiftProof": True,
                    "fullColorProof": True,
                    "fullColorRender": True,
                    "freshAuditRender": True,
                    "productionSourceReference": False,
                    "historicalProductionReference": False,
                    "strictLinked": True,
                    "visualVerificationStatus": "partial",
                    "resultPath": current_result_path,
                }
            )

            verification.update(
                {
                    "status": "partial",
                    "label": (
                        "Fresh full-color current recovery · fully linked · "
                        "display match pending"
                    ),
                    "detail": (
                        f"The current saved recovery resolves 342 / 342 "
                        f"picture references and preserves "
                        f"{recovery['detail']}. Geometry, character, hair, "
                        "wardrobe, materials, take and camera are present; "
                        "only the current-runtime brightness/display match "
                        "remains incomplete."
                    ),
                    "strictLinked": False,
                    "reviewedAt": now_iso(),
                    "authority": (
                        "Fresh Cinema 4D 2026.1 Redshift render from the "
                        "saved-and-reopened exact Mainframe recovery"
                    ),
                    "elements": {
                        "location": "match",
                        "camera": "match",
                        "character": "match",
                        "hair": "match",
                        "wardrobe": "match",
                        "materials": "match",
                        "lighting": "partial",
                    },
                    "notes": (
                        f"Current-process RMSE is {recovery['rmse']:.4f}. "
                        "The calibrated color image is the preferred "
                        "preview; final exposure/OCIO equivalence to the "
                        "production TIFF is still pending."
                    ),
                    "blockers": ["display_pipeline_mismatch"],
                    "remediation": [
                        (
                            "Reproduce the source-era render display "
                            "pipeline or calibrate the current-runtime "
                            "Redshift camera/output transform against the "
                            "canonical production TIFF without changing "
                            "geometry, take, camera, materials, or caches."
                        )
                    ],
                    "checks": {
                        **(verification.get("checks") or {}),
                        "projectLinked": True,
                        "dependencyAudited": True,
                        "dependencyRenderSafe": True,
                        "proxyRenderSafe": True,
                        "cameraProofRendered": True,
                        "cameraProofMatched": True,
                        "visualMatch": False,
                        "exactSourceProjectLinked": True,
                    },
                    "cameraProof": current_batch_public_path,
                    "cameraName": recovery["camera"],
                    "dependencyAuditPath": current_result_path,
                    "materialCompatibilityAudit": {
                        "status": (
                            "fresh_full_color_strict_dependency_safe_"
                            "display_pipeline_mismatch"
                        ),
                        "outputPath": current_batch_public_path,
                        "publicPath": current_batch_public_path,
                        "resultPath": current_result_path,
                        "savedRecoveryProject": current_project,
                        "sourceProjectPreserved": True,
                        "fullColor": True,
                        "freshAuditRender": True,
                        "exactRenderDataClone": True,
                        "strictDependencyRenderSafe": True,
                        "dependencyReferences": 342,
                        "linkedReferences": 342,
                        "unresolvedPictureFiles": 0,
                        "measuredDisplayExposureEv": recovery["ev"],
                        "comparisonRmse": recovery["rmse"],
                        "runtimeDetail": (
                            "The complete 15-file Mainframe recovery set "
                            "is local and byte-verified. The current saved "
                            "recovery resolves 342 / 342 picture references. "
                            "The preferred image is a measured display-"
                            "calibrated full-color process proof; source-era "
                            "display equivalence remains pending."
                        ),
                    },
                    "recoveryPrescription": (
                        f"Retain the exact 15-file Mainframe receipt, the "
                        f"saved recovery project, frame-{active_frame} "
                        "result, and preferred color proof together. Reopen "
                        f"{recovery['take']} / {recovery['renderData']} / "
                        f"{recovery['camera']} / frame {active_frame}; "
                        "require 342 / 342 picture references before "
                        "calibrating only the render display pipeline."
                    ),
                    "agentReadyChecklist": [
                        (
                            "Open the exact191-relinked saved recovery "
                            "read-only; preserve the source project and all "
                            "earlier recovery copies."
                        ),
                        (
                            f"Select {recovery['take']}, "
                            f"{recovery['renderData']}, "
                            f"{recovery['camera']}, and frame "
                            f"{active_frame}."
                        ),
                        (
                            "Require the dependency audit to report "
                            "342 / 342 linked with zero unresolved picture "
                            "files."
                        ),
                        (
                            "Change only exposure/OCIO/display behavior "
                            "while comparing against the canonical "
                            "production TIFF."
                        ),
                    ],
                }
            )
            link_status.update(
                {
                    "visualReview": {
                        "status": "partial",
                        "elements": dict(
                            verification.get("elements") or {}
                        ),
                        "notes": verification.get("notes"),
                    },
                    "materialCompatibilityAudit": dict(
                        verification.get("materialCompatibilityAudit")
                        or {}
                    ),
                    "recoveryPrescription": verification.get(
                        "recoveryPrescription"
                    ),
                    "agentReadyChecklist": list(
                        verification.get("agentReadyChecklist") or []
                    ),
                }
            )
            cut["c4dLinkStatus"] = link_status
            existing_linkage = {
                "authoritativeForCurrentRecovery": True,
                "authority": (
                    "Saved-and-reopened project-wide strict dependency "
                    "audit after the complete byte-verified 15-file "
                    "Mainframe recovery"
                ),
                "status": "fully_linked_confirmed",
                "savedReopenVerified": True,
                "mappedPaths": 191,
                "currentPathIdentityConfirmed": True,
                "sourceEraProxyIdentityConfirmed": True,
                "dependencyReferences": 342,
                "linkedReferences": 342,
                "missingReferences": 0,
                "renderCriticalMissingReferences": 0,
                "renderCriticalMissingFiles": 0,
                "strictDependencyRenderSafe": True,
                "missingExactFiles": [],
                "auditPath": current_result_path,
                "auditProject": current_project,
                "auditTake": recovery["take"],
                "auditFrame": active_frame,
                "activeProofFrame": active_frame,
                "scope": "active_project_take_and_frame",
                "matchesActiveProject": True,
                "matchesActiveFrame": True,
            }
            authoritative_current_recovery = True
            current_mainframe_audit_path = current_result_path
            current_mainframe_audit_selected = False
            source_camera_node = next(
                (
                    node
                    for node in lineage
                    if node.get("kind") == "camera"
                    and node.get("sourceCameraLineage") is True
                ),
                None,
            )
            if source_camera_node is None:
                source_camera_node = {"kind": "camera"}
                lineage.append(source_camera_node)
                camera_nodes_added += 1
            source_camera_node.update(
                {
                    "label": recovery["camera"],
                    "detail": (
                        "Distinct source-camera identity for "
                        f"{recovery['take']} / {recovery['renderData']} at "
                        f"frame {active_frame}, verified by the fresh "
                        "full-color current recovery."
                    ),
                    "path": current_project,
                    "projectPath": current_project,
                    "comparisonImage": current_batch_public_path,
                    "evidence": "confirmed",
                    "confirmationMethod": (
                        "fresh full-color Redshift process proof plus "
                        "current 342 / 342 dependency audit"
                    ),
                    "targetFrame": active_frame,
                    "cameraTake": recovery["take"],
                    "cameraRenderData": recovery["renderData"],
                    "cameraObjectPath": recovery["camera"],
                    "sourceCameraLineage": True,
                }
            )
        if cut_id == "CUT-075":
            current_project = (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/AS/0 Finishing/02 Projects/06 IJDKYY/"
                "_codex_mainframe_batch3_exact_073026/"
                "6 A 1222 - Copy (2)_codex_072526_codex_mainframe_"
                "exact_073026_codex_mainframe_batch3_exact_073026.c4d"
            )
            current_dormant_audit_path = (
                "data/c4d-source-runtime-recovery-20260730/"
                "CUT-075-main-frame72-dormant-five-inputs-audit.json"
            )
            active_project = current_project
            active_frame = 72
            exact_cut_audit = {
                "authority": (
                    "Evaluated Main/frame-72 material ownership and object "
                    "render-mode audit after the exact Mainframe recovery"
                ),
                "verificationPath": current_dormant_audit_path,
                "rawAuditPath": current_dormant_audit_path,
                "mappedPaths": 0,
                "manifestUnresolvedPaths": 5,
                "postRelinkUnresolvedFiles": 0,
                "postRelinkUnresolvedReferences": 0,
                "strictDependencyRenderSafe": True,
                "projectWideStrictDependencyRenderSafe": False,
                "projectWideUnresolvedFiles": 5,
                "take": "Main",
                "frame": 72,
                "project": current_project,
            }
            link_status = dict(link_status)
            link_status.update(
                {
                    "status": (
                        "active_frame_strict_linked_with_"
                        "dormant_project_residue"
                    ),
                    "label": (
                        "Frame 72 fully linked · five render-off inputs "
                        "retained"
                    ),
                    "detail": (
                        "The exact recovered character, hair, cupboard, "
                        "camera and visible materials render at Main / frame "
                        "72 with zero active render-critical unresolved "
                        "files. Four source-era decor/mug texture identities "
                        "belong only to the render-off Dining room props "
                        "hierarchy; the fifth belongs to an unassigned carpet "
                        "material."
                    ),
                    "projectPath": current_project,
                    "projectName": Path(current_project).name,
                    "take": "Main",
                    "frame": 72,
                    "dependencyReferences": 1490,
                    "linkedReferences": 1485,
                    "missingReferences": 5,
                    "renderCriticalMissingReferences": 0,
                    "renderCriticalMissingFiles": 0,
                    "renderCriticalUnresolvedFiles": 0,
                    "dependencyLabel": (
                        "Active frame safe · five dormant source identities"
                    ),
                    "strictDependencyRenderSafe": True,
                    "strictLinked": True,
                    "projectWideStrictDependencyRenderSafe": False,
                    "exactCutAudit": exact_cut_audit,
                }
            )
            cut["c4dLinkStatus"] = link_status
            verification_checks = dict(
                verification.get("checks") or {}
            )
            verification_checks.update(
                {
                    "projectLinked": True,
                    "dependencyAudited": True,
                    "dependencyRenderSafe": True,
                    "proxyRenderSafe": True,
                    "cameraProofRendered": True,
                    "cameraProofMatched": True,
                    "exactSourceProjectLinked": True,
                    "projectWideDependencyRenderSafe": False,
                }
            )
            verification["checks"] = verification_checks
            verification["dependencyAuditPath"] = (
                current_dormant_audit_path
            )
            existing_linkage = {
                "authoritativeForCurrentRecovery": True,
                "authority": (
                    "Evaluated Main/frame-72 material ownership and object "
                    "render-mode audit after the exact Mainframe recovery"
                ),
                "status": (
                    "active_frame_strict_linked_with_"
                    "dormant_project_residue"
                ),
                "savedReopenVerified": True,
                "currentPathIdentityConfirmed": True,
                "sourceEraProxyIdentityConfirmed": True,
                "dependencyReferences": 1490,
                "linkedReferences": 1485,
                "missingReferences": 5,
                "renderCriticalMissingReferences": 0,
                "renderCriticalMissingFiles": 0,
                "strictDependencyRenderSafe": True,
                "projectWideStrictDependencyRenderSafe": False,
                "projectWideUnresolvedFiles": 5,
                "missingExactFiles": [],
                "dormantMissingExactFiles": list(
                    (
                        verification.get("materialCompatibilityAudit")
                        or {}
                    ).get("remainingAssetErrors")
                    or []
                ),
                "auditPath": current_dormant_audit_path,
                "auditProject": current_project,
                "auditTake": "Main",
                "auditFrame": 72,
                "activeProofFrame": 72,
                "scope": "active_project_take_and_frame",
                "matchesActiveProject": True,
                "matchesActiveFrame": True,
            }
            authoritative_current_recovery = True
            current_mainframe_audit_path = current_dormant_audit_path
            current_mainframe_audit_selected = False
        dependency_path = str(
            current_mainframe_audit_path
            if current_mainframe_audit_selected
            else verification.get("dependencyAuditPath")
            or exact_cut_audit.get("verificationPath")
            or existing_linkage.get("auditPath")
            or dependency_path_overrides.get(cut_id)
            or audit.get("_relativePath")
            or ""
        )
        if dependency_path:
            verification["dependencyAuditPath"] = dependency_path
            dependency_links += 1

        per_cut_audit_selected = bool(
            dependency_path and dependency_path == audit.get("_relativePath")
        )
        audit_project = normalized_project(
            (
                audit.get("project")
                or (audit.get("sourceProject") or {}).get("path")
            )
            if per_cut_audit_selected
            else existing_linkage.get("auditProject") or active_project
        )
        audit_frame = (
            audit.get("frame")
            if per_cut_audit_selected
            else existing_linkage.get("auditFrame")
            if existing_linkage.get("auditFrame") is not None
            else active_frame
        )
        audit_take = str(
            (
                audit.get("take")
                if per_cut_audit_selected
                else existing_linkage.get("auditTake")
            )
            or link_status.get("take")
            or (active_proof or {}).get("cameraTake")
            or "Main"
        )
        same_project = bool(
            not audit_project
            or not active_project
            or audit_project == active_project
        )
        same_frame = bool(
            audit_frame is None
            or active_frame is None
            or int(audit_frame) == int(active_frame)
        )
        if same_project and not same_frame:
            scoped_frame_differences += 1
        scope = (
            "active_project_take_and_frame"
            if same_project and same_frame
            else "active_project_take_different_frame"
            if same_project
            else "supporting_project_only"
        )
        if authoritative_current_recovery:
            scope = str(
                existing_linkage.get("scope")
                or "current_path_recovery_copy_only"
            )
            same_project = bool(
                existing_linkage.get("matchesActiveProject")
            )
            same_frame = bool(
                existing_linkage.get("matchesActiveFrame")
            )
        if dependency_path_overrides.get(cut_id) == dependency_path:
            scope = "active_project_take_render_graph"
            same_project = True
            same_frame = True

        missing_exact_files: list[str] = []
        if authoritative_current_recovery:
            for item in existing_linkage.get("missingExactFiles") or []:
                value = str(item or "")
                if value and value not in missing_exact_files:
                    missing_exact_files.append(value)
        elif not (
            per_cut_audit_selected
            and audit.get("strictDependencyRenderSafe") is True
        ):
            for item in link_status.get("missingExamples") or []:
                if isinstance(item, dict):
                    if not item.get("renderCritical"):
                        continue
                    value = str(item.get("filename") or "")
                else:
                    value = str(item or "")
                if value and value not in missing_exact_files:
                    missing_exact_files.append(value)
        # A verification record from a different evidence path may remain in
        # the incremental per-cut directory. Never let its nonzero stale
        # counts replace an explicit zero from the active proof's linkage
        # audit.
        post = (
            audit.get("postRelinkDependencyAudit") or {}
            if per_cut_audit_selected
            else {}
        )
        if not authoritative_current_recovery:
            for value in post.get("renderCriticalUnresolvedPaths") or []:
                value = str(value or "")
                if value and value not in missing_exact_files:
                    missing_exact_files.append(value)

        linkage = dict(existing_linkage)
        linkage.update(
            {
                "status": (
                    existing_linkage.get("status")
                    if authoritative_current_recovery
                    else link_status.get("status")
                ),
                "dependencyReferences": int(
                    existing_linkage.get("dependencyReferences")
                    if authoritative_current_recovery
                    else link_status.get("dependencyReferences")
                    or post.get("dependencyReferences")
                    or 0
                ),
                "linkedReferences": int(
                    existing_linkage.get("linkedReferences")
                    if authoritative_current_recovery
                    else link_status.get("linkedReferences")
                    or post.get("linkedReferences")
                    or 0
                ),
                "missingReferences": int(
                    existing_linkage.get("missingReferences")
                    if authoritative_current_recovery
                    else link_status.get("missingReferences")
                    or post.get("missingReferences")
                    or 0
                ),
                "renderCriticalMissingReferences": int(
                    existing_linkage.get(
                        "renderCriticalMissingReferences"
                    )
                    if authoritative_current_recovery
                    else post.get("renderCriticalUnresolvedReferences")
                    if per_cut_audit_selected
                    else link_status.get("renderCriticalMissingReferences")
                    or 0
                ),
                "renderCriticalMissingFiles": int(
                    existing_linkage.get("renderCriticalMissingFiles")
                    if authoritative_current_recovery
                    else post.get("renderCriticalUnresolvedFiles")
                    if per_cut_audit_selected
                    else link_status.get("renderCriticalMissingFiles")
                    or 0
                ),
                "strictDependencyRenderSafe": bool(
                    existing_linkage.get("strictDependencyRenderSafe")
                    if authoritative_current_recovery
                    else audit.get("strictDependencyRenderSafe")
                    if per_cut_audit_selected
                    else exact_cut_audit.get("strictDependencyRenderSafe")
                    if exact_cut_audit.get("strictDependencyRenderSafe")
                    is not None
                    else link_status.get("strictDependencyRenderSafe")
                    if link_status.get("strictDependencyRenderSafe")
                    is not None
                    else verification.get("checks", {}).get(
                        "dependencyRenderSafe"
                    )
                ),
                "missingExactFiles": missing_exact_files,
                "auditPath": dependency_path or None,
                "auditProject": audit_project or active_project or None,
                "auditTake": audit_take,
                "auditFrame": audit_frame,
                "activeProofFrame": active_frame,
                "scope": scope,
                "matchesActiveProject": same_project,
                "matchesActiveFrame": same_frame,
            }
        )
        verification["linkageAudit"] = linkage
        linkage_links += 1

        if dependency_path:
            existing_audit_node = next(
                (
                    node
                    for node in lineage
                    if node.get("kind") == "c4d_dependency_audit"
                    and node.get("path") == str(APP_ROOT / dependency_path)
                ),
                None,
            )
            if existing_audit_node is None:
                lineage.append(
                    {
                        "kind": "c4d_dependency_audit",
                        "label": "Current linked dependency audit",
                        "detail": (
                            f"{scope.replace('_', ' ')} · take {audit_take}"
                            + (
                                f" · audited frame {audit_frame}"
                                if audit_frame is not None
                                else ""
                            )
                            + (
                                f" · active proof frame {active_frame}"
                                if active_frame is not None
                                else ""
                            )
                        ),
                        "path": str(APP_ROOT / dependency_path),
                        "projectPath": audit_project or active_project,
                        "evidence": "confirmed",
                        "take": audit_take,
                        "frame": audit_frame,
                        "activeProofFrame": active_frame,
                        "scope": scope,
                        "strictDependencyRenderSafe": linkage[
                            "strictDependencyRenderSafe"
                        ],
                    }
                )
                audit_nodes_added += 1

        if not any(node.get("kind") == "camera" for node in lineage):
            camera_label = re.sub(
                r"\s*[·-]\s*(?:live\s+Redshift\s+grey\s+geometry\s*[·-]\s*)?"
                r"frame\s+\d+\s*$",
                "",
                str(
                    (active_proof or {}).get("cameraObjectPath")
                    or verification.get("cameraName")
                    or (active_proof or {}).get("label")
                    or "Saved render camera"
                ),
                flags=re.IGNORECASE,
            ).strip()
            camera_result = str(
                (verification.get("elements") or {}).get("camera") or ""
            ).casefold()
            camera_matched = bool(
                (verification.get("checks") or {}).get(
                    "cameraProofMatched"
                )
                or camera_result == "match"
                or camera_result.startswith("match_")
                or camera_result.startswith("confirmed_exact_")
            )
            lineage.append(
                {
                    "kind": "camera",
                    "label": camera_label,
                    "detail": (
                        f"Distinct source-camera identity for take "
                        f"{audit_take}"
                        + (
                            f" at frame {active_frame}"
                            if active_frame is not None
                            else ""
                        )
                        + "; linked to the active camera proof and selected "
                        "C4D project."
                    ),
                    "path": active_project or None,
                    "projectPath": active_project or None,
                    "comparisonImage": verification.get("cameraProof"),
                    "evidence": (
                        "confirmed" if camera_matched else "partial"
                    ),
                    "confirmationMethod": (
                        "active camera proof plus current C4D verification"
                    ),
                    "targetFrame": active_frame,
                    "cameraTake": audit_take,
                    "sourceCameraLineage": True,
                }
            )
            camera_nodes_added += 1

        cut["c4dVerification"] = verification
        cut["lineage"] = lineage

    state["c4dEvidenceIntegration"] = {
        "authority": (
            "Final per-cut C4D evidence integration with explicit audit scope"
        ),
        "generatedAt": now_iso(),
        "dependencyAuditDirectory": str(
            C4D_CUT_DEPENDENCY_AUDIT_DIR.relative_to(APP_ROOT)
        ),
        "dependencyAuditLinks": dependency_links,
        "linkageAuditLinks": linkage_links,
        "cameraLineageNodesAdded": camera_nodes_added,
        "dependencyAuditNodesAdded": audit_nodes_added,
        "supersededCameraProofs": superseded_proofs,
        "scopedFrameDifferences": scoped_frame_differences,
    }
    return {
        "dependencyAuditLinks": dependency_links,
        "linkageAuditLinks": linkage_links,
        "cameraLineageNodesAdded": camera_nodes_added,
        "dependencyAuditNodesAdded": audit_nodes_added,
        "supersededCameraProofs": superseded_proofs,
        "scopedFrameDifferences": scoped_frame_differences,
    }


def integrate_exact_source_render_selections(
    state: dict[str, Any],
) -> dict[str, int]:
    """Publish manually compared exact-source renders as current evidence.

    The render inventory intentionally treats every new frame as process-only.
    A small, explicit selection record is therefore required before a frame can
    become the active atlas proof. Canonical-match selections have to point at
    a strict second-pass dependency verification; a visual score alone is
    insufficient. An explicit yellow selection may publish a fresh exact-source
    render with retained unresolved dependencies, but it can never count as a
    visual match or dependency-safe proof.
    """

    evidence_dir = DATA_DIR / "c4d-mainframe-recovery-20260730"
    selection_paths = sorted(
        set(evidence_dir.glob("CUT-???-exact-source-*-selection-*.json"))
        | set(evidence_dir.glob("CUT-???-exact-source-frame-selection-*.json"))
    )
    cuts_by_id = {
        str(cut.get("id") or ""): cut
        for cut in state.get("cuts", [])
        if not cut.get("isGap")
    }

    def public_path(value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        if text.startswith("/archive/"):
            return text
        path = (APP_ROOT / text).resolve()
        try:
            relative = path.relative_to((APP_ROOT / "public").resolve())
        except ValueError:
            return ""
        return f"/{relative.as_posix()}"

    selected = 0
    visual_matches = 0
    dependency_safe = 0
    for selection_path in selection_paths:
        try:
            selection = json.loads(
                selection_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue
        cut_id = str(selection.get("cutId") or "")
        cut = cuts_by_id.get(cut_id)
        if cut is None:
            continue
        proof = selection.get("selectedEvidence") or selection
        render_public = public_path(proof.get("render"))
        if not render_public:
            continue
        render_file = APP_ROOT / str(proof.get("render") or "")
        if not render_file.is_file():
            continue
        strict_verification_rel = str(
            proof.get("strictVerification")
            or selection.get("strictVerification")
            or proof.get("dependencyAudit")
            or selection.get("dependencyAudit")
            or ""
        )
        strict_verification_path = APP_ROOT / strict_verification_rel
        try:
            strict_verification = json.loads(
                strict_verification_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue
        strict_safe = bool(
            strict_verification.get("status") == "verified"
            and strict_verification.get("strictDependencyRenderSafe") is True
        )
        allow_incomplete = bool(
            selection.get("allowIncompleteDependencies") is True
            and str(selection.get("proofTier") or "").casefold() == "yellow"
            and selection.get("visualMatch") is not True
        )
        if not strict_safe and not allow_incomplete:
            continue

        manifest_rel = str(
            proof.get("strictManifest")
            or selection.get("strictManifest")
            or strict_verification.get("manifest")
            or ""
        )
        manifest: dict[str, Any] = {}
        if manifest_rel:
            try:
                manifest = json.loads(
                    (APP_ROOT / manifest_rel).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                manifest = {}
        mapping_count = int(
            strict_verification.get("mappingCount")
            or (manifest.get("summary") or {}).get("mappedPaths")
            or (manifest.get("summary") or {}).get("totalMappedPaths")
            or len(manifest.get("mappings") or [])
            or 0
        )
        unresolved_count = int(
            (manifest.get("summary") or {}).get("unresolvedPaths")
            or (manifest.get("summary") or {}).get("totalUnresolvedPaths")
            or len(manifest.get("unresolved") or [])
            or 0
        )
        if not strict_safe and unresolved_count < 1:
            continue
        post = strict_verification.get("postRelinkDependencyAudit") or {}
        unresolved_reference_count = int(
            post.get("renderCriticalUnresolvedReferences")
            or post.get("unresolvedPictureReferences")
            or unresolved_count
        )
        project_wide = (
            strict_verification.get("projectWidePostRelinkDependencyAudit")
            or {}
        )
        project = str(selection.get("project") or "")
        source_project = str(selection.get("sourceProject") or project)
        frame = selection.get("selectedProjectFrame", selection.get("frame"))
        take = str(selection.get("take") or "Main")
        camera_path = str(selection.get("cameraPath") or "saved camera")
        render_data = str(selection.get("renderData") or "saved render data")
        visual_match = bool(selection.get("visualMatch") is True)
        saved_reopen_verified = bool(
            selection.get("savedReopenVerified") is True
        )
        canonical_match = (
            strict_safe and visual_match and saved_reopen_verified
        )
        comparison = proof.get("comparison") or selection.get("comparison")
        contact_public = public_path(
            proof.get("contactSheet") or selection.get("contactSheet")
        )
        mae = proof.get("meanAbsoluteError", selection.get("meanAbsoluteError"))
        correlations = proof.get(
            "perChannelCorrelation",
            selection.get("perChannelCorrelation") or [],
        )
        metric_text = (
            f"MAE {float(mae):.6f}"
            if isinstance(mae, (int, float))
            else "manual comparison recorded"
        )
        if correlations:
            metric_text += " · RGB correlation " + "/".join(
                f"{float(value):.6f}" for value in correlations
            )
        proof_label = (
            "Exact-source full-color match"
            if canonical_match
            else (
                "Exact-source visual match · save/reopen pending"
                if visual_match
                else "Exact-source full-color recovery · residual drift"
            )
        )
        detail = (
            f"Exact shot-authored state · {take} · {camera_path} · "
            f"{render_data} · frame {frame} · {mapping_count} exact active "
            f"dependency mappings · {metric_text}. "
            + str(selection.get("notes") or "")
        ).strip()

        lineage = cut.setdefault("lineage", [])
        for node in lineage:
            if node.get("kind") == "camera_proof":
                node["primaryRecoveryProof"] = False
            if node.get("kind") == "cinema4d":
                node["sourceApplicationPrimary"] = False
        c4d_node = next(
            (
                node
                for node in lineage
                if node.get("kind") == "cinema4d"
                and str(node.get("projectPath") or node.get("path") or "")
                == project
            ),
            None,
        )
        if c4d_node is None:
            c4d_node = {
                "kind": "cinema4d",
                "label": Path(project).name,
            }
            lineage.append(c4d_node)
        c4d_node.update(
            {
                "path": project,
                "projectPath": project,
                "detail": (
                    "Saved and independently reopened exact recovery derived "
                    "from the untouched shot-authored source."
                    if saved_reopen_verified
                    else "Untouched shot-authored source selected by exact "
                    "frame, camera, render-setting, dependency, and visual "
                    "evidence; saved-reopen verification is still required "
                    "for a canonical-match promotion."
                ),
                "evidence": "confirmed",
                "sourceApplicationPrimary": True,
                "assetHealth": {
                    "status": (
                        "fully_linked_confirmed"
                        if strict_safe
                        else "missing_sources"
                    ),
                    "label": (
                        "Exact active dependencies verified"
                        if strict_safe
                        else "Exact source retained with active blockers"
                    ),
                    "take": take,
                    "frame": frame,
                    "strictDependencyRenderSafe": strict_safe,
                },
            }
        )
        proof_node = next(
            (
                node
                for node in lineage
                if node.get("kind") == "camera_proof"
                and node.get("comparisonImage") == render_public
            ),
            None,
        )
        if proof_node is None:
            proof_node = {"kind": "camera_proof"}
            lineage.append(proof_node)
        proof_node.update(
            {
                "label": f"{proof_label} · frame {frame}",
                "detail": detail,
                "path": project,
                "projectPath": project,
                "comparisonImage": render_public,
                "comparisonContactSheet": contact_public or None,
                "confirmationMethod": (
                    "Exact-source Redshift render plus retained-frame metrics"
                ),
                "evidence": "confirmed" if canonical_match else "partial",
                "proofStatus": (
                    "rendered_exact_source_match"
                    if canonical_match
                    else "rendered_exact_source_residual_drift"
                ),
                "primaryRecoveryProof": True,
                "redshiftProof": True,
                "fullColorProof": True,
                "targetFrame": frame,
                "cameraTake": take,
                "cameraObjectPath": camera_path,
                "renderData": render_data,
                "strictDependencyRenderSafe": strict_safe,
                "visualMatch": visual_match,
                "savedReopenVerified": saved_reopen_verified,
                "comparisonResult": comparison,
            }
        )

        linkage = {
            "authoritativeForCurrentRecovery": True,
            "authority": (
                "Exact-source selection plus strict second-pass Cinema "
                "dependency verification"
                if strict_safe
                else "Exact-source selection with explicit unresolved active "
                "dependency audit"
            ),
            "status": (
                "fully_linked_confirmed"
                if strict_safe
                else "missing_sources"
            ),
            "currentPathIdentityConfirmed": True,
            "savedReopenVerified": saved_reopen_verified,
            "mappedPaths": mapping_count,
            "renderCriticalExactRecoveries": mapping_count,
            "manifestPath": manifest_rel or None,
            "dependencyReferences": int(
                post.get("pictureReferences")
                or post.get("dependencyReferences")
                or 0
            ),
            "linkedReferences": int(post.get("linkedReferences") or 0),
            "missingReferences": int(
                post.get("renderCriticalUnresolvedReferences")
                or post.get("unresolvedPictureReferences")
                or 0
            ),
            "renderCriticalMissingReferences": (
                0 if strict_safe else unresolved_reference_count
            ),
            "renderCriticalMissingFiles": (
                0 if strict_safe else unresolved_count
            ),
            "renderCriticalUnresolvedFiles": (
                0 if strict_safe else unresolved_count
            ),
            "strictDependencyRenderSafe": strict_safe,
            "rawRenderCriticalMissingFiles": (
                0
                if strict_safe
                else int(post.get("unresolvedPictureFiles") or unresolved_count)
            ),
            "missingExamples": list(manifest.get("unresolved") or []),
            "projectWideStrictDependencyRenderSafe": bool(
                project_wide.get("strictDependencyRenderSafe")
            ),
            "auditPath": strict_verification_rel,
            "evidencePath": str(selection_path.relative_to(APP_ROOT)),
            "auditProject": project,
            "sourceProject": source_project,
            "auditTake": take,
            "auditFrame": frame,
            "activeProofFrame": frame,
            "scope": "active_project_take_and_frame",
            "matchesActiveProject": True,
            "matchesActiveFrame": True,
        }
        verification = dict(cut.get("c4dVerification") or {})
        checks = dict(verification.get("checks") or {})
        checks.update(
            {
                "projectLinked": True,
                "dependencyAudited": True,
                "dependencyRenderSafe": strict_safe,
                "proxyRenderSafe": strict_safe,
                "cameraProofRendered": True,
                "cameraProofMatched": True,
                "visualMatch": visual_match,
                "exactSourceProjectLinked": True,
            }
        )
        verification.update(
            {
                "status": "match" if canonical_match else "partial",
                "label": proof_label,
                "detail": detail,
                "projectPath": project,
                "targetFrame": frame,
                "cameraTake": take,
                "cameraName": camera_path,
                "renderData": render_data,
                "cameraProof": render_public,
                "comparisonImage": contact_public or render_public,
                "renderReference": selection.get("canonicalReference"),
                "dependencyAuditPath": strict_verification_rel,
                "strictLinked": strict_safe,
                "checks": checks,
                "linkageAudit": linkage,
                "materialCompatibilityAudit": {
                    "status": (
                        "rendered_match"
                        if canonical_match
                        else "rendered_residual_source_state_drift"
                    ),
                    "outputPath": render_public,
                    "publicPath": render_public,
                    "comparisonPath": contact_public or None,
                    "comparisonResult": comparison,
                    "fullColor": True,
                    "fullColorProof": True,
                    "freshAuditRender": True,
                    "strictDependencyRenderSafe": strict_safe,
                    "productionRuntime": selection.get("productionRuntime"),
                    "runtimeDetail": detail,
                },
            }
        )
        if not strict_safe:
            unresolved_paths = list(manifest.get("unresolved") or [])
            recovery_prescription = (
                "Recover every unresolved authored path retained in the exact "
                "manifest without cross-shot substitution; rerender the exact "
                "take, camera, render data, and frame; then save a dated "
                "sibling and independently reopen it before green promotion."
            )
            agent_ready_checklist = [
                f"Open {project} read-only and preserve the recovered source unchanged.",
                f"Select take {take}, camera {camera_path}, render data {render_data}, and frame {frame}.",
                (
                    "Recover and identity-check these exact active authored "
                    "dependencies: " + "; ".join(unresolved_paths)
                ),
                (
                    f"Rerender full color and compare 1:1 to "
                    f"{selection.get('canonicalReference')}."
                ),
                (
                    "Only after zero active dependency blockers and a visual "
                    "match, save a dated sibling and independently reopen it."
                ),
            ]
            verification.update(
                {
                    "elements": dict(selection.get("elements") or {}),
                    "notes": str(selection.get("notes") or ""),
                    "blockers": unresolved_paths,
                    "remediation": [
                        recovery_prescription,
                        *agent_ready_checklist,
                    ],
                    "recoveryPrescription": recovery_prescription,
                    "agentReadyChecklist": agent_ready_checklist,
                }
            )
        if canonical_match:
            recovery_prescription = (
                "Preserve the untouched shot-authored source, dated saved "
                "recovery, strict relink manifest, independent reopen audit, "
                "fresh render, and retained-frame comparison together."
            )
            agent_ready_checklist = [
                f"Open {project} read-only and preserve {source_project} unchanged.",
                f"Select take {take}, camera {camera_path}, render data {render_data}, and frame {frame}.",
                (
                    "Require the independent saved-reopen audit to retain zero "
                    "render-critical unresolved files before rendering."
                ),
                (
                    f"Compare the fresh full-color proof to "
                    f"{selection.get('canonicalReference')} using {comparison}."
                ),
            ]
            verification.update(
                {
                    "elements": {
                        "location": "match",
                        "camera": "match",
                        "character": "match",
                        "hair": "match",
                        "wardrobe": "match",
                        "teacup": "match",
                        "ocean": "match",
                        "materials": "match",
                        "lighting": "match",
                    },
                    "notes": str(selection.get("notes") or ""),
                    "blockers": [],
                    "remediation": [
                        recovery_prescription,
                        *agent_ready_checklist,
                    ],
                    "recoveryPrescription": recovery_prescription,
                    "agentReadyChecklist": agent_ready_checklist,
                }
            )
        cut["c4dVerification"] = verification
        cut["c4dLinkStatus"] = {
            **(cut.get("c4dLinkStatus") or {}),
            "status": (
                "fully_linked_confirmed"
                if strict_safe
                else "missing_sources"
            ),
            "label": (
                "Exact active dependencies verified"
                if strict_safe
                else "Exact source retained with active blockers"
            ),
            "detail": (
                f"Frame {frame} · take {take} · {mapping_count} exact "
                f"mappings · {unresolved_count if not strict_safe else 0} "
                "unresolved render-critical files"
            ),
            "projectPath": project,
            "projectName": Path(project).name,
            "take": take,
            "frame": frame,
            "renderCriticalExactRecoveries": mapping_count,
            "renderCriticalMissingReferences": (
                0 if strict_safe else unresolved_reference_count
            ),
            "renderCriticalMissingFiles": (
                0 if strict_safe else unresolved_count
            ),
            "renderCriticalUnresolvedFiles": (
                0 if strict_safe else unresolved_count
            ),
            "strictDependencyRenderSafe": strict_safe,
            "manifestPath": manifest_rel or None,
            "verificationPath": strict_verification_rel,
            "missingExamples": list(manifest.get("unresolved") or []),
            "dependencyLabel": (
                "Exact active dependencies verified"
                if strict_safe
                else "Exact active dependency recovery incomplete"
            ),
            "visualReview": {
                "status": (
                    "match" if canonical_match else "partial_match"
                ),
                "elements": (
                    dict(selection.get("elements") or {})
                    if not strict_safe
                    else dict(verification.get("elements") or {})
                ),
                "notes": str(selection.get("notes") or ""),
            },
            "materialCompatibilityAudit": verification.get(
                "materialCompatibilityAudit"
            ),
            "recoveryPrescription": (
                "Recover every path retained in the strict manifest, rerender "
                "the exact authored take/camera/frame, then save as a dated "
                "sibling and independently reopen before any green promotion."
                if not strict_safe
                else verification.get("recoveryPrescription")
            ),
        }
        selected += 1
        visual_matches += int(canonical_match)
        dependency_safe += int(strict_safe)

    state["c4dExactSourceRenderSelections"] = {
        "authority": (
            "Manually compared exact-source selection records with strict "
            "second-pass dependency verification; explicitly incomplete "
            "selections remain yellow and cannot count as visual matches"
        ),
        "generatedAt": now_iso(),
        "selectedRenders": selected,
        "visualMatches": visual_matches,
        "strictDependencySafe": dependency_safe,
    }
    return {
        "selectedRenders": selected,
        "visualMatches": visual_matches,
        "strictDependencySafe": dependency_safe,
    }


def refresh_current_c4d_status_rollup(state: dict[str, Any]) -> dict[str, int]:
    """Recompute the top-level C4D status from the published proof contract."""

    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()

    def source_c4d_node(cut: dict[str, Any]) -> dict[str, Any]:
        nodes = [
            node
            for node in cut.get("lineage", [])
            if node.get("kind") == "cinema4d"
            and (node.get("projectPath") or node.get("path"))
        ]
        return next(
            (node for node in nodes if node.get("sourceApplicationPrimary")),
            next(
                (
                    node
                    for node in nodes
                    if any(
                        tag.get("type") == "chapter_edit"
                        for tag in node.get("tags") or []
                        if isinstance(tag, dict)
                    )
                ),
                next(
                    (node for node in nodes if node.get("projectPath")),
                    nodes[0] if nodes else {},
                ),
            ),
        )

    def resolve(cut: dict[str, Any]) -> tuple[str, str]:
        verification = cut.get("c4dVerification") or {}
        c4d_node = source_c4d_node(cut)
        active_proof = next(
            (
                node
                for node in cut.get("lineage", [])
                if node.get("kind") == "camera_proof"
                and node.get("comparisonImage")
                == verification.get("cameraProof")
            ),
            {},
        )
        file_confirmed = c4d_node.get("evidence") == "confirmed"
        camera_result = str(
            (verification.get("elements") or {}).get("camera") or ""
        ).casefold()
        camera_matched = bool(
            (verification.get("checks") or {}).get("cameraProofMatched")
            or camera_result == "match"
            or camera_result.startswith("match_")
            or camera_result.startswith("confirmed_exact_")
        )
        proof_rendered = bool(
            (verification.get("checks") or {}).get("cameraProofRendered")
            and active_proof.get("comparisonImage")
            and str(active_proof.get("proofStatus") or "").startswith(
                "rendered"
            )
        )
        proof_confirmed = active_proof.get("evidence") == "confirmed"
        link_status = cut.get("c4dLinkStatus") or {}
        exact_audit = link_status.get("exactCutAudit") or {}
        exact_result = exact_audit.get("strictDependencyRenderSafe")
        if exact_result is None:
            exact_result = link_status.get("strictDependencyRenderSafe")
        dependency_safe = (
            bool(exact_result)
            if exact_result is not None
            else bool(
                (verification.get("checks") or {}).get("dependencyAudited")
                and (verification.get("checks") or {}).get(
                    "dependencyRenderSafe"
                )
            )
        )
        if not file_confirmed:
            return "unconfirmed", "c4d_file_unconfirmed"
        if not proof_rendered:
            return "file-confirmed", "camera_test_missing"
        if not camera_matched:
            return "file-confirmed", "camera_mismatch"
        if (
            active_proof.get("redshiftProof") is True
            and active_proof.get("fullColorProof") is True
            and proof_confirmed
            and dependency_safe
        ):
            return "redshift-verified", "redshift_camera_match"
        proof_supports_match = (
            proof_confirmed or active_proof.get("evidence") == "partial"
        )
        if (
            proof_supports_match
            and active_proof.get("redshiftProof") is True
            and active_proof.get("fullColorProof") is True
        ):
            return (
                "camera-verified",
                "redshift_camera_match_dependencies_incomplete",
            )
        if (
            proof_supports_match
            and active_proof.get("redshiftProof") is True
        ):
            return "camera-verified", "redshift_grey_camera_match"
        proof_text = " ".join(
            str(value or "")
            for value in (
                active_proof.get("detail"),
                active_proof.get("comparisonImage"),
                active_proof.get("confirmationMethod"),
            )
        ).casefold()
        if (
            proof_supports_match
            and active_proof.get("redshiftProof") is False
            and re.search(
                r"cinema 4d hardware|hardware camera proof|hardware preview",
                proof_text,
            )
        ):
            return "camera-verified", "hardware_camera_match"
        if proof_supports_match:
            return "camera-verified", "neutral_camera_match"
        if not proof_confirmed:
            return "file-confirmed", "camera_test_unconfirmed"
        return "file-confirmed", "renderer_unconfirmed"

    picture_cuts = [
        cut for cut in state.get("cuts", []) if not cut.get("isGap")
    ]
    for cut in picture_cuts:
        tone, reason = resolve(cut)
        counts[tone] += 1
        reasons[reason] += 1

    confirmed = counts["redshift-verified"] + counts["camera-verified"]
    rollup = {
        "pictureCuts": len(picture_cuts),
        "redshiftVerifiedCuts": counts["redshift-verified"],
        "cameraVerifiedCuts": counts["camera-verified"],
        "fileConfirmedCuts": counts["file-confirmed"],
        "unconfirmedCuts": counts["unconfirmed"],
        "greenYellowCuts": confirmed,
    }
    summary = state.setdefault("summary", {})
    summary.update(
        {
            "cameraConfirmed": confirmed,
            "cameraConfirmedCuts": confirmed,
            "renderAlignedCameraCuts": confirmed,
            "cameraUnresolvedCuts": len(picture_cuts) - confirmed,
            "c4dRedshiftVerifiedCuts": counts["redshift-verified"],
            "c4dCameraVerifiedCuts": counts["camera-verified"],
            "c4dFileConfirmedCuts": counts["file-confirmed"],
            "c4dUnconfirmedCuts": counts["unconfirmed"],
        }
    )
    linked_audits = [
        (cut.get("c4dVerification") or {}).get("linkageAudit") or {}
        for cut in picture_cuts
        if (cut.get("c4dVerification") or {}).get("dependencyAuditPath")
    ]
    safe_audits = sum(
        1
        for audit in linked_audits
        if audit.get("strictDependencyRenderSafe") is True
    )
    project_mismatches = sum(
        1
        for audit in linked_audits
        if audit.get("matchesActiveProject") is False
    )
    summary.update(
        {
            "c4dExactCutDependencyAuditedCuts": len(linked_audits),
            "c4dExactCutDependencySafeCuts": safe_audits,
            "c4dExactCutDependencyBlockedCuts": (
                len(linked_audits) - safe_audits
            ),
            "c4dExactCutDependencyUnavailableCuts": (
                len(picture_cuts) - len(linked_audits)
            ),
            "c4dExactCutDependencyProjectMismatches": project_mismatches,
        }
    )
    state["c4dCurrentStatusRollup"] = {
        "authority": (
            "AGENTS.md green/yellow/black/grey verification contract"
        ),
        "generatedAt": now_iso(),
        "statusAudit": "/data/c4d-status-consistency-audit-20260728.json",
        "counts": rollup,
        "reasons": dict(sorted(reasons.items())),
    }
    return rollup


def apply_c4d_proxy_recovery(
    cuts: list[dict[str, Any]],
    scene_state_archive: dict[str, Any],
    proxy_recovery_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach saved-scene visibility and Redshift proxy reproducibility.

    A proxy object is not considered render-safe merely because its path can be
    recovered. The exact proxy must be readable by the installed renderer and
    rendered through the saved camera before strict linkage can pass.
    """

    scene_by_cut: dict[str, dict[str, Any]] = {}
    for project in scene_state_archive.get("projects", []):
        for cut_id in project.get("cuts", []):
            scene_by_cut[str(cut_id)] = project

    proxy_by_cut: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in proxy_recovery_archive.get("records", []):
        for cut_id in record.get("cuts", []):
            proxy_by_cut[str(cut_id)].append(record)

    status_counts: Counter[str] = Counter()
    inspected_cuts = 0
    affected_cuts = 0
    for cut in cuts:
        if cut.get("isGap"):
            continue
        cut_id = str(cut.get("id") or "")
        scene = scene_by_cut.get(cut_id)
        records = proxy_by_cut.get(cut_id, [])
        inspected = bool(scene and scene.get("status") == "inspected")
        cut_index = int(cut.get("index") or 0)
        wardrobe_family = (
            "grey"
            if 1 <= cut_index <= 3 or 37 <= cut_index <= 56
            else "colored_grey"
            if 75 <= cut_index <= 87
            else "patchwork"
        )
        inspected_cuts += int(inspected)
        cut["c4dSceneState"] = {
            "inspected": inspected,
            "generatedAt": scene_state_archive.get("generatedAt"),
            "authority": scene_state_archive.get("authority"),
            "projectPath": (scene or {}).get("projectPath"),
            "projectName": (scene or {}).get("projectName"),
            "frameInspected": (scene or {}).get("frameInspected"),
            "diagnosis": (
                (scene or {}).get("diagnosis")
                or "scene_state_audit_unavailable"
            ),
            "activeProxyCount": int(
                (scene or {}).get("activeProxyCount") or 0
            ),
            "activeCharacterObjectCount": int(
                (scene or {}).get("activeCharacterObjectCount") or 0
            ),
            "activeHairObjectCount": int(
                (scene or {}).get("activeHairObjectCount") or 0
            ),
            "activeWardrobeObjectCount": int(
                (scene or {}).get("activeWardrobeObjectCount") or 0
            ),
            "expectedWardrobeFamily": wardrobe_family,
            "expectedSharedAssets": [
                "Abby character + skin",
                "canonical Abby hair",
                f"{wardrobe_family.replace('_', ' ')} wardrobe",
            ],
        }

        required = bool(records or int((scene or {}).get("activeProxyCount") or 0))
        if not required:
            status = "not_used" if inspected else "audit_unavailable"
            label = (
                "No active Redshift proxy"
                if inspected
                else "Proxy visibility audit unavailable"
            )
            detail = (
                "The saved scene renders editable geometry rather than an active proxy."
                if inspected
                else "The mapped source project was not included in the saved-scene census."
            )
        else:
            affected_cuts += 1
            record_statuses = {
                str(record.get("status") or "") for record in records
            }
            if "proxy_sequence_missing_runtime_compatible" in record_statuses:
                status = "unresolved"
                label = "RS proxy readable · exact animated sequence missing"
                detail = (
                    "Cinema 4D 2026.3 reads and renders the retained mesh-format-49 "
                    "proxy, but this shot requires the authored 0080-2160 animated "
                    "sequence and final saved camera state. The static proxy is "
                    "diagnostic only and cannot verify the shot."
                )
            elif "proxy_present_renderer_blocked" in record_statuses:
                status = "renderer_update_required"
                label = "RS proxy · renderer update required"
                detail = (
                    "The exact proxy exists, but its mesh format is newer than "
                    "the installed Redshift reader. It must render successfully "
                    "before this shot can be camera-verified."
                )
            elif (
                records
                and all(
                    record.get("sourceComponentsComplete")
                    for record in records
                )
            ):
                status = "rebuild_ready"
                label = "RS proxy · rebuild ready"
                detail = (
                    "The saved proxy file is missing, but body, face, boots, and "
                    "cloth source components are present for exact regeneration."
                )
            else:
                status = "unresolved"
                label = "RS proxy · unresolved"
                detail = (
                    "The active proxy is missing and its source components are "
                    "not yet complete."
                )

        proxy_records = []
        for record in records:
            summary = record.get("proxyAuditSummary") or {}
            compatibility = record.get("rendererCompatibility") or {}
            proxy_records.append(
                {
                    "proxyObjectName": record.get("proxyObjectName"),
                    "proxyObjectPath": record.get("proxyObjectPath"),
                    "proxyFile": record.get("proxyFile"),
                    "proxyAuditPath": record.get("proxyAuditPath"),
                    "proxyAuditSummary": summary,
                    "producerVersion": record.get("producerVersion"),
                    "rendererCompatibility": compatibility,
                    "sourceComponentsComplete": bool(
                        record.get("sourceComponentsComplete")
                    ),
                    "sourceComponents": record.get("sourceComponents", []),
                    "editableCharacterDiagnosis": record.get(
                        "editableCharacterDiagnosis"
                    ),
                }
            )
        cut["c4dProxyAudit"] = {
            "required": required,
            "status": status,
            "label": label,
            "detail": detail,
            "generatedAt": proxy_recovery_archive.get("generatedAt"),
            "authority": proxy_recovery_archive.get("authority"),
            "records": proxy_records,
        }
        for node in cut.get("lineage", []):
            if node.get("kind") in {"cinema4d", "camera"}:
                node["sceneStateDiagnosis"] = cut["c4dSceneState"][
                    "diagnosis"
                ]
                node["proxyAuditStatus"] = status
                node["proxyRenderSafe"] = status in {
                    "not_used",
                    "verified_rendered",
                }
        status_counts[status] += 1

    return {
        "c4dSceneStateAuditedCuts": inspected_cuts,
        "c4dProxyAffectedCuts": affected_cuts,
        "c4dProxyRendererUpdateRequiredCuts": status_counts[
            "renderer_update_required"
        ],
        "c4dProxyRebuildReadyCuts": status_counts["rebuild_ready"],
        "c4dProxyUnresolvedCuts": status_counts["unresolved"],
    }


def apply_c4d_structural_recoveries(
    cuts: list[dict[str, Any]],
    recovery_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach dated-copy repairs without promoting them to strict matches."""

    records = {
        str(item.get("cutId") or ""): item
        for item in recovery_archive.get("records", [])
        if item.get("cutId")
    }
    attached = 0
    rendered_proofs = 0
    for cut in cuts:
        record = records.get(str(cut.get("id") or ""))
        if not record:
            continue
        attached += 1
        external_hair_experiment = bool(
            record.get("sourceHairProject")
            or record.get("staticHairSource")
            or record.get("hairSource")
            or record.get("rejectedExternalHairExperiment")
            or record.get("rejectedHairExperiment")
            or record.get("rejectedHairExperiments")
            or record.get("externalHairExperimentRejected")
        )
        proofs = [
            proof
            for proof in record.get("proofs", [])
            if "rejected" not in str(proof.get("status") or "").casefold()
            and not (
                external_hair_experiment
                and "hair" in str(proof.get("kind") or "").casefold()
            )
        ]
        rendered_proofs += sum(
            item.get("status") == "rendered" for item in proofs
        )
        cut["c4dStructuralRecovery"] = {
            **record,
            "proofs": proofs,
            "generatedAt": recovery_archive.get("generatedAt"),
            "authority": recovery_archive.get("authority"),
            "crossShotHairAllowed": False,
            "externalHairExperimentRejected": external_hair_experiment,
        }
        for node in cut.get("lineage", []):
            if (
                node.get("kind") == "camera"
                and str(node.get("projectPath") or node.get("path") or "")
                == str(record.get("sourceProject") or "")
            ):
                node["label"] = record.get("cameraName") or node.get("label")
                node["detail"] = (
                    "Saved effective render camera · take Main · "
                    f"{record.get('renderData') or 'saved render data'} · "
                    "corrected by live saved-scene inspection"
                )
                node["confirmationMethod"] = "saved_take_effective_camera"
        cut.setdefault("lineage", []).append(
            {
                "kind": "cinema4d_recovery",
                "label": Path(str(record.get("recoveryProject") or "")).name,
                "detail": (
                    record.get("detail")
                    or (
                        "Dated recovery copy · camera, dependency, material, "
                        "and asset reconstruction proofs recorded · original "
                        "untouched · recovery remains partial"
                    )
                ),
                "path": record.get("recoveryProject"),
                "projectPath": record.get("recoveryProject"),
                "evidence": "confirmed",
                "recoveryStatus": record.get("status"),
            }
        )
        for proof in proofs:
            if proof.get("status") != "rendered" or not proof.get("image"):
                continue
            cut["lineage"].append(
                {
                    "kind": "camera_proof",
                    "label": (
                        f"{record.get('cameraName') or 'Recovered camera'} · "
                        f"frame {record.get('targetFrame')}"
                    ),
                    "detail": (
                        f"Dated recovery · {proof.get('kind', '').replace('_', ' ')} · "
                        f"{proof.get('visualResult') or 'rendered'}"
                    ),
                    "path": record.get("recoveryProject"),
                    "projectPath": record.get("recoveryProject"),
                    "comparisonImage": proof.get("image"),
                    "confirmationMethod": "dated-copy recovery proof",
                    "evidence": "confirmed",
                    "proofStatus": "rendered",
                    "recoveryProof": bool(
                        record.get("cameraProofEligible", True)
                    ),
                    "primaryRecoveryProof": bool(proof.get("primary")),
                    "strictLinked": False,
                    "visualVerificationStatus": record.get("status"),
                }
            )
    return {
        "c4dStructuralRecoveryCuts": attached,
        "c4dStructuralRecoveryProofs": rendered_proofs,
    }


def apply_c4d_redshift_proofs(
    cuts: list[dict[str, Any]],
    proof_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach real Redshift proofs for proxy scenes and viewport failures."""

    cuts_by_id = {str(cut.get("id") or ""): cut for cut in cuts}
    rendered = 0
    failed = 0
    isolated_rendered = 0
    attached: set[str] = set()
    for record in proof_archive.get("records", []):
        status = str(record.get("status") or "pending")
        if status == "rendered":
            rendered += 1
        elif status == "failed":
            failed += 1
        cut_id = str(record.get("cutId") or "")
        cut = cuts_by_id.get(cut_id)
        if cut is None:
            continue
        attached.add(cut_id)
        comparison_image = (
            record.get("publicPath")
            if status == "rendered"
            and Path(str(record.get("outputPath") or "")).exists()
            else None
        )
        detail_parts = [
            "Isolated read-only Redshift grey render",
            f"frame {record.get('targetFrame')}",
            f"take {record.get('cameraTake') or record.get('take') or 'Main'}",
            (
                "proxy geometry evaluated by Redshift"
                if record.get("proxyObjects")
                else "hardware-preview failure retried in Redshift"
            ),
        ]
        if record.get("cameraFallbackToTake"):
            detail_parts.append("requested camera absent; effective take camera used")
        if record.get("error"):
            detail_parts.append(f"render failure: {record['error']}")
        cut.setdefault("lineage", []).append(
            {
                "kind": "camera_proof",
                "label": (
                    f"{record.get('camera') or record.get('cameraName') or 'Camera'}"
                    f" · Redshift · frame {record.get('targetFrame')}"
                ),
                "detail": " · ".join(detail_parts),
                "path": record.get("projectPath"),
                "projectPath": record.get("projectPath"),
                "comparisonImage": comparison_image,
                "confirmationMethod": "C4D Redshift grey camera and proxy proof",
                "evidence": "candidate" if status == "rendered" else "missing",
                "proofStatus": status,
                "redshiftProof": True,
                "proxyProof": bool(record.get("proxyObjects")),
                "strictLinked": False,
            }
        )
        for isolated in record.get("isolatedProofs", []):
            isolated_status = str(isolated.get("status") or "failed")
            image = isolated.get("publicPath")
            if (
                isolated_status != "rendered"
                or not image
                or not Path(str(isolated.get("outputPath") or "")).exists()
            ):
                continue
            isolated_rendered += 1
            cut["lineage"].append(
                {
                    "kind": "camera_proof",
                    "label": (
                        f"{isolated.get('camera') or 'Camera'} · "
                        f"isolated Redshift · frame {record.get('targetFrame')}"
                    ),
                    "detail": (
                        f"{isolated.get('detail') or 'Render-critical roots isolated to fit available memory'} · "
                        "asset/camera evidence only; omitted scene roots remain unverified"
                    ),
                    "path": record.get("projectPath"),
                    "projectPath": record.get("projectPath"),
                    "comparisonImage": image,
                    "confirmationMethod": (
                        "C4D Redshift isolated-root grey asset proof"
                    ),
                    "evidence": "candidate",
                    "proofStatus": "rendered_partial",
                    "redshiftProof": True,
                    "isolatedRootProof": True,
                    "strictLinked": False,
                }
            )
    return {
        "c4dRedshiftProofTargets": len(proof_archive.get("records", [])),
        "c4dRedshiftProofRendered": rendered,
        "c4dRedshiftProofFailed": failed,
        "c4dRedshiftProofCuts": len(attached),
        "c4dRedshiftIsolatedProofs": isolated_rendered,
    }


def apply_c4d_nth_running_recovery(
    cuts: list[dict[str, Any]],
    recovery_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach the dated NTH proxy reconstruction without overstating matches."""

    cuts_by_id = {str(cut.get("id") or ""): cut for cut in cuts}
    recovery_project = recovery_archive.get("recoveryProject")
    render_time_project = recovery_archive.get("renderTimeProject")
    attached = 0
    partial = 0
    mismatched = 0
    for record in recovery_archive.get("records", []):
        cut = cuts_by_id.get(str(record.get("cutId") or ""))
        if cut is None:
            continue
        output_path = Path(str(record.get("outputPath") or ""))
        comparison_image = (
            record.get("publicPath") if output_path.exists() else None
        )
        visual_status = str(record.get("visualStatus") or "unreviewed")
        partial += int(visual_status == "partial")
        mismatched += int(visual_status == "mismatch")
        attached += 1

        camera_node = next(
            (
                node
                for node in cut.get("lineage", [])
                if node.get("kind") == "camera"
            ),
            None,
        )
        if camera_node is not None:
            camera_node.update(
                {
                    "label": record.get("cameraName"),
                    "detail": (
                        "Render-time take camera · "
                        f"Take: {record.get('cameraTake')} · "
                        f"Render data: {record.get('cameraRenderData')} · "
                        f"frame {record.get('targetFrame')}"
                    ),
                    "path": render_time_project,
                    "projectPath": render_time_project,
                    "evidence": "confirmed",
                    "confirmationMethod": (
                        "March 19 render-time backup effective take camera"
                    ),
                }
            )

        cut.setdefault("lineage", []).append(
            {
                "kind": "camera_proof",
                "label": (
                    f"{record.get('cameraName')} · dated Redshift recovery · "
                    f"frame {record.get('targetFrame')}"
                ),
                "detail": record.get("notes"),
                "path": recovery_project,
                "projectPath": recovery_project,
                "comparisonImage": comparison_image,
                "confirmationMethod": (
                    "canonical-source visual comparison of dated C4D recovery"
                ),
                "evidence": (
                    "candidate"
                    if visual_status in {"partial", "mismatch"}
                    else "confirmed"
                ),
                "proofStatus": record.get("proofStatus"),
                "redshiftProof": True,
                "recoveryProof": True,
                "primaryRecoveryProof": True,
                "strictLinked": False,
                "visualVerificationStatus": visual_status,
                "visualElements": record.get("elements"),
                "canonicalSourceFrame": record.get("canonicalSourceFrame"),
            }
        )
        cut["c4dNthRunningRecovery"] = {
            **record,
            "recoveryProject": recovery_project,
            "renderTimeProject": render_time_project,
            "dependencyAudit": recovery_archive.get("dependencyAudit"),
        }
    return {
        "c4dNthRunningRecoveryCuts": attached,
        "c4dNthRunningRecoveryPartial": partial,
        "c4dNthRunningRecoveryMismatch": mismatched,
    }


def apply_c4d_camera_candidate_audits(
    cuts: list[dict[str, Any]],
    audit_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach visually ruled-out camera searches without implying a match."""

    records = {
        str(item.get("cutId") or ""): item
        for item in audit_archive.get("records", [])
        if item.get("cutId")
    }
    attached = 0
    tested = 0
    matched = 0
    missing_state = 0
    for cut in cuts:
        record = records.get(str(cut.get("id") or ""))
        if not record:
            continue
        attached += 1
        candidates = record.get("candidates", [])
        tested += len(candidates)
        matched += sum(
            item.get("status") == "visual_match" for item in candidates
        )
        if record.get("status") == "camera_state_not_retained":
            missing_state += 1
        cut["c4dCameraCandidateAudit"] = {
            **record,
            "generatedAt": audit_archive.get("generatedAt"),
            "authority": audit_archive.get("authority"),
        }
        cut.setdefault("lineage", []).append(
            {
                "kind": "camera_search",
                "label": (
                    f"{len(candidates)} retained camera"
                    f"{'s' if len(candidates) != 1 else ''} tested"
                ),
                "detail": (
                    f"{record.get('summary') or 'Retained cameras audited.'} · "
                    f"Next: {record.get('nextResolution') or 'recover camera state'}"
                ),
                "path": record.get("sourceProject"),
                "projectPath": record.get("sourceProject"),
                "evidence": "confirmed",
                "candidateAuditStatus": record.get("status"),
            }
        )
        for proof in record.get("proofs", []):
            image = proof.get("image")
            if not image:
                continue
            cut["lineage"].append(
                {
                    "kind": proof.get("kind") or "camera_proof",
                    "label": proof.get("label") or "Ruled-out C4D proof",
                    "detail": (
                        f"{proof.get('detail') or 'Visually compared and ruled out.'} · "
                        "Mismatch proof; not a canonical camera confirmation"
                    ),
                    "path": proof.get("path") or record.get("sourceProject"),
                    "projectPath": (
                        proof.get("projectPath")
                        or proof.get("path")
                        or record.get("sourceProject")
                    ),
                    "comparisonImage": image,
                    "confirmationMethod": "canonical-thumbnail visual comparison",
                    "evidence": "confirmed",
                    "proofStatus": "rendered_mismatch",
                    "recoveryProof": False,
                    "strictLinked": False,
                    "visualVerificationStatus": record.get("status"),
                    "candidateAuditStatus": record.get("status"),
                }
            )
    return {
        "c4dCameraCandidateAuditCuts": attached,
        "c4dCameraCandidatesTested": tested,
        "c4dCameraCandidateMatches": matched,
        "c4dCameraStateNotRetainedCuts": missing_state,
    }


def apply_c4d_source_link_audits(
    cuts: list[dict[str, Any]],
    audit_archive: dict[str, Any],
) -> dict[str, int]:
    """Flag conform render links disproven by direct export-frame comparison."""

    cuts_by_id = {str(cut.get("id") or ""): cut for cut in cuts}
    attached = 0
    false_links = 0
    for record in audit_archive.get("records", []):
        cut = cuts_by_id.get(str(record.get("cutId") or ""))
        if cut is None:
            continue
        attached += 1
        status = str(record.get("status") or "unreviewed")
        false_links += int(status == "source_render_link_false")
        cut["c4dSourceLinkAudit"] = {
            **record,
            "generatedAt": audit_archive.get("generatedAt"),
            "authority": audit_archive.get("authority"),
        }
        linked_path = str(record.get("linkedRenderPath") or "")
        for node in cut.get("lineage", []):
            node_path = str(node.get("path") or node.get("renderPath") or "")
            if (
                status == "source_render_link_confirmed"
                and node.get("kind") == "camera"
                and record.get("sourceProject")
                and node_path
                == str(Path(str(record["sourceProject"])).expanduser().resolve())
            ):
                position = record.get("cameraPosition") or {}
                rotation = record.get("cameraRotationRadians") or {}
                node.update(
                    {
                        "label": record.get("cameraName") or node.get("label"),
                        "detail": (
                            f"Exact production source camera · "
                            f"Take: {record.get('cameraTake') or 'Main'} · "
                            f"Render data: {record.get('cameraRenderData') or 'unnamed'} · "
                            f"Object: {record.get('cameraObjectPath') or record.get('cameraName')} · "
                            f"GUID: {record.get('cameraGuid') or 'unavailable'} · "
                            f"Lens: {record.get('cameraFocalLength')} mm · "
                            f"Position: {position.get('x'):.6f}, "
                            f"{position.get('y'):.6f}, {position.get('z'):.6f} · "
                            f"Rotation (rad): {rotation.get('x'):.6f}, "
                            f"{rotation.get('y'):.6f}, {rotation.get('z'):.6f}"
                        ),
                        "evidence": "confirmed",
                        "confirmationMethod": (
                            "exact_multiframe_redshift_source_match"
                        ),
                        "cameraObject": {
                            "name": record.get("cameraName"),
                            "objectPath": record.get("cameraObjectPath"),
                            "guid": record.get("cameraGuid"),
                            "typeId": record.get("cameraTypeId"),
                            "active": True,
                            "position": position,
                            "rotationRadians": rotation,
                            "focalLength": record.get(
                                "cameraFocalLength"
                            ),
                        },
                    }
                )
            if (
                status == "source_render_link_false"
                and node.get("kind") == "render_sequence"
                and node_path == linked_path
            ):
                node["evidence"] = "candidate"
                node["sourceRenderAuditStatus"] = status
                node["sourceRenderAuditDetail"] = record.get("summary")
                for tag in node.get("tags", []):
                    if tag.get("type") == "source_render":
                        tag["evidence"] = "candidate"
                        tag["label"] = "False Source Link"
                        tag["detail"] = record.get("summary")
        cut.setdefault("lineage", []).append(
            {
                "kind": "source_render_audit",
                "label": (
                    "False source-render link"
                    if status == "source_render_link_false"
                    else "Source-render audit"
                ),
                "detail": record.get("summary"),
                "path": record.get("authoritativeExportPath"),
                "comparisonImage": record.get("referenceImage"),
                "confirmationMethod": (
                    "final-to-export-to-raw-sequence visual comparison"
                ),
                "evidence": "confirmed",
                "sourceRenderAuditStatus": status,
                "authoritativeExportFrame": record.get(
                    "authoritativeExportFrame"
                ),
                "strictLinked": False,
            }
        )
    return {
        "c4dSourceLinkAuditCuts": attached,
        "c4dFalseSourceRenderLinks": false_links,
    }


def apply_production_redshift_confirmations(
    cuts: list[dict[str, Any]],
    confirmation_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach retained production references and saved-camera metadata.

    A source-sequence frame can confirm what production rendered, but it is
    not a camera proof from the identified project. Only a newly rendered
    camera test may enter the camera-proof gate.
    """

    cuts_by_id = {str(cut.get("id") or ""): cut for cut in cuts}
    attached = 0
    projects: set[str] = set()
    for record in confirmation_archive.get("records", []):
        if record.get("status") != "confirmed":
            continue
        cut = cuts_by_id.get(str(record.get("cutId") or ""))
        if cut is None:
            continue
        project_path = str(record.get("projectPath") or "")
        source_output = Path(
            str(record.get("sourceFrameOutputPath") or "")
        )
        if not project_path or not Path(project_path).exists():
            continue
        if not source_output.exists():
            continue
        attached += 1
        projects.add(project_path)
        position = record.get("cameraPosition") or {}
        camera_matrix = record.get("cameraMatrix") or {}
        camera_object = {
            "name": record.get("cameraName"),
            "objectPath": record.get("cameraPath"),
            "typeId": record.get("cameraTypeId"),
            "legacyRedshift": bool(record.get("cameraLegacyRedshift")),
            "active": True,
            "position": position,
            "matrix": camera_matrix,
            "focalLength": record.get("cameraFocalLength"),
        }
        camera_node = next(
            (
                node
                for node in cut.get("lineage", [])
                if node.get("kind") == "camera"
                and str(node.get("projectPath") or node.get("path") or "")
                == project_path
            ),
            None,
        )
        if camera_node is not None:
            camera_node.update(
                {
                    "label": record.get("cameraName"),
                    "detail": (
                        "Exact production Redshift camera · "
                        f"Take: {record.get('cameraTake') or 'Main'} · "
                        f"Render data: {record.get('cameraRenderData') or 'unnamed'} · "
                        f"Object: {record.get('cameraPath')} · "
                        f"Lens: {record.get('cameraFocalLength')} mm · "
                        f"Position: {position.get('x')}, "
                        f"{position.get('y')}, {position.get('z')}"
                    ),
                    "evidence": "confirmed",
                    "confirmationMethod": (
                        "exact_production_redshift_source_frame"
                    ),
                    "cameraObject": camera_object,
                }
            )
        cut.setdefault("lineage", []).append(
            {
                "kind": "render_reference",
                "label": (
                    f"{record.get('cameraName') or 'Camera'} · "
                    "retained production Redshift reference · "
                    f"frame {record.get('targetFrame')}"
                ),
                "detail": (
                    f"Exact canonical conform source {record.get('sourceId')} · "
                    f"Take: {record.get('cameraTake') or 'Main'} · "
                    f"Render data: {record.get('cameraRenderData') or 'unnamed'} · "
                    f"image metrics: {record.get('metrics')} · "
                    "reference only; not counted as a camera proof"
                ),
                "path": project_path,
                "projectPath": project_path,
                "comparisonImage": record.get("sourceFramePublicPath"),
                "confirmationMethod": (
                    "Retained production render reference tied to the source "
                    "sequence; does not prove a current render from this file."
                ),
                "evidence": "confirmed",
                "referenceStatus": "retained",
                "productionSourceReference": True,
                "sourceId": record.get("sourceId"),
                "targetFrame": record.get("targetFrame"),
                "strictLinked": False,
            }
        )
        live_geometry_path = Path(
            str(record.get("liveRedshiftGeometryProofPath") or "")
        )
        live_geometry_public = record.get(
            "liveRedshiftGeometryProofPublicPath"
        )
        if (
            record.get("liveRedshiftGeometryProofStatus") == "confirmed"
            and live_geometry_path.is_file()
            and live_geometry_public
        ):
            cut.setdefault("lineage", []).append(
                {
                    "kind": "camera_proof",
                    "label": (
                        f"{record.get('cameraName') or 'Camera'} · "
                        "live Redshift grey geometry · "
                        f"frame {record.get('targetFrame')}"
                    ),
                    "detail": (
                        "Fresh Redshift geometry render from the saved "
                        f"{record.get('cameraTake') or 'Main'} take and "
                        f"{record.get('cameraPath') or record.get('cameraName')} "
                        "camera. Neutral grey override isolates camera and "
                        "scene geometry; archived production Redshift remains "
                        "the authoritative material result."
                    ),
                    "path": (
                        record.get("recoveryProjectPath") or project_path
                    ),
                    "projectPath": project_path,
                    "comparisonImage": live_geometry_public,
                    "confirmationMethod": (
                        "fresh_live_redshift_grey_geometry_render"
                    ),
                    "evidence": "confirmed",
                    "proofStatus": "rendered",
                    "redshiftProof": True,
                    "liveRedshiftGeometryProof": True,
                    "productionSourceProof": False,
                    "sourceId": record.get("sourceId"),
                    "targetFrame": record.get("targetFrame"),
                    "strictLinked": False,
                }
            )
        cut["c4dProductionRedshiftConfirmation"] = {
            **record,
            "generatedAt": confirmation_archive.get("generatedAt"),
            "authority": confirmation_archive.get("authority"),
        }
    return {
        "c4dProductionRedshiftConfirmedCuts": attached,
        "c4dProductionRedshiftConfirmedProjects": len(projects),
    }


def apply_c4d_aec_camera_reviews(
    cuts: list[dict[str, Any]],
    review_archive: dict[str, Any],
) -> dict[str, int]:
    """Attach exact render-side AEC camera comparisons to shot lineage."""

    cuts_by_id = {str(cut.get("id") or ""): cut for cut in cuts}
    attached = 0
    selected = 0
    for record in review_archive.get("records", []):
        cut = cuts_by_id.get(str(record.get("cutId") or ""))
        if cut is None:
            continue
        attached += 1
        is_selected = bool(record.get("selected"))
        selected += int(is_selected)
        proof_status = str(record.get("proofStatus") or "failed")
        if proof_status == "rendered" and record.get("comparisonImage"):
            cut.setdefault("lineage", []).append(
                {
                    "kind": "camera_proof",
                    "label": (
                        f"{record.get('aecCameraName') or 'AEC camera'} · "
                        f"AEC · frame {record.get('targetFrame')}"
                    ),
                    "detail": record.get("detail"),
                    "path": record.get("projectPath"),
                    "projectPath": record.get("projectPath"),
                    "comparisonImage": record.get("comparisonImage"),
                    "confirmationMethod": (
                        "render-side AEC transform plus manual "
                        "final/source/proof comparison"
                    ),
                    "evidence": "confirmed",
                    "proofStatus": (
                        "rendered" if is_selected else "rendered_mismatch"
                    ),
                    "aecExactProof": True,
                    "aecReviewStatus": record.get("reviewStatus"),
                    "strictLinked": False,
                    "visualVerificationStatus": record.get("reviewStatus"),
                }
            )
        elif proof_status == "failed":
            cut.setdefault("lineage", []).append(
                {
                    "kind": "camera_search",
                    "label": (
                        f"{record.get('aecCameraName') or 'AEC camera'} · "
                        "proof failed"
                    ),
                    "detail": (
                        f"{record.get('detail') or ''} · "
                        f"{record.get('error') or 'render failed'}"
                    ),
                    "path": record.get("projectPath"),
                    "projectPath": record.get("projectPath"),
                    "evidence": "confirmed",
                    "aecExactProof": True,
                    "proofStatus": "failed",
                    "aecReviewStatus": record.get("reviewStatus"),
                    "strictLinked": False,
                }
            )
    return {
        "c4dAecCameraReviewRecords": attached,
        "c4dAecSelectedCameraMatches": selected,
    }


def apply_strict_c4d_verification(
    cuts: list[dict[str, Any]],
    visual_review_archive: dict[str, Any],
) -> dict[str, int]:
    """Require dependency health plus a manually matched camera proof.

    A rendered bitmap is only proof that Cinema 4D produced an image. It is
    not proof that the source camera, character, hair, wardrobe, or materials
    match the canonical cut. This pass keeps those claims separate.
    """

    element_keys = (
        "location",
        "camera",
        "character",
        "hair",
        "wardrobe",
        "materials",
    )
    reviews = visual_review_archive.get("reviews", {})
    status_counts: Counter[str] = Counter()
    strict_linked = 0
    for cut in cuts:
        if cut.get("isGap"):
            continue
        cut_id = str(cut.get("id") or "")
        review_source = reviews.get(cut_id) or {}
        review_status = str(review_source.get("status") or "unreviewed")
        nth_recovery = cut.get("c4dNthRunningRecovery") or {}
        if nth_recovery.get("visualStatus") in {"match", "partial", "mismatch"}:
            # This dated recovery is newer, frame-specific visual evidence than
            # the original proxy-only review.  Let it drive the compact drawer
            # while the strict gate below still independently requires a safe
            # proxy, dependency audit, and exact visual match.
            review_source = nth_recovery
            review_status = str(nth_recovery.get("visualStatus"))
        elements = {
            key: str(
                (review_source.get("elements") or {}).get(key)
                or "not_verifiable"
            )
            for key in element_keys
        }
        notes = str(review_source.get("notes") or "")
        health = cut.get("c4dLinkStatus") or {}
        proof = next(
            (
                node
                for node in cut.get("lineage", [])
                if node.get("kind") == "camera_proof"
                and node.get("primaryRecoveryProof")
                and str(node.get("proofStatus") or "").startswith("rendered")
                and node.get("comparisonImage")
            ),
            None,
        )
        if proof is None:
            proof = next(
            (
                node
                for node in cut.get("lineage", [])
                if node.get("kind") == "camera_proof"
                and node.get("recoveryProof")
                and node.get("proofStatus") == "rendered"
                and node.get("comparisonImage")
            ),
            None,
        )
        if proof is None:
            proof = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if node.get("kind") == "camera_proof"
                    and node.get("aecExactProof")
                    and node.get("proofStatus") == "rendered"
                    and node.get("comparisonImage")
                ),
                None,
            )
        if proof is None:
            proof = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if node.get("kind") == "camera_proof"
                    and node.get("redshiftProof")
                    and node.get("proofStatus") == "rendered"
                    and node.get("comparisonImage")
                ),
                None,
            )
        if proof is None:
            proof = next(
                (
                    node
                    for node in cut.get("lineage", [])
                    if node.get("kind") == "camera_proof"
                    and node.get("proofStatus") == "rendered"
                    and node.get("comparisonImage")
                ),
                None,
            )
        proof_linkage = dict(
            (proof or {}).get("linkageAudit") or {}
        )
        project_path = str(
            (proof or {}).get("projectPath")
            or health.get("projectPath")
            or ""
        )
        project_linked = bool(project_path and Path(project_path).exists())
        if proof_linkage:
            dependency_audited = True
            dependency_render_safe = (
                int(
                    proof_linkage.get("renderCriticalMissingFiles") or 0
                )
                == 0
            )
        else:
            dependency_audited = bool(health) and (
                health.get("status") != "audit_unavailable"
            )
            dependency_render_safe = (
                dependency_audited
                and int(health.get("renderCriticalMissingFiles") or 0) == 0
                and health.get("status")
                in {"fully_linked_confirmed", "render_safe_with_warnings"}
            )
        proxy_audit = cut.get("c4dProxyAudit") or {}
        proxy_render_safe = (
            proxy_audit.get("status") in {"not_used", "verified_rendered"}
        )
        camera_proof_rendered = bool(proof)
        visual_match = (
            review_status == "match"
            and all(
                elements[key] in {"match", "not_visible"}
                for key in element_keys
            )
        )
        is_strict_linked = all(
            (
                project_linked,
                dependency_audited,
                dependency_render_safe,
                proxy_render_safe,
                camera_proof_rendered,
                visual_match,
            )
        )
        blockers = []
        if not project_linked:
            blockers.append("source_project_missing")
        if not dependency_audited:
            blockers.append("dependency_audit_missing")
        elif not dependency_render_safe:
            blockers.append("render_critical_dependencies_missing")
        if not proxy_render_safe:
            proxy_status = str(proxy_audit.get("status") or "")
            blockers.append(
                "proxy_renderer_update_required"
                if proxy_status == "renderer_update_required"
                else "proxy_rebuild_required"
                if proxy_status == "rebuild_ready"
                else "proxy_audit_missing"
                if proxy_status in {"", "audit_unavailable"}
                else "proxy_unresolved"
            )
        if not camera_proof_rendered:
            blockers.append("camera_proof_missing")
        if not visual_match:
            blockers.append(
                "visual_review_pending"
                if review_status == "unreviewed"
                else "asset_visual_incomplete"
                if review_status in {"partial", "partial_match"}
                and str(elements.get("camera") or "").startswith("match")
                else "camera_or_asset_visual_mismatch"
            )
        remediation: list[str] = []
        if not project_linked:
            remediation.append(
                "Locate the exact source C4D project for the canonical render."
            )
        if not dependency_audited:
            remediation.append(
                "Run the saved-scene dependency and visibility audit."
            )
        elif not dependency_render_safe:
            exact_recoveries = (
                len(proof_linkage.get("recoveredExactFiles") or [])
                if proof_linkage
                else int(
                    health.get("renderCriticalExactRecoveries") or 0
                )
            )
            unresolved_files = (
                len(proof_linkage.get("missingExactFiles") or [])
                if proof_linkage
                else int(
                    health.get("renderCriticalUnresolvedFiles") or 0
                )
            )
            if exact_recoveries:
                remediation.append(
                    f"Relink {exact_recoveries} exact Dropbox dependenc"
                    f"{'y' if exact_recoveries == 1 else 'ies'} in a dated C4D copy."
                )
            if unresolved_files:
                remediation.append(
                    f"Recover or rebuild {unresolved_files} remaining render-critical "
                    f"file{'s' if unresolved_files != 1 else ''}."
                )
        proxy_status = str(proxy_audit.get("status") or "")
        if proxy_status == "renderer_update_required":
            remediation.append(
                "Update Redshift to a reader compatible with the proxy mesh, "
                "then render the exact proxy through the saved shot camera."
            )
        elif proxy_status == "rebuild_ready":
            remediation.append(
                "Regenerate the missing RS proxy from the recovered body, face, "
                "boots, and cloth sources, then render it through the saved camera."
            )
        elif proxy_status in {"unresolved", "audit_unavailable"}:
            remediation.append(
                "Resolve the active proxy or prove that the saved scene does not use one."
            )
        if not camera_proof_rendered:
            remediation.append(
                "Render a grey camera proof at the canonical source frame."
            )
        if not visual_match:
            failed_elements = [
                key
                for key in element_keys
                if elements[key]
                in {"partial", "mismatch", "missing", "not_verifiable"}
            ]
            remediation.append(
                "Visually match "
                + ", ".join(failed_elements)
                + " against the canonical thumbnail."
            )
        label = (
            "Fully linked + camera verified"
            if is_strict_linked
            else "Camera proof missing"
            if not camera_proof_rendered
            else "Visual review pending"
            if review_status == "unreviewed"
            else "Camera / assets do not fully match"
            if review_status == "mismatch"
            else "Camera / assets partially match"
            if review_status in {"partial", "partial_match"}
            else "C4D verification incomplete"
        )
        detail_parts = []
        if notes:
            detail_parts.append(notes)
        if blockers:
            detail_parts.append(
                "Blocking: " + ", ".join(item.replace("_", " ") for item in blockers)
            )
        verification = {
            "status": (
                "strictly_verified"
                if is_strict_linked
                else review_status
            ),
            "label": label,
            "detail": " · ".join(detail_parts),
            "strictLinked": is_strict_linked,
            "reviewedAt": visual_review_archive.get("reviewedAt"),
            "authority": visual_review_archive.get("authority"),
            "elements": elements,
            "notes": notes,
            "blockers": blockers,
            "remediation": remediation,
            "checks": {
                "projectLinked": project_linked,
                "dependencyAudited": dependency_audited,
                "dependencyRenderSafe": dependency_render_safe,
                "proxyRenderSafe": proxy_render_safe,
                "cameraProofRendered": camera_proof_rendered,
                "visualMatch": visual_match,
            },
            "cameraProof": proof.get("comparisonImage") if proof else None,
            "cameraName": proof.get("label") if proof else None,
        }
        cut["c4dVerification"] = verification
        if health:
            health["dependencyLabel"] = health.get("label")
            health["strictLinked"] = is_strict_linked
            health["verificationStatus"] = verification["status"]
            health["visualReview"] = {
                "status": review_status,
                "elements": elements,
                "notes": notes,
            }
            health["verificationBlockers"] = blockers
            if health.get("status") == "fully_linked_confirmed":
                health["label"] = (
                    "Fully linked + camera verified"
                    if is_strict_linked
                    else "Dependencies linked · camera not verified"
                )
        for node in cut.get("lineage", []):
            if node.get("kind") in {"cinema4d", "camera_proof"}:
                node["strictLinked"] = is_strict_linked
                node["visualVerificationStatus"] = verification["status"]
            if node.get("kind") == "cinema4d" and node.get("assetHealth"):
                node["assetHealth"]["label"] = health.get(
                    "label", verification["label"]
                )
                if not is_strict_linked:
                    node["assetHealth"]["status"] = (
                        "render_safe_with_warnings"
                        if dependency_render_safe
                        else health.get("status", "audit_unavailable")
                    )
        status_counts[review_status] += 1
        strict_linked += int(is_strict_linked)
    return {
        "c4dStrictLinkedCuts": strict_linked,
        # Keep the public "fully linked" count honest: it now means the full
        # dependency + camera + visual contract, not dependency health alone.
        "c4dFullyLinkedCuts": strict_linked,
        "c4dVisualMatchCuts": status_counts["match"],
        "c4dVisualPartialCuts": status_counts["partial"],
        "c4dVisualMismatchCuts": status_counts["mismatch"],
        "c4dVisualMissingProofCuts": status_counts["missing"],
        "c4dVisualUnreviewedCuts": status_counts["unreviewed"],
    }


def inventory_assets() -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter]:
    log("Indexing Dropbox creative projects and C4D render directories")
    assets = []
    counts: Counter[str] = Counter()
    render_dirs: dict[Path, dict[str, Any]] = {}
    for root, dirs, files in os.walk(ABSOLUTELY):
        root_path = Path(root)
        dirs[:] = [
            name
            for name in dirs
            if name not in {".git", ".cache", "node_modules", "__pycache__"}
        ]
        image_files = [
            name for name in files if Path(name).suffix.lower() in IMAGE_EXTENSIONS
        ]
        if image_files and "_renders" in root_path.parts:
            first = sorted(image_files)[0]
            aec_path = next(
                (
                    root_path / name
                    for name in sorted(files)
                    if Path(name).suffix.lower() == ".aec"
                ),
                None,
            )
            render_dirs[root_path] = {
                "id": f"render-{len(render_dirs) + 1:04d}",
                "kind": "render_sequence",
                "name": root_path.name,
                "path": str(root_path),
                "firstFrame": str(root_path / first),
                "frameCount": len(image_files),
                "embeddedProjectPrefix": embedded_project_prefix(image_files),
                "aecCamera": (
                    parse_aec_render_camera(aec_path) if aec_path else None
                ),
                **safe_stat(root_path),
            }
        for filename in files:
            path = root_path / filename
            extension = path.suffix.lower()
            if extension not in PROJECT_EXTENSIONS:
                continue
            kind = {
                ".c4d": "cinema4d",
                ".aep": "after_effects",
                ".prproj": "premiere",
            }[extension]
            stat = safe_stat(path)
            assets.append(
                {
                    "id": f"asset-{len(assets) + 1:05d}",
                    "kind": kind,
                    "name": filename,
                    "path": str(path),
                    "normalizedName": normalize_name(filename),
                    **stat,
                }
            )
            counts[extension] += 1
    assets.sort(key=lambda item: (item["kind"], item["name"].lower(), item["path"]))
    renders = sorted(render_dirs.values(), key=lambda item: item["path"])
    counts["render_sequences"] = len(renders)
    return assets, renders, counts


def match_render_projects(
    assets: list[dict[str, Any]],
    renders: list[dict[str, Any]],
    c4d_cameras: dict[str, Any] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    c4d_assets = [item for item in assets if item["kind"] == "cinema4d"]
    exact_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in c4d_assets:
        exact_index[asset["normalizedName"]].append(asset)
    matches: dict[str, list[dict[str, Any]]] = {}
    exact_count = 0
    for render in renders:
        normalized = normalize_name(render["name"])
        exact = exact_index.get(normalized, [])
        if exact:
            exact_count += 1
            matches[render["id"]] = [
                {"assetId": item["id"], "score": 1.0, "evidence": "confirmed"}
                for item in sorted(
                    exact, key=lambda item: item.get("modifiedAt") or "", reverse=True
                )[:3]
            ]
            continue
        candidates = [
            candidate
            for score, candidate in sorted(
                (
                    (
                        difflib.SequenceMatcher(
                            None, normalized, candidate
                        ).ratio(),
                        candidate,
                    )
                    for candidate in exact_index
                ),
                reverse=True,
            )
            if score >= 0.48
        ][:3]
        result = []
        for candidate in candidates:
            score = difflib.SequenceMatcher(None, normalized, candidate).ratio()
            for item in sorted(
                exact_index[candidate],
                key=lambda item: item.get("modifiedAt") or "",
                reverse=True,
            )[:1]:
                result.append(
                    {
                        "assetId": item["id"],
                        "score": round(score, 3),
                        "evidence": "strong_inference" if score >= 0.78 else "candidate",
                    }
                )
        matches[render["id"]] = result[:3]

    # Camera extraction is necessarily incomplete for this very large archive.
    # Preserve exact render-time AOV project stems even when a project has not
    # yet been opened/probed by the C4D camera bridge. Otherwise an older
    # camera-indexed revision can incorrectly beat the project explicitly
    # named by the rendered frames.
    camera_project_paths = {
        str(Path(str(item.get("projectPath") or "")).expanduser().resolve())
        for item in (c4d_cameras or {}).get("projects", [])
        if item.get("projectPath")
    }
    for render in renders:
        embedded_prefix_raw = str(render.get("embeddedProjectPrefix") or "")
        embedded_prefix = normalize_name(embedded_prefix_raw)
        if not embedded_prefix:
            continue
        embedded_versions = re.findall(
            r"v0*(\d+)", embedded_prefix_raw, flags=re.IGNORECASE
        )
        embedded_as_variant = bool(
            re.search(
                r"(?:^|[ _-])as$", embedded_prefix_raw, re.IGNORECASE
            )
        )
        for asset in c4d_assets:
            resolved_asset_path = str(
                Path(str(asset["path"])).expanduser().resolve()
            )
            if resolved_asset_path in camera_project_paths:
                continue
            project_stem_raw = Path(str(asset["path"])).stem
            project_name = normalize_name(project_stem_raw)
            project_versions = re.findall(
                r"v0*(\d+)", project_stem_raw, flags=re.IGNORECASE
            )
            versions_align = (
                not embedded_versions
                or not project_versions
                or embedded_versions[-1] == project_versions[-1]
            )
            project_as_variant = bool(
                re.search(
                    r"(?:^|[ _-])as$", project_stem_raw, re.IGNORECASE
                )
            )
            if (
                difflib.SequenceMatcher(
                    None, embedded_prefix, project_name
                ).ratio()
                < 0.94
                or not versions_align
                or embedded_as_variant != project_as_variant
            ):
                continue
            matches[render["id"]].append(
                {
                    "assetId": asset["id"],
                    "score": 1.0,
                    "evidence": "confirmed",
                    "matchKind": "frame_prefix",
                    "outputAlignment": "frame_prefix",
                    "embeddedProjectPrefix": embedded_prefix_raw,
                }
            )
    if not c4d_cameras:
        return matches, exact_count

    assets_by_path = {
        str(Path(item["path"]).expanduser().resolve()): item
        for item in c4d_assets
    }
    assets_by_id = {item["id"]: item for item in c4d_assets}

    def expanded_output_path(
        value: str, project_path: str, take_name: str | None
    ) -> str:
        result = str(value or "")
        result = re.sub(
            r"\$prj",
            Path(project_path).stem,
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            r"\$take",
            "" if not take_name or take_name == "Main" else take_name,
            result,
            flags=re.IGNORECASE,
        )
        return result

    def render_tail(value: str) -> list[str]:
        parts = [
            part
            for part in str(value).replace("\\", "/").split("/")
            if part and part != "."
        ]
        start = next(
            (
                index + 1
                for index, part in enumerate(parts)
                if normalize_name(part) == "renders"
            ),
            0,
        )
        return [normalize_name(part) for part in parts[start:] if normalize_name(part)]

    def output_alignment(render: dict[str, Any], output_path: str) -> str | None:
        actual = render_tail(str(render["path"]))
        output = render_tail(output_path)
        if not actual or not output:
            return None
        render_name = normalize_name(render["name"])
        # C4D's RDATA_PATH normally includes both the output directory and the
        # filename prefix.  The prefix often differs from the containing render
        # directory (for example ``3E_zoom out/3E_extra wide``), so compare the
        # directory portion independently instead of stripping it only when
        # both names happen to be identical.
        output_directory = output[:-1]
        if actual == output or actual == output_directory:
            return "exact_path"
        if render_name in {
            output[-1],
            output_directory[-1] if output_directory else "",
        }:
            return "render_name"
        similarity = difflib.SequenceMatcher(
            None, render_name, output[-1]
        ).ratio()
        if output_directory:
            similarity = max(
                similarity,
                difflib.SequenceMatcher(
                    None, render_name, output_directory[-1]
                ).ratio(),
            )
        return "similar_name" if similarity >= 0.86 else None

    output_matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for camera in c4d_cameras.get("projects", []):
        project_path = str(camera.get("projectPath") or "")
        asset = assets_by_path.get(
            str(Path(project_path).expanduser().resolve())
        )
        if not asset:
            continue
        records = []
        active_output = str(camera.get("outputPath") or "")
        if active_output:
            records.append(
                {
                    "outputPath": active_output,
                    "take": camera.get("activeTake"),
                    "renderData": camera.get("activeRenderData"),
                    "cameraName": camera.get("activeCamera"),
                    "cameraObject": camera.get("activeCameraObject"),
                }
            )
        for take in camera.get("takes", []):
            take_render = take.get("render") or {}
            if take_render.get("outputPath"):
                records.append(
                    {
                        "outputPath": take_render["outputPath"],
                        "take": take.get("name"),
                        "renderData": take.get("renderData"),
                        "cameraName": take.get("camera")
                        or camera.get("activeCamera"),
                        "cameraObject": take.get("cameraObject")
                        or camera.get("activeCameraObject"),
                    }
                )
        for render_data in camera.get("renderDatas", []):
            if render_data and render_data.get("outputPath"):
                records.append(
                    {
                        "outputPath": render_data["outputPath"],
                        "take": camera.get("activeTake"),
                        "renderData": render_data.get("name"),
                        "cameraName": camera.get("activeCamera"),
                        "cameraObject": camera.get("activeCameraObject"),
                    }
                )
        for record in records:
            expanded = expanded_output_path(
                str(record["outputPath"]),
                project_path,
                str(record.get("take") or ""),
            )
            for render in renders:
                alignment = output_alignment(render, expanded)
                if not alignment:
                    continue
                score = {
                    "exact_path": 1.0,
                    "render_name": 0.97,
                    "similar_name": 0.86,
                }[alignment]
                output_matches[render["id"]].append(
                    {
                        "assetId": asset["id"],
                        "score": score,
                        "evidence": (
                            "confirmed"
                            if alignment == "exact_path"
                            else "strong_inference"
                            if alignment == "render_name"
                            else "candidate"
                        ),
                        "matchKind": "render_output",
                        "outputAlignment": alignment,
                        "outputPath": str(record["outputPath"]),
                        "cameraTake": record.get("take"),
                        "cameraRenderData": record.get("renderData"),
                        "cameraName": record.get("cameraName"),
                        "cameraObject": record.get("cameraObject"),
                    }
                )
        project_name = normalize_name(Path(project_path).stem)
        for render in renders:
            render_name = normalize_name(render["name"])
            embedded_prefix_raw = str(
                render.get("embeddedProjectPrefix") or ""
            )
            embedded_prefix = normalize_name(embedded_prefix_raw)
            project_stem_raw = Path(project_path).stem
            embedded_as_variant = bool(
                re.search(r"(?:^|[ _-])as$", embedded_prefix_raw, re.IGNORECASE)
            )
            project_as_variant = bool(
                re.search(r"(?:^|[ _-])as$", project_stem_raw, re.IGNORECASE)
            )
            prefix_similarity = (
                difflib.SequenceMatcher(
                    None, embedded_prefix, project_name
                ).ratio()
                if embedded_prefix and project_name
                else 0.0
            )
            embedded_versions = re.findall(
                r"v0*(\d+)", embedded_prefix_raw, flags=re.IGNORECASE
            )
            project_versions = re.findall(
                r"v0*(\d+)", project_stem_raw, flags=re.IGNORECASE
            )
            versions_align = (
                not embedded_versions
                or not project_versions
                or embedded_versions[-1] == project_versions[-1]
            )
            if (
                prefix_similarity >= 0.94
                and versions_align
                and embedded_as_variant == project_as_variant
            ):
                main_take = next(
                    (
                        take
                        for take in camera.get("takes", [])
                        if take.get("name") == "Main"
                    ),
                    None,
                )
                output_matches[render["id"]].append(
                    {
                        "assetId": asset["id"],
                        "score": 1.0,
                        "evidence": "confirmed",
                        "matchKind": "frame_prefix",
                        "outputAlignment": "frame_prefix",
                        "outputPath": str(camera.get("outputPath") or ""),
                        "cameraTake": "Main",
                        "cameraRenderData": (
                            (main_take or {}).get("renderData")
                            or camera.get("activeRenderData")
                        ),
                        "cameraName": (
                            (main_take or {}).get("camera")
                            or camera.get("activeCamera")
                        ),
                        "cameraObject": (
                            (main_take or {}).get("cameraObject")
                            or camera.get("activeCameraObject")
                        ),
                        "embeddedProjectPrefix": embedded_prefix_raw,
                    }
                )
            for take in camera.get("takes", []):
                take_name = str(take.get("name") or "")
                take_normalized = normalize_name(take_name)
                if (
                    not project_name
                    or not take_normalized
                    or take_name == "Main"
                    or render_name != f"{project_name}{take_normalized}"
                ):
                    continue
                take_render = take.get("render") or {}
                output_matches[render["id"]].append(
                    {
                        "assetId": asset["id"],
                        "score": 1.0,
                        "evidence": "confirmed",
                        "matchKind": "project_take",
                        "outputAlignment": "project_take",
                        "outputPath": str(take_render.get("outputPath") or ""),
                        "cameraTake": take_name,
                        "cameraRenderData": take.get("renderData"),
                        "cameraName": take.get("camera")
                        or camera.get("activeCamera"),
                        "cameraObject": take.get("cameraObject")
                        or camera.get("activeCameraObject"),
                    }
                )
            if render_name != project_name:
                continue
            main_take = next(
                (
                    take
                    for take in camera.get("takes", [])
                    if take.get("name") == "Main"
                ),
                None,
            )
            output_matches[render["id"]].append(
                {
                    "assetId": asset["id"],
                    "score": 1.0,
                    "evidence": "confirmed",
                    "matchKind": "project_name",
                    "outputAlignment": "project_name",
                    "outputPath": str(camera.get("outputPath") or ""),
                    "cameraTake": "Main",
                    "cameraRenderData": (
                        (main_take or {}).get("renderData")
                        or camera.get("activeRenderData")
                    ),
                    "cameraName": (
                        (main_take or {}).get("camera")
                        or camera.get("activeCamera")
                    ),
                    "cameraObject": (
                        (main_take or {}).get("cameraObject")
                        or camera.get("activeCameraObject")
                    ),
                }
            )

    for render in renders:
        combined = [
            *matches.get(render["id"], []),
            *output_matches.get(render["id"], []),
        ]
        best_by_asset: dict[str, dict[str, Any]] = {}
        match_kind_rank = {
            # A project prefix embedded in the rendered frame filename is
            # immutable render-time evidence. Saved output settings can be
            # redirected in a later revision while still pointing at an older
            # render directory, so they must not outrank an exact frame prefix.
            "frame_prefix": 4,
            "render_output": 3,
            "project_take": 2,
            "project_name": 1,
        }
        for item in combined:
            current = best_by_asset.get(item["assetId"])
            if (
                current is None
                or float(item["score"]) > float(current["score"])
                or (
                    float(item["score"]) == float(current["score"])
                    and match_kind_rank.get(str(item.get("matchKind") or ""), 0)
                    > match_kind_rank.get(
                        str(current.get("matchKind") or ""), 0
                    )
                )
            ):
                best_by_asset[item["assetId"]] = item
        matches[render["id"]] = sorted(
            best_by_asset.values(),
            key=lambda item: (
                float(item["score"]),
                match_kind_rank.get(str(item.get("matchKind") or ""), 0),
                (assets_by_id.get(item["assetId"]) or {}).get("modifiedAt") or "",
            ),
            reverse=True,
        )[:3]
    return matches, exact_count


def best_assets_for_planned_shot(
    shot: dict[str, Any], assets: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    c4d_assets = [item for item in assets if item["kind"] == "cinema4d"]
    query = normalize_name(shot.get("fileName") or shot["id"])
    if not query:
        return []
    scored = []
    for asset in c4d_assets:
        name = asset["normalizedName"]
        if not name:
            continue
        score = difflib.SequenceMatcher(None, query, name).ratio()
        if query in name or name in query:
            score = max(score, 0.92)
        shot_tokens = re.findall(r"[a-z]+\d+|\d+[a-z]+|\d+|[a-z]+", shot["id"].lower())
        if shot_tokens and any(token in name for token in shot_tokens if len(token) >= 2):
            score += 0.04
        if score >= 0.46:
            scored.append((min(score, 1.0), asset))
    scored.sort(
        key=lambda pair: (pair[0], pair[1].get("modifiedAt") or ""), reverse=True
    )
    return [
        {
            "assetId": asset["id"],
            "score": round(score, 3),
            "evidence": (
                "confirmed"
                if score >= 0.985
                else "strong_inference"
                if score >= 0.76
                else "candidate"
            ),
        }
        for score, asset in scored[:4]
    ]


def load_resolve() -> dict[str, Any]:
    export_path = DATA_DIR / "resolve-export.json"
    try:
        result = run([sys.executable, str(APP_ROOT / "scripts" / "export_resolve.py")])
        log(result.stdout.strip())
    except Exception as error:
        log(f"Resolve live export unavailable; using last archive if present ({error})")
    if export_path.exists():
        return json.loads(export_path.read_text(encoding="utf-8"))
    return {"project": "Paracosm", "timelines": [], "renderJobs": []}


def load_creative_app_archive(name: str) -> dict[str, Any]:
    path = DATA_DIR / name
    if not path.exists():
        return {"projects": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"projects": []}
    except (OSError, json.JSONDecodeError) as error:
        log(f"Ignoring unreadable creative-app archive {path.name} ({error})")
        return {"projects": []}


def active_after_effects_layer(
    comp: dict[str, Any], source_time: float
) -> dict[str, Any] | None:
    active = []
    for layer in comp.get("layers", []):
        if (
            not layer.get("enabled", True)
            or layer.get("adjustmentLayer")
            or layer.get("guideLayer")
            or not (layer.get("sourcePath") or layer.get("sourceKind") == "composition")
        ):
            continue
        try:
            in_point = float(layer["inPoint"])
            out_point = float(layer["outPoint"])
            index = int(layer.get("index") or 99999)
        except (KeyError, TypeError, ValueError):
            continue
        range_start, range_end = sorted((in_point, out_point))
        if range_start <= source_time < range_end:
            source_path = str(layer.get("sourcePath") or "").lower()
            source_name = str(
                layer.get("sourceName") or layer.get("name") or ""
            ).lower()
            if layer.get("sourceKind") == "composition" or "/_renders/" in source_path:
                priority = 0
            elif Path(source_path).suffix.lower() in IMAGE_EXTENSIONS:
                priority = 1
            elif re.search(r"\b(snow|grain|dust|overlay|matte)\b", source_name):
                priority = 4
            else:
                priority = 2
            active.append((priority, index, layer))
    return min(active, key=lambda item: (item[0], item[1]))[2] if active else None


def after_effects_comp_by_name(
    project: dict[str, Any], name: str | None
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in project.get("compositions", [])
            if item.get("name") == name
        ),
        None,
    )


def after_effects_layer_chain(
    project: dict[str, Any],
    comp: dict[str, Any],
    source_time: float,
    depth: int = 0,
) -> list[dict[str, Any]]:
    if depth >= 8:
        return []
    layer = active_after_effects_layer(comp, source_time)
    if not layer:
        return []
    chain = [{"comp": comp, "layer": layer, "sourceTime": source_time}]
    if layer.get("sourceKind") != "composition":
        return chain
    child = after_effects_comp_by_name(project, layer.get("sourceName"))
    if not child:
        return chain
    try:
        stretch = float(layer.get("stretch") or 100)
        start_time = float(layer.get("startTime") or 0)
        child_time = (source_time - start_time) * 100 / stretch
    except (TypeError, ValueError, ZeroDivisionError):
        return chain
    return chain + after_effects_layer_chain(
        project, child, child_time, depth + 1
    )


def after_effects_nested_edit_points(
    project: dict[str, Any],
    comp: dict[str, Any],
    depth: int = 0,
) -> list[float]:
    if depth >= 8:
        return []
    points = []
    for layer in comp.get("layers", []):
        if (
            not layer.get("enabled", True)
            or layer.get("adjustmentLayer")
            or layer.get("guideLayer")
            or not (layer.get("sourcePath") or layer.get("sourceKind") == "composition")
        ):
            continue
        try:
            in_point = float(layer["inPoint"])
            out_point = float(layer["outPoint"])
        except (KeyError, TypeError, ValueError):
            continue
        range_start, range_end = sorted((in_point, out_point))
        points.extend([range_start, range_end])
        if layer.get("sourceKind") != "composition":
            continue
        child = after_effects_comp_by_name(project, layer.get("sourceName"))
        if not child:
            continue
        try:
            stretch = float(layer.get("stretch") or 100)
            start_time = float(layer.get("startTime") or 0)
        except (TypeError, ValueError):
            continue
        for child_point in after_effects_nested_edit_points(
            project, child, depth + 1
        ):
            mapped = start_time + child_point * stretch / 100
            if range_start < mapped < range_end:
                points.append(mapped)
    return points


def after_effects_edit_mappings(
    primary_blocks: list[dict[str, Any]], after_effects: dict[str, Any]
) -> list[dict[str, Any]]:
    """Map final blocks into the source edit comps and their topmost footage layers."""

    specs = [
        ("GG", "gg_edit", None),
        ("IJDKYY", "paracosm ijdkyy", None),
        ("TH", "th_edit", None),
    ]
    projects = after_effects.get("projects", [])
    mappings = []
    for section_code, project_needle, block_needle in specs:
        section_blocks = [
            item
            for item in primary_blocks
            if item.get("sectionCode") == section_code
            and (
                block_needle is None
                or block_needle in str(item.get("name") or "").lower()
            )
        ]
        if not section_blocks:
            continue
        project = next(
            (
                item
                for item in projects
                if project_needle in str(item.get("path") or "").lower()
            ),
            None,
        )
        if section_code == "TH":
            block_targets = {
                normalize_name(
                    Path(str(item.get("path") or item.get("name") or "")).name
                )
                for item in section_blocks
            }
            exact_render_projects = [
                item
                for item in projects
                if any(
                    normalize_name(Path(str(output.get("file") or "")).name)
                    in block_targets
                    for queue_item in item.get("renderQueue", [])
                    for output in queue_item.get("outputs", [])
                    if output.get("file")
                )
            ]
            if exact_render_projects:
                project = max(
                    exact_render_projects,
                    key=lambda item: (
                        safe_stat(Path(str(item.get("path") or ""))).get(
                            "modifiedAt"
                        )
                        or ""
                    ),
                )
        if not project:
            continue
        final_start = min(float(item["start"]) for item in section_blocks)
        final_end = max(float(item["end"]) for item in section_blocks)
        final_duration = final_end - final_start
        block_targets = {
            normalize_name(Path(str(item.get("path") or item.get("name") or "")).name)
            for item in section_blocks
        }
        matching_queue_items = [
            queue_item
            for queue_item in project.get("renderQueue", [])
            if any(
                normalize_name(Path(str(output.get("file") or "")).name) in block_targets
                for output in queue_item.get("outputs", [])
                if output.get("file")
            )
        ]

        queue_comp_names = {
            str(item.get("compName") or "")
            for item in project.get("renderQueue", [])
            if any(
                section_code.lower() in str(output.get("file") or "").lower()
                for output in item.get("outputs", [])
            )
        }
        comps = project.get("compositions", [])
        if not comps:
            continue
        if section_code == "GG":
            gg_comps = [
                item
                for item in comps
                if item.get("name") == "Paracosm WIP_120525"
            ]
            comp = max(
                gg_comps or comps,
                key=lambda item: int(item.get("numLayers") or 0),
            )
        else:
            comp = min(
                comps,
                key=lambda item: (
                    0 if item.get("name") in queue_comp_names else 1,
                    abs(float(item.get("duration") or 0) - final_duration),
                    -int(item.get("numLayers") or 0),
                ),
            )
        try:
            comp_duration = float(comp.get("duration") or 0)
        except (TypeError, ValueError):
            continue
        exact_queue_item = next(
            (
                item
                for item in reversed(matching_queue_items)
                if item.get("compName") == comp.get("name")
            ),
            None,
        )
        first_section_block = min(
            section_blocks, key=lambda item: float(item["start"])
        )
        source_start = (
            float(exact_queue_item.get("timeSpanStart") or 0)
            + float(first_section_block.get("sourceIn") or 0)
            if exact_queue_item
            else 0.0
            if section_code in {"GG", "IJDKYY"}
            else max(0.0, comp_duration - final_duration)
        )
        source_end = source_start + final_duration

        points = {source_start, source_end}
        for value in after_effects_nested_edit_points(project, comp):
            if source_start < value < source_end:
                points.add(value)

        segments = []
        ordered = sorted(points)
        for index, point in enumerate(ordered[:-1]):
            next_point = ordered[index + 1]
            if next_point - point < 0.001:
                continue
            layer_chain = after_effects_layer_chain(
                project, comp, point + (next_point - point) / 2
            )
            if not layer_chain:
                continue
            layer = layer_chain[-1]["layer"]
            final_point = final_start + point - source_start
            final_next = final_start + next_point - source_start
            layer_identity = (
                layer_chain[-1]["comp"].get("name"),
                layer.get("index"),
                layer.get("sourcePath"),
                layer.get("sourceName"),
            )
            if segments and segments[-1]["layerIdentity"] == layer_identity:
                segments[-1]["finalEnd"] = final_next
                segments[-1]["sourceEnd"] = next_point
                continue
            segments.append(
                {
                    "finalStart": final_point,
                    "finalEnd": final_next,
                    "sourceStart": point,
                    "sourceEnd": next_point,
                    "layer": layer,
                    "layerChain": layer_chain,
                    "layerIdentity": layer_identity,
                }
            )
        if segments:
            mappings.append(
                {
                    "sectionCode": section_code,
                    "projectPath": project.get("path"),
                    "projectName": Path(project["path"]).name,
                    "project": project,
                    "comp": comp,
                    "finalStart": final_start,
                    "finalEnd": final_end,
                    "sourceStart": source_start,
                    "sourceEnd": source_end,
                    "segments": segments,
                }
            )
    return mappings


def exact_after_effects_block_mappings(
    blocks: list[dict[str, Any]], after_effects: dict[str, Any]
) -> list[dict[str, Any]]:
    """Map baked Premiere clips to the exact AE render-queue span that made them."""

    mappings = []
    for block in blocks:
        target = normalize_name(
            Path(str(block.get("path") or block.get("name") or "")).name
        )
        if not target:
            continue
        match = None
        for project in after_effects.get("projects", []):
            for queue_item in reversed(project.get("renderQueue", [])):
                if any(
                    normalize_name(Path(str(output.get("file") or "")).name)
                    == target
                    for output in queue_item.get("outputs", [])
                    if output.get("file")
                ):
                    match = (project, queue_item)
                    break
            if match:
                break
        if not match:
            continue
        project, queue_item = match
        comp = after_effects_comp_by_name(project, queue_item.get("compName"))
        if not comp:
            continue
        try:
            final_start = float(block["start"])
            final_end = float(block["end"])
            source_start = float(queue_item.get("timeSpanStart") or 0) + float(
                block.get("sourceIn") or 0
            )
        except (KeyError, TypeError, ValueError):
            continue
        source_end = source_start + final_end - final_start
        points = {source_start, source_end}
        for value in after_effects_nested_edit_points(project, comp):
            if source_start < value < source_end:
                points.add(value)

        segments = []
        ordered = sorted(points)
        for index, point in enumerate(ordered[:-1]):
            next_point = ordered[index + 1]
            if next_point - point < 0.001:
                continue
            layer_chain = after_effects_layer_chain(
                project, comp, point + (next_point - point) / 2
            )
            if not layer_chain:
                continue
            layer = layer_chain[-1]["layer"]
            final_point = final_start + point - source_start
            final_next = final_start + next_point - source_start
            layer_identity = (
                layer_chain[-1]["comp"].get("name"),
                layer.get("index"),
                layer.get("sourcePath"),
                layer.get("sourceName"),
            )
            if segments and segments[-1]["layerIdentity"] == layer_identity:
                segments[-1]["finalEnd"] = final_next
                segments[-1]["sourceEnd"] = next_point
                continue
            segments.append(
                {
                    "finalStart": final_point,
                    "finalEnd": final_next,
                    "sourceStart": point,
                    "sourceEnd": next_point,
                    "layer": layer,
                    "layerChain": layer_chain,
                    "layerIdentity": layer_identity,
                }
            )
        if segments:
            mappings.append(
                {
                    "sectionCode": block.get("sectionCode") or "UNK",
                    "projectPath": project.get("path"),
                    "projectName": Path(project["path"]).name,
                    "project": project,
                    "comp": comp,
                    "finalStart": final_start,
                    "finalEnd": final_end,
                    "sourceStart": source_start,
                    "sourceEnd": source_end,
                    "segments": segments,
                    "premiereBlockId": block.get("id"),
                    "exactRenderQueueMatch": True,
                }
            )
    return mappings


def after_effects_source_edit_boundaries(
    mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    boundaries = []
    for mapping in mappings:
        for segment in mapping["segments"]:
            layer = segment["layer"]
            comp = segment["layerChain"][-1]["comp"]
            boundaries.append(
                {
                    "time": segment["finalStart"],
                    "evidence": "after_effects_source_edit",
                    "detail": (
                        f"{comp.get('name') or 'AE comp'} · "
                        f"L{layer.get('index')} · "
                        f"{layer.get('sourceName') or layer.get('name')}"
                    ),
                }
            )
    return boundaries


def after_effects_segment_for_cut(
    cut: dict[str, Any], mappings: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    midpoint = float(cut["start"]) + float(cut["duration"]) / 2
    for mapping in mappings:
        if not (mapping["finalStart"] <= midpoint < mapping["finalEnd"]):
            continue
        for segment in mapping["segments"]:
            if segment["finalStart"] <= midpoint < segment["finalEnd"]:
                return mapping, segment
    return None


def after_effects_source_frame(
    layer: dict[str, Any], layer_source_time: float
) -> tuple[str, int | None]:
    source_path = normalize_local_media_path(str(layer.get("sourcePath") or ""))
    if not source_path or Path(source_path).suffix.lower() not in IMAGE_EXTENSIONS:
        return source_path, None
    match = re.search(r"(\d+)(\.[^.]+)$", source_path)
    if not match:
        return source_path, None
    try:
        first_frame = int(match.group(1))
        frame_rate = float(layer.get("sourceFrameRate") or 0)
        stretch = float(layer.get("stretch") or 100)
        start_time = float(layer.get("startTime") or 0)
        offset = max(0, round((layer_source_time - start_time) * 100 / stretch * frame_rate))
    except (TypeError, ValueError, ZeroDivisionError):
        return source_path, None
    frame = first_frame + offset
    candidate = (
        source_path[: match.start(1)]
        + str(frame).zfill(len(match.group(1)))
        + match.group(2)
    )
    if Path(candidate).exists():
        return candidate, frame
    for distance in (1, 2):
        for nearby_frame in (frame - distance, frame + distance):
            nearby = (
                source_path[: match.start(1)]
                + str(nearby_frame).zfill(len(match.group(1)))
                + match.group(2)
            )
            if Path(nearby).exists():
                return nearby, nearby_frame
    return source_path, frame


def best_after_effects_comp(
    planned: dict[str, Any], project: dict[str, Any]
) -> tuple[float, dict[str, Any]] | None:
    query = normalize_name(planned.get("fileName") or planned["id"])
    if not query:
        return None
    scored = []
    for comp in project.get("compositions", []):
        candidate = normalize_name(comp.get("name") or "")
        if not candidate:
            continue
        score = difflib.SequenceMatcher(None, query, candidate).ratio()
        if query in candidate or candidate in query:
            score = max(score, 0.92)
        layer_names = [
            normalize_name(
                layer.get("sourcePath")
                or layer.get("sourceName")
                or layer.get("name")
                or ""
            )
            for layer in comp.get("layers", [])
            if layer.get("enabled", True)
        ]
        if any(query in layer or layer in query for layer in layer_names if layer):
            score = max(score, 0.88)
        scored.append((score, comp))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0] if scored else None


def after_effects_render_project_for_block(
    block: dict[str, Any], archive: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    target = normalize_name(block.get("path") or block["name"])
    matches = []
    for project in archive.get("projects", []):
        for queue_item in project.get("renderQueue", []):
            if any(
                target
                and normalize_name(output.get("file") or "")
                and (
                    target in normalize_name(output.get("file") or "")
                    or normalize_name(output.get("file") or "") in target
                )
                for output in queue_item.get("outputs", [])
            ):
                modified = safe_stat(Path(project["path"])).get("modifiedAt") or ""
                matches.append((modified, project, queue_item))
    if not matches:
        return None
    _, project, queue_item = sorted(matches, key=lambda item: item[0])[0]
    return project, queue_item


def render_job_for_block(
    block: dict[str, Any], resolve: dict[str, Any]
) -> dict[str, Any] | None:
    target_name = Path(block.get("path") or block["name"]).name.lower()
    jobs = []
    for job in resolve.get("renderJobs", []):
        output = str(
            job.get("OutputFilename")
            or job.get("OutputFileName")
            or job.get("RenderJobName")
            or ""
        ).lower()
        if output and (
            output == target_name
            or Path(output).stem == Path(target_name).stem
            or Path(target_name).stem in Path(output).stem
        ):
            jobs.append(job)
    return jobs[-1] if jobs else None


def resolve_item_for_cut(
    block: dict[str, Any],
    cut: dict[str, Any],
    job: dict[str, Any],
    resolve: dict[str, Any],
) -> dict[str, Any] | None:
    timeline_name = str(job.get("TimelineName") or job.get("Timeline") or "")
    timeline = next(
        (
            item
            for item in resolve.get("timelines", [])
            if item.get("name") == timeline_name
        ),
        None,
    )
    if not timeline:
        return None
    try:
        fps = float(job.get("FrameRate") or resolve.get("frameRate") or 24)
    except (TypeError, ValueError):
        fps = 24.0
    mark_in = float(job.get("MarkIn") or timeline.get("startFrame") or 0)
    midpoint = cut["start"] + cut["duration"] / 2
    source_frame = mark_in + (midpoint - block["start"]) * fps
    matches = []
    for track in timeline.get("tracks", []):
        for item in track.get("items", []):
            if float(item.get("start") or 0) <= source_frame < float(item.get("end") or 0):
                matches.append((int(track.get("index") or 0), item))
    if not matches:
        return None
    track_index, item = sorted(matches, key=lambda pair: pair[0], reverse=True)[0]
    result = dict(item)
    result["_trackIndex"] = track_index
    result["_timelineName"] = timeline_name
    result["_timelineSourceFrame"] = source_frame
    result["_frameRate"] = fps
    return result


def resolve_source_frame_path(item: dict[str, Any]) -> tuple[str, int | None]:
    source_path = str(item.get("filePath") or "")
    if Path(source_path).suffix.lower() not in IMAGE_EXTENSIONS:
        return source_path, None
    try:
        source_start = int(item.get("sourceStartFrame"))
        timeline_source = float(item.get("_timelineSourceFrame"))
        timeline_start = float(item.get("start"))
        frame_number = source_start + max(0, int(round(timeline_source - timeline_start)))
    except (TypeError, ValueError):
        frame_number = None
    range_match = re.search(r"\[(\d+)-(\d+)\](\.[^.]+)$", source_path)
    if range_match and frame_number is not None:
        width = len(range_match.group(1))
        candidate = (
            source_path[: range_match.start()]
            + str(frame_number).zfill(width)
            + range_match.group(3)
        )
        return (candidate if Path(candidate).exists() else source_path), frame_number
    if frame_number is not None:
        concrete, _ = numbered_sequence_frame(source_path, 0)
        match = re.search(r"(\d+)(\.[^.]+)$", concrete)
        if match:
            candidate = (
                concrete[: match.start(1)]
                + str(frame_number).zfill(len(match.group(1)))
                + match.group(2)
            )
            return (candidate if Path(candidate).exists() else source_path), frame_number
    return source_path, frame_number


def concrete_sequence_frame(source_path: str, frame_number: int) -> str:
    range_match = re.search(r"\[(\d+)-(\d+)\](\.[^.]+)$", source_path)
    if range_match:
        candidate = (
            source_path[: range_match.start()]
            + str(frame_number).zfill(len(range_match.group(1)))
            + range_match.group(3)
        )
        return candidate
    match = re.search(r"(\d+)(\.[^.]+)$", source_path)
    if not match:
        return source_path
    return (
        source_path[: match.start(1)]
        + str(frame_number).zfill(len(match.group(1)))
        + match.group(2)
    )


def resolve_image_conform_segments(
    timeline: dict[str, Any],
    final_start: float,
    final_end: float,
    mark_in: float,
    frame_rate: float,
    section_code: str,
    evidence: str,
) -> list[dict[str, Any]]:
    image_items = []
    for track in timeline.get("tracks", []):
        for item in track.get("items", []):
            source_path = str(item.get("filePath") or "")
            if Path(source_path).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image_items.append(
                {
                    **item,
                    "_trackIndex": int(track.get("index") or 0),
                }
            )
    source_end = mark_in + (final_end - final_start) * frame_rate
    points = {mark_in, source_end}
    for item in image_items:
        start = max(mark_in, float(item.get("start") or 0))
        end = min(source_end, float(item.get("end") or 0))
        if start < end:
            points.update((start, end))
    segments: list[dict[str, Any]] = []
    ordered = sorted(points)
    for index, point in enumerate(ordered[:-1]):
        next_point = ordered[index + 1]
        midpoint = point + (next_point - point) / 2
        active = [
            item
            for item in image_items
            if float(item.get("start") or 0) <= midpoint
            < float(item.get("end") or 0)
        ]
        if not active:
            continue
        item = max(active, key=lambda candidate: candidate["_trackIndex"])
        try:
            source_start_frame = int(item.get("sourceStartFrame")) + int(
                round(point - float(item.get("start") or 0))
            )
        except (TypeError, ValueError):
            continue
        source_duration = max(1, int(round(next_point - point)))
        source_path = str(item.get("filePath") or "")
        segment = {
            "id": "",
            "sectionCode": section_code,
            "finalStart": final_start + (point - mark_in) / frame_rate,
            "finalEnd": final_start + (next_point - mark_in) / frame_rate,
            "sourceSystem": "resolve",
            "sourceEdit": timeline.get("name") or "Resolve timeline",
            "sourcePath": source_path,
            "sourceFirstFramePath": concrete_sequence_frame(
                source_path, source_start_frame
            ),
            "sourceStartFrame": source_start_frame,
            "sourceEndFrame": source_start_frame + source_duration - 1,
            "sourceFrameRate": frame_rate,
            "sourceTrack": item["_trackIndex"],
            "playBackwards": False,
            "evidence": evidence,
        }
        identity = (
            source_path,
            item["_trackIndex"],
            evidence,
        )
        if (
            segments
            and segments[-1].get("_identity") == identity
            and abs(float(segments[-1]["finalEnd"]) - segment["finalStart"]) < 1e-5
            and int(segments[-1]["sourceEndFrame"]) + 1 == source_start_frame
        ):
            segments[-1]["finalEnd"] = segment["finalEnd"]
            segments[-1]["sourceEndFrame"] = segment["sourceEndFrame"]
        else:
            segment["_identity"] = identity
            segments.append(segment)
    for segment in segments:
        segment.pop("_identity", None)
    return segments


def premiere_image_conform_segments(
    premiere: dict[str, Any],
    start: float,
    end: float,
    section_code: str,
    frame_rate: float = 24.0,
) -> list[dict[str, Any]]:
    def image_sequence_identity(path: str) -> tuple[str, str, str]:
        """Treat numbered still files from one sequence as one conform source."""

        normalized = normalize_local_media_path(path)
        match = re.search(r"(\d+)(\.[^.]+)$", normalized)
        if not match:
            return (str(Path(normalized).parent), Path(normalized).name, "")
        return (
            str(Path(normalized).parent),
            Path(normalized).name[: match.start(1)],
            match.group(2).lower(),
        )

    segments: list[dict[str, Any]] = []
    frame_count = max(0, int(round((end - start) * frame_rate)))
    for frame_index in range(frame_count):
        final_start = start + frame_index / frame_rate
        final_end = min(end, start + (frame_index + 1) / frame_rate)
        terminal = premiere_terminal_source(
            premiere,
            str(premiere.get("sequence") or "Paracosm Full Copy 01"),
            final_start + (final_end - final_start) / 2,
        )
        if not terminal:
            continue
        item = terminal["item"]
        source_path = normalize_local_media_path(str(item.get("path") or ""))
        if Path(source_path).suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        source_frame_path, source_frame = numbered_sequence_frame(
            source_path, float(terminal.get("sourceTime") or 0), frame_rate
        )
        if source_frame is None:
            continue
        identity = (
            image_sequence_identity(source_path),
            bool(item.get("playBackwards")),
            " → ".join(
                str(value.get("sequence") or "")
                for value in terminal.get("sequenceChain", [])
                if value.get("sequence")
            ),
        )
        segment = {
            "id": "",
            "sectionCode": section_code,
            "finalStart": final_start,
            "finalEnd": final_end,
            "sourceSystem": "premiere_nested",
            "sourceEdit": " → ".join(
                str(value.get("sequence") or "")
                for value in terminal.get("sequenceChain", [])
                if value.get("sequence")
            ),
            "sourcePath": source_path,
            "sourceFirstFramePath": source_frame_path,
            "sourceStartFrame": source_frame,
            "sourceEndFrame": source_frame,
            "sourceFrameRate": frame_rate,
            "sourceTrack": item.get("track"),
            "playBackwards": bool(item.get("playBackwards")),
            "evidence": "confirmed",
        }
        if (
            segments
            and segments[-1].get("_identity") == identity
            and abs(float(segments[-1]["finalEnd"]) - final_start) < 1e-5
        ):
            segments[-1]["finalEnd"] = final_end
            segments[-1]["sourceEndFrame"] = source_frame
        else:
            segment["_identity"] = identity
            segments.append(segment)
    for segment in segments:
        segment.pop("_identity", None)
    return segments


def after_effects_image_conform_segments(
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    result = []
    for segment in mapping.get("segments", []):
        midpoint = float(segment["sourceStart"]) + (
            float(segment["sourceEnd"]) - float(segment["sourceStart"])
        ) / 2
        chain = after_effects_layer_chain(
            mapping["project"], mapping["comp"], midpoint
        )
        if not chain:
            continue
        layer = chain[-1]["layer"]
        source_path = normalize_local_media_path(str(layer.get("sourcePath") or ""))
        if Path(source_path).suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        start_chain = after_effects_layer_chain(
            mapping["project"],
            mapping["comp"],
            float(segment["sourceStart"]) + 1e-5,
        )
        end_chain = after_effects_layer_chain(
            mapping["project"],
            mapping["comp"],
            max(float(segment["sourceStart"]), float(segment["sourceEnd"]) - 1e-5),
        )
        if not start_chain or not end_chain:
            continue
        start_path, start_frame = after_effects_source_frame(
            start_chain[-1]["layer"], float(start_chain[-1]["sourceTime"])
        )
        end_path, end_frame = after_effects_source_frame(
            end_chain[-1]["layer"], float(end_chain[-1]["sourceTime"])
        )
        if start_frame is None or end_frame is None:
            continue
        result.append(
            {
                "id": "",
                "sectionCode": mapping["sectionCode"],
                "finalStart": float(segment["finalStart"]),
                "finalEnd": float(segment["finalEnd"]),
                "sourceSystem": "after_effects",
                "sourceEdit": (
                    f"{Path(mapping['projectPath']).name} · "
                    f"{mapping['comp'].get('name') or 'Comp'}"
                ),
                "sourcePath": source_path,
                "sourceFirstFramePath": start_path,
                "sourceStartFrame": start_frame,
                "sourceEndFrame": end_frame,
                "sourceFrameRate": float(
                    layer.get("sourceFrameRate") or mapping["comp"].get("frameRate") or 24
                ),
                "sourceTrack": layer.get("index"),
                "playBackwards": end_frame < start_frame,
                "evidence": "confirmed",
            }
        )
    return result


def th_visual_conform_segments(
    archive: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the TH conform from direct final/edit/render frame matches."""

    result = []
    for interval in archive.get("intervals", []):
        terminal = interval.get("terminalSource") or {}
        midpoint_path = Path(str(terminal.get("midpointFramePath") or ""))
        if not midpoint_path.exists():
            continue
        midpoint_match = re.search(r"(\d+)(\.[^.]+)$", midpoint_path.name)
        if not midpoint_match:
            continue
        prefix = midpoint_path.name[: midpoint_match.start(1)]
        suffix = midpoint_match.group(2).lower()
        files = sorted(
            (
                path
                for path in midpoint_path.parent.iterdir()
                if path.is_file()
                and path.suffix.lower() == suffix
                and (
                    (candidate_match := re.search(
                        r"(\d+)(\.[^.]+)$", path.name
                    ))
                    is not None
                )
                and path.name[: candidate_match.start(1)] == prefix
            ),
            key=lambda path: int(
                re.search(r"(\d+)(\.[^.]+)$", path.name).group(1)
            ),
        )
        if not files:
            continue
        first_match = re.search(r"(\d+)(\.[^.]+)$", files[0].name)
        last_match = re.search(r"(\d+)(\.[^.]+)$", files[-1].name)
        first_frame = int(first_match.group(1))
        last_frame = int(last_match.group(1))
        source_start = max(
            first_frame, int(terminal.get("sourceStartFrame") or first_frame)
        )
        source_end = min(
            last_frame, int(terminal.get("sourceEndFrame") or last_frame)
        )
        start_path = midpoint_path.parent / (
            prefix
            + str(source_start).zfill(len(first_match.group(1)))
            + first_match.group(2)
        )
        result.append(
            {
                "id": "",
                "sectionCode": "TH",
                "finalStart": float(interval["finalStart"]),
                "finalEnd": float(interval["finalEnd"]),
                "sourceSystem": "after_effects_visual_conform",
                "sourceEdit": "TH_0427.mp4 · direct final-frame alignment",
                "sourcePath": str(files[0]),
                "sourceFirstFramePath": str(start_path),
                "sourceStartFrame": source_start,
                "sourceEndFrame": source_end,
                "sourceFrameRate": float(
                    terminal.get("sourceFrameRate") or 24
                ),
                "sourceTrack": None,
                "playBackwards": False,
                "evidence": "confirmed",
                "visualMatch": {
                    "sourceEditPath": archive.get("sourceEditPath"),
                    "sourceEditTime": interval.get("sourceEditTime"),
                    "midpointFramePath": str(midpoint_path),
                    "siftInliers": terminal.get("siftInliers"),
                    "siftGoodMatches": terminal.get("siftGoodMatches"),
                },
            }
        )
    return result


def build_conform_manifest(
    premiere: dict[str, Any],
    resolve: dict[str, Any],
    after_effects_mappings: list[dict[str, Any]],
    th_visual_matches: dict[str, Any],
    final_frame_rate: float,
) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    primary_by_code = {
        block["sectionCode"]: block
        for block in premiere.get("primaryBlocks", [])
        if block.get("sectionCode")
    }

    nd_block = primary_by_code.get("ND")
    if nd_block:
        nd_job = render_job_for_block(nd_block, resolve)
        nd_timeline = next(
            (
                timeline
                for timeline in resolve.get("timelines", [])
                if timeline.get("name") == (nd_job or {}).get("TimelineName")
            ),
            None,
        )
        if nd_job and nd_timeline:
            segments.extend(
                resolve_image_conform_segments(
                    nd_timeline,
                    float(nd_block["start"]),
                    float(nd_block["end"]),
                    float(nd_job.get("MarkIn") or nd_timeline.get("startFrame") or 0),
                    float(nd_job.get("FrameRate") or resolve.get("frameRate") or 24),
                    "ND",
                    "confirmed",
                )
            )

    nth_block = primary_by_code.get("NTH")
    if nth_block:
        segments.extend(
            premiere_image_conform_segments(
                premiere,
                float(nth_block["start"]),
                float(nth_block["end"]),
                "NTH",
            )
        )

    na_blocks = [
        block
        for block in premiere.get("primaryBlocks", [])
        if block.get("sectionCode") == "NA"
    ]
    na_long = next(
        (
            block
            for block in na_blocks
            if "na_0419" in str(block.get("name") or "").lower()
        ),
        None,
    )
    na_timeline = next(
        (
            timeline
            for timeline in resolve.get("timelines", [])
            if timeline.get("name") == "Timeline 13"
        ),
        None,
    )
    if na_long and na_timeline:
        na_job = next(
            (
                job
                for job in reversed(resolve.get("renderJobs", []))
                if job.get("TimelineName") == "Timeline 13"
            ),
            None,
        )
        segments.extend(
            resolve_image_conform_segments(
                na_timeline,
                float(na_long["start"]),
                float(na_long["end"]),
                float((na_job or {}).get("MarkIn") or na_timeline.get("startFrame") or 0),
                float((na_job or {}).get("FrameRate") or resolve.get("frameRate") or 24),
                "NA",
                "strong_inference",
            )
        )

    for mapping in after_effects_mappings:
        segments.extend(after_effects_image_conform_segments(mapping))
    segments.extend(th_visual_conform_segments(th_visual_matches))

    segments.sort(
        key=lambda item: (
            float(item["finalStart"]),
            float(item["finalEnd"]),
            item["sourceSystem"],
        )
    )
    # A source-layer interval shorter than half an output frame cannot be
    # represented as an independent clip in the 23.976 fps Premiere conform.
    # Keep it in the manifest as an audited subframe event, but do not pretend
    # that it is a visible terminal-source shot.
    minimum_picture_duration = 0.5 / final_frame_rate
    omitted_subframe_events = [
        {
            **segment,
            "reason": "subframe_interval_below_half_output_frame",
        }
        for segment in segments
        if float(segment["finalEnd"]) - float(segment["finalStart"])
        < minimum_picture_duration
    ]
    segments = [
        segment
        for segment in segments
        if float(segment["finalEnd"]) - float(segment["finalStart"])
        >= minimum_picture_duration
    ]
    for index, segment in enumerate(segments, start=1):
        segment["id"] = f"SRC-{index:03d}"
        segment["finalStart"] = round(float(segment["finalStart"]), 6)
        segment["finalEnd"] = round(float(segment["finalEnd"]), 6)
    for event in omitted_subframe_events:
        event["finalStart"] = round(float(event["finalStart"]), 6)
        event["finalEnd"] = round(float(event["finalEnd"]), 6)

    manifest = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "premiereProject": str(PREMIERE_PROJECT),
        "baseSequence": premiere.get("sequence"),
        "referenceMovie": str(REFERENCE_MOV),
        "frameRate": final_frame_rate,
        "blocks": premiere.get("primaryBlocks", []),
        "segments": segments,
        "omittedSubframeEvents": omitted_subframe_events,
        "summary": {
            "segments": len(segments),
            "omittedSubframeEvents": len(omitted_subframe_events),
            "confirmed": sum(
                1 for item in segments if item.get("evidence") == "confirmed"
            ),
            "strongInference": sum(
                1
                for item in segments
                if item.get("evidence") == "strong_inference"
            ),
            "sections": dict(Counter(item["sectionCode"] for item in segments)),
        },
    }
    (DATA_DIR / "conform-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def apply_conform_verification(
    manifest: dict[str, Any], verification: dict[str, Any]
) -> dict[str, Any]:
    """Attach archived final/source comparison evidence to conform segments."""

    matches = {
        str(item.get("segmentId")): item
        for item in verification.get("matches", [])
        if item.get("segmentId")
    }
    for segment in manifest.get("segments", []):
        match = matches.get(str(segment.get("id")))
        if not match:
            continue
        segment["verification"] = {
            key: match[key]
            for key in (
                "score",
                "luminanceCorrelation",
                "edgeCorrelation",
                "evidence",
                "sourceFramePath",
                "finalImage",
                "sourceImage",
                "pairImage",
            )
            if key in match
        }
    manifest["summary"]["framePairsArchived"] = len(matches)
    manifest["summary"]["framePairsVisuallyConfirmed"] = sum(
        1
        for item in matches.values()
        if item.get("evidence") == "visually_confirmed"
    )
    (DATA_DIR / "conform-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def best_render_for_planned_shot(
    shot: dict[str, Any], renders: list[dict[str, Any]]
) -> tuple[float, dict[str, Any]] | None:
    query = normalize_name(shot.get("fileName") or shot["id"])
    if not query:
        return None
    scored = []
    for render in renders:
        name = normalize_name(render["name"])
        score = difflib.SequenceMatcher(None, query, name).ratio()
        if query in name or name in query:
            score = max(score, 0.92)
        if score >= 0.46:
            scored.append((score, render))
    scored.sort(
        key=lambda pair: (pair[0], pair[1].get("modifiedAt") or ""), reverse=True
    )
    return scored[0] if scored else None


def closest_planned_shot(
    cut: dict[str, Any],
    block: dict[str, Any] | None,
    shots: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not block:
        return None
    section_shots = [shot for shot in shots if int(shot["scene"]) == block["scene"]]
    if not section_shots:
        return None
    midpoint = cut["start"] + cut["duration"] / 2
    if block["scene"] == 6:
        progress = (midpoint - block["start"]) / max(block["duration"], 0.001)
        index = min(len(section_shots) - 1, max(0, int(progress * len(section_shots))))
        return section_shots[index]
    timed = [shot for shot in section_shots if shot["start"] is not None]
    for shot in timed:
        if shot["start"] <= midpoint < (shot["end"] or shot["start"] + 0.01):
            return shot
    return min(timed, key=lambda shot: abs((shot["start"] or 0) - midpoint)) if timed else None


def make_cuts(
    duration: float,
    boundaries: list[float],
    boundary_evidence: dict[float, dict[str, Any]],
    blocks: list[dict[str, Any]],
    premiere: dict[str, Any],
    shots: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    renders: list[dict[str, Any]],
    render_matches: dict[str, list[dict[str, Any]]],
    resolve: dict[str, Any],
    after_effects: dict[str, Any],
    after_effects_candidates: dict[str, Any],
    after_effects_mappings: list[dict[str, Any]],
    frame_matches: dict[str, Any],
    c4d_cameras: dict[str, Any],
    conform: dict[str, Any],
) -> list[dict[str, Any]]:
    asset_by_id = {item["id"]: item for item in assets}
    render_by_path = {
        str(Path(item["path"]).expanduser().resolve()): item for item in renders
    }
    ae_projects_by_path = {
        str(Path(item["path"]).expanduser().resolve()): item
        for item in after_effects.get("projects", [])
        if item.get("path")
    }
    cameras_by_path = {
        str(Path(item["projectPath"]).expanduser().resolve()): item
        for item in c4d_cameras.get("projects", [])
        if item.get("projectPath")
    }
    frame_matches_by_start = {
        round(float(item["cutStart"]), 4): item
        for item in frame_matches.get("matches", [])
        if item.get("cutStart") is not None
    }
    conform_segments = conform.get("segments", [])

    def append_c4d_camera(
        cut: dict[str, Any],
        best: dict[str, Any],
        detail: str,
        render: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        asset = asset_by_id[best["assetId"]]
        cut["lineage"].append(
            {
                "kind": "cinema4d",
                "label": asset["name"],
                "detail": f"{detail} · score {best['score']:.3f}",
                "path": asset["path"],
                "evidence": best["evidence"],
            }
        )
        camera = cameras_by_path.get(str(Path(asset["path"]).resolve()))
        aec_camera = (render or {}).get("aecCamera") or {}
        active_camera = (
            aec_camera.get("activeCamera")
            or best.get("cameraName")
            or (camera.get("activeCamera") if camera else None)
        )
        if active_camera:
            camera_object = (
                aec_camera.get("activeCameraObject")
                or best.get("cameraObject")
                or (camera or {}).get("activeCameraObject")
                or {}
            )
            output_path = str(
                best.get("outputPath") or (camera or {}).get("outputPath") or ""
            )
            output_alignment = str(best.get("outputAlignment") or "")
            render_alignment = bool(output_alignment)
            if render and not render_alignment:
                render_name = normalize_name(render["name"])
                project_name = normalize_name(asset["name"])
                output_name = normalize_name(output_path)
                render_alignment = bool(
                    render_name
                    and (
                        render_name in output_name
                        or (output_name and output_name in render_name)
                        or ("$prj" in output_path.lower() and render_name == project_name)
                    )
                )
            camera_evidence = (
                "confirmed"
                if aec_camera.get("activeCamera")
                or output_alignment
                in {
                    "exact_path",
                    "frame_prefix",
                    "project_take",
                    "project_name",
                }
                else "strong_inference"
                if output_alignment == "render_name"
                else best["evidence"]
                if render and render_alignment
                else "candidate"
            )
            detail_parts = [
                (
                    "Render data: "
                    f"{best.get('cameraRenderData') or (camera or {}).get('activeRenderData') or 'unnamed'}"
                ),
                f"Take: {best.get('cameraTake') or (camera or {}).get('activeTake') or 'Main'}",
                (
                    "Render-output alignment: exact path"
                    if output_alignment == "exact_path"
                    else (
                        "Render/project alignment: embedded frame prefix "
                        f"{best.get('embeddedProjectPrefix')}"
                    )
                    if output_alignment == "frame_prefix"
                    else "Render/project alignment: exact project + take name"
                    if output_alignment == "project_take"
                    else "Render/project alignment: exact project basename"
                    if output_alignment == "project_name"
                    else "Render-output alignment: render name"
                    if output_alignment == "render_name"
                    else "Render-output alignment: matched"
                    if render_alignment
                    else "Render-output alignment: not yet matched"
                ),
            ]
            if aec_camera.get("activeCamera"):
                detail_parts[0] = (
                    "Render-time camera recorded by Cinema 4D AEC metadata"
                )
                detail_parts[1] = (
                    f"Composition: {aec_camera.get('composition') or render['name']}"
                )
                detail_parts[2] = (
                    f"AEC evidence: {aec_camera.get('path')}"
                )
            if camera_object.get("objectPath"):
                detail_parts.append(f"Object: {camera_object['objectPath']}")
            if camera_object.get("guid"):
                detail_parts.append(f"GUID: {camera_object['guid']}")
            if camera_object.get("focalLength") is not None:
                detail_parts.append(f"Lens: {camera_object['focalLength']} mm")
            position = camera_object.get("position") or {}
            if all(axis in position for axis in ("x", "y", "z")):
                detail_parts.append(
                    "Position: "
                    f"{float(position['x']):.2f}, "
                    f"{float(position['y']):.2f}, "
                    f"{float(position['z']):.2f}"
                )
            rotation = camera_object.get("rotationRadians") or {}
            if all(axis in rotation for axis in ("x", "y", "z")):
                detail_parts.append(
                    "Rotation (rad): "
                    f"{float(rotation['x']):.4f}, "
                    f"{float(rotation['y']):.4f}, "
                    f"{float(rotation['z']):.4f}"
                )
            rotation_degrees = camera_object.get("rotationDegrees") or {}
            if all(axis in rotation_degrees for axis in ("x", "y", "z")):
                detail_parts.append(
                    "Rotation (deg): "
                    f"{float(rotation_degrees['x']):.3f}, "
                    f"{float(rotation_degrees['y']):.3f}, "
                    f"{float(rotation_degrees['z']):.3f}"
                )
            if output_path:
                detail_parts.append(f"Output: {output_path}")
            cut["lineage"].append(
                {
                    "kind": "camera",
                    "label": active_camera,
                    "detail": " · ".join(detail_parts),
                    "path": asset["path"],
                    "evidence": camera_evidence,
                }
            )
        else:
            cut["lineage"].append(
                {
                    "kind": "camera",
                    "label": "Active render camera pending",
                    "detail": (
                        "Must be confirmed from render settings or a matched test render"
                    ),
                    "path": asset["path"],
                    "evidence": "candidate",
                }
            )
        return asset

    cuts = []
    for index, start in enumerate(boundaries):
        end = boundaries[index + 1] if index + 1 < len(boundaries) else duration
        midpoint = start + (end - start) / 2
        containing = [
            block
            for block in blocks
            if block["start"] - 0.2 <= midpoint <= block["end"] + 0.2
        ]
        block = (
            max(containing, key=lambda item: int(item.get("track") or 0))
            if containing
            else None
        )
        section_block = block
        if block and block.get("sectionCode") == "UNK":
            section_block = next(
                (
                    item
                    for item in sorted(
                        containing, key=lambda candidate: int(candidate.get("track") or 0)
                    )
                    if item.get("sectionCode") != "UNK"
                ),
                block,
            )
        boundary_record = boundary_evidence.get(
            round(float(start), 6),
            {
                "kind": "visual_boundary",
                "detail": "Reference-film scene boundary candidate",
            },
        )
        cut = {
            "id": f"CUT-{index + 1:03d}",
            "index": index + 1,
            "start": round(start, 6),
            "end": round(end, 6),
            "duration": round(end - start, 6),
            "timecode": timecode(start),
            "endTimecode": timecode(end),
            "thumbnail": f"/archive/cuts/CUT-{index + 1:03d}.jpg",
            "boundaryEvidence": boundary_record["kind"],
            "boundaryDetail": boundary_record["detail"],
            "verification": (
                "source_edit_confirmed"
                if boundary_record["kind"]
                in {
                    "resolve_source_edit",
                    "premiere_source_edit",
                    "source_media_edit",
                    "after_effects_source_edit",
                    "source_conform",
                }
                else "machine_detected"
            ),
            "blockId": block["id"] if block else None,
            "sectionCode": section_block["sectionCode"] if block else "GAP",
            "sectionName": section_block["sectionName"] if block else "Editorial gap",
            "isGap": block is None,
            "plannedShotId": None,
            "confidence": "candidate",
            "lineage": [],
            "sourceSegments": [
                segment
                for segment in conform_segments
                if float(segment["finalStart"]) < end
                and float(segment["finalEnd"]) > start
            ],
        }
        conform_frame_match = next(
            (
                segment.get("verification")
                for segment in cut["sourceSegments"]
                if segment.get("sectionCode") == cut["sectionCode"]
                and float(segment["finalStart"]) <= midpoint
                < float(segment["finalEnd"])
                and segment.get("verification")
            ),
            None,
        )
        planned = closest_planned_shot(cut, section_block, shots)
        if planned:
            cut["plannedShotId"] = planned["id"]
        direct_render = None
        direct_c4d = None

        cut["lineage"].append(
            {
                "kind": "reference",
                "label": "Frame.io ground truth",
                "detail": "Paracosm 050726 / local original",
                "path": str(REFERENCE_MOV),
                "evidence": "confirmed",
            }
        )
        if not block:
            cut["lineage"].append(
                {
                    "kind": "premiere_gap",
                    "label": "No active picture block",
                    "detail": "Intentional editorial gap in Paracosm Full Copy 01",
                    "path": str(PREMIERE_PROJECT),
                    "evidence": "confirmed",
                }
            )
            cut["confidence"] = "confirmed"
            cuts.append(cut)
            continue
        if block:
            cut["lineage"].append(
                {
                    "kind": "premiere",
                    "label": block["name"],
                    "detail": f"V{block['track']} · {timecode(block['start'])}–{timecode(block['end'])}",
                    "path": block.get("path") or str(PREMIERE_PROJECT),
                    "projectPath": str(PREMIERE_PROJECT),
                    "evidence": "confirmed",
                }
            )
            supporting_export_block = None
            if (
                Path(str(block.get("path") or "")).suffix.lower()
                not in VIDEO_EXTENSIONS
            ):
                supporting_export_block = next(
                    (
                        item
                        for item in sorted(
                            containing,
                            key=lambda candidate: int(
                                candidate.get("track") or 0
                            ),
                            reverse=True,
                        )
                        if item.get("id") != block.get("id")
                        and Path(str(item.get("path") or "")).suffix.lower()
                        in VIDEO_EXTENSIONS
                        and Path(
                            normalize_local_media_path(
                                str(item.get("path") or "")
                            )
                        ).exists()
                    ),
                    None,
                )
            if supporting_export_block:
                cut["supportingPremiereExportBlockId"] = (
                    supporting_export_block["id"]
                )
                cut["lineage"].append(
                    {
                        "kind": "premiere_export",
                        "label": supporting_export_block["name"],
                        "detail": (
                            f"Concrete V{supporting_export_block['track']} "
                            "section export beneath the active nested sequence; "
                            "archived as an editorial comparison frame"
                        ),
                        "path": supporting_export_block["path"],
                        "projectPath": str(PREMIERE_PROJECT),
                        "evidence": "confirmed",
                    }
                )
            premiere_source = premiere_terminal_source(
                premiere,
                str(premiere.get("sequence") or "Paracosm Full Copy 01"),
                midpoint,
            )
            if premiere_source:
                terminal_item = premiere_source["item"]
                terminal_path = str(terminal_item.get("path") or "")
                chain_label = " → ".join(
                    str(item.get("name") or item.get("sequence") or "Nested sequence")
                    for item in premiere_source.get("sequenceChain", [])
                )
                cut["lineage"].append(
                    {
                        "kind": "premiere_sequence",
                        "label": chain_label or terminal_item.get("name") or "Premiere source",
                        "detail": (
                            "Recursively flattened from the visible track in "
                            "Paracosm Full Copy 01"
                        ),
                        "path": terminal_path or str(PREMIERE_PROJECT),
                        "evidence": "confirmed",
                    }
                )
                if Path(terminal_path).suffix.lower() in IMAGE_EXTENSIONS:
                    source_frame_path, source_frame_number = numbered_sequence_frame(
                        terminal_path,
                        float(premiere_source.get("sourceTime") or 0),
                    )
                    cut["premiereConform"] = {
                        "sourcePath": terminal_path,
                        "sourceFramePath": source_frame_path,
                        "sourceFrame": source_frame_number,
                        "sourceTime": premiere_source.get("sourceTime"),
                        "sequenceChain": premiere_source.get("sequenceChain", []),
                    }
                    terminal_render = render_by_path.get(
                        str(Path(terminal_path).expanduser().resolve().parent)
                    )
                    if terminal_render:
                        cut["lineage"].append(
                            {
                                "kind": "render_sequence",
                                "label": terminal_render["name"],
                                "detail": (
                                    f"{terminal_render.get('frameCount', 0)} frames · "
                                    "direct nested-Premiere source"
                                ),
                                "path": terminal_render["path"],
                                "evidence": "confirmed",
                            }
                        )
                        linked = render_matches.get(terminal_render["id"], [])
                        if linked:
                            append_c4d_camera(
                                cut,
                                linked[0],
                                "Project matched from the nested Premiere render folder",
                                terminal_render,
                            )
            job = render_job_for_block(block, resolve)
            if job:
                timeline_name = (
                    job.get("TimelineName")
                    or job.get("Timeline")
                    or job.get("RenderJobName")
                    or "Resolve timeline"
                )
                cut["lineage"].append(
                    {
                        "kind": "resolve",
                        "label": str(timeline_name),
                        "detail": f"Resolve render job → {block['name']}",
                        "path": str(RESOLVE_DB),
                        "evidence": "confirmed",
                    }
                    )
                resolve_item = resolve_item_for_cut(block, cut, job, resolve)
                if resolve_item:
                    source_path = resolve_item.get("filePath") or ""
                    cut["lineage"].append(
                        {
                            "kind": "resolve_media",
                            "label": resolve_item.get("name") or Path(source_path).name,
                            "detail": "Direct Resolve timeline source at this cut",
                            "path": source_path or str(RESOLVE_DB),
                            "evidence": "confirmed",
                        }
                    )
                    try:
                        resolve_media_time = float(
                            resolve_item.get("sourceStartTime") or 0
                        ) + (
                            float(resolve_item.get("_timelineSourceFrame") or 0)
                            - float(resolve_item.get("start") or 0)
                        ) / float(resolve_item.get("_frameRate") or 24)
                    except (TypeError, ValueError, ZeroDivisionError):
                        resolve_media_time = 0.0
                    cut["resolveMediaExport"] = {
                        "timeline": resolve_item.get("_timelineName"),
                        "track": resolve_item.get("_trackIndex"),
                        "exportPath": source_path,
                        "sourceTime": resolve_media_time,
                    }
                    if Path(source_path).suffix.lower() in IMAGE_EXTENSIONS:
                        source_frame_path, source_frame_number = (
                            resolve_source_frame_path(resolve_item)
                        )
                        cut["resolveConform"] = {
                            "timeline": resolve_item.get("_timelineName"),
                            "track": resolve_item.get("_trackIndex"),
                            "sourcePath": source_path,
                            "sourceFramePath": source_frame_path,
                            "sourceFrame": source_frame_number,
                            "timelineSourceFrame": resolve_item.get(
                                "_timelineSourceFrame"
                            ),
                        }
                        source_parent = Path(source_path).parent
                        resolve_render = render_by_path.get(
                            str(source_parent.expanduser().resolve())
                        )
                        if resolve_render:
                            cut["lineage"].append(
                                {
                                    "kind": "render_sequence",
                                    "label": resolve_render["name"],
                                    "detail": (
                                        f"{resolve_render.get('frameCount', 0)} frames · "
                                        "direct Resolve source"
                                    ),
                                    "path": resolve_render["path"],
                                    "evidence": "confirmed",
                                }
                            )
                            linked = render_matches.get(resolve_render["id"], [])
                            if linked:
                                append_c4d_camera(
                                    cut,
                                    linked[0],
                                    "Project matched from the Resolve source folder",
                                    resolve_render,
                                )
            if block.get("sectionCode") == "NA":
                ae_render_candidate = after_effects_render_project_for_block(
                    block, after_effects_candidates
                )
                if ae_render_candidate:
                    candidate_project, queue_item = ae_render_candidate
                    cut["lineage"].append(
                        {
                            "kind": "after_effects",
                            "label": Path(candidate_project["path"]).name,
                            "detail": (
                                "Nearest surviving render-queue project for this "
                                "source export; exact Apr 20 project state is not "
                                "present locally"
                            ),
                            "path": candidate_project["path"],
                            "evidence": "strong_inference",
                        }
                    )
                    cut["lineage"].append(
                        {
                            "kind": "after_effects_comp",
                            "label": queue_item.get("compName") or "AE composition",
                            "detail": (
                                "Render queue explicitly targets "
                                f"{block.get('name')}"
                            ),
                            "path": candidate_project["path"],
                            "evidence": "strong_inference",
                        }
                    )
        visual_conform_segment = next(
            (
                segment
                for segment in cut["sourceSegments"]
                if segment.get("sourceSystem")
                == "after_effects_visual_conform"
                and float(segment["finalStart"]) <= midpoint
                < float(segment["finalEnd"])
            ),
            None,
        )
        if visual_conform_segment:
            visual_project = next(
                (
                    project
                    for project in after_effects.get("projects", [])
                    if "paracosm (converted)"
                    in str(project.get("path") or "").lower()
                ),
                None,
            )
            if visual_project:
                cut["lineage"].append(
                    {
                        "kind": "after_effects",
                        "label": Path(visual_project["path"]).name,
                        "detail": (
                            "Later consolidated source edit; TH_0427 render "
                            "matches the final reference frame-for-frame"
                        ),
                        "path": visual_project["path"],
                        "evidence": "confirmed",
                    }
                )
            cut["lineage"].append(
                {
                    "kind": "after_effects_comp",
                    "label": "TH_0427.mp4 source-edit state",
                    "detail": (
                        "Baked source edit aligned directly to the final "
                        "23.976 fps reference"
                    ),
                    "path": str(
                        (
                            visual_conform_segment.get("visualMatch") or {}
                        ).get("sourceEditPath")
                        or visual_project["path"]
                        if visual_project
                        else visual_conform_segment["sourcePath"]
                    ),
                    "evidence": "confirmed",
                }
            )
            source_frame = int(visual_conform_segment["sourceStartFrame"]) + int(
                round(
                    (midpoint - float(visual_conform_segment["finalStart"]))
                    * float(visual_conform_segment["sourceFrameRate"])
                )
            )
            source_frame_path = concrete_sequence_frame(
                str(visual_conform_segment["sourcePath"]), source_frame
            )
            cut["afterEffectsConform"] = {
                "projectPath": (
                    visual_project.get("path") if visual_project else None
                ),
                "comp": "TH_0427.mp4 direct visual conform",
                "sourcePath": visual_conform_segment["sourcePath"],
                "sourceFramePath": source_frame_path,
                "sourceFrame": source_frame,
                "sourceTime": (
                    visual_conform_segment.get("visualMatch") or {}
                ).get("sourceEditTime"),
            }
            direct_render = render_by_path.get(
                str(
                    Path(visual_conform_segment["sourcePath"])
                    .expanduser()
                    .resolve()
                    .parent
                )
            )
            if direct_render:
                cut["lineage"].append(
                    {
                        "kind": "render_sequence",
                        "label": direct_render["name"],
                        "detail": (
                            f"{direct_render.get('frameCount', 0)} frames · "
                            "directly matched to the TH_0427 source-edit frame"
                        ),
                        "path": direct_render["path"],
                        "evidence": "confirmed",
                    }
                )
                linked = render_matches.get(direct_render["id"], [])
                if linked:
                    direct_c4d = linked[0]
                    append_c4d_camera(
                        cut,
                        direct_c4d,
                        "Project matched from the direct TH render folder",
                        direct_render,
                    )
                    cut["confidence"] = direct_c4d["evidence"]
        ae_segment_match = (
            None
            if visual_conform_segment
            else after_effects_segment_for_cut(cut, after_effects_mappings)
        )
        if ae_segment_match:
            ae_mapping, ae_segment = ae_segment_match
            cut_midpoint = float(cut["start"]) + float(cut["duration"]) / 2
            mapped_source_time = (
                float(ae_mapping["sourceStart"])
                + cut_midpoint
                - float(ae_mapping["finalStart"])
            )
            layer_chain = after_effects_layer_chain(
                ae_mapping["project"],
                ae_mapping["comp"],
                mapped_source_time,
            ) or (ae_segment.get("layerChain") or [])
            comp = (
                layer_chain[-1]["comp"] if layer_chain else ae_mapping["comp"]
            )
            layer = (
                layer_chain[-1]["layer"] if layer_chain else ae_segment["layer"]
            )
            terminal_source_time = float(
                layer_chain[-1]["sourceTime"]
                if layer_chain
                else ae_segment["sourceStart"]
            )
            source_path, source_frame = after_effects_source_frame(
                layer, terminal_source_time
            )
            if source_path and Path(source_path).suffix.lower() in IMAGE_EXTENSIONS:
                cut["afterEffectsConform"] = {
                    "projectPath": ae_mapping["projectPath"],
                    "comp": ae_mapping["comp"].get("name"),
                    "sourcePath": str(layer.get("sourcePath") or ""),
                    "sourceFramePath": source_path,
                    "sourceFrame": source_frame,
                    "sourceTime": terminal_source_time,
                }
            comp_path = " → ".join(
                str(item["comp"].get("name") or "AE comp")
                for item in layer_chain
            ) or str(comp.get("name") or "AE comp")
            cut["lineage"].append(
                {
                    "kind": "after_effects",
                    "label": ae_mapping["projectName"],
                    "detail": "Source edit project containing this final interval",
                    "path": ae_mapping["projectPath"],
                    "evidence": "confirmed",
                }
            )
            cut["lineage"].append(
                {
                    "kind": "after_effects_comp",
                    "label": comp_path,
                    "detail": (
                        f"Terminal comp has {comp.get('numLayers', 0)} layers · "
                        f"source time "
                        f"{terminal_source_time:.3f}s"
                    ),
                    "path": ae_mapping["projectPath"],
                    "evidence": "confirmed",
                }
            )
            cut["lineage"].append(
                {
                    "kind": "after_effects_layer",
                    "label": layer.get("sourceName")
                    or layer.get("name")
                    or "AE source layer",
                    "detail": (
                        f"Layer {layer.get('index')} · topmost enabled visual source"
                        + (
                            f" · source frame {source_frame}"
                            if source_frame is not None
                            else ""
                        )
                    ),
                    "path": source_path or ae_mapping["projectPath"],
                    "evidence": "confirmed",
                }
            )
            if source_path:
                direct_render = render_by_path.get(
                    str(Path(source_path).expanduser().resolve().parent)
                )
            if direct_render:
                cut["lineage"].append(
                    {
                        "kind": "render_sequence",
                        "label": direct_render["name"],
                        "detail": (
                            f"{direct_render.get('frameCount', 0)} frames · "
                            "direct AE footage source"
                        ),
                        "path": direct_render["path"],
                        "evidence": "confirmed",
                    }
                )
                linked = render_matches.get(direct_render["id"], [])
                if linked:
                    direct_c4d = linked[0]
                    append_c4d_camera(
                        cut,
                        direct_c4d,
                        "Project matched from the direct AE render folder",
                        direct_render,
                    )
                    cut["confidence"] = direct_c4d["evidence"]
        terminal_segment = next(
            (
                segment
                for segment in cut["sourceSegments"]
                if float(segment["finalStart"]) <= midpoint
                < float(segment["finalEnd"])
            ),
            None,
        )
        if terminal_segment:
            terminal_source = str(terminal_segment.get("sourcePath") or "")
            terminal_directory = str(
                Path(terminal_source).expanduser().resolve().parent
            )
            terminal_render = render_by_path.get(terminal_directory)
            if terminal_render:
                if not any(
                    node.get("kind") == "render_sequence"
                    and str(Path(str(node.get("path") or "")).expanduser().resolve())
                    == terminal_directory
                    for node in cut["lineage"]
                ):
                    cut["lineage"].append(
                        {
                            "kind": "render_sequence",
                            "label": terminal_render["name"],
                            "detail": (
                                f"{terminal_segment['id']} · terminal conform "
                                "source directory at this cut midpoint"
                            ),
                            "path": terminal_render["path"],
                            "evidence": terminal_segment.get("evidence")
                            or "confirmed",
                        }
                    )
                linked = render_matches.get(terminal_render["id"], [])
                terminal_asset_paths = {
                    str(
                        Path(asset_by_id[item["assetId"]]["path"])
                        .expanduser()
                        .resolve()
                    )
                    for item in linked
                    if item.get("assetId") in asset_by_id
                }
                already_linked = any(
                    node.get("kind") == "cinema4d"
                    and str(Path(str(node.get("path") or "")).expanduser().resolve())
                    in terminal_asset_paths
                    for node in cut["lineage"]
                )
                if linked and not already_linked:
                    direct_render = terminal_render
                    direct_c4d = linked[0]
                    append_c4d_camera(
                        cut,
                        direct_c4d,
                        "Project matched from the terminal conform render folder",
                        terminal_render,
                    )
                    cut["confidence"] = direct_c4d["evidence"]
        frame_match = conform_frame_match or frame_matches_by_start.get(
            round(float(cut["start"]), 4)
        )
        if frame_match:
            pair_path = APP_ROOT / "public" / str(
                frame_match["pairImage"]
            ).lstrip("/")
            cut["comparison"] = {
                "score": frame_match["score"],
                "evidence": frame_match["evidence"],
                "sourceFramePath": frame_match["sourceFramePath"],
                "finalImage": frame_match["finalImage"],
                "sourceImage": frame_match["sourceImage"],
                "pairImage": frame_match["pairImage"],
            }
            cut["lineage"].append(
                {
                    "kind": "visual_match",
                    "label": f"{float(frame_match['score']):.3f} structural match",
                    "detail": (
                        "Final-reference midpoint compared directly with the "
                        "terminal AE source frame"
                    ),
                    "path": str(pair_path),
                    "evidence": frame_match["evidence"],
                }
            )
            if frame_match["evidence"] == "visually_confirmed":
                has_confirmed_camera = any(
                    item["kind"] == "camera" and item["evidence"] == "confirmed"
                    for item in cut["lineage"]
                )
                cut["confidence"] = (
                    "confirmed" if has_confirmed_camera else "strong_inference"
                )
        if planned:
            candidates = best_assets_for_planned_shot(planned, assets)
            selected_ae = None
            if planned.get("fileName") and not ae_segment_match:
                ae_matches = [
                    asset
                    for asset in assets
                    if asset["kind"] == "after_effects"
                    and (
                        cut["sectionCode"].lower() in asset["name"].lower()
                        or cut["sectionName"].split()[0].lower() in asset["name"].lower()
                    )
                ]
                if ae_matches:
                    selected_ae = sorted(
                        ae_matches,
                        key=lambda item: item.get("modifiedAt") or "",
                        reverse=True,
                    )[0]
                    cut["lineage"].append(
                        {
                            "kind": "after_effects",
                            "label": selected_ae["name"],
                            "detail": (
                                "Section edit candidate; composition archive available"
                                if str(Path(selected_ae["path"]).resolve())
                                in ae_projects_by_path
                                else "Section edit candidate; layer export pending"
                            ),
                            "path": selected_ae["path"],
                            "evidence": (
                                "confirmed"
                                if str(Path(selected_ae["path"]).resolve())
                                in ae_projects_by_path
                                else "strong_inference"
                            ),
                        }
                    )
                    ae_project = ae_projects_by_path.get(
                        str(Path(selected_ae["path"]).resolve())
                    )
                    comp_match = (
                        best_after_effects_comp(planned, ae_project)
                        if ae_project
                        else None
                    )
                    if comp_match:
                        comp_score, comp = comp_match
                        cut["lineage"].append(
                            {
                                "kind": "after_effects_comp",
                                "label": comp.get("name") or "AE composition",
                                "detail": (
                                    f"{comp.get('numLayers', 0)} layers · "
                                    f"planned-source score {comp_score:.3f}"
                                ),
                                "path": selected_ae["path"],
                                "evidence": (
                                    "strong_inference"
                                    if comp_score >= 0.70
                                    else "candidate"
                                ),
                            }
                        )
            render_candidate = (
                None
                if direct_render
                else best_render_for_planned_shot(planned, renders)
            )
            best = candidates[0] if candidates else None
            if render_candidate:
                render_score, render = render_candidate
                cut["lineage"].append(
                    {
                        "kind": "render_sequence",
                        "label": render["name"],
                        "detail": (
                            f"{render.get('frameCount', 0)} frames · planned-source "
                            f"score {render_score:.3f}"
                        ),
                        "path": render["path"],
                        "evidence": (
                            "strong_inference" if render_score >= 0.76 else "candidate"
                        ),
                    }
                )
                linked = render_matches.get(render["id"], [])
                if linked:
                    best = linked[0]
            if best and not direct_c4d:
                append_c4d_camera(cut, best, "Planned source candidate")
                cut["confidence"] = (
                    "strong_inference"
                    if best["evidence"] in {"confirmed", "strong_inference"}
                    else "candidate"
                )
        cuts.append(cut)
    return cuts


def write_sqlite(
    shots: list[dict[str, Any]],
    cuts: list[dict[str, Any]],
    assets: list[dict[str, Any]],
) -> None:
    target = DATA_DIR / "provenance.sqlite"
    temp = DATA_DIR / "provenance.sqlite.tmp"
    if temp.exists():
        temp.unlink()
    connection = sqlite3.connect(temp)
    connection.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE planned_shots (
          id TEXT PRIMARY KEY, scene INTEGER, song TEXT, shot TEXT,
          start REAL, end REAL, description TEXT, file_name TEXT, camera TEXT,
          payload TEXT NOT NULL
        );
        CREATE TABLE edit_cuts (
          id TEXT PRIMARY KEY, cut_index INTEGER, start REAL, end REAL,
          block_id TEXT, section_code TEXT, planned_shot_id TEXT,
          confidence TEXT, payload TEXT NOT NULL
        );
        CREATE TABLE assets (
          id TEXT PRIMARY KEY, kind TEXT, name TEXT, path TEXT UNIQUE,
          modified_at TEXT, size INTEGER, payload TEXT NOT NULL
        );
        CREATE TABLE lineage_edges (
          cut_id TEXT, ordinal INTEGER, kind TEXT, label TEXT, path TEXT,
          evidence TEXT, payload TEXT NOT NULL,
          PRIMARY KEY (cut_id, ordinal)
        );
        CREATE INDEX assets_kind_name_idx ON assets(kind, name);
        CREATE INDEX cuts_section_idx ON edit_cuts(section_code, cut_index);
        """
    )
    connection.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?)", ("generated_at", now_iso())
    )
    connection.executemany(
        "INSERT INTO planned_shots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                shot["id"],
                int(shot["scene"]),
                shot["song"],
                shot["shot"],
                shot["start"],
                shot["end"],
                shot["description"],
                shot["fileName"],
                shot["camera"],
                json.dumps(shot),
            )
            for shot in shots
        ],
    )
    connection.executemany(
        "INSERT INTO edit_cuts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                cut["id"],
                cut["index"],
                cut["start"],
                cut["end"],
                cut["blockId"],
                cut["sectionCode"],
                cut["plannedShotId"],
                cut["confidence"],
                json.dumps(cut),
            )
            for cut in cuts
        ],
    )
    connection.executemany(
        "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                asset["id"],
                asset["kind"],
                asset["name"],
                asset["path"],
                asset.get("modifiedAt"),
                asset.get("size", 0),
                json.dumps(asset),
            )
            for asset in assets
        ],
    )
    edges = []
    for cut in cuts:
        for ordinal, edge in enumerate(cut["lineage"]):
            edges.append(
                (
                    cut["id"],
                    ordinal,
                    edge["kind"],
                    edge["label"],
                    edge.get("path"),
                    edge["evidence"],
                    json.dumps(edge),
                )
            )
    connection.executemany("INSERT INTO lineage_edges VALUES (?, ?, ?, ?, ?, ?, ?)", edges)
    connection.commit()
    connection.close()
    temp.replace(target)


def source_status(
    name: str, kind: str, path: Path | None, detail: str, state: str = "online"
) -> dict[str, Any]:
    stat = safe_stat(path) if path else {"exists": state == "online", "modifiedAt": None}
    return {
        "name": name,
        "kind": kind,
        "state": state if stat["exists"] else "missing",
        "detail": detail,
        "path": str(path) if path else None,
        "modifiedAt": stat.get("modifiedAt"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Reuse boundary cache; refresh thumbnails only when stale",
    )
    args = parser.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    CUT_ARCHIVE.mkdir(parents=True, exist_ok=True)

    if not REFERENCE_MOV.exists():
        raise SystemExit(f"Reference film is missing: {REFERENCE_MOV}")
    if not PREMIERE_PROJECT.exists():
        raise SystemExit(f"Premiere project is missing: {PREMIERE_PROJECT}")

    started = now_iso()
    reference_probe = ffprobe(REFERENCE_MOV)
    duration = float(reference_probe["format"]["duration"])
    video_stream = next(
        stream
        for stream in reference_probe["streams"]
        if stream.get("codec_type") == "video"
    )
    rate_parts = str(video_stream.get("r_frame_rate", "24000/1001")).split("/")
    fps = float(rate_parts[0]) / float(rate_parts[1])

    shots = load_shotlist()
    premiere = parse_premiere()
    assets, renders, counts = inventory_assets()
    c4d_cameras = load_creative_app_archive("c4d-camera-export.json")
    c4d_dependencies = load_creative_app_archive(
        "c4d-dependency-export.json"
    )
    camera_proofs = load_creative_app_archive(
        "c4d-camera-proof-renders.json"
    )
    c4d_visual_reviews = load_creative_app_archive(
        "c4d-visual-review.json"
    )
    c4d_dependency_recovery = load_creative_app_archive(
        "c4d-dependency-recovery.json"
    )
    c4d_cut_relink_summary = load_creative_app_archive(
        C4D_CUT_RELINK_SUMMARY.name
    )
    c4d_scene_state_audit = load_creative_app_archive(
        "c4d-scene-state-audit.json"
    )
    c4d_proxy_recovery = load_creative_app_archive(
        "c4d-proxy-recovery.json"
    )
    c4d_semantic_recovery = load_creative_app_archive(
        "c4d-semantic-recovery.json"
    )
    c4d_structural_recoveries = load_creative_app_archive(
        "c4d-structural-recoveries.json"
    )
    c4d_redshift_proofs = load_creative_app_archive(
        "c4d-redshift-proxy-proofs-20260726.json"
    )
    c4d_nth_running_recovery = load_creative_app_archive(
        "c4d-nth-running-recovery-20260726.json"
    )
    c4d_camera_candidate_audits = load_creative_app_archive(
        "c4d-camera-candidate-audits.json"
    )
    c4d_source_link_audits = load_creative_app_archive(
        "c4d-source-link-audits.json"
    )
    c4d_production_redshift_confirmations = load_creative_app_archive(
        "c4d-production-redshift-confirmations-20260726.json"
    )
    c4d_aec_camera_reviews = load_creative_app_archive(
        "c4d-aec-camera-review-20260726.json"
    )
    render_matches, exact_render_matches = match_render_projects(
        assets, renders, c4d_cameras
    )
    resolve = load_resolve()
    after_effects = load_creative_app_archive("after-effects-export.json")
    after_effects_candidates = load_creative_app_archive(
        "after-effects-na-candidates.json"
    )
    frame_matches = load_creative_app_archive("conform-verification.json")
    th_visual_matches = load_creative_app_archive(
        "th-visual-source-matches.json"
    )
    premiere_conform_status = load_creative_app_archive(
        "premiere/premiere-conform-status.json"
    )
    revised_conform_archive = (
        "premiere/clean-conform-export.json"
        if CLEAN_CONFORM_EXPORT.exists()
        else (
            "premiere/canonical-v6-v7-conform-export.json"
            if CANONICAL_V6_V7_CONFORM_EXPORT.exists()
            else (
                "premiere/yellow-recovery-conform-export.json"
                if YELLOW_RECOVERY_CONFORM_EXPORT.exists()
                else "premiere/revised-conform-export.json"
            )
        )
    )
    revised_conform = load_creative_app_archive(revised_conform_archive)
    alternate_search = load_creative_app_archive(
        "premiere/alternate-search.json"
    )
    primary_block_ids = {
        block["id"] for block in premiere.get("primaryBlocks", [])
    }
    exact_overlay_mappings = exact_after_effects_block_mappings(
        [
            block
            for block in premiere.get("blocks", [])
            if block.get("id") not in primary_block_ids
        ],
        after_effects,
    )
    section_edit_mappings = after_effects_edit_mappings(
        premiere["primaryBlocks"], after_effects
    )
    if th_visual_matches.get("intervals"):
        section_edit_mappings = [
            mapping
            for mapping in section_edit_mappings
            if mapping.get("sectionCode") != "TH"
        ]
    after_effects_mappings = [
        *exact_overlay_mappings,
        *section_edit_mappings,
    ]
    conform = build_conform_manifest(
        premiere,
        resolve,
        after_effects_mappings,
        th_visual_matches,
        fps,
    )
    conform = apply_conform_verification(conform, frame_matches)
    boundaries, boundary_evidence = scene_boundaries(
        duration,
        premiere["primaryBlocks"],
        premiere,
        resolve,
        after_effects_mappings,
        conform,
    )
    cuts = make_cuts(
        duration,
        boundaries,
        boundary_evidence,
        premiere["blocks"],
        premiere,
        shots,
        assets,
        renders,
        render_matches,
        resolve,
        after_effects,
        after_effects_candidates,
        after_effects_mappings,
        frame_matches,
        c4d_cameras,
        conform,
    )
    revised_stats: dict[str, Any] = {}
    if revised_conform.get("inventory"):
        cuts, conform, revised_stats, manual_blocks = (
            reconcile_revised_conform(
                cuts,
                revised_conform,
                renders,
                render_matches,
                assets,
                alternate_search,
                fps,
            )
        )
        premiere["project"] = revised_conform.get("projectPath")
        premiere["sequence"] = revised_conform.get("sequence")
        premiere["primaryBlocks"] = manual_blocks
        premiere_conform_status = {
            "success": True,
            "authority": (
                revised_conform.get("authorityKind")
                or "saved_premiere_clip_instances"
            ),
            "verifiedSegments": len(revised_conform.get("sources", [])),
            "expectedSegments": len(revised_conform.get("sources", [])),
            "sourceClipCount": len(revised_conform.get("sources", [])),
            "exactSourceClipCount": (
                revised_stats.get("canonicalSources")
                if revised_conform.get("authorityKind") == "clean_v1_v2"
                else revised_stats.get("v6ExactSources", 0)
            ),
            "canonicalSourceClipCount": (
                revised_stats.get("canonicalSources", 0)
                if revised_conform.get("authorityKind") == "clean_v1_v2"
                else (
                    revised_stats.get("v6ExactSources", 0)
                    + revised_stats.get("v7NewerSources", 0)
                )
            ),
            "reverseVerified": sum(
                bool(item.get("playBackwards"))
                for item in revised_conform.get("sources", [])
            ),
            "reverseExpected": sum(
                bool(item.get("playBackwards"))
                for item in revised_conform.get("sources", [])
            ),
            "projectExport": revised_conform.get("projectPath"),
            "projectSha256": revised_conform.get("projectSha256"),
            "sequence": revised_conform.get("sequence"),
            "fcpXml": revised_conform.get("fcpXmlPath") or "",
        }
        camera_audit_confirmations = 0
    else:
        camera_audit_confirmations = apply_camera_confirmations(
            cuts, c4d_cameras
        )
    source_recovery_counts = apply_source_confirmations(cuts)
    c4d_source_link_audit_counts = apply_c4d_source_link_audits(
        cuts, c4d_source_link_audits
    )
    c4d_production_redshift_confirmation_counts = (
        apply_production_redshift_confirmations(
            cuts, c4d_production_redshift_confirmations
        )
    )
    c4d_dependency_counts = apply_c4d_dependency_health(
        cuts,
        c4d_dependencies,
        c4d_dependency_recovery,
        c4d_semantic_recovery,
    )
    c4d_exact_dependency_counts = apply_exact_cut_dependency_audits(
        cuts, c4d_cut_relink_summary
    )
    camera_proof_counts = apply_camera_proof_renders(
        cuts, camera_proofs
    )
    c4d_proxy_counts = apply_c4d_proxy_recovery(
        cuts, c4d_scene_state_audit, c4d_proxy_recovery
    )
    c4d_structural_recovery_counts = apply_c4d_structural_recoveries(
        cuts, c4d_structural_recoveries
    )
    c4d_redshift_proof_counts = apply_c4d_redshift_proofs(
        cuts, c4d_redshift_proofs
    )
    c4d_nth_running_recovery_counts = apply_c4d_nth_running_recovery(
        cuts, c4d_nth_running_recovery
    )
    c4d_camera_candidate_audit_counts = (
        apply_c4d_camera_candidate_audits(
            cuts, c4d_camera_candidate_audits
        )
    )
    c4d_aec_camera_review_counts = apply_c4d_aec_camera_reviews(
        cuts, c4d_aec_camera_reviews
    )
    c4d_strict_counts = apply_strict_c4d_verification(
        cuts, c4d_visual_reviews
    )
    generate_thumbnails(cuts, args.quick)
    apply_authoritative_chapter_edits(cuts, tag_nodes=False)
    archive_lineage_export_screenshots(
        cuts,
        premiere["blocks"],
        premiere,
        [after_effects, after_effects_candidates],
    )
    lineage_export_screenshots = sum(
        len(cut.get("exportScreenshots", [])) for cut in cuts
    )
    lineage_role_counts = tag_lineage_roles(cuts)
    authoritative_chapters = apply_authoritative_chapter_edits(
        cuts, tag_nodes=True
    )
    lineage_role_counts["chapterEditTaggedCuts"] = (
        authoritative_chapters["chapterEditTaggedCuts"]
    )
    write_sqlite(shots, cuts, assets)

    evidence_counts = Counter(cut["confidence"] for cut in cuts)
    camera_confirmed = sum(
        1
        for cut in cuts
        for edge in cut["lineage"]
        if edge["kind"] == "camera" and edge["evidence"] == "confirmed"
    )
    picture_cuts = [cut for cut in cuts if not cut.get("isGap")]
    camera_confirmed_cuts = sum(
        1
        for cut in picture_cuts
        if any(
            edge["kind"] == "camera" and edge["evidence"] == "confirmed"
            for edge in cut["lineage"]
        )
    )
    render_aligned_camera_cuts = sum(
        1
        for cut in picture_cuts
        if any(
            edge["kind"] == "camera"
            and edge["evidence"] == "confirmed"
            and (
                edge.get("confirmationMethod")
                or re.search(
                    (
                        r"exact path|render name|project.*take|project basename|"
                        r"embedded frame prefix|AEC evidence|camera audit|"
                        r"Audit metrics"
                    ),
                    str(edge.get("detail") or ""),
                    flags=re.IGNORECASE,
                )
            )
            for edge in cut["lineage"]
        )
    )
    generated_at = now_iso()
    state = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "scanStartedAt": started,
        "readOnly": True,
        "groundTruth": {
            "title": "Paracosm 050726",
            "frameIoUrl": (
                "https://next.frame.io/share/6240562c-8658-4ebe-ae77-ca619b663be9/"
                "view/d0a66a84-eaab-4f86-9c42-90056285a780"
            ),
            "localPath": str(REFERENCE_MOV),
            "hoverProxy": (
                "/archive/reference/paracosm-hover.mp4"
                if HOVER_PROXY.exists()
                else None
            ),
            "duration": duration,
            "durationTimecode": timecode(duration, fps),
            "fps": fps,
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "codec": video_stream.get("codec_name"),
            "pixelFormat": video_stream.get("pix_fmt"),
            **safe_stat(REFERENCE_MOV),
        },
        "summary": {
            "editCuts": len(cuts),
            "plannedShots": len(shots),
            "finalBlocks": len(premiere["primaryBlocks"]),
            "resolveTimelines": len(resolve.get("timelines", [])),
            "resolveRenderJobs": len(resolve.get("renderJobs", [])),
            "c4dProjects": counts[".c4d"],
            "afterEffectsProjects": counts[".aep"],
            "premiereProjects": counts[".prproj"],
            "renderSequences": counts["render_sequences"],
            "exactRenderProjectMatches": exact_render_matches,
            "cameraConfirmed": camera_confirmed,
            "pictureCuts": len(picture_cuts),
            "cameraConfirmedCuts": camera_confirmed_cuts,
            "renderAlignedCameraCuts": render_aligned_camera_cuts,
            "cameraUnresolvedCuts": len(picture_cuts)
            - render_aligned_camera_cuts,
            "cameraAuditConfirmations": camera_audit_confirmations,
            "framePairsArchived": len(frame_matches.get("matches", [])),
            "framePairsVisuallyConfirmed": sum(
                1
                for item in frame_matches.get("matches", [])
                if item.get("evidence") == "visually_confirmed"
            ),
            "lineageExportScreenshots": lineage_export_screenshots,
            **lineage_role_counts,
            **source_recovery_counts,
            "afterEffectsProjectsArchived": len(after_effects.get("projects", [])),
            "c4dProjectsCameraProbed": len(c4d_cameras.get("projects", [])),
            **c4d_dependency_counts,
            **c4d_exact_dependency_counts,
            **camera_proof_counts,
            **c4d_proxy_counts,
            **c4d_structural_recovery_counts,
            **c4d_redshift_proof_counts,
            **c4d_nth_running_recovery_counts,
            **c4d_camera_candidate_audit_counts,
            **c4d_production_redshift_confirmation_counts,
            **c4d_strict_counts,
            "sourceConformSegments": conform["summary"]["segments"],
            "sourceConformConfirmed": conform["summary"]["confirmed"],
            "premiereConformVerified": bool(
                premiere_conform_status.get("success")
            ),
            "premiereConformClips": int(
                premiere_conform_status.get("sourceClipCount") or 0
            ),
            "manualConformPictureClips": revised_stats.get(
                "pictureClips",
                revised_stats.get("v1PictureClips", 0),
            ),
            "manualConformIntentionalBlanks": revised_stats.get(
                "intentionalBlanks", 0
            ),
            "manualConformExactSources": revised_stats.get(
                "canonicalSources",
                revised_stats.get("v6ExactSources", 0),
            ),
            "manualConformOlderSources": revised_stats.get(
                "v5OlderSources", 0
            ),
            "manualConformNewerSources": revised_stats.get(
                "v7NewerSources", 0
            ),
            "manualConformCanonicalSources": (
                revised_stats.get("canonicalSources", 0)
                if revised_conform.get("authorityKind") == "clean_v1_v2"
                else (
                    revised_stats.get("v6ExactSources", 0)
                    + revised_stats.get("v7NewerSources", 0)
                )
            ),
            "manualConformV1Sources": revised_stats.get(
                "v1CanonicalSources", 0
            ),
            "manualConformV2Sources": revised_stats.get(
                "v2CanonicalSources", 0
            ),
            "sourceMediaCompleteClips": revised_stats.get(
                "completeSourceClips", 0
            ),
            "sourceMediaIncompleteClips": revised_stats.get(
                "incompleteSourceClips", 0
            ),
            "sourceMediaMissingSelectedFrames": revised_stats.get(
                "missingSelectedRenderFrames", 0
            ),
            "manualConformStatusCounts": revised_stats.get(
                "statusCounts", {}
            ),
            "evidenceCounts": dict(evidence_counts),
        },
        "sources": [
            source_status(
                "Frame.io reference",
                "reference",
                REFERENCE_MOV,
                "Immutable editorial ground truth; local original identified",
            ),
            source_status(
                "Premiere 2026",
                "premiere",
                (
                    Path(str(revised_conform.get("projectPath")))
                    if revised_conform.get("projectPath")
                    else PREMIERE_PROJECT
                ),
                (
                    "Canonical V1/V2 source-render clip instances and Audio 1 "
                    "chapter cuts parsed read-only"
                    if revised_conform.get("authorityKind") == "clean_v1_v2"
                    else "User-aligned V1/V5/V6/V7 clip instances parsed read-only"
                    if revised_conform.get("inventory")
                    else "Paracosm Full Copy 01 parsed read-only"
                ),
            ),
            source_status(
                "DaVinci Resolve",
                "resolve",
                RESOLVE_DB,
                f"{len(resolve.get('timelines', []))} live timelines archived",
                "online" if resolve.get("timelines") else "archived",
            ),
            source_status(
                "After Effects",
                "after_effects",
                DATA_DIR / "after-effects-export.json"
                if after_effects.get("projects")
                else ABSOLUTELY / "AS" / "1 Edit",
                (
                    f"{len(after_effects.get('projects', []))} project composition archives loaded"
                    if after_effects.get("projects")
                    else "Projects indexed; composition/layer export pending"
                ),
                "online" if after_effects.get("projects") else "partial",
            ),
            source_status(
                "Cinema 4D 2026",
                "cinema4d",
                DATA_DIR / "c4d-dependency-export.json"
                if c4d_dependencies.get("projects")
                else Path(
                    "/Users/alphaone/Library/Preferences/Maxon/"
                    "Maxon Cinema 4D 2026_9D810372/plugins/mcp_server_plugin.pyp"
                ),
                (
                    f"{len(c4d_dependencies.get('projects', []))} source projects "
                    f"dependency-audited; {c4d_dependency_counts['c4dDependencyAuditedCuts']} "
                    "picture cuts take-mapped"
                    if c4d_dependencies.get("projects")
                    else "Camera extraction plugin installed; live verification pending"
                ),
                "online" if c4d_dependencies.get("projects") else "partial",
            ),
            source_status(
                "Frame-pair verification",
                "visual_match",
                DATA_DIR / "conform-verification.json",
                (
                    f"{len(frame_matches.get('matches', []))} comparison pairs; "
                    f"{sum(1 for item in frame_matches.get('matches', []) if item.get('evidence') == 'visually_confirmed')} visually confirmed"
                ),
                "online" if frame_matches.get("matches") else "partial",
            ),
            source_status(
                (
                    "Premiere source conform · VERIFIED"
                    if premiere_conform_status.get("success")
                    else "Premiere source conform"
                ),
                "conform",
                (
                    Path(str(premiere_conform_status.get("projectExport")))
                    if premiere_conform_status.get("success")
                    else DATA_DIR / "conform-manifest.json"
                ),
                (
                    f"{premiere_conform_status.get('verifiedSegments', 0)}/"
                    f"{premiere_conform_status.get('expectedSegments', conform['summary']['segments'])} "
                    + (
                        "saved V1/V2 canonical render clips and Audio 1 "
                        "chapter cuts verified with exact timeline/source In/Out"
                        if revised_conform.get("authorityKind") == "clean_v1_v2"
                        else "saved V5/V6/V7 clip instances verified with exact "
                        "timeline and source In/Out"
                        if revised_conform.get("inventory")
                        else "source-image clips verified above Paracosm Full Copy 01"
                    )
                    if premiere_conform_status.get("success")
                    else (
                        f"{conform['summary']['segments']} source-image segments "
                        "aligned above Paracosm Full Copy 01"
                    )
                ),
                "online" if premiere_conform_status.get("success") else "partial",
            ),
        ],
        "premiere": premiere,
        "premiereConform": premiere_conform_status,
        "conform": conform,
        "revisedConform": {
            "active": bool(revised_conform.get("inventory")),
            "authorityKind": revised_conform.get("authorityKind"),
            "authority": revised_conform.get("authority"),
            "projectPath": revised_conform.get("projectPath"),
            "projectSha256": revised_conform.get("projectSha256"),
            "projectModifiedAt": revised_conform.get("projectModifiedAt"),
            "sequence": revised_conform.get("sequence"),
            "timelineFrameRate": revised_conform.get(
                "timelineFrameRate"
            ),
            "sourceImageFrameRate": revised_conform.get(
                "sourceImageFrameRate"
            ),
            "manualTrimPolicy": revised_conform.get("manualTrimPolicy"),
            "trackSemantics": revised_conform.get("trackSemantics", {}),
            "canonicalTracks": revised_conform.get("canonicalTracks", []),
            "chapterBoundaryTrack": revised_conform.get(
                "chapterBoundaryTrack"
            ),
            "chapterCuts": revised_conform.get("chapterCuts", []),
            "visualAlignment": revised_conform.get("visualAlignment", {}),
            "summary": revised_stats,
            "alternateSearch": alternate_search,
        },
        "plannedShots": shots,
        "chapterEdits": authoritative_chapters["chapterEdits"],
        "cuts": cuts,
        "assets": assets,
        "renderSequences": renders,
        "renderProjectMatches": render_matches,
        "resolve": {
            "project": resolve.get("project"),
            "exportedAt": resolve.get("exportedAt"),
            "timelines": [
                {
                    "index": timeline.get("index"),
                    "name": timeline.get("name"),
                    "startFrame": timeline.get("startFrame"),
                    "endFrame": timeline.get("endFrame"),
                    "itemCount": sum(
                        len(track.get("items", []))
                        for track in timeline.get("tracks", [])
                    ),
                }
                for timeline in resolve.get("timelines", [])
            ],
            "renderJobs": resolve.get("renderJobs", []),
        },
        "afterEffects": {
            "exportedAt": after_effects.get("exportedAt"),
            "projectCount": len(after_effects.get("projects", [])),
        },
        "cinema4d": {
            "updatedAt": c4d_cameras.get("updatedAt"),
            "cameraProjectCount": len(c4d_cameras.get("projects", [])),
            "dependencyUpdatedAt": c4d_dependencies.get("updatedAt"),
            "dependencyProjectCount": len(
                c4d_dependencies.get("projects", [])
            ),
            "dependencyMethod": c4d_dependencies.get("method"),
            "dependencyRecoveryGeneratedAt": (
                c4d_dependency_recovery.get("generatedAt")
            ),
            "dependencyRecoverySummary": (
                c4d_dependency_recovery.get("summary", {})
            ),
            "sceneStateGeneratedAt": (
                c4d_scene_state_audit.get("generatedAt")
            ),
            "sceneStateSummary": (
                c4d_scene_state_audit.get("summary", {})
            ),
            "proxyRecoveryGeneratedAt": (
                c4d_proxy_recovery.get("generatedAt")
            ),
            "proxyRecoverySummary": (
                c4d_proxy_recovery.get("summary", {})
            ),
            "semanticRecoveryGeneratedAt": (
                c4d_semantic_recovery.get("generatedAt")
            ),
            "semanticRecoverySummary": (
                c4d_semantic_recovery.get("summary", {})
            ),
            "structuralRecoveryGeneratedAt": (
                c4d_structural_recoveries.get("generatedAt")
            ),
            "cameraCandidateAuditGeneratedAt": (
                c4d_camera_candidate_audits.get("generatedAt")
            ),
            "cameraCandidateAuditAuthority": (
                c4d_camera_candidate_audits.get("authority")
            ),
            "sourceLinkAuditGeneratedAt": (
                c4d_source_link_audits.get("generatedAt")
            ),
            "sourceLinkAuditSummary": c4d_source_link_audit_counts,
            "aecCameraReviewGeneratedAt": (
                c4d_aec_camera_reviews.get("generatedAt")
            ),
            "aecCameraReviewSummary": c4d_aec_camera_review_counts,
        },
        "cameraProofs": {
            "authority": camera_proofs.get("authority"),
            "generatedAt": camera_proofs.get("generatedAt"),
            "manifest": str(CAMERA_PROOF_RENDER_EXPORT),
            "summary": camera_proofs.get("summary", {}),
        },
        "c4dVerification": {
            "authority": c4d_visual_reviews.get("authority"),
            "reviewedAt": c4d_visual_reviews.get("reviewedAt"),
            "strictDefinition": (
                "source project + dependency audit + no render-critical "
                "missing files + proxy render safety + rendered camera proof "
                "+ manual element match"
            ),
            "summary": c4d_strict_counts,
        },
        "c4dExactCutDependencyAudit": {
            "authority": c4d_cut_relink_summary.get("authority"),
            "updatedAt": c4d_cut_relink_summary.get("updatedAt"),
            "manifest": str(C4D_CUT_RELINK_SUMMARY),
            "summary": {
                **(c4d_cut_relink_summary.get("summary") or {}),
                **c4d_exact_dependency_counts,
            },
        },
        "method": {
            "boundaryThreshold": 0.30,
            "minimumBoundaryGap": 0.45,
            "boundaryStatus": (
                "saved_premiere_clip_instance_in_out"
                if revised_conform.get("inventory")
                else "visible_cuts_with_recursive_source_conform"
            ),
            "evidenceLevels": [
                "confirmed",
                "visually_confirmed",
                "strong_inference",
                "candidate",
                "missing",
            ],
            "notes": [
                (
                    "Canonical CUT ids follow the user's exact saved V1/V2 "
                    "timeline and source In/Out; uncovered intervals are "
                    "verified Premiere black."
                    if revised_conform.get("authorityKind") == "clean_v1_v2"
                    else "Canonical CUT ids follow the user's exact saved V1 "
                    "timeline In/Out, including five intentional blanks."
                    if revised_conform.get("inventory")
                    else "Canonical CUT ids are tied to the immutable reference film."
                ),
                (
                    "V1 and V2 are the user's canonical source-render layers; "
                    "Audio 1 edit points define the six chapter boundaries."
                    if revised_conform.get("authorityKind") == "clean_v1_v2"
                    else "V5 Rose is retained as older reference material. V6 "
                    "Iris and V7 Green are the user's canonical source layers; "
                    "their saved source In/Out values are copied without "
                    "recalculation."
                    if revised_conform.get("inventory")
                    else "Visible CUT ids stay anchored to final-reference boundaries; source-edit segments are preserved separately in the conform."
                ),
                "Nested Premiere sequences, Resolve image tracks, and AE comps are flattened to terminal source frames.",
                "Direct source frames are archived beside final-reference frames for structural comparison.",
                "Subframe AE layer events without a distinct final-reference frame are audited but excluded from the Premiere picture conform.",
                "Later-than-reference project versions remain candidates and never replace the ground truth automatically.",
                "Dropbox, Desktop, Downloads, and creative projects are read-only.",
            ],
        },
    }
    if revised_conform.get("authorityKind") == "clean_v1_v2":
        state = assign_clean_shot_identities(state)
        as_finishing_camera_proofs = merge_camera_proof_recovery_overrides(
            load_creative_app_archive(
                AS_FINISHING_CAMERA_PROOFS.relative_to(DATA_DIR).as_posix()
            ),
            load_creative_app_archive(
                AS_FINISHING_CAMERA_PROOF_RECOVERY_OVERRIDES.relative_to(
                    DATA_DIR
                ).as_posix()
            ),
        )
        as_finishing_counts = apply_as_finishing_chronology(
            state,
            load_creative_app_archive(
                AS_FINISHING_CHRONOLOGY.relative_to(DATA_DIR).as_posix()
            ),
            as_finishing_camera_proofs,
            load_creative_app_archive(
                AS_FINISHING_REVISION_TARGETS.relative_to(
                    DATA_DIR
                ).as_posix()
            ),
        )
        unresolved_camera_counts = apply_unresolved_camera_recoveries(
            state,
            load_creative_app_archive(
                C4D_UNRESOLVED_CAMERA_RECOVERIES.relative_to(
                    DATA_DIR
                ).as_posix()
            ),
        )
        # A confirmed source correction is stronger than an older proof
        # attached only by the display CUT ordinal. Apply it after chronology
        # and unresolved-camera overlays so a later scan cannot restore a
        # superseded render family, project, or camera proof to that card.
        state = apply_source_corrections(state)
        state = sync_clean_conform_registry(state)
        manual_lineage_counts = apply_manual_lineage_enrichments(
            state,
            load_creative_app_archive(
                "manual-lineage-enrichments-20260728.json"
            ),
        )
        evidence_integration_counts = (
            integrate_current_c4d_verification_evidence(state)
        )
        exact_source_render_counts = (
            integrate_exact_source_render_selections(state)
        )
        prescription_counts = ensure_agent_ready_c4d_prescriptions(state)
        cuts = state["cuts"]
        log(
            "Preserved canonical Clean V1/V2 source intervals and applied "
            "confirmed source corrections before publishing state; attached "
            f"{as_finishing_counts['appliedRenderLogs']} exact AS Redshift "
            "render logs and "
            f"{unresolved_camera_counts['applied']} evidence-complete "
            "unresolved camera recovery; applied "
            f"{manual_lineage_counts['updatedCuts']} manual cross-app "
            "lineage enrichment; linked "
            f"{evidence_integration_counts['dependencyAuditLinks']} "
            "dependency audits and "
            f"{evidence_integration_counts['linkageAuditLinks']} linkage "
            "audits; selected "
            f"{exact_source_render_counts['selectedRenders']} exact-source "
            "renders, including "
            f"{exact_source_render_counts['visualMatches']} strict visual "
            "matches; published "
            f"{prescription_counts['pictureCutsCovered']} agent-ready "
            "recovery or preservation checklists"
        )
    elif DEFAULT_EDL.exists():
        state = sync_generated_state(state)
        cuts = state["cuts"]
        log(
            "Applied canonical EDL shot order and persistent shot identities "
            "before publishing state"
        )
    # Chronology, recovery overrides, and manual source corrections can replace
    # the selected C4D node after the first dependency pass. Reapply the exact
    # cut/take/frame ledger to the final canonical lineage so the card, drawer,
    # and audit all describe the same project.
    final_exact_dependency_counts = apply_exact_cut_dependency_audits(
        state["cuts"], c4d_cut_relink_summary
    )
    state.setdefault("summary", {}).update(
        final_exact_dependency_counts
    )
    state.setdefault("c4dExactCutDependencyAudit", {}).update(
        {
            "authority": c4d_cut_relink_summary.get("authority"),
            "updatedAt": c4d_cut_relink_summary.get("updatedAt"),
            "manifest": str(C4D_CUT_RELINK_SUMMARY),
            "summary": {
                **(c4d_cut_relink_summary.get("summary") or {}),
                **final_exact_dependency_counts,
            },
        }
    )
    full_color_render_counts = attach_fresh_full_color_render_inventory(
        state["cuts"]
    )
    state.setdefault("summary", {}).update(full_color_render_counts)
    state["c4dFullColorRenderInventory"] = {
        "authority": (
            "Fresh material-enabled Redshift audit renders; manual visual "
            "acceptance remains required for proof status"
        ),
        "manifest": str(C4D_FULL_COLOR_RENDER_INVENTORY),
        "summary": full_color_render_counts,
    }
    refresh_current_c4d_status_rollup(state)
    cuts = state["cuts"]
    target = PUBLIC_DATA_DIR / "state.json"
    temp_target = PUBLIC_DATA_DIR / "state.json.tmp"
    temp_target.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    temp_target.replace(target)
    log(
        f"Indexed {len(cuts)} cut candidates, {len(shots)} planned shots, "
        f"{len(assets)} project files, and {len(renders)} render sequences"
    )
    log(f"Wrote {target} and {DATA_DIR / 'provenance.sqlite'}")


if __name__ == "__main__":
    main()
