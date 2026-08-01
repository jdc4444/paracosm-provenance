#!/usr/bin/env python3
"""Render six orthographic review angles for a GLB with important openings."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(arguments)


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [
        item.matrix_world @ Vector(corner)
        for item in objects
        for corner in item.bound_box
    ]
    return (
        Vector(
            tuple(min(point[index] for point in points) for index in range(3))
        ),
        Vector(
            tuple(max(point[index] for point in points) for index in range(3))
        ),
    )


def look_at(item: bpy.types.Object, target: Vector) -> None:
    item.rotation_euler = (target - item.location).to_track_quat(
        "-Z", "Y"
    ).to_euler()


def add_area_light(
    name: str,
    location: Vector,
    energy: float,
    size: float,
    target: Vector,
) -> None:
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    item = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(item)
    item.location = location
    look_at(item, target)


args = parse_args()
model = args.model.expanduser().resolve()
output_dir = args.output_dir.expanduser().resolve()
output_dir.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(model))
meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
if not meshes:
    raise RuntimeError(f"No mesh objects imported from {model}")

minimum, maximum = bounds(meshes)
center = (minimum + maximum) * 0.5
extent = maximum - minimum
view_extent = max(extent)
distance = view_extent * 3.2

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1024
scene.render.resolution_y = 1024
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("White review world")
scene.world.use_nodes = True
background = scene.world.node_tree.nodes.get("Background")
background.inputs["Color"].default_value = (0.95, 0.95, 0.95, 1.0)
background.inputs["Strength"].default_value = 0.8
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass

camera_data = bpy.data.cameras.new("Review camera")
camera_data.type = "ORTHO"
camera_data.ortho_scale = view_extent * 1.28
camera = bpy.data.objects.new("Review camera", camera_data)
bpy.context.collection.objects.link(camera)
scene.camera = camera

add_area_light(
    "Key",
    center + Vector((-2.5, -3.0, 3.0)) * view_extent,
    1100.0,
    view_extent * 2.5,
    center,
)
add_area_light(
    "Fill",
    center + Vector((2.7, -1.0, 1.8)) * view_extent,
    650.0,
    view_extent * 3.0,
    center,
)
add_area_light(
    "Rear",
    center + Vector((0.5, 3.0, 2.3)) * view_extent,
    850.0,
    view_extent * 2.2,
    center,
)

angles = {
    "front": Vector((0.0, -distance, view_extent * 0.04)),
    "rear": Vector((0.0, distance, view_extent * 0.04)),
    "left": Vector((-distance, 0.0, view_extent * 0.04)),
    "right": Vector((distance, 0.0, view_extent * 0.04)),
    "top": Vector((0.0, 0.0, distance)),
    "bottom": Vector((0.0, 0.0, -distance)),
}
for label, offset in angles.items():
    camera.location = center + offset
    look_at(camera, center)
    scene.render.filepath = str(output_dir / f"{label}.png")
    bpy.ops.render.render(write_still=True)

print(
    {
        "model": str(model),
        "outputDir": str(output_dir),
        "angles": list(angles),
        "dimensions": list(extent),
    }
)
