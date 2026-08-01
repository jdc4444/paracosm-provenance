"""Read-only inventory of an FBX facial-animation take."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


FOCUS_TERMS = (
    "eye",
    "eyelid",
    "jaw",
    "lip",
    "mouth",
    "brow",
    "facialroot",
    "head",
)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    result = bpy.ops.import_scene.fbx(
        filepath=str(source),
        use_anim=True,
        use_image_search=False,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"FBX import failed: {result}")

    scene = bpy.context.scene
    actions = []
    for action in bpy.data.actions:
        curves = list(action.fcurves)
        key_times = [
            float(point.co.x)
            for curve in curves
            for point in curve.keyframe_points
        ]
        animated_bones: dict[str, int] = {}
        varying_bones: dict[str, float] = {}
        focus_bones: dict[str, dict[str, float | int]] = {}
        for curve in curves:
            data_path = curve.data_path
            values = [
                float(point.co.y) for point in curve.keyframe_points
            ]
            value_range = max(values, default=0.0) - min(
                values, default=0.0
            )
            bone_name = None
            marker = 'pose.bones["'
            if marker in data_path:
                bone_name = data_path.split(marker, 1)[1].split('"]', 1)[0]
            if bone_name:
                animated_bones[bone_name] = (
                    animated_bones.get(bone_name, 0)
                    + len(curve.keyframe_points)
                )
                if value_range > 1.0e-7:
                    varying_bones[bone_name] = max(
                        varying_bones.get(bone_name, 0.0), value_range
                    )
                if any(term in bone_name.casefold() for term in FOCUS_TERMS):
                    record = focus_bones.setdefault(
                        bone_name,
                        {"keys": 0, "maxCurveRange": 0.0},
                    )
                    record["keys"] = int(record["keys"]) + len(
                        curve.keyframe_points
                    )
                    record["maxCurveRange"] = max(
                        float(record["maxCurveRange"]), value_range
                    )
        actions.append(
            {
                "name": action.name,
                "frameRange": [
                    min(key_times, default=0.0),
                    max(key_times, default=0.0),
                ],
                "curveCount": len(curves),
                "keyCount": sum(
                    len(curve.keyframe_points) for curve in curves
                ),
                "animatedBoneCount": len(animated_bones),
                "varyingCurveCount": sum(
                    1
                    for curve in curves
                    if (
                        max(
                            (
                                float(point.co.y)
                                for point in curve.keyframe_points
                            ),
                            default=0.0,
                        )
                        - min(
                            (
                                float(point.co.y)
                                for point in curve.keyframe_points
                            ),
                            default=0.0,
                        )
                    )
                    > 1.0e-7
                ),
                "varyingBoneCount": len(varying_bones),
                "focusBones": dict(
                    sorted(
                        focus_bones.items(),
                        key=lambda item: (
                            -float(item[1]["maxCurveRange"]),
                            item[0],
                        ),
                    )[:80]
                ),
            }
        )

    armatures = []
    for item in scene.objects:
        if item.type != "ARMATURE":
            continue
        armatures.append(
            {
                "name": item.name,
                "boneCount": len(item.data.bones),
                "action": (
                    item.animation_data.action.name
                    if item.animation_data and item.animation_data.action
                    else None
                ),
            }
        )

    print(
        "ABBY_FBX_FACE_ANIMATION="
        + json.dumps(
            {
                "input": str(source),
                "sceneFps": float(scene.render.fps)
                / float(scene.render.fps_base),
                "sceneFrameRange": [scene.frame_start, scene.frame_end],
                "objects": [
                    {"name": item.name, "type": item.type}
                    for item in scene.objects
                ],
                "armatures": armatures,
                "actions": actions,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
