"""List the object hierarchy exposed by a Cinema 4D-readable Alembic archive."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=0)
    args = parser.parse_args()

    archive = args.archive.expanduser().resolve()
    if not archive.exists():
        raise FileNotFoundError(archive)
    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(archive), load_flags)
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {archive}")
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_EXTERNALRENDERER", 0),
        )
        records = []
        for op in walk_objects(doc.GetFirstObject()):
            cache = op.GetDeformCache() or op.GetCache()
            records.append(
                {
                    "name": op.GetName(),
                    "path": object_path(op),
                    "typeId": op.GetType(),
                    "pointCount": (
                        op.GetPointCount()
                        if isinstance(op, c4d.PointObject)
                        else None
                    ),
                    "polygonCount": (
                        op.GetPolygonCount()
                        if isinstance(op, c4d.PolygonObject)
                        else None
                    ),
                    "cacheTypeId": cache.GetType() if cache else None,
                    "cachePointCount": (
                        cache.GetPointCount()
                        if isinstance(cache, c4d.PointObject)
                        else None
                    ),
                    "cachePolygonCount": (
                        cache.GetPolygonCount()
                        if isinstance(cache, c4d.PolygonObject)
                        else None
                    ),
                }
            )
        print(
            "PARACOSM_ALEMBIC_ARCHIVE_JSON="
            + json.dumps(
                {
                    "archive": str(archive),
                    "frame": args.frame,
                    "fps": doc.GetFps(),
                    "minFrame": doc.GetMinTime().GetFrame(doc.GetFps()),
                    "maxFrame": doc.GetMaxTime().GetFrame(doc.GetFps()),
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
