"""Export the authored Spin facial shape-key animation for retarget analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object", default="abby_basemesh_FACE")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    face = bpy.data.objects.get(args.object)
    if face is None or face.type != "MESH":
        raise RuntimeError(f"Missing facial mesh {args.object!r}")
    shape_keys = face.data.shape_keys
    if shape_keys is None:
        raise RuntimeError(f"Facial mesh {args.object!r} has no shape keys")

    action = (
        shape_keys.animation_data.action
        if shape_keys.animation_data is not None
        else None
    )
    fcurves = {}
    if action is not None:
        for curve in action.fcurves:
            fcurves[curve.data_path] = {
                "arrayIndex": int(curve.array_index),
                "keyframeCount": len(curve.keyframe_points),
                "keyframes": [
                    [
                        round(float(point.co.x), 6),
                        round(float(point.co.y), 9),
                    ]
                    for point in curve.keyframe_points
                ],
            }

    blocks = list(shape_keys.key_blocks)[1:]
    samples = {block.name: [] for block in blocks}
    for frame in range(args.start, args.end + 1):
        bpy.context.scene.frame_set(frame)
        for block in blocks:
            samples[block.name].append(round(float(block.value), 9))

    curves = []
    for block in blocks:
        values = samples[block.name]
        data_path = f'key_blocks["{block.name}"].value'
        curves.append(
            {
                "name": block.name,
                "min": min(values),
                "max": max(values),
                "animated": max(values) - min(values) > 1.0e-8,
                "samples": values,
                "fcurve": fcurves.get(data_path),
            }
        )

    payload = {
        "source": bpy.data.filepath,
        "object": face.name,
        "action": action.name if action else None,
        "fps": float(bpy.context.scene.render.fps)
        / float(bpy.context.scene.render.fps_base),
        "start": args.start,
        "end": args.end,
        "basis": shape_keys.key_blocks[0].name,
        "curveCount": len(curves),
        "animatedCurveCount": sum(item["animated"] for item in curves),
        "curves": curves,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, separators=(",", ":")))
    print(
        "ABBY_SPIN_FACIAL_CURVES="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "output": str(output),
                "action": payload["action"],
                "curveCount": payload["curveCount"],
                "animatedCurveCount": payload["animatedCurveCount"],
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


main()
