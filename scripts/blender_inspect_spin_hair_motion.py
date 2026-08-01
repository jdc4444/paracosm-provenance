"""Inspect the authored Spin hair animation without changing the .blend."""

from __future__ import annotations

import json

import bpy


hair = bpy.data.objects.get("hair")
if hair is None or hair.type != "MESH":
    raise RuntimeError("Missing mesh 'hair'")

scene = bpy.context.scene
frames = [0, 90, 170, 270, 365]
samples = []
baseline = None
for frame in frames:
    scene.frame_set(frame)
    bpy.context.view_layer.update()
    evaluated = hair.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        world = evaluated.matrix_world
        points = [world @ vertex.co for vertex in mesh.vertices]
        if baseline is None:
            baseline = points
        step = max(len(points) // 512, 1)
        sampled = points[::step]
        baseline_sampled = baseline[::step]
        displacements = [
            (point - base).length
            for point, base in zip(sampled, baseline_sampled)
        ]
        samples.append(
            {
                "frame": frame,
                "vertices": len(points),
                "polygons": len(mesh.polygons),
                "boundsMin": [
                    min(point[index] for point in points) for index in range(3)
                ],
                "boundsMax": [
                    max(point[index] for point in points) for index in range(3)
                ],
                "sampledMaxDisplacementFromFrame0": max(displacements),
                "sampledMeanDisplacementFromFrame0": sum(displacements)
                / max(len(displacements), 1),
            }
        )
    finally:
        evaluated.to_mesh_clear()

payload = {
    "source": bpy.data.filepath,
    "object": hair.name,
    "parent": hair.parent.name if hair.parent else None,
    "parentType": hair.parent_type,
    "vertices": len(hair.data.vertices),
    "polygons": len(hair.data.polygons),
    "modifiers": [
        {"name": modifier.name, "type": modifier.type}
        for modifier in hair.modifiers
    ],
    "shapeKeys": (
        [key.name for key in hair.data.shape_keys.key_blocks]
        if hair.data.shape_keys
        else []
    ),
    "objectAction": (
        hair.animation_data.action.name
        if hair.animation_data and hair.animation_data.action
        else None
    ),
    "dataAction": (
        hair.data.animation_data.action.name
        if hair.data.animation_data and hair.data.animation_data.action
        else None
    ),
    "samples": samples,
}
print("ABBY_SPIN_HAIR_MOTION=" + json.dumps(payload), flush=True)
