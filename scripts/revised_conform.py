#!/usr/bin/env python3
"""Read the user-aligned Premiere conform without changing the project.

V1 is the authoritative final-cut/gap map. V5 contains sources known to be
older than the cut, V6 contains exact matches, and V7 contains sources known
to be newer than the cut. Timeline trims and source In/Out values are copied
directly from the saved Premiere clip instances.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = (
    APP_ROOT / "data" / "premiere" / "Paracosm_Source_Conform_VERIFIED_V2.prproj"
)
DEFAULT_OUTPUT = (
    APP_ROOT / "data" / "premiere" / "revised-conform-export.json"
)
REFERENCE_MOV = Path(
    "/Users/alphaone/Desktop/desktop 0705/Paracosm Full Copy 01.mov"
)
SEQUENCE_NAME = "Paracosm Source Conform"
TICKS_PER_SECOND = 254_016_000_000
TIMELINE_FPS = 24_000 / 1_001
SOURCE_FPS = 24.0

TRACK_SEMANTICS = {
    1: {
        "role": "final_cut",
        "label": "Final cut and intentional gaps",
        "premiereLabel": None,
    },
    5: {
        "role": "older_than_cut",
        "label": "Older render than final cut",
        "premiereLabel": "Rose",
        "premiereLabelIndex": 6,
    },
    6: {
        "role": "exact_match",
        "label": "Exact render match",
        "premiereLabel": "Iris",
        "premiereLabelIndex": 1,
    },
    7: {
        "role": "newer_than_cut",
        "label": "Newer render than final cut",
        "premiereLabel": "Green",
        "premiereLabelIndex": 13,
    },
}

SECTION_NAMES = {
    "ND": "Natural Disaster",
    "NTH": "Nothing to Hide",
    "TH": "Teardrop",
    "NA": "New Again",
    "GG": "Goodbye Glitter",
    "IJDKYY": "If You Don't Know Yourself Yet",
    "GAP": "Intentional blank",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_object_graph(
    root: ET.Element,
) -> tuple[dict[str, ET.Element], dict[str, ET.Element]]:
    by_id: dict[str, ET.Element] = {}
    by_uid: dict[str, ET.Element] = {}
    for element in root.iter():
        if object_id := element.attrib.get("ObjectID"):
            by_id[object_id] = element
        if object_uid := element.attrib.get("ObjectUID"):
            by_uid[object_uid] = element
    return by_id, by_uid


def object_ref(element: ET.Element | None, tag: str) -> str | None:
    if element is None:
        return None
    child = element.find(f".//{tag}")
    return child.attrib.get("ObjectRef") if child is not None else None


def normalize_local_media_path(value: str) -> str:
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


def media_for_subclip(
    subclip: ET.Element,
    by_id: dict[str, ET.Element],
    by_uid: dict[str, ET.Element],
) -> tuple[ET.Element | None, ET.Element | None, ET.Element | None]:
    clip = by_id.get(object_ref(subclip, "Clip") or "")
    source = by_id.get(object_ref(clip, "Source") or "")
    media_link = source.find(".//Media") if source is not None else None
    media = (
        by_uid.get(media_link.attrib.get("ObjectURef", ""))
        if media_link is not None
        else None
    )
    return clip, source, media


def media_path(media: ET.Element | None) -> str:
    if media is None:
        return ""
    return normalize_local_media_path(
        media.findtext("ActualMediaFilePath")
        or media.findtext("FilePath")
        or media.findtext("RelativePath")
        or ""
    )


def project_item_label(
    subclip: ET.Element,
    by_id: dict[str, ET.Element],
    by_uid: dict[str, ET.Element],
) -> dict[str, Any]:
    master_link = subclip.find("MasterClip")
    master = (
        by_uid.get(master_link.attrib.get("ObjectURef", ""))
        if master_link is not None
        else None
    )
    clip_link = master.find("./Clips/Clip") if master is not None else None
    clip = (
        by_id.get(clip_link.attrib.get("ObjectRef", ""))
        if clip_link is not None
        else None
    )
    label_key = (
        clip.findtext(".//asl.clip.label.name") if clip is not None else None
    )
    match = re.search(r"LabelColors\.(\d+)", label_key or "")
    return {
        "key": label_key,
        "index": int(match.group(1)) if match else None,
        "colorValue": (
            clip.findtext(".//asl.clip.label.color")
            if clip is not None
            else None
        ),
    }


def source_frame_rate(
    media: ET.Element | None,
    by_id: dict[str, ET.Element],
) -> tuple[float | None, bool]:
    stream_link = media.find("VideoStream") if media is not None else None
    stream = (
        by_id.get(stream_link.attrib.get("ObjectRef", ""))
        if stream_link is not None
        else None
    )
    if stream is None:
        return None, False
    overridden = (
        (stream.findtext("IsFrameRateOverridden") or "").lower() == "true"
    )
    ticks = int(
        stream.findtext("OveriddenFrameRate")
        or stream.findtext("FrameRate")
        or 0
    )
    return (
        TICKS_PER_SECOND / ticks if ticks else None,
        overridden,
    )


def frame_number(path: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)(?=\.[^.]+$)", Path(path).name)
    return (
        (int(match.group(1)), len(match.group(1)))
        if match
        else (None, None)
    )


def section_for(name: str, start: float) -> str:
    normalized = name.lower()
    if "natural disaster" in normalized:
        return "ND"
    if "nth" in normalized:
        return "NTH"
    if "th_test" in normalized or "teardrop" in normalized:
        return "TH"
    if normalized.startswith("na_") or "new again" in normalized:
        return "NA"
    if "goodbye glitter" in normalized:
        return "GG"
    if "ijdkyy" in normalized:
        return "IJDKYY"
    for code, threshold in (
        ("IJDKYY", 359.0),
        ("GG", 284.0),
        ("NA", 205.0),
        ("TH", 138.0),
        ("NTH", 69.0),
        ("ND", 0.0),
    ):
        if start >= threshold:
            return code
    return "ND"


def union_frames(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    result = 0
    current_start, current_end = sorted(intervals)[0]
    for start, end in sorted(intervals)[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            result += current_end - current_start
            current_start, current_end = start, end
    return result + current_end - current_start


def source_coverage(
    edit: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    overlaps = []
    for source in sources:
        overlap_start = max(edit["startFrame"], source["startFrame"])
        overlap_end = min(edit["endFrame"], source["endFrame"])
        if overlap_end <= overlap_start:
            continue
        overlaps.append(
            {
                "sourceId": source["id"],
                "role": source["role"],
                "track": source["track"],
                "overlapStartFrame": overlap_start,
                "overlapEndFrame": overlap_end,
                "overlapFrames": overlap_end - overlap_start,
            }
        )
    roles = sorted({item["role"] for item in overlaps})
    any_frames = union_frames(
        [
            (item["overlapStartFrame"], item["overlapEndFrame"])
            for item in overlaps
        ]
    )
    exact_frames = union_frames(
        [
            (item["overlapStartFrame"], item["overlapEndFrame"])
            for item in overlaps
            if item["role"] == "exact_match"
        ]
    )
    total_frames = edit["endFrame"] - edit["startFrame"]
    full_exact = exact_frames >= total_frames
    full_any = any_frames >= total_frames
    if full_exact:
        status = "exact_match"
    elif {"older_than_cut", "newer_than_cut"}.issubset(roles):
        status = "bracketed_missing_exact"
    elif "exact_match" in roles:
        status = "partially_exact"
    elif "older_than_cut" in roles:
        status = "older_than_cut" if full_any else "partially_tracked"
    elif "newer_than_cut" in roles:
        status = "newer_than_cut" if full_any else "partially_tracked"
    else:
        status = "untracked"
    return {
        "status": status,
        "roles": roles,
        "sourceIds": [item["sourceId"] for item in overlaps],
        "overlaps": overlaps,
        "coveredFrames": any_frames,
        "exactFrames": exact_frames,
        "totalFrames": total_frames,
        "coverage": round(any_frames / total_frames, 6) if total_frames else 0,
        "exactCoverage": (
            round(exact_frames / total_frames, 6) if total_frames else 0
        ),
        "fullyTracked": full_any,
        "fullyExact": full_exact,
    }


def reference_metadata(reference: Path) -> tuple[float, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames:format=duration",
            "-of",
            "json",
            str(reference),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return (
        float(payload["format"]["duration"]),
        int(payload["streams"][0]["nb_frames"]),
    )


def parse_revised_conform(
    project_path: Path = DEFAULT_PROJECT,
    output_path: Path | None = DEFAULT_OUTPUT,
    reference_duration: float | None = None,
    reference_frames: int | None = None,
    sequence_name: str = SEQUENCE_NAME,
) -> dict[str, Any]:
    project_path = project_path.expanduser().resolve()
    payload = gzip.open(project_path, "rb").read()
    root = ET.fromstring(payload)
    by_id, by_uid = resolve_object_graph(root)
    sequence = next(
        (
            item
            for item in root.iter("Sequence")
            if item.findtext("Name") == sequence_name
        ),
        None,
    )
    if sequence is None:
        raise RuntimeError(f'Premiere sequence "{sequence_name}" was not found')

    if reference_duration is None or reference_frames is None:
        reference_duration, reference_frames = reference_metadata(REFERENCE_MOV)
    frame_duration = 1 / TIMELINE_FPS

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
    if video_group is None:
        raise RuntimeError("The revised sequence has no video tracks")

    tracks: dict[int, list[dict[str, Any]]] = {}
    source_number = 0
    edit_number = 0
    for track_link in video_group.findall("./TrackGroup/Tracks/Track"):
        track = by_uid.get(track_link.attrib.get("ObjectURef", ""))
        if track is None:
            continue
        track_number = int(track.findtext(".//Index") or 0) + 1
        if track_number not in TRACK_SEMANTICS:
            continue
        semantic = TRACK_SEMANTICS[track_number]
        records = []
        for item_link in track.findall(
            ".//ClipItems/TrackItems/TrackItem"
        ):
            item = by_id.get(item_link.attrib.get("ObjectRef", ""))
            if item is None or item.tag != "VideoClipTrackItem":
                continue
            subclip = by_id.get(object_ref(item, "SubClip") or "")
            if subclip is None:
                continue
            clip, _, media = media_for_subclip(subclip, by_id, by_uid)
            start_ticks = int(item.findtext(".//TrackItem/Start") or 0)
            end_ticks = int(item.findtext(".//TrackItem/End") or 0)
            source_in_ticks = int(clip.findtext(".//InPoint") or 0)
            source_out_ticks = int(clip.findtext(".//OutPoint") or 0)
            start_frame = round(start_ticks / TICKS_PER_SECOND * TIMELINE_FPS)
            end_frame = round(end_ticks / TICKS_PER_SECOND * TIMELINE_FPS)
            source_in_frame_offset = round(
                source_in_ticks / TICKS_PER_SECOND * TIMELINE_FPS
            )
            source_out_frame_offset = round(
                source_out_ticks / TICKS_PER_SECOND * TIMELINE_FPS
            )
            path = media_path(media)
            first_frame, frame_padding = frame_number(path)
            rate, rate_overridden = source_frame_rate(media, by_id)
            if track_number == 1:
                edit_number += 1
                record_id = f"EDIT-{edit_number:03d}"
            else:
                source_number += 1
                record_id = f"USER-SRC-{source_number:03d}"
            label = project_item_label(subclip, by_id, by_uid)
            code = section_for(subclip.findtext("Name") or "", start_ticks / TICKS_PER_SECOND)
            record = {
                "id": record_id,
                "track": track_number,
                "role": semantic["role"],
                "name": subclip.findtext("Name") or "Untitled",
                "path": path,
                "renderDirectory": (
                    str(Path(path).parent)
                    if Path(path).suffix.lower()
                    in {".tif", ".tiff", ".png", ".exr", ".jpg", ".jpeg"}
                    else None
                ),
                "sectionCode": code,
                "sectionName": SECTION_NAMES[code],
                "startTicks": start_ticks,
                "endTicks": end_ticks,
                "start": round(start_ticks / TICKS_PER_SECOND, 9),
                "end": round(end_ticks / TICKS_PER_SECOND, 9),
                "duration": round(
                    (end_ticks - start_ticks) / TICKS_PER_SECOND, 9
                ),
                "startFrame": start_frame,
                "endFrame": end_frame,
                "durationFrames": end_frame - start_frame,
                "sourceInTicks": source_in_ticks,
                "sourceOutTicks": source_out_ticks,
                "sourceIn": round(
                    source_in_ticks / TICKS_PER_SECOND, 9
                ),
                "sourceOut": round(
                    source_out_ticks / TICKS_PER_SECOND, 9
                ),
                "sourceInFrameOffset": source_in_frame_offset,
                "sourceOutFrameOffset": source_out_frame_offset,
                "mediaFirstFrame": first_frame,
                "mediaFramePadding": frame_padding,
                "selectedFirstFrame": (
                    first_frame + source_in_frame_offset
                    if first_frame is not None
                    else None
                ),
                "selectedEndFrameExclusive": (
                    first_frame + source_out_frame_offset
                    if first_frame is not None
                    else None
                ),
                "selectedLastFrame": (
                    first_frame + source_out_frame_offset - 1
                    if first_frame is not None
                    else None
                ),
                "playBackwards": (
                    (clip.findtext(".//PlayBackwards") or "").lower()
                    == "true"
                ),
                "sourceFrameRate": (
                    round(rate, 6) if rate is not None else None
                ),
                "sourceFrameRateOverridden": rate_overridden,
                "premiereLabel": label,
                "premiereLabelExpected": semantic.get(
                    "premiereLabel"
                ),
                "premiereLabelExpectedIndex": semantic.get(
                    "premiereLabelIndex"
                ),
                "manualTrimAuthority": True,
            }
            records.append(record)
        tracks[track_number] = sorted(
            records, key=lambda item: (item["startFrame"], item["endFrame"])
        )

    edits = tracks.get(1, [])
    sources = sorted(
        [
            item
            for track_number in (5, 6, 7)
            for item in tracks.get(track_number, [])
        ],
        key=lambda item: (
            item["startFrame"],
            item["track"],
            item["endFrame"],
        ),
    )
    for edit in edits:
        edit["sourceCoverage"] = source_coverage(edit, sources)

    gaps = []
    cursor = 0
    for edit in edits:
        if edit["startFrame"] > cursor:
            gaps.append(
                {
                    "id": f"GAP-{len(gaps) + 1:03d}",
                    "role": "intentional_blank",
                    "sectionCode": "GAP",
                    "sectionName": SECTION_NAMES["GAP"],
                    "startFrame": cursor,
                    "endFrame": edit["startFrame"],
                    "durationFrames": edit["startFrame"] - cursor,
                    "start": round(cursor * frame_duration, 9),
                    "end": round(edit["startFrame"] * frame_duration, 9),
                    "duration": round(
                        (edit["startFrame"] - cursor) * frame_duration, 9
                    ),
                    "manualTrimAuthority": True,
                }
            )
        cursor = max(cursor, edit["endFrame"])
    if cursor < reference_frames:
        gaps.append(
            {
                "id": f"GAP-{len(gaps) + 1:03d}",
                "role": "intentional_blank",
                "sectionCode": "GAP",
                "sectionName": SECTION_NAMES["GAP"],
                "startFrame": cursor,
                "endFrame": reference_frames,
                "durationFrames": reference_frames - cursor,
                "start": round(cursor * frame_duration, 9),
                "end": round(reference_frames * frame_duration, 9),
                "duration": round(
                    (reference_frames - cursor) * frame_duration, 9
                ),
                "manualTrimAuthority": True,
            }
        )

    inventory = sorted(
        [*edits, *gaps],
        key=lambda item: (item["startFrame"], item["endFrame"]),
    )
    for index, item in enumerate(inventory, start=1):
        item["canonicalId"] = f"CUT-{index:03d}"
        item["canonicalIndex"] = index

    stat = project_path.stat()
    result = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "authority": "user_aligned_premiere_sequence",
        "manualTrimPolicy": (
            "Timeline start/end and source In/Out are copied directly from "
            "the saved Premiere clip instances and are never regenerated "
            "from the prior automated conform."
        ),
        "projectPath": str(project_path),
        "projectSize": stat.st_size,
        "projectModifiedAt": datetime.fromtimestamp(
            stat.st_mtime, timezone.utc
        ).isoformat(),
        "projectSha256": hashlib.sha256(project_path.read_bytes()).hexdigest(),
        "sequence": sequence_name,
        "timelineFrameRate": TIMELINE_FPS,
        "sourceImageFrameRate": SOURCE_FPS,
        "referenceDuration": reference_duration,
        "referenceFrames": reference_frames,
        "trackSemantics": {
            str(key): value for key, value in TRACK_SEMANTICS.items()
        },
        "tracks": {str(key): value for key, value in tracks.items()},
        "edits": edits,
        "gaps": gaps,
        "sources": sources,
        "inventory": inventory,
        "summary": {
            "v1PictureClips": len(edits),
            "intentionalBlanks": len(gaps),
            "v5OlderSources": len(tracks.get(5, [])),
            "v6ExactSources": len(tracks.get(6, [])),
            "v7NewerSources": len(tracks.get(7, [])),
            "exactCuts": sum(
                item["sourceCoverage"]["status"] == "exact_match"
                for item in edits
            ),
            "partiallyExactCuts": sum(
                item["sourceCoverage"]["status"] == "partially_exact"
                for item in edits
            ),
            "bracketedMissingExactCuts": sum(
                item["sourceCoverage"]["status"]
                == "bracketed_missing_exact"
                for item in edits
            ),
            "olderCuts": sum(
                item["sourceCoverage"]["status"] == "older_than_cut"
                for item in edits
            ),
            "newerCuts": sum(
                item["sourceCoverage"]["status"] == "newer_than_cut"
                for item in edits
            ),
            "partiallyTrackedCuts": sum(
                item["sourceCoverage"]["status"] == "partially_tracked"
                for item in edits
            ),
            "untrackedCuts": sum(
                item["sourceCoverage"]["status"] == "untracked"
                for item in edits
            ),
            "exactTimelineFrames": union_frames(
                [
                    (item["startFrame"], item["endFrame"])
                    for item in sources
                    if item["role"] == "exact_match"
                ]
            ),
            "pictureTimelineFrames": sum(
                item["durationFrames"] for item in edits
            ),
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sequence-name", default=SEQUENCE_NAME)
    args = parser.parse_args()
    result = parse_revised_conform(
        args.project,
        args.output,
        sequence_name=args.sequence_name,
    )
    print(
        "Revised Premiere conform: "
        f"{result['summary']['v1PictureClips']} V1 clips · "
        f"{result['summary']['v5OlderSources']} older · "
        f"{result['summary']['v6ExactSources']} exact · "
        f"{result['summary']['v7NewerSources']} newer · "
        f"{result['summary']['intentionalBlanks']} true blanks"
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
