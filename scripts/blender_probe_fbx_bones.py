"""Report matching pose-bone positions from an FBX without saving a scene."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--frame", type=int, action="append", required=True)
    parser.add_argument("--bone", action="append", default=[])
    parser.add_argument("--bone-term", action="append", default=[])
    parser.add_argument("--mesh", action="append", default=[])
    return parser.parse_args(argv)


def vector(value) -> list[float]:
    return [float(value.x), float(value.y), float(value.z)]


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
    terms = tuple(item.casefold() for item in args.bone_term)
    names = set(args.bone)
    armatures = [
        item for item in scene.objects if item.type == "ARMATURE"
    ]
    frames = []
    for frame in args.frame:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        records = []
        for armature in armatures:
            for bone in armature.pose.bones:
                if (
                    (terms or names)
                    and bone.name not in names
                    and not any(
                        term in bone.name.casefold() for term in terms
                    )
                ):
                    continue
                matrix = armature.matrix_world @ bone.matrix
                records.append(
                    {
                        "armature": armature.name,
                        "bone": bone.name,
                        "position": vector(matrix.translation),
                    }
                )
        meshes = []
        for name in args.mesh:
            item = scene.objects.get(name)
            if item is None or item.type != "MESH":
                meshes.append({"name": name, "error": "mesh not found"})
                continue
            evaluated = item.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            try:
                points = [
                    item.matrix_world @ vertex.co
                    for vertex in mesh.vertices
                ]
                low = [
                    min(point[index] for point in points) for index in range(3)
                ]
                high = [
                    max(point[index] for point in points) for index in range(3)
                ]
                meshes.append(
                    {
                        "name": name,
                        "vertexCount": len(points),
                        "min": low,
                        "max": high,
                        "center": [
                            (low[index] + high[index]) * 0.5
                            for index in range(3)
                        ],
                        "extent": [
                            high[index] - low[index] for index in range(3)
                        ],
                    }
                )
            finally:
                evaluated.to_mesh_clear()
        frames.append({"frame": frame, "bones": records, "meshes": meshes})

    print(
        "PARACOSM_BLENDER_BONE_PROBE_JSON="
        + json.dumps(
            {
                "input": str(source),
                "fps": scene.render.fps,
                "armatures": [
                    {
                        "name": item.name,
                        "boneCount": len(item.pose.bones),
                    }
                    for item in armatures
                ],
                "frames": frames,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
