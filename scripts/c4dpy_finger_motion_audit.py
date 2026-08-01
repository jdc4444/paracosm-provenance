"""Read-only audit of finger rotation ranges in a Cinema 4D/FBX animation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        fingers = {
            item.GetName(): item
            for item in walk(doc.GetFirstObject())
            if "Hand" in item.GetName()
            and item.GetName() not in {"LeftHand", "RightHand"}
            and not item.GetName().endswith("_IK")
        }
        samples = {
            name: {"x": [], "y": [], "z": []} for name in fingers
        }
        fps = doc.GetFps()
        for frame in range(args.start, args.end + 1):
            doc.SetTime(c4d.BaseTime(frame, fps))
            doc.ExecutePasses(None, True, True, True, 0)
            for name, item in fingers.items():
                rotation = item.GetRelRot()
                samples[name]["x"].append(float(rotation.x))
                samples[name]["y"].append(float(rotation.y))
                samples[name]["z"].append(float(rotation.z))
        records = []
        for name, axes in samples.items():
            ranges = {axis: max(values) - min(values) for axis, values in axes.items()}
            records.append(
                {
                    "name": name,
                    "rangesRadians": ranges,
                    "maxRangeRadians": max(ranges.values()),
                }
            )
        records.sort(key=lambda item: (-item["maxRangeRadians"], item["name"]))
        print(
            "ABBY_FINGER_MOTION_AUDIT="
            + json.dumps(
                {
                    "source": str(project),
                    "fps": fps,
                    "range": [args.start, args.end],
                    "fingerCount": len(records),
                    "animatedFingerCount": sum(
                        item["maxRangeRadians"] > 1.0e-5 for item in records
                    ),
                    "records": records,
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
