#!/usr/bin/env python3
"""Export the saved Clean conform directly from Premiere's project XML.

Premiere projects are gzip-compressed XML. Reading the saved project avoids
depending on the CEP panel when the user has just corrected the live sequence,
while retaining the exact timeline and source ticks used by the normal Clean
conform parser.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from revised_conform import (
    TICKS_PER_SECOND,
    media_for_subclip,
    media_path,
    object_ref,
    resolve_object_graph,
    source_frame_rate,
)


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = (
    APP_ROOT / "data" / "premiere" / "confirm 0725 Codex JD.prproj"
)
DEFAULT_OUTPUT = (
    APP_ROOT / "data" / "premiere" / "clean-conform-latest.json"
)
SEQUENCE_NAME = "Paracosm Conform Codex JD Clean"
TIMELINE_TICKS_PER_FRAME = 10_594_584_000


def time_value(ticks: int) -> dict[str, Any]:
    return {
        "ticks": str(ticks),
        "seconds": ticks / TICKS_PER_SECOND,
    }


def track_items(
    group: ET.Element,
    by_id: dict[str, ET.Element],
    by_uid: dict[str, ET.Element],
    *,
    media_type: str,
) -> list[dict[str, Any]]:
    tracks = []
    expected_tag = (
        "VideoClipTrackItem"
        if media_type == "video"
        else "AudioClipTrackItem"
    )
    for track_link in group.findall("./TrackGroup/Tracks/Track"):
        track = by_uid.get(track_link.attrib.get("ObjectURef", ""))
        if track is None:
            continue
        track_index = int(track.findtext(".//Index") or 0)
        clips = []
        for clip_index, item_link in enumerate(
            track.findall(".//ClipItems/TrackItems/TrackItem")
        ):
            item = by_id.get(item_link.attrib.get("ObjectRef", ""))
            if item is None or item.tag != expected_tag:
                continue
            subclip = by_id.get(object_ref(item, "SubClip") or "")
            if subclip is None:
                continue
            clip, _, media = media_for_subclip(subclip, by_id, by_uid)
            if clip is None:
                continue
            start_ticks = int(item.findtext(".//TrackItem/Start") or 0)
            end_ticks = int(item.findtext(".//TrackItem/End") or 0)
            in_ticks = int(clip.findtext(".//InPoint") or 0)
            out_ticks = int(clip.findtext(".//OutPoint") or 0)
            path = media_path(media)
            rate, _ = source_frame_rate(media, by_id)
            clips.append(
                {
                    "trackIndex": track_index,
                    "clipIndex": clip_index,
                    "mediaType": media_type,
                    "name": subclip.findtext("Name") or Path(path).name,
                    "nodeId": item.attrib.get("ObjectID") or "",
                    "start": time_value(start_ticks),
                    "end": time_value(end_ticks),
                    "inPoint": time_value(in_ticks),
                    "outPoint": time_value(out_ticks),
                    "duration": time_value(end_ticks - start_ticks),
                    "speed": 1,
                    "speedReversed": (
                        (clip.findtext(".//PlayBackwards") or "").lower()
                        == "true"
                    ),
                    "projectItem": {
                        "name": Path(path).name,
                        "nodeId": subclip.attrib.get("ObjectID") or "",
                        "mediaPath": path,
                        "footageInterpretation": {
                            "frameRate": rate or 24.0,
                        },
                    },
                    "components": [],
                }
            )
        tracks.append(
            {
                "trackIndex": track_index,
                "name": track.findtext("Name")
                or f"{media_type.title()} {track_index + 1}",
                "mediaType": media_type,
                "clips": clips,
                "isMuted": (
                    (track.findtext(".//IsMuted") or "").lower() == "true"
                ),
                "isLocked": False,
            }
        )
    return tracks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sequence-name", default=SEQUENCE_NAME)
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Inspect the supplied project in place instead of archiving a copy.",
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    root = ET.fromstring(gzip.open(project, "rb").read())
    by_id, by_uid = resolve_object_graph(root)
    sequence = next(
        (
            item
            for item in root.iter("Sequence")
            if item.findtext("Name") == args.sequence_name
        ),
        None,
    )
    if sequence is None:
        raise SystemExit(
            f'Premiere sequence "{args.sequence_name}" was not found.'
        )

    group_refs = [
        item.attrib.get("ObjectRef")
        for item in sequence.findall("./TrackGroups/TrackGroup/Second")
        if item.attrib.get("ObjectRef")
    ]
    video_group = next(
        (
            by_id[ref]
            for ref in group_refs
            if ref in by_id and by_id[ref].tag == "VideoTrackGroup"
        ),
        None,
    )
    audio_group = next(
        (
            by_id[ref]
            for ref in group_refs
            if ref in by_id and by_id[ref].tag == "AudioTrackGroup"
        ),
        None,
    )
    if video_group is None or audio_group is None:
        raise SystemExit("The Clean conform video/audio track groups were not found.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project_export = project
    if not args.no_copy:
        project_export = (
            args.output.parent
            / f"Paracosm_Conform_Codex_JD_Clean_CANONICAL_{stamp}.prproj"
        )
        shutil.copy2(project, project_export)
    payload = {
        "schemaVersion": 2,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "projectPath": str(project),
        "expectedSequence": args.sequence_name,
        "success": True,
        "errors": [],
        "sequence": {
            "name": args.sequence_name,
            "sequenceId": sequence.attrib.get("ObjectUID") or "",
            "timebaseTicksPerFrame": str(TIMELINE_TICKS_PER_FRAME),
            "ticksPerSecond": TICKS_PER_SECOND,
            "videoTracks": track_items(
                video_group,
                by_id,
                by_uid,
                media_type="video",
            ),
            "audioTracks": track_items(
                audio_group,
                by_id,
                by_uid,
                media_type="audio",
            ),
        },
        "projectExport": str(project_export),
        "fcpXml": "",
        "inventoryPath": str(args.output),
        "fcpXmlExported": False,
        "projectExported": True,
        "exportMethod": "saved_prproj_xml",
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "projectExport": str(project_export),
                "videoTracks": {
                    f"V{item['trackIndex'] + 1}": len(item["clips"])
                    for item in payload["sequence"]["videoTracks"][:2]
                },
                "audio1Clips": len(
                    payload["sequence"]["audioTracks"][0]["clips"]
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
