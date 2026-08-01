"""Rank same-action FBX frames by a hands-near-face pose.

This is a read-only pose search. It does not import or replace hair, wardrobe,
or any other shot asset.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1842)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--head", default="head_3")
    parser.add_argument("--left-hand", default="hand_l_2")
    parser.add_argument("--right-hand", default="hand_r_2")
    return parser.parse_args(argv)


def distance(a, b) -> float:
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


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
    scene.render.fps = 30
    scene.render.fps_base = 1.0
    armature = next(
        (item for item in scene.objects if item.type == "ARMATURE"),
        None,
    )
    if armature is None:
        raise RuntimeError("FBX contains no armature")
    bones = {
        name: armature.pose.bones.get(name)
        for name in (args.head, args.left_hand, args.right_hand)
    }
    missing = [name for name, item in bones.items() if item is None]
    if missing:
        raise RuntimeError(f"Missing pose bones: {missing}")

    records = []
    for frame in range(args.start, args.end + 1, args.step):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        positions = {
            name: tuple(
                float(value)
                for value in (
                    armature.matrix_world @ item.matrix
                ).translation
            )
            for name, item in bones.items()
        }
        head = positions[args.head]
        left = positions[args.left_hand]
        right = positions[args.right_hand]
        hand_mid = tuple(
            (left[index] + right[index]) * 0.5 for index in range(3)
        )
        separation = distance(left, right)
        midpoint_to_head = distance(hand_mid, head)
        vertical_above_head = hand_mid[2] - head[2]
        depth_from_head = hand_mid[1] - head[1]
        # The cut shows both hands close to the face, separated enough to hold
        # the carousel, and not raised far above the crown.
        score = (
            abs(vertical_above_head - 0.02) * 3.0
            + abs(depth_from_head) * 1.5
            + abs(separation - 0.28)
            + midpoint_to_head * 0.35
        )
        records.append(
            {
                "frame": frame,
                "score": score,
                "head": head,
                "leftHand": left,
                "rightHand": right,
                "handSeparation": separation,
                "handMidpointToHead": midpoint_to_head,
                "handMidpointVerticalAboveHead": vertical_above_head,
                "handMidpointDepthFromHead": depth_from_head,
            }
        )
    records.sort(key=lambda item: item["score"])
    print(
        "PARACOSM_HAND_POSE_SCAN_JSON="
        + json.dumps(
            {
                "input": str(source),
                "fps": scene.render.fps,
                "frameRange": [args.start, args.end, args.step],
                "bones": {
                    "head": args.head,
                    "leftHand": args.left_hand,
                    "rightHand": args.right_hand,
                },
                "candidates": records[: args.limit],
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
