"""Evaluate selected Alembic generators while suppressing unrelated streams."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import (
    find_camera,
    find_take,
    object_path,
    walk_objects,
)


def vector(value):
    return {"x": value.x, "y": value.y, "z": value.z}


def geometry_record(item):
    cache = item.GetDeformCache() or item.GetCache()
    polygon = (
        cache
        if isinstance(cache, c4d.PolygonObject)
        else item
        if isinstance(item, c4d.PolygonObject)
        else None
    )
    bounds = cache or polygon
    return {
        "path": object_path(item),
        "sourcePath": (
            str(item[c4d.DescID(1000)])
            if item.GetType() == 1028083
            else None
        ),
        "identifier": (
            str(item[c4d.DescID(1001)])
            if item.GetType() == 1028083
            else None
        ),
        "renderMode": item.GetRenderMode(),
        "editorMode": item.GetEditorMode(),
        "globalPosition": vector(item.GetMg().off),
        "boundingRadius": vector(item.GetRad()),
        "cacheTypeId": bounds.GetType() if bounds is not None else None,
        "cachePointCount": polygon.GetPointCount() if polygon else None,
        "cachePolygonCount": polygon.GetPolygonCount() if polygon else None,
        "cacheBoundingRadius": vector(bounds.GetRad()) if bounds else None,
        "cacheBoundingCenter": vector(bounds.GetMp()) if bounds else None,
        "cacheGlobalPosition": vector(bounds.GetMg().off) if bounds else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--take")
    parser.add_argument("--camera")
    parser.add_argument("--camera-path")
    parser.add_argument("--basis")
    parser.add_argument("--target", action="append", required=True)
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
    report = {
        "project": str(project),
        "frame": args.frame,
        "fps": doc.GetFps(),
        "take": args.take,
        "targets": [],
        "suppressedAlembicGenerators": 0,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        all_objects = list(walk_objects(doc.GetFirstObject()))
        targets = [
            item
            for item in all_objects
            if object_path(item) in set(args.target)
        ]
        missing_targets = sorted(
            set(args.target) - {object_path(item) for item in targets}
        )
        if missing_targets:
            raise RuntimeError(f"Targets not found: {missing_targets}")

        for item in all_objects:
            if item.GetType() != 1028083 or item in targets:
                continue
            item.SetEditorMode(c4d.MODE_OFF)
            item.SetRenderMode(c4d.MODE_OFF)
            report["suppressedAlembicGenerators"] += 1
        for item in targets:
            item.SetEditorMode(c4d.MODE_ON)
            item.SetRenderMode(c4d.MODE_ON)

        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        passes_ok = doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_EXTERNALRENDERER", 0),
        )
        report["executePassesResult"] = bool(passes_ok)
        report["targets"] = [geometry_record(item) for item in targets]
        basis = next(
            (
                item
                for item in all_objects
                if args.basis
                and (
                    object_path(item) == args.basis
                    or item.GetName() == args.basis
                )
            ),
            None,
        )
        if basis is not None:
            basis_inverse = ~basis.GetMg()
            report["basis"] = {
                "path": object_path(basis),
                "targetCentersInBasisSpace": {
                    object_path(item): vector(
                        basis_inverse
                        * ((item.GetDeformCache() or item.GetCache() or item).GetMg()
                        * (item.GetDeformCache() or item.GetCache() or item).GetMp())
                    )
                    for item in targets
                    if (
                        (item.GetDeformCache() or item.GetCache()) is not None
                        or isinstance(item, c4d.PointObject)
                    )
                },
            }
        camera = (
            find_camera(doc, args.camera or "", args.camera_path)
            if args.camera
            else None
        )
        if camera is not None:
            camera_inverse = ~camera.GetMg()
            report["camera"] = {
                "path": object_path(camera),
                "globalPosition": vector(camera.GetMg().off),
                "focalLength": float(camera[500]),
                "targetLocalPositions": {
                    object_path(item): vector(
                        camera_inverse
                        * ((item.GetDeformCache() or item.GetCache() or item).GetMg()
                        * (item.GetDeformCache() or item.GetCache() or item).GetMp())
                    )
                    for item in targets
                    if (
                        (item.GetDeformCache() or item.GetCache()) is not None
                        or isinstance(item, c4d.PointObject)
                    )
                },
            }
        print(
            "PARACOSM_ALEMBIC_TARGETS_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_ALEMBIC_TARGETS_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
