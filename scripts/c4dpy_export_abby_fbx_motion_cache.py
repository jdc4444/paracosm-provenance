"""Export native C4D FBX curves into a compact retargeting cache."""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path

import c4d


FPS = 30
START_FRAME = 0
END_FRAME = 299


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def desc_payload(desc_id: c4d.DescID) -> list[list[int]]:
    return [
        [
            int(desc_id[index].id),
            int(desc_id[index].dtype),
            int(desc_id[index].creator),
        ]
        for index in range(desc_id.GetDepth())
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fbx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fbx = args.fbx.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite motion cache: {output}")

    doc = c4d.documents.LoadDocument(
        str(fbx),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {fbx}")

    try:
        records = []
        curve_count = 0
        key_count = 0
        for item in walk_objects(doc.GetFirstObject()):
            tracks = []
            for track in item.GetCTracks():
                curve = track.GetCurve()
                if curve is None:
                    continue
                values = [
                    float(
                        curve.GetValue(c4d.BaseTime(frame, FPS))
                    )
                    for frame in range(START_FRAME, END_FRAME + 1)
                ]
                value_range = max(values) - min(values)
                tracks.append(
                    {
                        "desc": desc_payload(track.GetDescriptionID()),
                        "base": values[0],
                        "values": values if value_range > 1.0e-7 else None,
                    }
                )
                if value_range > 1.0e-7:
                    curve_count += 1
                    key_count += len(values)
            if tracks:
                records.append(
                    {
                        "name": item.GetName(),
                        "path": object_path(item),
                        "tracks": tracks,
                    }
                )

        payload = {
            "source": str(fbx),
            "fps": FPS,
            "startFrame": START_FRAME,
            "endFrame": END_FRAME,
            "objects": records,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(output, "wt", encoding="utf-8", compresslevel=9) as handle:
            json.dump(payload, handle, separators=(",", ":"))
        print(
            "ABBY_FBX_MOTION_CACHE="
            + json.dumps(
                {
                    "source": str(fbx),
                    "output": str(output),
                    "objects": len(records),
                    "varyingCurves": curve_count,
                    "keys": key_count,
                    "fps": FPS,
                    "frames": END_FRAME - START_FRAME + 1,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
