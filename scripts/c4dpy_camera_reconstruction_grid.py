"""Render a non-destructive camera-distance/focal grid toward one world target."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import render_record


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def vector_payload(value):
    return {"x": value.x, "y": value.y, "z": value.z}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--base-x", type=float, required=True)
    parser.add_argument("--base-y", type=float, required=True)
    parser.add_argument("--base-z", type=float, required=True)
    parser.add_argument("--target-x", type=float, required=True)
    parser.add_argument("--target-y", type=float, required=True)
    parser.add_argument("--target-z", type=float, required=True)
    parser.add_argument("--distance", action="append", type=float, required=True)
    parser.add_argument("--focal", action="append", type=float, required=True)
    parser.add_argument("--right-offset", action="append", type=float, default=[])
    parser.add_argument("--fixed-base", action="store_true")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=405)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    results = []
    try:
        c4d.documents.SetActiveDocument(doc)
        target = c4d.Vector(args.target_x, args.target_y, args.target_z)
        base = c4d.Vector(args.base_x, args.base_y, args.base_z)
        initial_forward = (target - base).GetNormalized()
        initial_right = c4d.Vector(
            initial_forward.z, 0.0, -initial_forward.x
        ).GetNormalized()

        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        base_draw[c4d.BASEDRAW_DATA_SDISPLAYACTIVE] = (
            c4d.BASEDRAW_SDISPLAY_GOURAUD
        )
        base_draw[c4d.BASEDRAW_DATA_SDISPLAYINACTIVE] = (
            c4d.BASEDRAW_SDISPLAY_GOURAUD
        )
        for scene_object in walk_objects(doc.GetFirstObject()):
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
        proof_light.SetName("PARACOSM_CAMERA_RECONSTRUCTION_LIGHT")
        proof_light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        proof_light[c4d.LIGHT_COLOR] = c4d.Vector(1.0, 1.0, 1.0)
        proof_light[c4d.LIGHT_BRIGHTNESS] = 1.5
        proof_light[c4d.LIGHT_SHADOWTYPE] = 0
        doc.InsertObject(proof_light)
        take_data = doc.GetTakeData()

        records = []
        for right_offset in args.right_offset or [0.0]:
            aimed_target = target + initial_right * right_offset
            forward = (aimed_target - base).GetNormalized()
            right = c4d.Vector(
                forward.z, 0.0, -forward.x
            ).GetNormalized()
            up = forward.Cross(right).GetNormalized()
            for distance in args.distance:
                position = (
                    base
                    if args.fixed_base
                    else aimed_target - forward * distance
                )
                for focal in args.focal:
                    camera = c4d.BaseObject(c4d.Ocamera)
                    slug = (
                        f"r{int(right_offset):+04d}-"
                        f"d{int(distance):04d}-f{int(focal):03d}"
                    )
                    camera.SetName(f"PARACOSM CODEX {slug}")
                    camera.SetMg(c4d.Matrix(position, right, up, forward))
                    camera[c4d.CAMERA_FOCUS] = focal
                    doc.InsertObject(camera)
                    records.append(
                        (
                            camera,
                            {
                                "sourceId": slug,
                                "outputPath": str(
                                    output_dir / f"{slug}.png"
                                ),
                                "targetFrame": args.frame,
                                "cameraName": camera.GetName(),
                                "cameraObject": {
                                    "objectPath": camera.GetName(),
                                },
                            },
                        )
                    )
        for camera, record in records:
            result = render_record(
                doc,
                take_data,
                base_draw,
                proof_light,
                record,
                args.width,
                args.height,
            )
            result["position"] = vector_payload(camera.GetMg().off)
            result["forward"] = vector_payload(camera.GetMg().v3)
            result["focalLength"] = camera[c4d.CAMERA_FOCUS]
            results.append(result)
        print(
            "PARACOSM_CAMERA_RECONSTRUCTION_JSON="
            + json.dumps(results, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
