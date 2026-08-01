"""Prepare a disposable Cinema 4D look-match scene from Abby's source.

The canonical look-development file is loaded read-only. Only the Redshift
camera framing and output dimensions are changed before a derived C4D document
is saved. Render the derived document with Cinema 4D Commandline so the
archived Redshift materials, area light, and dome light remain untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import c4d


LEGACY_RS_CAMERA_OBJECT_ID = 1057516


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def point_camera_at(camera, target: c4d.Vector) -> None:
    position = camera.GetMg().off
    forward = (target - position).GetNormalized()
    world_up = c4d.Vector(0.0, 1.0, 0.0)
    right = world_up.Cross(forward).GetNormalized()
    camera_up = forward.Cross(right).GetNormalized()
    camera.SetMg(c4d.Matrix(position, right, camera_up, forward))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--focal", type=float, default=80.0)
    parser.add_argument("--zoom", type=float, default=1.0)
    parser.add_argument(
        "--sensor-scale",
        type=float,
        default=1.0,
        help="Scale the legacy Redshift camera sensor without moving the camera",
    )
    parser.add_argument("--target-x", type=float, default=0.0)
    parser.add_argument("--target-y", type=float, default=146.9)
    parser.add_argument("--target-z", type=float, default=-2.25)
    parser.add_argument("--camera-x", type=float)
    parser.add_argument("--camera-y", type=float)
    parser.add_argument("--camera-z", type=float)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {source}")

    try:
        c4d.documents.SetActiveDocument(doc)
        camera = next(
            (
                item
                for item in walk_objects(doc.GetFirstObject())
                if item.GetName() == "RS Camera"
                and item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
            ),
            None,
        )
        if camera is None:
            raise RuntimeError("The source scene has no legacy RS Camera")

        camera[500] = float(args.focal)
        camera[7003] = float(args.focal)
        camera[7022] = float(args.zoom)
        sensor_size = camera[7002]
        if not isinstance(sensor_size, c4d.Vector):
            raise RuntimeError("The legacy RS Camera has no vector sensor size")
        camera[7002] = c4d.Vector(
            sensor_size.x * args.sensor_scale,
            sensor_size.y * args.sensor_scale,
            sensor_size.z,
        )
        camera_coordinates = (args.camera_x, args.camera_y, args.camera_z)
        if any(value is not None for value in camera_coordinates):
            if not all(value is not None for value in camera_coordinates):
                raise RuntimeError(
                    "camera-x, camera-y and camera-z must be supplied together"
                )
            camera_matrix = camera.GetMg()
            camera_matrix.off = c4d.Vector(
                args.camera_x, args.camera_y, args.camera_z
            )
            camera.SetMg(camera_matrix)
        target = c4d.Vector(args.target_x, args.target_y, args.target_z)
        point_camera_at(camera, target)

        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("The source scene has no render view")
        base_draw.SetSceneCamera(camera)
        doc.SetActiveObject(camera)

        render_data = doc.GetActiveRenderData()
        render_data[c4d.RDATA_XRES] = float(args.width)
        render_data[c4d.RDATA_YRES] = float(args.height)
        render_data[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        render_data[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(0, doc.GetFps())
        render_data[c4d.RDATA_FRAMETO] = c4d.BaseTime(0, doc.GetFps())
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        c4d.EventAdd()

        output.parent.mkdir(parents=True, exist_ok=True)
        source_texture_directory = source.parent / "tex"
        derived_texture_directory = output.parent / "tex"
        if (
            source_texture_directory.is_dir()
            and not derived_texture_directory.exists()
        ):
            derived_texture_directory.symlink_to(
                source_texture_directory, target_is_directory=True
            )
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        if not saved:
            raise RuntimeError(f"Cinema 4D could not save derived scene {output}")

        payload = {
            "source": str(source),
            "output": str(output),
            "camera": camera.GetName(),
            "focal": args.focal,
            "zoom": args.zoom,
            "sensorScale": args.sensor_scale,
            "sensorSize": [
                float(camera[7002].x),
                float(camera[7002].y),
                float(camera[7002].z),
            ],
            "cameraPosition": [
                float(camera.GetMg().off.x),
                float(camera.GetMg().off.y),
                float(camera.GetMg().off.z),
            ],
            "target": [args.target_x, args.target_y, args.target_z],
            "resolution": [args.width, args.height],
            "textureDirectory": str(derived_texture_directory),
        }
        print(
            "ABBY_C4D_LOOKMATCH_PREPARED="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
