"""Emit a compact, take-aware C4D hierarchy and geometry inventory.

Run with Maxon's bundled c4dpy. The source document is loaded read-only and
destroyed without saving.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take, object_path, walk_objects


def vector(value):
    return {"x": value.x, "y": value.y, "z": value.z}


def geometry_payload(op):
    cache = op.GetDeformCache() or op.GetCache()
    return {
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
    }


def effective_render_enabled(op):
    current = op
    while current:
        if current.GetRenderMode() == c4d.MODE_OFF:
            return False
        current = current.GetUp()
    return True


def tag_payload(op):
    tags = []
    tag = op.GetFirstTag()
    while tag:
        item = {"name": tag.GetName(), "typeId": tag.GetType()}
        if tag.CheckType(c4d.Ttexture):
            material = tag[c4d.TEXTURETAG_MATERIAL]
            item["material"] = material.GetName() if material else None
        tags.append(item)
        tag = tag.GetNext()
    return tags


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--take")
    parser.add_argument("--root")
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--max-relative-depth", type=int)
    parser.add_argument(
        "--build-flags",
        choices=("none", "internal", "external"),
        default="external",
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        fps = doc.GetFps()
        doc.SetTime(c4d.BaseTime(args.frame, fps))
        build_flags = {
            "none": c4d.BUILDFLAGS_NONE,
            "internal": c4d.BUILDFLAGS_INTERNALRENDERER,
            "external": c4d.BUILDFLAGS_EXTERNALRENDERER,
        }[args.build_flags]
        passes_ok = doc.ExecutePasses(
            None, True, True, True, build_flags
        )
        objects = list(walk_objects(doc.GetFirstObject()))
        root = next(
            (
                op
                for op in objects
                if args.root
                and (
                    object_path(op) == args.root
                    or op.GetName() == args.root
                )
            ),
            None,
        )
        root_path = object_path(root) if root else None
        terms = tuple(item.casefold() for item in args.term)
        records = []
        for op in objects:
            path = object_path(op)
            if root_path and path != root_path and not path.startswith(
                root_path + "/"
            ):
                continue
            relative_depth = (
                path.count("/") - root_path.count("/")
                if root_path
                else path.count("/")
            )
            if (
                args.max_relative_depth is not None
                and relative_depth > args.max_relative_depth
            ):
                continue
            if terms and not any(term in path.casefold() for term in terms):
                continue
            records.append(
                {
                    "name": op.GetName(),
                    "path": path,
                    "guid": str(op.GetGUID()),
                    "relativeDepth": relative_depth,
                    "typeId": op.GetType(),
                    "renderMode": op.GetRenderMode(),
                    "editorMode": op.GetEditorMode(),
                    "effectiveRenderEnabled": effective_render_enabled(op),
                    "position": vector(op.GetMg().off),
                    "boundingRadius": vector(op.GetRad()),
                    "boundingCenter": vector(op.GetMp()),
                    "trackCount": len(op.GetCTracks()),
                    "tags": tag_payload(op),
                    **geometry_payload(op),
                }
            )
        print(
            "PARACOSM_COMPACT_OBJECT_INVENTORY_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "frame": args.frame,
                    "fps": fps,
                    "cameraTake": take.GetName() if take else None,
                    "buildFlags": args.build_flags,
                    "executePassesResult": bool(passes_ok),
                    "root": root_path,
                    "records": records,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_COMPACT_OBJECT_INVENTORY_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
