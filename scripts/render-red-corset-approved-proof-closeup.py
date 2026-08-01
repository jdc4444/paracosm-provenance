#!/usr/bin/env python3
"""Render a true 1280 closeup from the approved Red Corset cloth scene."""

import os

import bpy
from mathutils import Vector


ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance"
OUTPUT = os.path.join(
    ROOT,
    "public/archive/objects/3d/simulations/red-corset-top",
    "red-corset-top-cloth-static-proof-v1-closeup.png",
)


def evaluated_world_bounds(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    points = [
        evaluated.matrix_world @ vertex.co
        for vertex in evaluated.data.vertices
    ]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


scene = bpy.context.scene
scene.frame_set(16)
bpy.context.view_layer.update()
corset = bpy.data.objects["Red_Corset_Render_Mesh"]
minimum, maximum = evaluated_world_bounds(corset)
extent = maximum - minimum
focus = Vector(
    (
        (minimum.x + maximum.x) * 0.5,
        (minimum.y + maximum.y) * 0.5,
        minimum.z + extent.z * 0.66,
    )
)
camera = scene.camera
camera.data.type = "ORTHO"
camera.data.ortho_scale = 1.12
camera.rotation_euler = (
    focus - camera.location
).to_track_quat("-Z", "Y").to_euler()

scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1280
scene.render.resolution_y = 1280
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass
scene.render.filepath = OUTPUT
bpy.ops.render.render(write_still=True)

print(f"RED_CORSET_CLOSEUP_COMPLETE {OUTPUT}")
