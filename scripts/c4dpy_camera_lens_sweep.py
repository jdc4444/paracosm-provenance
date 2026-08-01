"""Render non-destructive focal-length variants of one retained C4D camera."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import c4d

from c4dpy_camera_proof import (
    LEGACY_RS_CAMERA_OBJECT_ID,
    clean_base_draw,
    object_path,
    render_record,
    walk_objects,
)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "camera"


def vector_payload(value: c4d.Vector) -> dict[str, float]:
    return {"x": value.x, "y": value.y, "z": value.z}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--focal", action="append", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        source_camera = next(
            (
                item
                for item in walk_objects(doc.GetFirstObject())
                if (
                    item.CheckType(c4d.Ocamera)
                    or item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                )
                and (
                    item.GetName() == args.camera
                    or object_path(item) == args.camera
                )
            ),
            None,
        )
        if source_camera is None:
            raise RuntimeError(f"Camera not found: {args.camera}")
        source_matrix = source_camera.GetMg()
        source_focal = float(source_camera[c4d.CAMERA_FOCUS])

        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        clean_base_draw(base_draw)
        for scene_object in walk_objects(doc.GetFirstObject()):
            tag = scene_object.GetFirstTag()
            while tag:
                next_tag = tag.GetNext()
                if tag.CheckType(c4d.Ttexture):
                    tag.Remove()
                tag = next_tag
            if scene_object.CheckType(c4d.Olight):
                scene_object[c4d.LIGHT_BRIGHTNESS] = 0.0
            else:
                scene_object[c4d.ID_BASEOBJECT_USECOLOR] = (
                    c4d.ID_BASEOBJECT_USECOLOR_ALWAYS
                )
                scene_object[c4d.ID_BASEOBJECT_COLOR] = c4d.Vector(
                    0.72, 0.72, 0.72
                )

        proof_light = c4d.BaseObject(c4d.Olight)
        proof_light.SetName("PARACOSM_CAMERA_LENS_SWEEP_LIGHT")
        proof_light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        proof_light[c4d.LIGHT_COLOR] = c4d.Vector(1.0, 1.0, 1.0)
        proof_light[c4d.LIGHT_BRIGHTNESS] = 2.0
        proof_light[c4d.LIGHT_SHADOWTYPE] = 0
        doc.InsertObject(proof_light)

        take_data = doc.GetTakeData()
        results = []
        for focal in args.focal:
            camera = c4d.BaseObject(c4d.Ocamera)
            focal_slug = str(focal).replace(".", "p")
            camera.SetName(
                f"PARACOSM LENS SWEEP {slug(args.camera)} {focal_slug}"
            )
            camera.SetMg(source_matrix)
            camera[c4d.CAMERA_FOCUS] = focal
            doc.InsertObject(camera)
            output_path = output_dir / (
                f"{args.prefix}__{slug(args.camera)}__focal-{focal_slug}"
                f"__f{args.frame:04d}.png"
            )
            result = render_record(
                doc,
                take_data,
                base_draw,
                proof_light,
                {
                    "sourceId": (
                        f"{args.prefix}__{slug(args.camera)}__"
                        f"focal-{focal_slug}"
                    ),
                    "targetFrame": args.frame,
                    "cameraName": camera.GetName(),
                    "cameraObject": {"objectPath": object_path(camera)},
                    "outputPath": str(output_path),
                },
                args.width,
                args.height,
            )
            result["sourceCameraName"] = source_camera.GetName()
            result["sourceCameraObjectPath"] = object_path(source_camera)
            result["sourceFocalLength"] = source_focal
            result["testFocalLength"] = focal
            result["sourceCameraMatrix"] = {
                "position": vector_payload(source_matrix.off),
                "right": vector_payload(source_matrix.v1),
                "up": vector_payload(source_matrix.v2),
                "forward": vector_payload(source_matrix.v3),
            }
            results.append(result)

        print(
            "PARACOSM_CAMERA_LENS_SWEEP_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "frame": args.frame,
                    "camera": args.camera,
                    "sourceFocalLength": source_focal,
                    "results": results,
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
