#!/usr/bin/env python3
"""Build an importable Premiere FCP7 XML from the user-aligned conform.

The saved Premiere-derived JSON remains the timing authority. Existing V1 and
V5-V7 clip instances are copied frame-for-frame, then newly recovered sources
are added to the semantic track declared in source-confirmations.json. Only
newly added clips receive the Yellow label.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVISED = ROOT / "data" / "premiere" / "revised-conform-export.json"
CONFIRMATIONS = ROOT / "data" / "source-confirmations.json"
OUTPUT = ROOT / "data" / "premiere" / "Paracosm_Source_Conform_YELLOW_RECOVERIES.xml"
SEQUENCE_NAME = "Paracosm Source Conform YELLOW RECOVERIES"
LABEL_NAMES = {
    0: "Violet",
    1: "Iris",
    2: "Caribbean",
    3: "Lavender",
    4: "Cerulean",
    5: "Forest",
    6: "Rose",
    7: "Mango",
    8: "Purple",
    9: "Blue",
    10: "Teal",
    11: "Magenta",
    12: "Tan",
    13: "Green",
    14: "Brown",
    15: "Yellow",
}


def child(parent: ET.Element, name: str, text: Any | None = None) -> ET.Element:
    node = ET.SubElement(parent, name)
    if text is not None:
        node.text = str(text)
    return node


def rate(parent: ET.Element) -> None:
    node = child(parent, "rate")
    child(node, "timebase", 24)
    child(node, "ntsc", "TRUE")


def path_url(path: str) -> str:
    return "file://localhost" + urllib.parse.quote(path, safe="/:")


def image_sequence_length(path: Path, minimum: int) -> int:
    match = re.match(r"^(.*?)(\d+)(\.[^.]+)$", path.name)
    if not match or not path.parent.is_dir():
        return max(minimum, 1)
    prefix, _, suffix = match.groups()
    frames: list[int] = []
    pattern = re.compile(
        rf"^{re.escape(prefix)}(\d+){re.escape(suffix)}$", re.IGNORECASE
    )
    for candidate in path.parent.iterdir():
        found = pattern.match(candidate.name)
        if found:
            frames.append(int(found.group(1)))
    return max(minimum, len(frames), 1)


def sample_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        if path.suffix.lower() in {
            ".png",
            ".tif",
            ".tiff",
            ".jpg",
            ".jpeg",
            ".exr",
        }:
            with Image.open(path) as image:
                return image.size
    except Exception:
        pass
    return 1920, 1080


def add_file(
    clip: ET.Element,
    file_id: str,
    path: Path,
    duration: int,
) -> None:
    file_node = child(clip, "file")
    file_node.set("id", file_id)
    child(file_node, "name", path.name)
    child(file_node, "pathurl", path_url(str(path)))
    rate(file_node)
    child(file_node, "duration", max(duration, 1))
    timecode = child(file_node, "timecode")
    rate(timecode)
    child(timecode, "string", "00:00:00:00")
    child(timecode, "frame", 0)
    child(timecode, "displayformat", "NDF")
    media = child(file_node, "media")
    video = child(media, "video")
    sample = child(video, "samplecharacteristics")
    rate(sample)
    width, height = sample_size(path)
    child(sample, "width", width)
    child(sample, "height", height)
    child(sample, "anamorphic", "FALSE")
    child(sample, "pixelaspectratio", "square")
    child(sample, "fielddominance", "none")


def add_clip(
    track: ET.Element,
    record: dict[str, Any],
    clip_index: int,
    label: str,
) -> None:
    start = int(record["startFrame"])
    end = int(record["endFrame"])
    source_in = int(record["sourceInFrameOffset"])
    source_out = int(record["sourceOutFrameOffset"])
    duration = max(end - start, source_out, 1)
    path = Path(str(record["path"]))
    if path.suffix.lower() in {".png", ".tif", ".tiff", ".jpg", ".jpeg", ".exr"}:
        duration = image_sequence_length(path, duration)

    clip = child(track, "clipitem")
    clip.set("id", f"yellow-clipitem-{clip_index}")
    child(clip, "masterclipid", f"yellow-masterclip-{clip_index}")
    child(clip, "name", record["name"])
    child(clip, "enabled", "TRUE")
    child(clip, "duration", duration)
    rate(clip)
    child(clip, "start", start)
    child(clip, "end", end)
    child(clip, "in", source_in)
    child(clip, "out", source_out)
    child(clip, "pproTicksIn", int(record.get("sourceInTicks") or 0))
    child(clip, "pproTicksOut", int(record.get("sourceOutTicks") or 0))
    child(clip, "alphatype", "none")
    child(clip, "pixelaspectratio", "square")
    child(clip, "anamorphic", "FALSE")
    add_file(clip, f"yellow-file-{clip_index}", path, duration)
    labels = child(clip, "labels")
    child(labels, "label2", label)


def make_recovery_records(
    revised: dict[str, Any], confirmations: dict[str, Any]
) -> list[dict[str, Any]]:
    edits = {
        item["canonicalId"]: item
        for item in revised["inventory"]
        if item.get("role") == "final_cut"
    }
    recovered: list[dict[str, Any]] = []
    for confirmation in confirmations["confirmations"]:
        track = int(confirmation.get("conformTrack") or 0)
        if track not in {5, 6, 7}:
            continue
        edit = edits.get(confirmation["cutId"])
        if not edit:
            raise RuntimeError(f'{confirmation["cutId"]}: V1 interval is missing')
        duration_frames = int(edit["endFrame"]) - int(edit["startFrame"])
        recovered.append(
            {
                "cutId": confirmation["cutId"],
                "track": track,
                "role": confirmation["conformRole"],
                "name": (
                    f'YELLOW-{confirmation["status"].upper()}-'
                    f'{confirmation["cutId"]} · {Path(confirmation["sourcePath"]).name}'
                ),
                "path": confirmation["sourcePath"],
                "startFrame": int(edit["startFrame"]),
                "endFrame": int(edit["endFrame"]),
                "sourceInFrameOffset": 0,
                "sourceOutFrameOffset": duration_frames,
                "sourceInTicks": 0,
                "sourceOutTicks": duration_frames * 10_594_584_000,
                "label": "Yellow",
                "status": confirmation["status"],
            }
        )
    return recovered


def main() -> None:
    revised = json.loads(REVISED.read_text())
    confirmations = json.loads(CONFIRMATIONS.read_text())
    recovered = make_recovery_records(revised, confirmations)

    xmeml = ET.Element("xmeml", version="5")
    sequence = child(xmeml, "sequence")
    sequence.set("id", "yellow-recovery-sequence")
    child(sequence, "name", SEQUENCE_NAME)
    child(sequence, "duration", revised["referenceFrames"])
    rate(sequence)
    timecode = child(sequence, "timecode")
    rate(timecode)
    child(timecode, "string", "00:00:00:00")
    child(timecode, "frame", 0)
    child(timecode, "displayformat", "NDF")

    media = child(sequence, "media")
    video = child(media, "video")
    fmt = child(video, "format")
    sample = child(fmt, "samplecharacteristics")
    rate(sample)
    child(sample, "width", 1920)
    child(sample, "height", 1080)
    child(sample, "anamorphic", "FALSE")
    child(sample, "pixelaspectratio", "square")
    child(sample, "fielddominance", "none")

    tracks = {track_number: child(video, "track") for track_number in range(1, 8)}
    records_by_track: dict[int, list[dict[str, Any]]] = {
        1: list(revised["tracks"]["1"]),
        5: list(revised["tracks"]["5"]),
        6: list(revised["tracks"]["6"]),
        7: list(revised["tracks"]["7"]),
    }
    for record in recovered:
        records_by_track[record["track"]].append(record)

    clip_index = 0
    for track_number in range(1, 8):
        for record in sorted(
            records_by_track.get(track_number, []),
            key=lambda item: (item["startFrame"], item["endFrame"], item["name"]),
        ):
            clip_index += 1
            label = record.get("label")
            if not label:
                label_index = (
                    (record.get("premiereLabel") or {}).get("index")
                    if isinstance(record.get("premiereLabel"), dict)
                    else None
                )
                label = LABEL_NAMES.get(label_index, "Violet")
            add_clip(tracks[track_number], record, clip_index, label)
        child(tracks[track_number], "enabled", "TRUE")
        child(tracks[track_number], "locked", "FALSE")

    ET.indent(xmeml, space="  ")
    OUTPUT.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(xmeml, encoding="unicode")
        + "\n"
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "sequence": SEQUENCE_NAME,
                "v1Clips": len(records_by_track[1]),
                "existingSources": sum(
                    len(revised["tracks"][str(track)]) for track in (5, 6, 7)
                ),
                "newRecoveries": [
                    {
                        "cutId": item["cutId"],
                        "track": item["track"],
                        "label": item["label"],
                        "status": item["status"],
                    }
                    for item in recovered
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
