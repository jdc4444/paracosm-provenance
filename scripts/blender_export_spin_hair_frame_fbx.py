"""Export one exact evaluated Spin hair frame as a derived FBX."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


HAIR_NAME = "hair"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=170)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    output = args.output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite derived FBX: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    hair = bpy.data.objects.get(HAIR_NAME)
    if hair is None or hair.type != "MESH":
        raise RuntimeError(f"Missing mesh {HAIR_NAME!r}")
    scene = bpy.context.scene
    scene.frame_set(args.frame)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    hair.select_set(True)
    bpy.context.view_layer.objects.active = hair
    result = bpy.ops.export_scene.fbx(
        filepath=str(output),
        use_selection=True,
        object_types={"MESH"},
        use_mesh_modifiers=True,
        bake_anim=False,
        path_mode="AUTO",
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"FBX export failed: {result}")
    print(
        "CODEX_ABBY_SPIN_HAIR_FBX="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "object": hair.name,
                "frame": args.frame,
                "output": str(output),
                "vertices": len(hair.data.vertices),
                "polygons": len(hair.data.polygons),
                "materials": [
                    material.name for material in hair.data.materials
                ],
            }
        ),
        flush=True,
    )


main()
