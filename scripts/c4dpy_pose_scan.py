"""Scan evaluated mesh bounds across an animation without saving the project."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


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


def polygon_bounds(op):
    evaluated = op.GetDeformCache() or op.GetCache() or op
    if not isinstance(evaluated, c4d.PolygonObject):
        return None
    points = evaluated.GetAllPoints()
    if not points:
        return None
    matrix = evaluated.GetMg()
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for point in points:
        world = matrix * point
        for index, value in enumerate((world.x, world.y, world.z)):
            low[index] = min(low[index], value)
            high[index] = max(high[index], value)
    return {
        "min": low,
        "max": high,
        "center": [
            (low[index] + high[index]) * 0.5 for index in range(3)
        ],
        "extent": [high[index] - low[index] for index in range(3)],
        "pointCount": evaluated.GetPointCount(),
        "polygonCount": evaluated.GetPolygonCount(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object-path", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--step", type=int, default=10)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        target = next(
            (
                op
                for op in walk_objects(doc.GetFirstObject())
                if object_path(op) == args.object_path
            ),
            None,
        )
        if target is None:
            raise RuntimeError(f"Object not found: {args.object_path}")
        fps = doc.GetFps()
        records = []
        for frame in range(args.start, args.end + 1, args.step):
            doc.SetTime(c4d.BaseTime(frame, fps))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
            records.append(
                {
                    "frame": frame,
                    "seconds": frame / fps,
                    "bounds": polygon_bounds(target),
                }
            )
        print(
            "PARACOSM_POSE_SCAN_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "objectPath": args.object_path,
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
