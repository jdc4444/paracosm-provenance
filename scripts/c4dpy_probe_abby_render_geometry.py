"""Report evaluated render geometry bounds for Abby meshes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


NAMES = {"Hair", "Face.001", "Eye_Lashes.001", "Body.001", "garments.001"}


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def object_path(op):
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def polygon_cache(op):
    candidates = (op.GetDeformCache(), op.GetCache(), op)
    for candidate in candidates:
        if candidate is not None and candidate.CheckType(c4d.Opolygon):
            return candidate
    return None


def bounds(op):
    cache = polygon_cache(op)
    if cache is None or not cache.GetPointCount():
        return None
    points = [point * cache.GetMg() for point in cache.GetAllPoints()]
    low = c4d.Vector(
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    )
    high = c4d.Vector(
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    )
    return {
        "low": [low.x, low.y, low.z],
        "high": [high.x, high.y, high.z],
        "pointCount": cache.GetPointCount(),
        "cachePath": object_path(cache),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
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
        doc.SetTime(c4d.BaseTime(0, max(doc.GetFps(), 1)))
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        records = []
        for item in walk(doc.GetFirstObject()):
            if (
                item.GetName() not in NAMES
                and not item.GetName().startswith("Hair -")
                and item.GetName().casefold() != "hair"
            ):
                continue
            records.append(
                {
                    "name": item.GetName(),
                    "path": object_path(item),
                    "editorMode": int(item.GetEditorMode()),
                    "renderMode": int(item.GetRenderMode()),
                    "bounds": bounds(item),
                }
            )
        print(
            "ABBY_RENDER_GEOMETRY=" + json.dumps(
                {
                    "source": str(project),
                    "modeConstants": {
                        "on": int(c4d.MODE_ON),
                        "off": int(c4d.MODE_OFF),
                        "undef": int(c4d.MODE_UNDEF),
                    },
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
