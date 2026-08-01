"""Export the exact body and face meshes from one same-action FBX to Alembic.

Run with Blender in background mode and place script arguments after ``--``.
The script deliberately excludes hair, cloth, shoes, and all cross-shot assets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


TARGET_NAMES = (
    "SKM_AbbyV2Character_BodyMesh",
    "SKM_NewMetaHumanCharacter_FaceMesh",
)


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1842)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    source = args.input.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if args.end < args.start:
        raise ValueError("--end must be greater than or equal to --start")

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
    scene.frame_start = args.start
    scene.frame_end = args.end

    targets = []
    for name in TARGET_NAMES:
        item = bpy.data.objects.get(name)
        if item is None or item.type != "MESH":
            raise RuntimeError(f"Required same-action mesh not found: {name}")
        targets.append(item)

    bpy.ops.object.select_all(action="DESELECT")
    for item in targets:
        item.select_set(True)
    bpy.context.view_layer.objects.active = targets[0]

    output.parent.mkdir(parents=True, exist_ok=True)
    export_result = bpy.ops.wm.alembic_export(
        filepath=str(output),
        check_existing=False,
        start=args.start,
        end=args.end,
        xsamples=1,
        gsamples=1,
        selected=True,
        visible_objects_only=False,
        flatten=False,
        uvs=True,
        packuv=False,
        normals=True,
        vcolors=True,
        face_sets=False,
        subdiv_schema=False,
        apply_subdiv=False,
        curves_as_mesh=False,
        use_instancing=False,
        global_scale=1.0,
        triangulate=False,
        export_hair=False,
        export_particles=False,
        export_custom_properties=False,
        as_background_job=False,
        evaluation_mode="RENDER",
        init_scene_frame_range=False,
    )
    if "FINISHED" not in export_result:
        raise RuntimeError(f"Alembic export failed: {export_result}")
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"Alembic output was not created: {output}")

    payload = {
        "source": str(source),
        "output": str(output),
        "outputBytes": output.stat().st_size,
        "fps": scene.render.fps,
        "frameRange": [args.start, args.end],
        "targets": [
            {
                "name": item.name,
                "mesh": item.data.name,
                "vertices": len(item.data.vertices),
                "polygons": len(item.data.polygons),
                "modifiers": [modifier.type for modifier in item.modifiers],
            }
            for item in targets
        ],
        "actions": [
            {
                "name": action.name,
                "frameRange": list(action.frame_range),
            }
            for action in bpy.data.actions
        ],
    }
    print(
        "PARACOSM_SAME_ACTION_ABC_JSON="
        + json.dumps(payload, separators=(",", ":")),
        flush=True,
    )


if __name__ == "__main__":
    main()
