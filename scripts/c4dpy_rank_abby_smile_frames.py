"""Rank native Abby facial-mocap frames by a simple smile/open-mouth score.

The source is opened read-only and never evaluated through the renderer.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import c4d


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


def find_control(doc, name: str):
    matches = [
        item
        for item in walk_objects(doc.GetFirstObject())
        if item.GetName() == name and "root.002/" in object_path(item)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one root.002 control named {name}")
    return matches[0]


def component_desc_id(vector_parameter: int, component: int) -> c4d.DescID:
    return c4d.DescID(
        c4d.DescLevel(vector_parameter, c4d.DTYPE_VECTOR, 0),
        c4d.DescLevel(component, c4d.DTYPE_REAL, 0),
    )


def curve_for(item, vector_parameter: int, component: int):
    track = item.FindCTrack(component_desc_id(vector_parameter, component))
    curve = track.GetCurve() if track is not None else None
    return curve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--top", type=int, default=16)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")

    try:
        fps = doc.GetFps()
        controls = {
            name: find_control(doc, name)
            for name in (
                "FACIAL_C_Jaw",
                "FACIAL_C_LowerLipRotation",
                "FACIAL_C_MouthUpper",
                "FACIAL_L_LipCorner",
                "FACIAL_R_LipCorner",
                "FACIAL_L_CheekInner",
                "FACIAL_R_CheekInner",
            )
        }
        curves = {
            "jaw": curve_for(
                controls["FACIAL_C_Jaw"],
                c4d.ID_BASEOBJECT_REL_ROTATION,
                c4d.VECTOR_Y,
            ),
            "lowerLip": curve_for(
                controls["FACIAL_C_LowerLipRotation"],
                c4d.ID_BASEOBJECT_REL_ROTATION,
                c4d.VECTOR_Y,
            ),
            "upperY": curve_for(
                controls["FACIAL_C_MouthUpper"],
                c4d.ID_BASEOBJECT_REL_POSITION,
                c4d.VECTOR_Y,
            ),
            "leftCorner": curve_for(
                controls["FACIAL_L_LipCorner"],
                c4d.ID_BASEOBJECT_REL_ROTATION,
                c4d.VECTOR_X,
            ),
            "rightCorner": curve_for(
                controls["FACIAL_R_LipCorner"],
                c4d.ID_BASEOBJECT_REL_ROTATION,
                c4d.VECTOR_X,
            ),
            "leftCheekY": curve_for(
                controls["FACIAL_L_CheekInner"],
                c4d.ID_BASEOBJECT_REL_POSITION,
                c4d.VECTOR_Y,
            ),
            "rightCheekY": curve_for(
                controls["FACIAL_R_CheekInner"],
                c4d.ID_BASEOBJECT_REL_POSITION,
                c4d.VECTOR_Y,
            ),
        }
        baseline = {
            name: (
                curve.GetValue(c4d.BaseTime(0, fps))
                if curve is not None
                else 0.0
            )
            for name, curve in curves.items()
        }
        rows = []
        for frame in range(args.frames):
            time = c4d.BaseTime(frame, fps)
            values = {
                name: (
                    curve.GetValue(time)
                    if curve is not None
                    else baseline[name]
                )
                for name, curve in curves.items()
            }
            delta = {
                name: values[name] - baseline[name]
                for name in values
            }
            corner_smile_degrees = math.degrees(
                -delta["leftCorner"] + delta["rightCorner"]
            )
            jaw_open_degrees = math.degrees(delta["jaw"])
            lower_lip_degrees = math.degrees(delta["lowerLip"])
            cheek_lift = delta["leftCheekY"] + delta["rightCheekY"]
            score = (
                corner_smile_degrees * 1.8
                + max(jaw_open_degrees, 0.0) * 0.6
                + max(lower_lip_degrees, 0.0) * 0.25
                + delta["upperY"] * 8.0
                + cheek_lift * 4.0
            )
            rows.append(
                {
                    "frame": frame,
                    "seconds": frame / fps,
                    "score": score,
                    "cornerSmileDegrees": corner_smile_degrees,
                    "jawOpenDegrees": jaw_open_degrees,
                    "lowerLipDegrees": lower_lip_degrees,
                    "upperY": delta["upperY"],
                    "cheekLift": cheek_lift,
                }
            )
        rows.sort(key=lambda item: item["score"], reverse=True)
        print(
            "ABBY_SMILE_FRAME_RANKING="
            + json.dumps(
                {
                    "project": str(project),
                    "fps": fps,
                    "top": rows[: args.top],
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
