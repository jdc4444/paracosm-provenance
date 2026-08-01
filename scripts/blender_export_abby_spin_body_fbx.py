"""Export Abby's full Spin body animation as a derived FBX motion source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


ARMATURE_NAME = "1_cut0_AbbyCharacter-BODY_character"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    args = parser.parse_args(
        sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    )

    output = args.output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite derived FBX: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    armature = bpy.data.objects.get(ARMATURE_NAME)
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError(f"Missing armature {ARMATURE_NAME!r}")

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.context.scene.frame_start = args.start
    bpy.context.scene.frame_end = args.end

    result = bpy.ops.export_scene.fbx(
        filepath=str(output),
        use_selection=True,
        object_types={"ARMATURE"},
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        path_mode="AUTO",
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"FBX export failed: {result}")

    print(
        "CODEX_ABBY_SPIN_BODY_FBX="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "armature": ARMATURE_NAME,
                "action": armature.animation_data.action.name
                if armature.animation_data and armature.animation_data.action
                else None,
                "fps": bpy.context.scene.render.fps
                / bpy.context.scene.render.fps_base,
                "range": [args.start, args.end],
                "output": str(output),
                "bones": len(armature.data.bones),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
