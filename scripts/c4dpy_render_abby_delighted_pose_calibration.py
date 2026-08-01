"""Render a compact pose grid for Abby's Delighted Side Glance expression.

The facial-animation source is opened read-only. Existing animation is
neutralized in memory, a set of hand-authored joint poses is evaluated, and
each candidate is rendered without saving the Cinema 4D document.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import c4d
import maxon


REDSHIFT_RENDERER_ID = 1036219
DRIVER_TAG_NAME = "Slide 7 Facial Animation Driver"
LEGACY_RS_CAMERA_OBJECT_ID = 1057516


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


def point_camera_at(camera, target: c4d.Vector) -> None:
    position = camera.GetMg().off
    forward = (target - position).GetNormalized()
    world_up = c4d.Vector(0.0, 1.0, 0.0)
    right = world_up.Cross(forward).GetNormalized()
    camera_up = forward.Cross(right).GetNormalized()
    camera.SetMg(c4d.Matrix(position, right, camera_up, forward))


def remove_animation_driver(doc) -> int:
    removed = 0
    for item in walk_objects(doc.GetFirstObject()):
        for tag in list(item.GetTags()):
            if tag.GetType() == c4d.Tpython and tag.GetName() == DRIVER_TAG_NAME:
                tag.Remove()
                removed += 1
    return removed


def strip_tracks(items) -> int:
    removed = 0
    for item in items:
        position = c4d.Vector(item.GetRelPos())
        rotation = c4d.Vector(item.GetRelRot())
        scale = c4d.Vector(item.GetRelScale())
        for track in list(item.GetCTracks()):
            track.Remove()
            removed += 1
        item.SetRelPos(position)
        item.SetRelRot(rotation)
        item.SetRelScale(scale)
    return removed


def render_data_video_posts(render_data) -> list[dict[str, object]]:
    result = []
    video_post = render_data.GetFirstVideoPost()
    while video_post is not None:
        result.append(
            {
                "name": video_post.GetName(),
                "type": video_post.GetType(),
            }
        )
        video_post = video_post.GetNext()
    return result


def apply_pose(
    controls,
    base_positions,
    base_rotations,
    pose,
) -> None:
    for name, item in controls.items():
        item.SetRelPos(c4d.Vector(base_positions[name]))
        item.SetRelRot(c4d.Vector(base_rotations[name]))

    for name, horizontal_key, vertical_key, roll_key in (
        (
            "FACIAL_L_Eye",
            "eyeXLeft",
            "eyeYLeft",
            "eyeZLeft",
        ),
        (
            "FACIAL_R_Eye",
            "eyeXRight",
            "eyeYRight",
            "eyeZRight",
        ),
    ):
        rotation = c4d.Vector(base_rotations[name])
        rotation.x += math.radians(
            pose.get(horizontal_key, pose["eyeX"])
        )
        rotation.y += math.radians(
            pose.get(vertical_key, pose["eyeY"])
        )
        rotation.z += math.radians(
            pose.get(roll_key, pose.get("eyeZ", 0.0))
        )
        controls[name].SetRelRot(rotation)

    jaw = c4d.Vector(base_rotations["FACIAL_C_Jaw"])
    jaw.y += math.radians(pose["jaw"])
    controls["FACIAL_C_Jaw"].SetRelRot(jaw)

    chin = c4d.Vector(base_positions["FACIAL_C_Chin"])
    chin.y += pose.get("chinUp", 0.0)
    controls["FACIAL_C_Chin"].SetRelPos(chin)

    upper_teeth = c4d.Vector(base_positions["FACIAL_C_TeethUpper"])
    upper_teeth.y += pose.get("teethUpperY", 0.0)
    controls["FACIAL_C_TeethUpper"].SetRelPos(upper_teeth)

    lower_lip = c4d.Vector(base_rotations["FACIAL_C_LowerLipRotation"])
    lower_lip.y += math.radians(pose["lowerLip"])
    controls["FACIAL_C_LowerLipRotation"].SetRelRot(lower_lip)

    upper = c4d.Vector(base_positions["FACIAL_C_MouthUpper"])
    upper.y += pose["upperY"]
    controls["FACIAL_C_MouthUpper"].SetRelPos(upper)

    for name, direction in (
        ("FACIAL_L_LipCorner", 1.0),
        ("FACIAL_R_LipCorner", -1.0),
    ):
        corner = c4d.Vector(base_rotations[name])
        corner.x += math.radians(pose["corners"] * direction)
        controls[name].SetRelRot(corner)
        corner_position = c4d.Vector(base_positions[name])
        corner_position.x += pose.get("cornerOut", 0.0) * direction
        corner_position.y += pose.get("cornerUp", 0.0)
        controls[name].SetRelPos(corner_position)

    for name in (
        "FACIAL_L_CheekInner",
        "FACIAL_R_CheekInner",
        "FACIAL_L_CheekOuter",
        "FACIAL_R_CheekOuter",
    ):
        cheek = c4d.Vector(base_positions[name])
        cheek.y += pose.get("cheekUp", 0.0)
        controls[name].SetRelPos(cheek)

    for name in ("FACIAL_L_EyelidLowerA", "FACIAL_R_EyelidLowerA"):
        lower_lid = c4d.Vector(base_positions[name])
        lower_lid.y += pose.get("lowerLidUp", 0.0)
        controls[name].SetRelPos(lower_lid)

    for name in ("FACIAL_L_EyelidUpperA", "FACIAL_R_EyelidUpperA"):
        upper_lid = c4d.Vector(base_positions[name])
        upper_lid.y += pose.get("upperLidUp", 0.0)
        controls[name].SetRelPos(upper_lid)

    for name in (
        "FACIAL_L_ForeheadIn",
        "FACIAL_R_ForeheadIn",
        "FACIAL_L_ForeheadMid",
        "FACIAL_R_ForeheadMid",
        "FACIAL_L_ForeheadOut",
        "FACIAL_R_ForeheadOut",
    ):
        forehead = c4d.Vector(base_positions[name])
        forehead.y += pose.get("foreheadUp", 0.0)
        controls[name].SetRelPos(forehead)

    head = c4d.Vector(base_rotations["head"])
    head.x += math.radians(pose.get("headX", 0.0))
    head.y += math.radians(pose.get("headY", 0.0))
    head.z += math.radians(pose.get("headZ", 0.0))
    controls["head"].SetRelRot(head)

    for item in controls.values():
        item.Message(c4d.MSG_UPDATE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--camera-focal", type=float, default=95.0)
    parser.add_argument("--sensor-scale", type=float, default=1.0)
    parser.add_argument(
        "--camera-exposure",
        type=float,
        default=0.0,
        help="Set the legacy Redshift camera exposure in EV.",
    )
    parser.add_argument("--target-x", type=float, default=0.0)
    parser.add_argument("--target-y", type=float, default=146.9)
    parser.add_argument("--target-z", type=float, default=-2.25)
    parser.add_argument(
        "--pose-set",
        choices=(
            "axes",
            "smile",
            "brow",
            "refinement",
            "head",
            "gaze",
            "gaze2",
            "mouth",
            "finaleyes",
            "eyeaxis",
            "parallel",
            "chin",
            "chinlift",
            "chinlift2",
            "friendly",
            "friendlymouth",
            "friendlyfix",
        ),
        default="axes",
    )
    parser.add_argument("--preserve-head-track", action="store_true")
    parser.add_argument("--max-poses", type=int)
    parser.add_argument("--pose-label")
    parser.add_argument(
        "--proof-light",
        type=float,
        default=0.0,
        help="Add a neutral camera-side fill light at this brightness.",
    )
    parser.add_argument(
        "--dome-intensity",
        type=float,
        help="Temporarily override the master Redshift dome intensity.",
    )
    parser.add_argument(
        "--area-intensity",
        type=float,
        help="Temporarily override the master Redshift area-light intensity.",
    )
    parser.add_argument(
        "--dome-reflection",
        type=float,
        help="Temporarily override the dome's reflection contribution.",
    )
    parser.add_argument(
        "--area-reflection",
        type=float,
        help="Temporarily override the area light's reflection contribution.",
    )
    parser.add_argument(
        "--hair-casts-shadows",
        choices=("source", "on", "off"),
        default="source",
        help=(
            "Temporarily override the Hair object's Redshift Casts Shadows "
            "flag while keeping the hair visible."
        ),
    )
    parser.add_argument(
        "--skin-reflectance",
        choices=("source", "on", "off"),
        default="source",
        help="Temporarily override Abby_Face reflectance.",
    )
    parser.add_argument(
        "--skin-reflection-brightness",
        type=float,
        help="Temporarily override Abby_Face legacy reflection brightness.",
    )
    parser.add_argument(
        "--skin-specular-brightness",
        type=float,
        help="Temporarily override Abby_Face legacy specular brightness.",
    )
    parser.add_argument(
        "--skin-roughness",
        type=float,
        help="Temporarily override Abby_Face roughness.",
    )
    parser.add_argument(
        "--skin-node-reflection-weight",
        type=float,
        help="Temporarily override Abby_Face Redshift reflection weight.",
    )
    parser.add_argument(
        "--skin-node-bump-scale",
        type=float,
        help="Temporarily override Abby_Face Redshift bump scale.",
    )
    parser.add_argument(
        "--skin-base-color",
        type=Path,
        help=(
            "Temporarily relink Abby_Face's UDIM 1001 base-color texture "
            "for a non-destructive render proof."
        ),
    )
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
        raise RuntimeError(f"Cinema 4D could not load {project}")

    report = {
        "project": str(project),
        "outputDir": str(output_dir),
        "sourceSaved": False,
        "driverTagsRemoved": 0,
        "tracksRemoved": 0,
        "renders": [],
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        names = (
            "head",
            "FACIAL_L_Eye",
            "FACIAL_R_Eye",
            "FACIAL_C_Jaw",
            "FACIAL_C_Chin",
            "FACIAL_C_TeethUpper",
            "FACIAL_C_LowerLipRotation",
            "FACIAL_C_MouthUpper",
            "FACIAL_L_LipCorner",
            "FACIAL_R_LipCorner",
            "FACIAL_L_CheekInner",
            "FACIAL_R_CheekInner",
            "FACIAL_L_CheekOuter",
            "FACIAL_R_CheekOuter",
            "FACIAL_L_EyelidLowerA",
            "FACIAL_R_EyelidLowerA",
            "FACIAL_L_EyelidUpperA",
            "FACIAL_R_EyelidUpperA",
            "FACIAL_L_ForeheadIn",
            "FACIAL_R_ForeheadIn",
            "FACIAL_L_ForeheadMid",
            "FACIAL_R_ForeheadMid",
            "FACIAL_L_ForeheadOut",
            "FACIAL_R_ForeheadOut",
        )
        controls = {name: find_control(doc, name) for name in names}
        base_positions = {
            name: c4d.Vector(item.GetRelPos())
            for name, item in controls.items()
        }
        base_rotations = {
            name: c4d.Vector(item.GetRelRot())
            for name, item in controls.items()
        }
        report["driverTagsRemoved"] = remove_animation_driver(doc)
        tracks_to_strip = [
            item
            for name, item in controls.items()
            if not (args.preserve_head_track and name == "head")
        ]
        report["tracksRemoved"] = strip_tracks(tracks_to_strip)

        axes_poses = (
            (
                "00_neutral",
                {
                    "eyeX": 0.0,
                    "eyeY": 0.0,
                    "jaw": 0.0,
                    "lowerLip": 0.0,
                    "upperY": 0.0,
                    "corners": 0.0,
                },
            ),
            (
                "01_gaze_xplus_yminus_soft",
                {
                    "eyeX": 9.0,
                    "eyeY": -6.0,
                    "jaw": 4.0,
                    "lowerLip": 2.0,
                    "upperY": 0.12,
                    "corners": -2.0,
                },
            ),
            (
                "02_gaze_xminus_yminus_soft",
                {
                    "eyeX": -9.0,
                    "eyeY": -6.0,
                    "jaw": 4.0,
                    "lowerLip": 2.0,
                    "upperY": 0.12,
                    "corners": -2.0,
                },
            ),
            (
                "03_gaze_xplus_yplus_soft",
                {
                    "eyeX": 9.0,
                    "eyeY": 6.0,
                    "jaw": 4.0,
                    "lowerLip": 2.0,
                    "upperY": 0.12,
                    "corners": -2.0,
                },
            ),
            (
                "04_gaze_xplus_yminus_broad",
                {
                    "eyeX": 11.0,
                    "eyeY": -7.0,
                    "jaw": 5.5,
                    "lowerLip": 2.8,
                    "upperY": 0.18,
                    "corners": -4.0,
                    "headZ": 2.0,
                },
            ),
            (
                "05_gaze_xminus_yminus_broad",
                {
                    "eyeX": -11.0,
                    "eyeY": -7.0,
                    "jaw": 5.5,
                    "lowerLip": 2.8,
                    "upperY": 0.18,
                    "corners": -4.0,
                    "headZ": 2.0,
                },
            ),
            (
                "06_corner_sign_check",
                {
                    "eyeX": 9.0,
                    "eyeY": -6.0,
                    "jaw": 4.0,
                    "lowerLip": 2.0,
                    "upperY": 0.12,
                    "corners": 3.0,
                },
            ),
            (
                "07_open_delight",
                {
                    "eyeX": 10.0,
                    "eyeY": -7.0,
                    "jaw": 7.0,
                    "lowerLip": 3.4,
                    "upperY": 0.22,
                    "corners": -4.5,
                    "headZ": 2.0,
                },
            ),
        )
        smile_poses = (
            (
                "10_open_delight_baseline",
                {
                    "eyeX": 10.0,
                    "eyeY": -7.0,
                    "jaw": 7.0,
                    "lowerLip": 3.4,
                    "upperY": 0.22,
                    "corners": -4.5,
                    "headZ": 2.0,
                },
            ),
            (
                "11_smile_lift_1",
                {
                    "eyeX": 10.0,
                    "eyeY": -7.0,
                    "jaw": 6.5,
                    "lowerLip": 3.2,
                    "upperY": 0.22,
                    "corners": -5.0,
                    "cornerUp": 0.15,
                    "cornerOut": 0.15,
                    "cheekUp": 0.10,
                    "lowerLidUp": 0.05,
                    "headZ": 2.0,
                },
            ),
            (
                "12_smile_lift_2",
                {
                    "eyeX": 10.0,
                    "eyeY": -7.0,
                    "jaw": 6.5,
                    "lowerLip": 3.2,
                    "upperY": 0.22,
                    "corners": -6.0,
                    "cornerUp": 0.30,
                    "cornerOut": 0.25,
                    "cheekUp": 0.20,
                    "lowerLidUp": 0.10,
                    "headZ": 2.0,
                },
            ),
            (
                "13_smile_lift_3",
                {
                    "eyeX": 10.0,
                    "eyeY": -7.0,
                    "jaw": 6.5,
                    "lowerLip": 3.2,
                    "upperY": 0.22,
                    "corners": -7.0,
                    "cornerUp": 0.45,
                    "cornerOut": 0.35,
                    "cheekUp": 0.30,
                    "lowerLidUp": 0.15,
                    "headZ": 2.0,
                },
            ),
            (
                "14_smile_lift_2_open",
                {
                    "eyeX": 10.0,
                    "eyeY": -7.0,
                    "jaw": 8.0,
                    "lowerLip": 4.0,
                    "upperY": 0.26,
                    "corners": -6.0,
                    "cornerUp": 0.30,
                    "cornerOut": 0.25,
                    "cheekUp": 0.20,
                    "lowerLidUp": 0.10,
                    "headZ": 2.0,
                },
            ),
            (
                "15_smile_lift_2_wide_gaze",
                {
                    "eyeX": 13.0,
                    "eyeY": -8.0,
                    "jaw": 6.5,
                    "lowerLip": 3.2,
                    "upperY": 0.22,
                    "corners": -6.0,
                    "cornerUp": 0.30,
                    "cornerOut": 0.25,
                    "cheekUp": 0.20,
                    "lowerLidUp": 0.10,
                    "headZ": 2.0,
                },
            ),
        )
        final_pose = {
            "eyeX": -13.0,
            "eyeY": -8.0,
            "jaw": 6.8,
            "lowerLip": 3.4,
            "upperY": 0.23,
            "corners": -7.0,
            "cornerUp": 0.45,
            "cornerOut": 0.35,
            "cheekUp": 0.30,
            "lowerLidUp": 0.12,
        }
        brow_poses = (
            ("20_final_no_brow", dict(final_pose)),
            (
                "21_final_brow_soft",
                {**final_pose, "foreheadUp": 0.12},
            ),
            (
                "22_final_brow_high",
                {**final_pose, "foreheadUp": 0.25},
            ),
        )
        refinement_base = {
            **final_pose,
            "eyeY": -12.0,
            "lowerLidUp": 0.05,
            "upperLidUp": 0.15,
            "foreheadUp": 0.12,
        }
        refinement_poses = (
            (
                "30_eye_up_tilt_plus",
                {**refinement_base, "headZ": 5.0},
            ),
            (
                "31_eye_up_tilt_minus",
                {**refinement_base, "headZ": -5.0},
            ),
            (
                "32_eye_up_wide_tilt_plus",
                {
                    **refinement_base,
                    "eyeX": -15.0,
                    "upperLidUp": 0.22,
                    "headZ": 5.0,
                },
            ),
            (
                "33_eye_up_wide_tilt_minus",
                {
                    **refinement_base,
                    "eyeX": -15.0,
                    "upperLidUp": 0.22,
                    "headZ": -5.0,
                },
            ),
        )
        head_base = {
            **final_pose,
            "eyeY": -12.0,
            "lowerLidUp": 0.05,
            "upperLidUp": 0.18,
            "foreheadUp": 0.12,
        }
        head_poses = (
            (
                "40_head_x_plus",
                {**head_base, "headX": 8.0},
            ),
            (
                "41_head_x_minus",
                {**head_base, "headX": -8.0},
            ),
            (
                "42_head_y_plus",
                {**head_base, "headY": 8.0},
            ),
            (
                "43_head_y_minus",
                {**head_base, "headY": -8.0},
            ),
            (
                "44_head_z_plus",
                {**head_base, "headZ": 8.0},
            ),
            (
                "45_head_z_minus",
                {**head_base, "headZ": -8.0},
            ),
            (
                "46_head_x_plus_gaze_plus",
                {**head_base, "eyeX": 13.0, "headX": 8.0},
            ),
            (
                "47_head_x_minus_gaze_plus",
                {**head_base, "eyeX": 13.0, "headX": -8.0},
            ),
        )
        gaze_base = {
            **head_base,
            "headX": 8.0,
        }
        gaze_poses = (
            (
                "50_upper_right_balanced",
                {
                    **gaze_base,
                    "eyeXLeft": -13.0,
                    "eyeXRight": 13.0,
                },
            ),
            (
                "51_upper_right_strong",
                {
                    **gaze_base,
                    "eyeXLeft": -16.0,
                    "eyeXRight": 16.0,
                },
            ),
            (
                "52_upper_right_right_eye_soft",
                {
                    **gaze_base,
                    "eyeXLeft": -14.0,
                    "eyeXRight": 11.0,
                },
            ),
            (
                "53_upper_right_left_eye_soft",
                {
                    **gaze_base,
                    "eyeXLeft": -11.0,
                    "eyeXRight": 14.0,
                },
            ),
        )
        gaze2_poses = (
            (
                "54_upper_right_corner",
                {
                    **gaze_base,
                    "eyeXLeft": -18.0,
                    "eyeXRight": 20.0,
                },
            ),
            (
                "55_upper_right_corner_strong",
                {
                    **gaze_base,
                    "eyeXLeft": -18.0,
                    "eyeXRight": 22.0,
                    "eyeY": -13.0,
                },
            ),
            (
                "56_upper_right_corner_high",
                {
                    **gaze_base,
                    "eyeXLeft": -16.0,
                    "eyeXRight": 20.0,
                    "eyeY": -14.0,
                },
            ),
        )
        mouth_base = {
            **gaze_base,
            "eyeXLeft": -18.0,
            "eyeXRight": 22.0,
            "eyeY": -13.0,
        }
        mouth_poses = (
            (
                "60_open_smile_medium",
                {
                    **mouth_base,
                    "jaw": 8.5,
                    "lowerLip": 4.2,
                    "upperY": 0.27,
                },
            ),
            (
                "61_open_smile_reference",
                {
                    **mouth_base,
                    "jaw": 10.0,
                    "lowerLip": 5.0,
                    "upperY": 0.30,
                },
            ),
            (
                "62_open_smile_broad",
                {
                    **mouth_base,
                    "jaw": 11.5,
                    "lowerLip": 5.8,
                    "upperY": 0.34,
                },
            ),
        )
        finaleyes_base = {
            **mouth_base,
            "jaw": 11.5,
            "lowerLip": 5.8,
            "upperY": 0.34,
        }
        finaleyes_poses = (
            (
                "70_right_eye_corner_30",
                {
                    **finaleyes_base,
                    "eyeXRight": 30.0,
                },
            ),
            (
                "71_right_eye_corner_36",
                {
                    **finaleyes_base,
                    "eyeXRight": 36.0,
                },
            ),
            (
                "72_right_eye_corner_42",
                {
                    **finaleyes_base,
                    "eyeXRight": 42.0,
                },
            ),
        )
        eyeaxis_base = {
            **finaleyes_base,
            "eyeXLeft": 0.0,
            "eyeXRight": 0.0,
            "eyeY": 0.0,
        }
        eyeaxis_poses = (
            (
                "80_eye_x_plus",
                {**eyeaxis_base, "eyeXLeft": 30.0, "eyeXRight": 30.0},
            ),
            (
                "81_eye_x_minus",
                {**eyeaxis_base, "eyeXLeft": -30.0, "eyeXRight": -30.0},
            ),
            (
                "82_eye_y_plus",
                {**eyeaxis_base, "eyeYLeft": 30.0, "eyeYRight": 30.0},
            ),
            (
                "83_eye_y_minus",
                {**eyeaxis_base, "eyeYLeft": -30.0, "eyeYRight": -30.0},
            ),
            (
                "84_eye_z_plus",
                {**eyeaxis_base, "eyeZLeft": 30.0, "eyeZRight": 30.0},
            ),
            (
                "85_eye_z_minus",
                {**eyeaxis_base, "eyeZLeft": -30.0, "eyeZRight": -30.0},
            ),
        )
        parallel_base = {
            **finaleyes_base,
        }
        parallel_poses = (
            (
                "90_parallel_upper_right_soft",
                {
                    **parallel_base,
                    "eyeXLeft": 18.0,
                    "eyeXRight": 18.0,
                    "eyeY": -13.0,
                },
            ),
            (
                "91_parallel_upper_right_reference",
                {
                    **parallel_base,
                    "eyeXLeft": 24.0,
                    "eyeXRight": 24.0,
                    "eyeY": -15.0,
                },
            ),
            (
                "92_parallel_upper_right_corner",
                {
                    **parallel_base,
                    "eyeXLeft": 30.0,
                    "eyeXRight": 30.0,
                    "eyeY": -18.0,
                },
            ),
        )
        compact_chin_base = {
            **parallel_base,
            "eyeXLeft": 24.0,
            "eyeXRight": 24.0,
            "eyeY": -15.0,
        }
        compact_chin_poses = (
            (
                "93_compact_chin_jaw_8_5",
                {
                    **compact_chin_base,
                    "jaw": 8.5,
                    "lowerLip": 4.2,
                    "upperY": 0.31,
                },
            ),
            (
                "94_compact_chin_jaw_9_5",
                {
                    **compact_chin_base,
                    "jaw": 9.5,
                    "lowerLip": 4.7,
                    "upperY": 0.32,
                },
            ),
            (
                "95_compact_chin_jaw_10",
                {
                    **compact_chin_base,
                    "jaw": 10.0,
                    "lowerLip": 5.0,
                    "upperY": 0.33,
                },
            ),
        )
        chin_lift_base = {
            **parallel_base,
            "eyeXLeft": 24.0,
            "eyeXRight": 24.0,
            "eyeY": -15.0,
        }
        chin_lift_poses = (
            (
                "96_open_smile_chin_up_0_25",
                {**chin_lift_base, "chinUp": 0.25},
            ),
            (
                "97_open_smile_chin_up_0_45",
                {**chin_lift_base, "chinUp": 0.45},
            ),
            (
                "98_open_smile_chin_up_0_65",
                {**chin_lift_base, "chinUp": 0.65},
            ),
            (
                "99_open_smile_chin_up_0_9",
                {**chin_lift_base, "chinUp": 0.9},
            ),
            (
                "100_open_smile_chin_up_1_2",
                {**chin_lift_base, "chinUp": 1.2},
            ),
        )
        friendly_poses = (
            (
                "101_friendly_soft",
                {
                    **parallel_base,
                    "eyeXLeft": 18.0,
                    "eyeXRight": 18.0,
                    "eyeY": -9.0,
                    "jaw": 9.5,
                    "lowerLip": 4.7,
                    "upperY": 0.30,
                    "corners": -6.0,
                    "cornerUp": 0.50,
                    "cornerOut": 0.32,
                    "cheekUp": 0.32,
                    "lowerLidUp": 0.09,
                    "upperLidUp": 0.10,
                    "foreheadUp": 0.10,
                    "headX": 7.0,
                    "chinUp": 1.0,
                },
            ),
            (
                "102_friendly_reference",
                {
                    **parallel_base,
                    "eyeXLeft": 20.0,
                    "eyeXRight": 20.0,
                    "eyeY": -10.5,
                    "jaw": 10.0,
                    "lowerLip": 5.0,
                    "upperY": 0.31,
                    "corners": -6.3,
                    "cornerUp": 0.52,
                    "cornerOut": 0.34,
                    "cheekUp": 0.34,
                    "lowerLidUp": 0.09,
                    "upperLidUp": 0.11,
                    "foreheadUp": 0.10,
                    "headX": 7.0,
                    "chinUp": 1.1,
                },
            ),
            (
                "103_friendly_delighted",
                {
                    **parallel_base,
                    "eyeXLeft": 22.0,
                    "eyeXRight": 22.0,
                    "eyeY": -11.0,
                    "jaw": 10.25,
                    "lowerLip": 5.1,
                    "upperY": 0.32,
                    "corners": -6.5,
                    "cornerUp": 0.55,
                    "cornerOut": 0.35,
                    "cheekUp": 0.35,
                    "lowerLidUp": 0.10,
                    "upperLidUp": 0.12,
                    "foreheadUp": 0.11,
                    "headX": 7.0,
                    "chinUp": 1.1,
                },
            ),
        )
        friendly_mouth_base = {
            **parallel_base,
            "eyeXLeft": 18.0,
            "eyeXRight": 18.0,
            "eyeY": -9.0,
            "corners": -6.0,
            "cornerUp": 0.50,
            "cornerOut": 0.32,
            "cheekUp": 0.32,
            "lowerLidUp": 0.09,
            "upperLidUp": 0.10,
            "foreheadUp": 0.10,
            "headX": 7.0,
            "chinUp": 1.1,
        }
        friendly_mouth_poses = (
            (
                "104_friendly_open_lip_4",
                {
                    **friendly_mouth_base,
                    "jaw": 11.0,
                    "lowerLip": 4.0,
                    "upperY": 0.33,
                },
            ),
            (
                "105_friendly_open_lip_2",
                {
                    **friendly_mouth_base,
                    "jaw": 11.0,
                    "lowerLip": 2.0,
                    "upperY": 0.33,
                },
            ),
            (
                "106_friendly_open_lip_3",
                {
                    **friendly_mouth_base,
                    "jaw": 11.5,
                    "lowerLip": 3.0,
                    "upperY": 0.34,
                },
            ),
        )
        friendly_fix_base = {
            **parallel_base,
            "eyeXLeft": 18.0,
            "eyeXRight": 18.0,
            "eyeY": -9.0,
            "corners": -6.0,
            "cornerUp": 0.46,
            "cornerOut": 0.30,
            "cheekUp": 0.30,
            "lowerLidUp": 0.09,
            "upperLidUp": 0.10,
            "foreheadUp": 0.10,
            "headX": 7.0,
        }
        friendly_fix_poses = (
            (
                "107_compact_chin_teeth_up_0_25",
                {
                    **friendly_fix_base,
                    "jaw": 9.5,
                    "chinUp": 0.20,
                    "teethUpperY": 0.25,
                    "lowerLip": 3.0,
                    "upperY": 0.28,
                },
            ),
            (
                "108_compact_chin_teeth_up_0_4",
                {
                    **friendly_fix_base,
                    "jaw": 9.75,
                    "chinUp": 0.30,
                    "teethUpperY": 0.40,
                    "lowerLip": 3.2,
                    "upperY": 0.29,
                },
            ),
            (
                "109_compact_chin_teeth_up_0_55",
                {
                    **friendly_fix_base,
                    "jaw": 10.0,
                    "chinUp": 0.40,
                    "teethUpperY": 0.55,
                    "lowerLip": 3.4,
                    "upperY": 0.30,
                },
            ),
        )
        poses = {
            "axes": axes_poses,
            "smile": smile_poses,
            "brow": brow_poses,
            "refinement": refinement_poses,
            "head": head_poses,
            "gaze": gaze_poses,
            "gaze2": gaze2_poses,
            "mouth": mouth_poses,
            "finaleyes": finaleyes_poses,
            "eyeaxis": eyeaxis_poses,
            "parallel": parallel_poses,
            "chin": compact_chin_poses,
            "chinlift": chin_lift_poses,
            "chinlift2": chin_lift_poses[-2:],
            "friendly": friendly_poses,
            "friendlymouth": friendly_mouth_poses,
            "friendlyfix": friendly_fix_poses,
        }[args.pose_set]
        if args.max_poses is not None:
            poses = poses[: args.max_poses]
        if args.pose_label is not None:
            poses = tuple(
                item for item in poses if item[0] == args.pose_label
            )
            if not poses:
                raise RuntimeError(
                    f"Pose label not found in {args.pose_set}: "
                    f"{args.pose_label}"
                )

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
        camera[500] = float(args.camera_focal)
        camera[7003] = float(args.camera_focal)
        camera[1220] = float(args.camera_exposure)
        sensor_size = camera[7002]
        if not isinstance(sensor_size, c4d.Vector):
            raise RuntimeError("The legacy RS Camera has no vector sensor size")
        camera[7002] = c4d.Vector(
            sensor_size.x * args.sensor_scale,
            sensor_size.y * args.sensor_scale,
            sensor_size.z,
        )
        point_camera_at(
            camera,
            c4d.Vector(args.target_x, args.target_y, args.target_z),
        )
        base_draw = doc.GetRenderBaseDraw()
        if base_draw is not None:
            base_draw.SetSceneCamera(camera)
        report["camera"] = {
            "name": camera.GetName(),
            "focal": args.camera_focal,
            "sensorScale": args.sensor_scale,
            "exposure": args.camera_exposure,
            "target": [args.target_x, args.target_y, args.target_z],
        }
        if args.dome_intensity is not None:
            dome_light = next(
                (
                    item
                    for item in walk_objects(doc.GetFirstObject())
                    if item.GetName() == "RS Dome Light"
                    and item.GetType() == 1036751
                ),
                None,
            )
            if dome_light is None:
                raise RuntimeError("The source scene has no RS Dome Light")
            previous_dome_intensity = float(dome_light[12024])
            dome_light[12024] = float(args.dome_intensity)
            dome_light.Message(c4d.MSG_UPDATE)
            report["domeLight"] = {
                "name": dome_light.GetName(),
                "previousIntensity": previous_dome_intensity,
                "intensity": args.dome_intensity,
            }
            if args.dome_reflection is not None:
                previous_dome_reflection = float(dome_light[10034])
                dome_light[10034] = float(args.dome_reflection)
                dome_light.Message(c4d.MSG_UPDATE)
                report["domeLight"].update(
                    {
                        "previousReflection": previous_dome_reflection,
                        "reflection": args.dome_reflection,
                    }
                )
        elif args.dome_reflection is not None:
            raise RuntimeError(
                "--dome-reflection requires --dome-intensity"
            )
        if args.area_intensity is not None:
            area_light = next(
                (
                    item
                    for item in walk_objects(doc.GetFirstObject())
                    if item.GetName() == "RS Area Light.1"
                    and item.GetType() == 1036751
                ),
                None,
            )
            if area_light is None:
                raise RuntimeError("The source scene has no RS Area Light.1")
            previous_area_intensity = float(area_light[11004])
            area_light[11004] = float(args.area_intensity)
            area_light.Message(c4d.MSG_UPDATE)
            report["areaLight"] = {
                "name": area_light.GetName(),
                "previousIntensity": previous_area_intensity,
                "intensity": args.area_intensity,
            }
            if args.area_reflection is not None:
                previous_area_reflection = float(area_light[10034])
                area_light[10034] = float(args.area_reflection)
                area_light.Message(c4d.MSG_UPDATE)
                report["areaLight"].update(
                    {
                        "previousReflection": previous_area_reflection,
                        "reflection": args.area_reflection,
                    }
                )
        elif args.area_reflection is not None:
            raise RuntimeError(
                "--area-reflection requires --area-intensity"
            )
        if args.hair_casts_shadows != "source":
            hair = next(
                (
                    item
                    for item in walk_objects(doc.GetFirstObject())
                    if item.GetName() == "Hair"
                    and "root.002/" in object_path(item)
                ),
                None,
            )
            if hair is None:
                raise RuntimeError("The source scene has no root.002 Hair")
            redshift_object_tag = next(
                (
                    tag
                    for tag in hair.GetTags()
                    if tag.GetType() == 1036222
                ),
                None,
            )
            if redshift_object_tag is None:
                raise RuntimeError("Hair has no Redshift Object tag")
            previous_hair_casts_shadows = bool(
                redshift_object_tag[2002]
            )
            hair_casts_shadows = args.hair_casts_shadows == "on"
            redshift_object_tag[2002] = hair_casts_shadows
            redshift_object_tag.Message(c4d.MSG_UPDATE)
            report["hairShadows"] = {
                "object": object_path(hair),
                "tag": redshift_object_tag.GetName(),
                "previousCastsShadows": previous_hair_casts_shadows,
                "castsShadows": hair_casts_shadows,
                "hairVisible": True,
            }
        if args.proof_light > 0.0:
            proof_light = c4d.BaseObject(c4d.Olight)
            proof_light.SetName("ABBY_EXPRESSION_PROOF_FILL")
            camera_matrix = camera.GetMg()
            proof_light.SetAbsPos(
                camera_matrix.off
                - camera_matrix.v1 * 24.0
                + camera_matrix.v2 * 18.0
                + camera_matrix.v3 * 28.0
            )
            proof_light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
            proof_light[c4d.LIGHT_BRIGHTNESS] = args.proof_light
            proof_light[c4d.LIGHT_COLOR] = c4d.Vector(1.0, 0.95, 0.9)
            proof_light[c4d.LIGHT_SHADOWTYPE] = 0
            doc.InsertObject(proof_light)
            report["proofLight"] = {
                "name": proof_light.GetName(),
                "brightness": args.proof_light,
            }
        if (
            args.skin_reflectance != "source"
            or args.skin_reflection_brightness is not None
            or args.skin_specular_brightness is not None
            or args.skin_roughness is not None
            or args.skin_node_reflection_weight is not None
            or args.skin_node_bump_scale is not None
            or args.skin_base_color is not None
        ):
            skin_material = next(
                (
                    material
                    for material in doc.GetMaterials()
                    if material.GetName() == "Abby_Face"
                ),
                None,
            )
            if skin_material is None:
                raise RuntimeError("The source scene has no Abby_Face material")
            skin_report = {
                "name": skin_material.GetName(),
                "sourceReflectance": bool(skin_material[2004]),
                "sourceReflectionBrightness": float(skin_material[2501]),
                "sourceSpecularBrightness": float(skin_material[3101]),
                "sourceRoughness": float(skin_material[1135]),
            }
            if args.skin_reflectance != "source":
                skin_material[2004] = args.skin_reflectance == "on"
            if args.skin_reflection_brightness is not None:
                skin_material[2501] = float(
                    args.skin_reflection_brightness
                )
            if args.skin_specular_brightness is not None:
                skin_material[3101] = float(args.skin_specular_brightness)
            if args.skin_roughness is not None:
                skin_material[1135] = float(args.skin_roughness)
            skin_material.Message(c4d.MSG_UPDATE)
            skin_report.update(
                {
                    "reflectance": bool(skin_material[2004]),
                    "reflectionBrightness": float(skin_material[2501]),
                    "specularBrightness": float(skin_material[3101]),
                    "roughness": float(skin_material[1135]),
                }
            )
            if (
                args.skin_node_reflection_weight is not None
                or args.skin_node_bump_scale is not None
                or args.skin_base_color is not None
            ):
                node_space = maxon.Id(
                    "com.redshift3d.redshift4c4d.class.nodespace"
                )
                node_reference = skin_material.GetNodeMaterialReference()
                if not node_reference.HasSpace(node_space):
                    raise RuntimeError(
                        "Abby_Face has no Redshift node graph"
                    )
                graph = node_reference.GetGraph(node_space)
                ports = list(
                    graph.GetRoot().GetInnerNodes(
                        maxon.NODE_KIND.ALL_MASK, True
                    )
                )
                target_ports = {}
                for port in ports:
                    path = str(port.GetPath())
                    if path.endswith("standardmaterial.refl_weight"):
                        target_ports["reflectionWeight"] = port
                    elif path.endswith("bumpmap.scale"):
                        target_ports["bumpScale"] = port
                    elif path.endswith("texturesampler.tex0/path"):
                        try:
                            value_text = str(port.GetPortValue())
                        except Exception:
                            value_text = ""
                        if "BaseColor.1001.png" in value_text:
                            target_ports["baseColorAsset"] = port
                requested_node_values = {
                    "reflectionWeight": args.skin_node_reflection_weight,
                    "bumpScale": args.skin_node_bump_scale,
                    "baseColorAsset": args.skin_base_color,
                }
                changes = {}
                with graph.BeginTransaction() as transaction:
                    for key, requested_value in requested_node_values.items():
                        if requested_value is None:
                            continue
                        port = target_ports.get(key)
                        if port is None:
                            raise RuntimeError(
                                f"Abby_Face node port not found: {key}"
                            )
                        previous_value = port.GetPortValue()
                        if key == "baseColorAsset":
                            requested_path = Path(requested_value).expanduser()
                            requested_path = requested_path.resolve()
                            if not requested_path.is_file():
                                raise RuntimeError(
                                    "Skin base-color proof does not exist: "
                                    f"{requested_path}"
                                )
                            port.SetPortValue(maxon.Url(str(requested_path)))
                            rendered_value = str(requested_path)
                        else:
                            port.SetPortValue(float(requested_value))
                            rendered_value = float(requested_value)
                        changes[key] = {
                            "previous": str(previous_value),
                            "value": rendered_value,
                        }
                    transaction.Commit()
                skin_report["nodeOverrides"] = changes
            report["skinMaterial"] = skin_report

        source_render_data = doc.GetActiveRenderData()
        source_video_posts = render_data_video_posts(source_render_data)
        render_data = source_render_data.GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        if render_data is None:
            raise RuntimeError(
                f"Could not clone render data {source_render_data.GetName()}"
            )
        render_data.SetName(
            source_render_data.GetName() + " CODEX EXACT IN-MEMORY COPY"
        )
        doc.InsertRenderData(render_data)
        doc.SetActiveRenderData(render_data)
        cloned_video_posts = render_data_video_posts(render_data)
        if cloned_video_posts != source_video_posts:
            raise RuntimeError(
                "Exact render-data clone changed the VideoPost chain"
            )
        settings = render_data.GetDataInstance()
        report["renderData"] = {
            "source": source_render_data.GetName(),
            "exactClone": render_data.GetName(),
            "videoPosts": cloned_video_posts,
        }
        settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_SAVEIMAGE] = False
        if hasattr(c4d, "RDATA_MULTIPASS_ENABLE"):
            settings[c4d.RDATA_MULTIPASS_ENABLE] = False

        output_dir.mkdir(parents=True, exist_ok=True)
        render_flags = c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS
        render_flags |= getattr(c4d, "RENDERFLAGS_NODOCUMENTCLONE", 0)
        for label, pose in poses:
            apply_pose(controls, base_positions, base_rotations, pose)
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
            bitmap = c4d.bitmaps.MultipassBitmap(
                args.width, args.height, c4d.COLORMODE_RGB
            )
            bitmap.AddChannel(True, True)
            render_result = c4d.documents.RenderDocument(
                doc,
                settings,
                bitmap,
                render_flags,
            )
            if render_result != c4d.RENDERRESULT_OK:
                raise RuntimeError(
                    f"RenderDocument returned {render_result} for {label}"
                )
            output = output_dir / f"{label}.png"
            layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
            save_result = layer.Save(
                str(output),
                c4d.FILTER_PNG,
                c4d.BaseContainer(),
            )
            if save_result != c4d.IMAGERESULT_OK:
                raise RuntimeError(f"Bitmap save failed for {label}")
            report["renders"].append(
                {
                    "label": label,
                    "output": str(output),
                    "pose": pose,
                }
            )
            print(f"ABBY_DELIGHTED_CALIBRATION={label}", flush=True)

        print(
            "ABBY_DELIGHTED_CALIBRATION_REPORT="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
