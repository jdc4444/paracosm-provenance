"""Export the exact Spin armature rest pose as a derived FBX calibration rig."""

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

    action_name = (
        armature.animation_data.action.name
        if armature.animation_data and armature.animation_data.action
        else None
    )
    if armature.animation_data:
        armature.animation_data.action = None
    armature.data.pose_position = "REST"
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    result = bpy.ops.export_scene.fbx(
        filepath=str(output),
        use_selection=True,
        object_types={"ARMATURE"},
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="AUTO",
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"FBX export failed: {result}")

    print(
        "CODEX_ABBY_SPIN_BODY_REST_FBX="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "armature": ARMATURE_NAME,
                "detachedAction": action_name,
                "output": str(output),
                "bones": len(armature.data.bones),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
