"""Render the native FBX mocap retarget from its C4D animation curves."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


REDSHIFT_RENDERER_ID = 1036219
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
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=299)
    parser.add_argument("--step", type=int, default=2)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=270)
    parser.add_argument(
        "--camera-focal",
        type=float,
        help="Optional render-only focal length for the archived RS Camera.",
    )
    parser.add_argument("--camera-target-x", type=float)
    parser.add_argument("--camera-target-y", type=float)
    parser.add_argument("--camera-target-z", type=float)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")

    report = {
        "project": str(project),
        "outputDir": str(output_dir),
        "frames": [],
        "saved": False,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        main_take = take_data.GetMainTake() if take_data else None
        if take_data and main_take:
            take_data.SetCurrentTake(main_take)
        animation_tracks = [
            (item, track, track.GetDescriptionID())
            for item in doc.GetObjects()
            for track in item.GetCTracks()
            if track.GetCurve() is not None
        ]
        if not animation_tracks:
            # GetObjects() only returns top-level items in some C4D builds.
            animation_tracks = [
                (item, track, track.GetDescriptionID())
                for item in walk_objects(doc.GetFirstObject())
                for track in item.GetCTracks()
                if track.GetCurve() is not None
            ]
        look_take = main_take.GetDown() if main_take else None
        if take_data and look_take:
            take_data.SetCurrentTake(look_take)
        if args.camera_focal is not None:
            legacy_camera = next(
                (
                    item
                    for item in walk_objects(doc.GetFirstObject())
                    if item.GetName() == "RS Camera"
                    and item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                ),
                None,
            )
            effective_camera_result = (
                look_take.GetEffectiveCamera(take_data)
                if look_take is not None and take_data is not None
                else None
            )
            effective_camera = (
                effective_camera_result[0]
                if isinstance(effective_camera_result, tuple)
                else effective_camera_result
            )
            if legacy_camera is None and effective_camera is None:
                raise RuntimeError("The scene has no render camera")
            if legacy_camera is not None:
                legacy_camera[500] = float(args.camera_focal)
                legacy_camera[7003] = float(args.camera_focal)
            if (
                effective_camera is not None
                and effective_camera.CheckType(c4d.Ocamera)
            ):
                effective_camera[c4d.CAMERA_FOCUS] = float(args.camera_focal)
            target_values = (
                args.camera_target_x,
                args.camera_target_y,
                args.camera_target_z,
            )
            if any(value is not None for value in target_values):
                if not all(value is not None for value in target_values):
                    raise RuntimeError(
                        "camera-target-x, camera-target-y and "
                        "camera-target-z must be supplied together"
                    )
                target = c4d.Vector(*target_values)
                if legacy_camera is not None:
                    point_camera_at(legacy_camera, target)
                if effective_camera is not None:
                    point_camera_at(effective_camera, target)

        settings = doc.GetActiveRenderData().GetData().GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_SAVEIMAGE] = False
        output_dir.mkdir(parents=True, exist_ok=True)

        render_flags = c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS
        render_flags |= getattr(c4d, "RENDERFLAGS_NODOCUMENTCLONE", 0)
        fps = doc.GetFps()
        frames = range(args.start, args.end + 1, args.step)
        total = len(frames)
        for frame in frames:
            doc.SetTime(c4d.BaseTime(frame, fps))
            doc.ExecutePasses(None, True, True, True, 0)
            time = c4d.BaseTime(frame, fps)
            for item, track, parameter_id in animation_tracks:
                item.SetParameter(
                    parameter_id,
                    float(track.GetCurve().GetValue(time)),
                    c4d.DESCFLAGS_SET_0,
                )
            doc.ExecutePasses(None, False, False, True, 0)
            bitmap = c4d.bitmaps.MultipassBitmap(
                args.width, args.height, c4d.COLORMODE_RGB
            )
            bitmap.AddChannel(True, True)
            result = c4d.documents.RenderDocument(
                doc, settings, bitmap, render_flags
            )
            if result != c4d.RENDERRESULT_OK:
                raise RuntimeError(
                    f"RenderDocument returned {result} at frame {frame}"
                )
            output = output_dir / f"frame{frame:04d}.tif"
            layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
            saved = layer.Save(
                str(output), c4d.FILTER_TIF, c4d.BaseContainer()
            )
            if saved != c4d.IMAGERESULT_OK:
                raise RuntimeError(f"Bitmap save failed at frame {frame}")
            report["frames"].append(frame)
            print(
                "ABBY_MOCAP_PREVIEW_FRAME="
                + json.dumps(
                    {
                        "frame": frame,
                        "completed": len(report["frames"]),
                        "total": total,
                        "output": str(output),
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        print(
            "ABBY_MOCAP_PREVIEW="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
