"""Read-only geometry, transform, and visibility probe for scene assets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take


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


def vector(value):
    return {"x": value.x, "y": value.y, "z": value.z}


def matrix(value):
    return {
        "off": vector(value.off),
        "v1": vector(value.v1),
        "v2": vector(value.v2),
        "v3": vector(value.v3),
    }


def geometry_counts(op):
    cache = op.GetDeformCache() or op.GetCache()
    result = {
        "pointCount": (
            op.GetPointCount() if isinstance(op, c4d.PointObject) else None
        ),
        "polygonCount": (
            op.GetPolygonCount() if isinstance(op, c4d.PolygonObject) else None
        ),
        "cacheTypeId": cache.GetType() if cache is not None else None,
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
        "cacheGlobalMatrix": (
            matrix(cache.GetMg()) if cache is not None else None
        ),
    }
    return result


def subtree_summary(root):
    summary = {
        "objectCount": 0,
        "effectiveRenderEnabledCount": 0,
        "pointCount": 0,
        "polygonCount": 0,
        "cachePointCount": 0,
        "cachePolygonCount": 0,
        "geometryObjects": [],
        "worldBounds": None,
    }
    bounds_min = [float("inf")] * 3
    bounds_max = [float("-inf")] * 3
    root_depth = object_path(root).count("/")
    for op in walk_objects(root):
        path = object_path(op)
        # ``walk_objects`` crosses siblings. Once it leaves the requested
        # hierarchy, stop instead of accidentally summarizing the whole scene.
        if op is not root and not path.startswith(object_path(root) + "/"):
            break
        parent_enabled = True
        parent = op.GetUp()
        while parent:
            if parent.GetRenderMode() == c4d.MODE_OFF:
                parent_enabled = False
                break
            parent = parent.GetUp()
        cache = op.GetDeformCache() or op.GetCache()
        counts = geometry_counts(op)
        summary["objectCount"] += 1
        summary["effectiveRenderEnabledCount"] += int(
            parent_enabled and op.GetRenderMode() != c4d.MODE_OFF
        )
        for key in (
            "pointCount",
            "polygonCount",
            "cachePointCount",
            "cachePolygonCount",
        ):
            summary[key] += counts.get(key) or 0
        if any(
            counts.get(key)
            for key in (
                "pointCount",
                "polygonCount",
                "cachePointCount",
                "cachePolygonCount",
            )
        ):
            summary["geometryObjects"].append(
                {
                    "path": path,
                    "relativeDepth": path.count("/") - root_depth,
                    **counts,
                }
            )
        point_source = (
            cache if isinstance(cache, c4d.PointObject) else op
        )
        if isinstance(point_source, c4d.PointObject):
            matrix_value = (
                cache.GetMg()
                if isinstance(cache, c4d.PointObject)
                else op.GetMg()
            )
            for point in point_source.GetAllPoints():
                world = matrix_value * point
                for index, value in enumerate((world.x, world.y, world.z)):
                    bounds_min[index] = min(bounds_min[index], value)
                    bounds_max[index] = max(bounds_max[index], value)
    if bounds_min[0] != float("inf"):
        summary["worldBounds"] = {
            "min": {
                "x": bounds_min[0],
                "y": bounds_min[1],
                "z": bounds_min[2],
            },
            "max": {
                "x": bounds_max[0],
                "y": bounds_max[1],
                "z": bounds_max[2],
            },
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--take")
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--exact-path", action="append", default=[])
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--subtree-summary", action="store_true")
    parser.add_argument("--compact-summary", action="store_true")
    parser.add_argument("--include-materials", action="store_true")
    parser.add_argument("--max-depth", type=int)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    terms = tuple(item.casefold() for item in args.term)
    exact_paths = set(args.exact_path)
    names = set(args.name)
    if not terms and not exact_paths and not names:
        parser.error("at least one --term, --exact-path, or --name is required")
    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    if args.include_materials:
        load_flags |= c4d.SCENEFILTER_MATERIALS
    doc = c4d.documents.LoadDocument(str(project), load_flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        fps = doc.GetFps()
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        doc.SetTime(c4d.BaseTime(args.frame, fps))
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        records = []
        for op in walk_objects(doc.GetFirstObject()):
            path = object_path(op)
            if (
                args.max_depth is not None
                and path.count("/") > args.max_depth
            ):
                continue
            if (
                path not in exact_paths
                and op.GetName() not in names
                and not any(term in path.casefold() for term in terms)
            ):
                continue
            parent_enabled = True
            parent = op.GetUp()
            while parent:
                if parent.GetRenderMode() == c4d.MODE_OFF:
                    parent_enabled = False
                    break
                parent = parent.GetUp()
            records.append(
                {
                    "name": op.GetName(),
                    "path": path,
                    "typeId": op.GetType(),
                    "renderMode": op.GetRenderMode(),
                    "editorMode": op.GetEditorMode(),
                    "effectiveRenderEnabled": (
                        parent_enabled and op.GetRenderMode() != c4d.MODE_OFF
                    ),
                    "globalMatrix": matrix(op.GetMg()),
                    "localMatrix": matrix(op.GetMl()),
                    "boundingRadius": vector(op.GetRad()),
                    "boundingCenter": vector(op.GetMp()),
                    "subtreeSummary": (
                        subtree_summary(op) if args.subtree_summary else None
                    ),
                    **geometry_counts(op),
                }
            )
        if args.compact_summary:
            for record in records:
                summary = record.get("subtreeSummary")
                if summary is not None:
                    summary["geometryObjects"] = []
        payload = {
            "project": str(project),
            "fps": fps,
            "frame": args.frame,
            "timeSeconds": args.frame / fps,
            "cameraTake": take.GetName() if take else None,
            "records": records,
        }
        print(
            "PARACOSM_ASSET_GEOMETRY_PROBE_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_ASSET_GEOMETRY_PROBE_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
