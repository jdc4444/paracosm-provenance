"""Read-only summary of facial deformation data in Abby's Blender source."""

from __future__ import annotations

import json

import bpy


def main() -> None:
    meshes = []
    for item in bpy.data.objects:
        if item.type != "MESH":
            continue
        name = item.name.lower()
        facial_groups = [
            group.name
            for group in item.vertex_groups
            if any(
                token in group.name.lower()
                for token in ("facial", "eyelid", "lip", "mouth", "jaw", "eye")
            )
        ]
        shape_keys = (
            [key.name for key in item.data.shape_keys.key_blocks]
            if item.data.shape_keys
            else []
        )
        modifiers = [
            {
                "name": modifier.name,
                "type": modifier.type,
                "object": getattr(modifier.object, "name", None),
            }
            for modifier in item.modifiers
            if modifier.type == "ARMATURE"
        ]
        focus_groups = {}
        for group_name in (
            "FACIAL_L_EyelidUpperA1",
            "FACIAL_R_EyelidUpperA1",
            "FACIAL_L_EyelidLowerA1",
            "FACIAL_R_EyelidLowerA1",
            "FACIAL_C_Jaw",
            "FACIAL_L_LipCorner",
            "FACIAL_R_LipCorner",
            "head",
        ):
            group = item.vertex_groups.get(group_name)
            if group is None:
                continue
            values = [
                membership.weight
                for vertex in item.data.vertices
                for membership in vertex.groups
                if membership.group == group.index and membership.weight > 0.0
            ]
            focus_groups[group_name] = {
                "weightedVertices": len(values),
                "maxWeight": max(values, default=0.0),
                "weightSum": sum(values),
            }
        if (
            any(token in name for token in ("face", "head", "eye", "lash"))
            or facial_groups
            or shape_keys
        ):
            meshes.append(
                {
                    "name": item.name,
                    "vertices": len(item.data.vertices),
                    "facialVertexGroups": facial_groups[:20],
                    "facialVertexGroupCount": len(facial_groups),
                    "focusGroupWeights": focus_groups,
                    "shapeKeys": shape_keys[:20],
                    "shapeKeyCount": len(shape_keys),
                    "armatureModifiers": modifiers,
                }
            )

    armatures = []
    for item in bpy.data.objects:
        if item.type != "ARMATURE":
            continue
        facial_bones = [
            bone.name
            for bone in item.data.bones
            if any(
                token in bone.name.lower()
                for token in ("facial", "eyelid", "lip", "mouth", "jaw", "eye")
            )
        ]
        armatures.append(
            {
                "name": item.name,
                "boneCount": len(item.data.bones),
                "facialBoneCount": len(facial_bones),
                "facialBones": facial_bones[:20],
            }
        )

    print(
        "ABBY_BLENDER_FACE_RIG="
        + json.dumps(
            {"file": bpy.data.filepath, "meshes": meshes, "armatures": armatures},
            separators=(",", ":"),
        ),
        flush=True,
    )


main()
