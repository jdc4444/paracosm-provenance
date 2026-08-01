"""Render direct mouth-control poses from Abby's repaired 1:1 C4D scene."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

import c4d


REDSHIFT_RENDERER_ID = 1036219


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
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
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    doc = c4d.documents.LoadDocument(
        str(args.project.expanduser().resolve()),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError("Could not load calibration project")

    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        doc.ExecutePasses(None, True, True, True, 0)
        names = {
            "FACIAL_C_Jaw",
            "FACIAL_C_LowerLipRotation",
            "FACIAL_C_MouthUpper",
            "FACIAL_L_LipCorner",
            "FACIAL_R_LipCorner",
        }
        controls = {
            item.GetName(): item
            for item in walk_objects(doc.GetFirstObject())
            if item.GetName() in names and "root.002/" in object_path(item)
        }
        if set(controls) != names:
            raise RuntimeError(f"Missing controls: {sorted(names - set(controls))}")
        base_rotations = {
            name: c4d.Vector(item.GetRelRot()) for name, item in controls.items()
        }
        base_positions = {
            name: c4d.Vector(item.GetRelPos()) for name, item in controls.items()
        }
        poses = (
            ("00_neutral", {}),
            ("01_jaw_2", {"jaw": 2.0}),
            ("02_jaw_4", {"jaw": 4.0}),
            ("03_jaw_6", {"jaw": 6.0}),
            ("04_lowerlip_2", {"lowerLip": 2.0}),
            ("05_jaw4_lower2", {"jaw": 4.0, "lowerLip": 2.0}),
            ("06_jaw3_corners_out", {"jaw": 3.0, "corners": 2.0}),
            ("07_jaw3_corners_in", {"jaw": 3.0, "corners": -2.0}),
            ("08_upper_up", {"jaw": 3.0, "upperY": 0.3}),
            ("09_lower_down", {"jaw": 3.0, "lowerY": -0.3}),
        )

        settings = doc.GetActiveRenderData().GetData().GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
        settings[c4d.RDATA_XRES] = 320.0
        settings[c4d.RDATA_YRES] = 180.0
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_SAVEIMAGE] = False
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        for label, pose in poses:
            for name, item in controls.items():
                item.SetRelRot(c4d.Vector(base_rotations[name]))
                item.SetRelPos(c4d.Vector(base_positions[name]))
            jaw = c4d.Vector(base_rotations["FACIAL_C_Jaw"])
            jaw.y += math.radians(pose.get("jaw", 0.0))
            controls["FACIAL_C_Jaw"].SetRelRot(jaw)
            lower = c4d.Vector(base_rotations["FACIAL_C_LowerLipRotation"])
            lower.y += math.radians(pose.get("lowerLip", 0.0))
            controls["FACIAL_C_LowerLipRotation"].SetRelRot(lower)
            for name, direction in (
                ("FACIAL_L_LipCorner", 1.0),
                ("FACIAL_R_LipCorner", -1.0),
            ):
                corner = c4d.Vector(base_rotations[name])
                corner.x += math.radians(pose.get("corners", 0.0) * direction)
                controls[name].SetRelRot(corner)
            upper = c4d.Vector(base_positions["FACIAL_C_MouthUpper"])
            upper.y += pose.get("upperY", 0.0)
            controls["FACIAL_C_MouthUpper"].SetRelPos(upper)
            lower_mouth = c4d.Vector(base_positions["FACIAL_C_LowerLipRotation"])
            lower_mouth.y += pose.get("lowerY", 0.0)
            controls["FACIAL_C_LowerLipRotation"].SetRelPos(lower_mouth)

            doc.ExecutePasses(None, True, True, True, 0)
            bitmap = c4d.bitmaps.MultipassBitmap(
                320, 180, c4d.COLORMODE_RGB
            )
            bitmap.AddChannel(True, True)
            result = c4d.documents.RenderDocument(
                doc,
                settings,
                bitmap,
                c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
            )
            if result != c4d.RENDERRESULT_OK:
                raise RuntimeError(f"Render failed for {label}: {result}")
            layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
            saved = layer.Save(
                str(output_dir / f"{label}.png"),
                c4d.FILTER_PNG,
                c4d.BaseContainer(),
            )
            if saved != c4d.IMAGERESULT_OK:
                raise RuntimeError(f"Save failed for {label}")
            print(f"ABBY_MOUTH_CALIBRATION={label}", flush=True)
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
