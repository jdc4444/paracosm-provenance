"""Probe a baked Blender FBX at selected frames inside Cinema 4D."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


JOINTS = (
    "Hips",
    "Head",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "LeftFoot",
    "RightFoot",
)


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def vector(value):
    return [value.x, value.y, value.z]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
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
        nodes = {
            item.GetName(): item
            for item in walk(doc.GetFirstObject())
            if item.GetName() in JOINTS
        }
        missing = sorted(set(JOINTS) - set(nodes))
        if missing:
            raise RuntimeError(f"Missing joints: {missing}")
        records = []
        for frame in args.frames:
            doc.SetTime(c4d.BaseTime(frame, doc.GetFps()))
            doc.ExecutePasses(
                None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
            )
            records.append(
                {
                    "frame": frame,
                    "positions": {
                        name: vector(nodes[name].GetMg().off) for name in JOINTS
                    },
                    "relativeRotations": {
                        name: vector(nodes[name].GetRelRot()) for name in JOINTS
                    },
                }
            )
        print(
            "CODEX_FBX_MOTION_PROBE="
            + json.dumps(
                {
                    "source": str(project),
                    "fps": doc.GetFps(),
                    "minFrame": doc.GetMinTime().GetFrame(doc.GetFps()),
                    "maxFrame": doc.GetMaxTime().GetFrame(doc.GetFps()),
                    "records": records,
                }
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
