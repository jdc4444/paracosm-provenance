"""Sample one C4D object's evaluated world transform across a frame range.

Run with Maxon's bundled c4dpy.  The source project is loaded read-only and
never saved.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take


def vector(value):
    return {"x": value.x, "y": value.y, "z": value.z}


def find_top_level_occurrence(doc, name: str, occurrence: int):
    matches = []
    root = doc.GetFirstObject()
    while root:
        if root.GetName() == name:
            matches.append(root)
        root = root.GetNext()
    return matches[occurrence] if occurrence < len(matches) else None


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def find_by_path(doc, path: str):
    for op in walk(doc.GetFirstObject()):
        if object_path(op) == path:
            return op
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--name")
    target.add_argument("--path")
    parser.add_argument("--occurrence", type=int, default=0)
    parser.add_argument("--take", default="Main")
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--step", type=int, default=1)
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--start cannot exceed --end")
    if args.step < 1:
        parser.error("--step must be positive")

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        target = (
            find_by_path(doc, args.path)
            if args.path
            else find_top_level_occurrence(
                doc, args.name, args.occurrence
            )
        )
        if target is None:
            if args.path:
                raise RuntimeError(f"Object path {args.path!r} not found")
            raise RuntimeError(
                f"Top-level object {args.name!r} occurrence "
                f"{args.occurrence} not found"
            )
        fps = doc.GetFps()
        records = []
        for frame in range(args.start, args.end + 1, args.step):
            doc.SetTime(c4d.BaseTime(frame, fps))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                c4d.BUILDFLAGS_NONE,
            )
            matrix = target.GetMg()
            records.append(
                {
                    "frame": frame,
                    "position": vector(matrix.off),
                    "rotationRadians": vector(
                        c4d.utils.MatrixToHPB(matrix)
                    ),
                    "scale": vector(target.GetAbsScale()),
                }
            )
        print(
            "PARACOSM_OBJECT_TRANSFORM_SAMPLES_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "name": target.GetName(),
                    "path": object_path(target),
                    "occurrence": args.occurrence,
                    "take": take.GetName() if take else None,
                    "fps": fps,
                    "records": records,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
