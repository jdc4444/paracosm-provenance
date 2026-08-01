"""Render a fast read-only grey frame sweep through one saved C4D camera.

This keeps a large document open once, which makes animation-offset diagnosis
practical for the Paracosm recovery scenes.  The source project is never saved.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import (
    LEGACY_RS_CAMERA_OBJECT_ID,
    clean_base_draw,
    find_take,
    render_record,
    walk_objects,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--take")
    parser.add_argument("--render-data")
    parser.add_argument("--frame-start", type=int, required=True)
    parser.add_argument("--frame-end", type=int, required=True)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--width", type=int, default=360)
    parser.add_argument("--height", type=int, default=203)
    args = parser.parse_args()

    if args.frame_step < 1:
        raise ValueError("--frame-step must be positive")
    if args.frame_end < args.frame_start:
        raise ValueError("--frame-end must be at least --frame-start")

    project = args.project.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")

    try:
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)

        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        clean_base_draw(base_draw)

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
        proof_light.SetName("PARACOSM_FRAME_SWEEP_LIGHT")
        proof_light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        proof_light[c4d.LIGHT_COLOR] = c4d.Vector(1.0, 1.0, 1.0)
        proof_light[c4d.LIGHT_BRIGHTNESS] = 1.5
        proof_light[c4d.LIGHT_SHADOWTYPE] = 0
        doc.InsertObject(proof_light)

        records = []
        for frame in range(
            args.frame_start, args.frame_end + 1, args.frame_step
        ):
            records.append(
                {
                    "sourceId": f"{args.prefix}-f{frame:04d}",
                    "targetFrame": frame,
                    "cameraName": args.camera,
                    "cameraTake": args.take,
                    "cameraRenderData": args.render_data,
                    "outputPath": str(
                        output_dir / f"{args.prefix}-f{frame:04d}.png"
                    ),
                }
            )

        legacy_source_camera = next(
            (
                item
                for item in walk_objects(doc.GetFirstObject())
                if item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                and item.GetName() == args.camera
            ),
            None,
        )
        results = []
        for record in records:
            results.append(
                render_record(
                    doc,
                    take_data,
                    base_draw,
                    proof_light,
                    record,
                    args.width,
                    args.height,
                )
            )
            # render_record has to bridge a legacy Redshift camera to a
            # temporary native camera for Hardware Preview.  Remove that
            # bridge before the next frame so find_camera cannot accidentally
            # reuse a frozen transform from the preceding frame.
            if legacy_source_camera is not None:
                temporary_bridges = [
                    item
                    for item in walk_objects(doc.GetFirstObject())
                    if item.CheckType(c4d.Ocamera)
                    and item.GetName() == args.camera
                ]
                for bridge in temporary_bridges:
                    bridge.Remove()
                base_draw.SetSceneCamera(None)
        print(
            "PARACOSM_FRAME_SWEEP_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "camera": args.camera,
                    "take": args.take,
                    "renderData": args.render_data,
                    "frameStart": args.frame_start,
                    "frameEnd": args.frame_end,
                    "frameStep": args.frame_step,
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
