"""Export the authored Blender Spin face as a read-only animation carrier.

The source .blend is opened by Blender before this script runs.  Only the
facial mesh and its armature are exported to a new, versioned FBX; the source
file is never saved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--face", default="abby_basemesh_FACE")
    parser.add_argument("--armature", default="1_cut0_AbbyCharacter-BODY_character")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    output = args.output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    face = bpy.data.objects.get(args.face)
    armature = bpy.data.objects.get(args.armature)
    if face is None or face.type != "MESH":
        raise RuntimeError(f"Missing face mesh {args.face!r}")
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError(f"Missing armature {args.armature!r}")
    if face.data.shape_keys is None:
        raise RuntimeError("The Spin face has no authored shape keys")

    bpy.ops.object.select_all(action="DESELECT")
    face.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.context.scene.frame_start = args.start
    bpy.context.scene.frame_end = args.end

    bpy.ops.export_scene.fbx(
        filepath=str(output),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        use_mesh_modifiers=False,
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        path_mode="AUTO",
        axis_forward="-Z",
        axis_up="Y",
    )

    payload = {
        "source": bpy.data.filepath,
        "output": str(output),
        "face": face.name,
        "armature": armature.name,
        "start": args.start,
        "end": args.end,
        "fps": float(bpy.context.scene.render.fps)
        / float(bpy.context.scene.render.fps_base),
        "shapeKeys": len(face.data.shape_keys.key_blocks),
        "bytes": output.stat().st_size,
    }
    print("ABBY_SPIN_FACE_CARRIER_FBX=" + json.dumps(payload), flush=True)


main()
