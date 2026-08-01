#!/usr/bin/env python3
"""Bake a reviewed piano-note timeline into the separate keys in piano v3."""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path


JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
FLOAT_COMPONENT = 5126


def read_glb(path: Path) -> tuple[dict, bytearray]:
    payload = path.read_bytes()
    magic, version, _ = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2:
        raise ValueError(f"{path.name} is not a glTF 2.0 binary.")
    offset = 12
    json_length, json_type = struct.unpack_from("<II", payload, offset)
    offset += 8
    if json_type != JSON_CHUNK:
        raise ValueError("The first GLB chunk is not JSON.")
    document = json.loads(payload[offset : offset + json_length].decode("utf8"))
    offset += json_length
    bin_length, bin_type = struct.unpack_from("<II", payload, offset)
    offset += 8
    if bin_type != BIN_CHUNK:
        raise ValueError("The second GLB chunk is not binary.")
    return document, bytearray(payload[offset : offset + bin_length])


def align_buffer(buffer: bytearray) -> None:
    while len(buffer) % 4:
        buffer.append(0)


def append_float_accessor(
    document: dict,
    buffer: bytearray,
    values: list[float],
    element_type: str,
    element_width: int,
    minimum: list[float] | None = None,
    maximum: list[float] | None = None,
) -> int:
    align_buffer(buffer)
    byte_offset = len(buffer)
    buffer.extend(struct.pack(f"<{len(values)}f", *values))
    view_index = len(document.setdefault("bufferViews", []))
    document["bufferViews"].append(
        {"buffer": 0, "byteOffset": byte_offset, "byteLength": len(values) * 4}
    )
    accessor = {
        "bufferView": view_index,
        "componentType": FLOAT_COMPONENT,
        "count": len(values) // element_width,
        "type": element_type,
    }
    if minimum is not None:
        accessor["min"] = minimum
    if maximum is not None:
        accessor["max"] = maximum
    accessor_index = len(document.setdefault("accessors", []))
    document["accessors"].append(accessor)
    return accessor_index


def smooth_step(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def key_press_amount(time: float, notes: list[list]) -> float:
    amount = 0.0
    attack = 0.035
    release = 0.065
    for _, _, start, end, _, _ in notes:
        if start - attack <= time < start:
            amount = max(amount, smooth_step((time - start + attack) / attack))
        elif start <= time <= end:
            amount = 1.0
        elif end < time <= end + release:
            amount = max(amount, 1.0 - smooth_step((time - end) / release))
    return amount


def bake_animation(document: dict, buffer: bytearray, performance: dict) -> dict:
    if document.get("animations"):
        raise ValueError("piano-v3.glb unexpectedly already contains animation.")

    notes = []
    for chord_name, start, end, velocity, midi_notes in performance["chords"]:
        for midi in midi_notes:
            notes.append(
                [
                    midi,
                    chord_name,
                    start,
                    end,
                    velocity,
                    "waveform-chord",
                ]
            )
    notes_by_midi: dict[int, list[list]] = {}
    for note in notes:
        notes_by_midi.setdefault(int(note[0]), []).append(note)

    key_nodes: dict[int, tuple[int, str]] = {}
    for node_index, node in enumerate(document.get("nodes", [])):
        name = node.get("name", "")
        if "_MIDI_" not in name:
            continue
        midi = int(name.rsplit("_MIDI_", 1)[1])
        key_nodes[midi] = (node_index, name)

    missing = sorted(set(notes_by_midi) - set(key_nodes))
    if missing:
        raise ValueError(f"Performance refers to missing MIDI keys: {missing}")

    fps = 60
    duration = float(performance["durationSeconds"]) + 0.10
    frame_count = math.ceil(duration * fps) + 1
    times = [frame / fps for frame in range(frame_count)]
    time_accessor = append_float_accessor(
        document,
        buffer,
        times,
        "SCALAR",
        1,
        [times[0]],
        [times[-1]],
    )

    samplers = []
    channels = []
    for midi in sorted(notes_by_midi):
        node_index, node_name = key_nodes[midi]
        is_black = node_name.startswith("BlackKey")
        full_angle = math.radians(1.9 if is_black else 2.15)
        rotations: list[float] = []
        for time in times:
            angle = full_angle * key_press_amount(time, notes_by_midi[midi])
            rotations.extend((math.sin(angle / 2), 0.0, 0.0, math.cos(angle / 2)))
        rotation_accessor = append_float_accessor(
            document,
            buffer,
            rotations,
            "VEC4",
            4,
        )
        sampler_index = len(samplers)
        samplers.append(
            {
                "input": time_accessor,
                "output": rotation_accessor,
                "interpolation": "LINEAR",
            }
        )
        channels.append(
            {
                "sampler": sampler_index,
                "target": {"node": node_index, "path": "rotation"},
            }
        )

    document["animations"] = [
        {
            "name": "VID_5 Performance",
            "samplers": samplers,
            "channels": channels,
            "extras": {
                "source": performance["sourceFile"],
                "review": "waveform attacks plus visual frame verification",
                "chordEvents": performance["summary"]["chordEvents"],
            },
        }
    ]
    document.setdefault("asset", {}).setdefault("extras", {})[
        "pianoPerformance"
    ] = {
        "id": performance["id"],
        "label": performance["label"],
        "durationSeconds": performance["durationSeconds"],
        "chordEvents": performance["summary"]["chordEvents"],
        "distinctKeys": performance["summary"]["distinctKeys"],
    }
    document["buffers"][0]["byteLength"] = len(buffer)
    return {
        "animation": "VID_5 Performance",
        "durationSeconds": round(times[-1], 3),
        "channels": len(channels),
        "samplesPerChannel": frame_count,
    }


def write_glb(path: Path, document: dict, buffer: bytearray) -> None:
    align_buffer(buffer)
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf8")
    while len(json_bytes) % 4:
        json_bytes += b" "
    total_length = 12 + 8 + len(json_bytes) + 8 + len(buffer)
    payload = bytearray(struct.pack("<4sII", b"glTF", 2, total_length))
    payload.extend(struct.pack("<II", len(json_bytes), JSON_CHUNK))
    payload.extend(json_bytes)
    payload.extend(struct.pack("<II", len(buffer), BIN_CHUNK))
    payload.extend(buffer)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    source = root / "public/archive/objects/3d/piano-v3.glb"
    output = root / "public/archive/objects/3d/piano-v4.glb"
    data_path = root / "data/piano-performance-vid5.json"
    document, buffer = read_glb(source)
    performance = json.loads(data_path.read_text())
    result = bake_animation(document, buffer, performance)
    write_glb(output, document, buffer)
    result["model"] = str(output.relative_to(root))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
