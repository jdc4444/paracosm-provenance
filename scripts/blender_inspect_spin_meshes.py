"""Inventory evaluated Spin meshes at a chosen frame."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=170)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def vector(value):
    return [float(value.x), float(value.y), float(value.z)]


def main():
    args = parse_args()
    scene = bpy.context.scene
    scene.frame_set(args.frame)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    records = []
    for item in bpy.data.objects:
        if item.type != "MESH":
            continue
        evaluated = item.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            corners = [
                evaluated.matrix_world @ item
                for item in (
                    __import__("mathutils").Vector(corner)
                    for corner in item.bound_box
                )
            ]
            records.append(
                {
                    "name": item.name,
                    "parent": item.parent.name if item.parent else None,
                    "vertices": len(mesh.vertices),
                    "polygons": len(mesh.polygons),
                    "hideRender": bool(item.hide_render),
                    "materials": [
                        material.name for material in item.data.materials
                    ],
                    "modifiers": [
                        {
                            "name": modifier.name,
                            "type": modifier.type,
                            "object": (
                                modifier.object.name
                                if hasattr(modifier, "object")
                                and modifier.object is not None
                                else None
                            ),
                        }
                        for modifier in item.modifiers
                    ],
                    "action": (
                        item.animation_data.action.name
                        if item.animation_data
                        and item.animation_data.action
                        else None
                    ),
                    "shapeKeys": (
                        len(item.data.shape_keys.key_blocks)
                        if item.data.shape_keys
                        else 0
                    ),
                    "bounds": {
                        "low": [
                            min(point[index] for point in corners)
                            for index in range(3)
                        ],
                        "high": [
                            max(point[index] for point in corners)
                            for index in range(3)
                        ],
                    },
                }
            )
        finally:
            evaluated.to_mesh_clear()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "source": bpy.data.filepath,
                "frame": args.frame,
                "fps": scene.render.fps / scene.render.fps_base,
                "records": records,
            },
            indent=2,
        )
    )
    print(f"ABBY_SPIN_MESH_INVENTORY={args.output}", flush=True)


main()
