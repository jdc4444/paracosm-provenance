"""Report evaluated camera transforms from one C4D scene without saving it.

Run with Maxon's bundled c4dpy. This is intentionally read-only and is useful
for matching Cinema 4D AEC camera metadata back to a candidate source scene.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import (
    LEGACY_RS_CAMERA_OBJECT_ID,
    effective_item,
    find_take,
    object_path,
    walk_objects,
)


def vector_payload(value: c4d.Vector) -> dict[str, float]:
    return {"x": value.x, "y": value.y, "z": value.z}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--take")
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional path for the complete structured camera-state result.",
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
        raise RuntimeError(f"Cinema 4D could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        fps = doc.GetFps()
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        doc.SetTime(c4d.BaseTime(args.frame, fps))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        effective_camera = (
            effective_item(take.GetEffectiveCamera(take_data))
            if take_data and take
            else None
        )
        effective_render_data = (
            effective_item(take.GetEffectiveRenderData(take_data))
            if take_data and take
            else None
        )
        effective_render_data_payload = None
        if effective_render_data is not None:
            render_settings = effective_render_data.GetData()
            effective_render_data_payload = {
                "name": effective_render_data.GetName(),
                "rendererId": int(
                    render_settings[c4d.RDATA_RENDERENGINE]
                ),
                "outputPath": str(
                    render_settings[c4d.RDATA_PATH] or ""
                ),
                "xResolution": float(
                    render_settings[c4d.RDATA_XRES] or 0
                ),
                "yResolution": float(
                    render_settings[c4d.RDATA_YRES] or 0
                ),
                "frameFrom": effective_render_data[
                    c4d.RDATA_FRAMEFROM
                ].GetFrame(fps),
                "frameTo": effective_render_data[
                    c4d.RDATA_FRAMETO
                ].GetFrame(fps),
            }
        cameras = []
        for item in walk_objects(doc.GetFirstObject()):
            if not (
                item.CheckType(c4d.Ocamera)
                or item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
            ):
                continue
            matrix = item.GetMg()
            rotation = c4d.utils.MatrixToHPB(matrix)
            try:
                focal = float(item[c4d.CAMERA_FOCUS])
            except Exception:
                try:
                    focal = float(item[500])
                except Exception:
                    focal = None
            cameras.append(
                {
                    "name": item.GetName(),
                    "objectPath": object_path(item),
                    "guid": str(item.GetGUID()),
                    "typeId": item.GetType(),
                    "position": vector_payload(matrix.off),
                    "matrixV1": vector_payload(matrix.v1),
                    "matrixV2": vector_payload(matrix.v2),
                    "matrixV3": vector_payload(matrix.v3),
                    "rotationRadians": vector_payload(rotation),
                    "rotationDegrees": {
                        axis: math.degrees(value)
                        for axis, value in vector_payload(rotation).items()
                    },
                    "focalLength": focal,
                    "trackCount": len(item.GetCTracks()),
                    "editorMode": item.GetEditorMode(),
                    "renderMode": item.GetRenderMode(),
                }
            )
        top_level_objects = []
        root = doc.GetFirstObject()
        while root:
            top_level_objects.append(
                {
                    "name": root.GetName(),
                    "typeId": root.GetType(),
                    "editorMode": root.GetEditorMode(),
                    "renderMode": root.GetRenderMode(),
                }
            )
            root = root.GetNext()
        result = {
            "project": str(project),
            "documentFps": fps,
            "documentMinFrame": doc.GetMinTime().GetFrame(fps),
            "documentMaxFrame": doc.GetMaxTime().GetFrame(fps),
            "frame": args.frame,
            "cameraTake": take.GetName() if take else None,
            "takeEffectiveCamera": (
                {
                    "name": effective_camera.GetName(),
                    "objectPath": object_path(effective_camera),
                    "guid": str(effective_camera.GetGUID()),
                    "typeId": effective_camera.GetType(),
                    "position": vector_payload(effective_camera.GetMg().off),
                }
                if effective_camera is not None
                else None
            ),
            "takeEffectiveRenderData": (
                effective_render_data.GetName()
                if effective_render_data is not None
                else None
            ),
            "takeEffectiveRenderDataDetails": (
                effective_render_data_payload
            ),
            "cameraCount": len(cameras),
            "cameras": cameras,
            "topLevelObjects": top_level_objects,
        }
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(result, indent=2),
                encoding="utf-8",
            )
        print(
            "PARACOSM_CAMERA_STATE_JSON="
            + json.dumps(result, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
    os._exit(0)


if __name__ == "__main__":
    main()
