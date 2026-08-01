"""Export rotation-invariant joint-distance signatures from a Blender armature."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import bpy


ARMATURE_NAME = "1_cut0_AbbyCharacter-BODY_character"
JOINTS = {
    "pelvis": "Hips",
    "head": "Head",
    "hand_l": "LeftHand",
    "hand_r": "RightHand",
    "foot_l": "LeftFoot",
    "foot_r": "RightFoot",
    "upperarm_l": "LeftArm",
    "upperarm_r": "RightArm",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    parser.add_argument("--step", type=int, default=1)
    args = parser.parse_args(
        sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    )

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    armature = bpy.data.objects.get(ARMATURE_NAME)
    if armature is None:
        raise RuntimeError(f"Missing armature {ARMATURE_NAME!r}")

    pairs = list(itertools.combinations(JOINTS, 2))
    records = []
    for frame in range(args.start, args.end + 1, args.step):
        bpy.context.scene.frame_set(frame)
        points = {
            key: armature.matrix_world
            @ armature.pose.bones[bone_name].head
            for key, bone_name in JOINTS.items()
        }
        scale = max((points["head"] - points["pelvis"]).length, 1.0e-8)
        signature = [
            (points[left] - points[right]).length / scale
            for left, right in pairs
        ]
        records.append({"frame": frame, "signature": signature})

    payload = {
        "source": bpy.data.filepath,
        "fps": bpy.context.scene.render.fps
        / bpy.context.scene.render.fps_base,
        "joints": JOINTS,
        "pairs": pairs,
        "records": records,
    }
    output.write_text(json.dumps(payload, separators=(",", ":")))
    print(
        "CODEX_BLENDER_POSE_SIGNATURE="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "output": str(output),
                "frames": len(records),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
