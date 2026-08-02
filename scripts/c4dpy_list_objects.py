"""List object paths from one Cinema 4D document without modifying it."""

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


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--match", action="append", default=[])
    parser.add_argument("--path-prefix")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--no-materials", action="store_true")
    parser.add_argument(
        "--skip-evaluation",
        action="store_true",
        help=(
            "Inspect the document's saved hierarchy without SetTime or "
            "ExecutePasses. Useful for diagnosing scenes whose expressions "
            "cannot be evaluated in the current runtime."
        ),
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        help="Only emit hierarchy paths at or above this slash depth.",
    )
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    if not args.no_materials:
        load_flags |= c4d.SCENEFILTER_MATERIALS
    doc = c4d.documents.LoadDocument(
        str(project),
        load_flags,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        if not args.skip_evaluation:
            doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        terms = [item.casefold() for item in args.match]
        records = []
        for op in walk(doc.GetFirstObject()):
            path = object_path(op)
            if args.path_prefix and not path.startswith(args.path_prefix):
                continue
            if args.max_depth is not None and path.count("/") > args.max_depth:
                continue
            if terms and not any(term in path.casefold() for term in terms):
                continue
            record = {
                "name": op.GetName(),
                "path": path,
                "typeId": op.GetType(),
                "typeName": op.GetTypeName(),
                "editorMode": op.GetEditorMode(),
                "renderMode": op.GetRenderMode(),
            }
            layer = op.GetLayerObject(doc)
            if layer is not None:
                layer_data = layer.GetLayerData(doc)
                record["layer"] = {
                    "name": layer.GetName(),
                    "view": bool(layer_data[c4d.ID_LAYER_VIEW]),
                    "render": bool(layer_data[c4d.ID_LAYER_RENDER]),
                    "generators": bool(
                        layer_data[c4d.ID_LAYER_GENERATORS]
                    ),
                    "deformers": bool(
                        layer_data[c4d.ID_LAYER_DEFORMERS]
                    ),
                    "expressions": bool(
                        layer_data[c4d.ID_LAYER_EXPRESSIONS]
                    ),
                    "animation": bool(
                        layer_data[c4d.ID_LAYER_ANIMATION]
                    ),
                }
            if isinstance(op, c4d.PointObject):
                record["pointCount"] = op.GetPointCount()
            if isinstance(op, c4d.PolygonObject):
                record["polygonCount"] = op.GetPolygonCount()
                points = op.GetAllPoints()
                if points:
                    matrix = op.GetMg()
                    world = [matrix * point for point in points]
                    low = [
                        min(point[index] for point in world)
                        for index in range(3)
                    ]
                    high = [
                        max(point[index] for point in world)
                        for index in range(3)
                    ]
                    record["worldBounds"] = {
                        "low": low,
                        "high": high,
                        "center": [
                            (low[index] + high[index]) * 0.5
                            for index in range(3)
                        ],
                    }
            cache = op.GetDeformCache() or op.GetCache()
            if isinstance(cache, c4d.PointObject):
                record["cachePointCount"] = cache.GetPointCount()
            if isinstance(cache, c4d.PolygonObject):
                record["cachePolygonCount"] = cache.GetPolygonCount()
            records.append(record)
        print(
            "PARACOSM_OBJECT_LIST_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "frame": args.frame,
                    "evaluated": not args.skip_evaluation,
                    "objectCount": len(records),
                    "objects": records,
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
