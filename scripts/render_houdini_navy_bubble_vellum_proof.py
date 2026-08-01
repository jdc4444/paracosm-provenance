#!/usr/bin/env python3
"""Render high-resolution static evidence from the Houdini Vellum OBJ handoff."""

from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path("/Users/alphaone/Documents/Code/paracosm-provenance")
OUTPUT_DIR = (
    ROOT
    / "public/archive/objects/3d/simulations/navy-bubble-skirt/houdini-vellum-v1"
)
SOURCE_OBJ = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-frame28.obj"
MEDIUM_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-medium.png"
CLOSEUP_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-closeup.png"
BLEND_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-render.blend"
METADATA_PATH = OUTPUT_DIR / "navy-bubble-skirt-houdini-vellum-v1-metadata.json"


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def combined_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [
        obj.matrix_world @ Vector(corner)
        for obj in objects
        for corner in obj.bound_box
    ]
    return (
        Vector(tuple(min(point[index] for point in points) for index in range(3))),
        Vector(tuple(max(point[index] for point in points) for index in range(3))),
    )


def look_at(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat(
        "-Z", "Y"
    ).to_euler()


def add_area_light(
    name: str,
    location: tuple[float, float, float],
    energy: float,
    size: float,
    color: tuple[float, float, float],
    target: Vector,
) -> None:
    light_data = bpy.data.lights.new(name, type="AREA")
    light_data.energy = energy
    light_data.shape = "DISK"
    light_data.size = size
    light_data.color = color
    light_object = bpy.data.objects.new(name, light_data)
    bpy.context.collection.objects.link(light_object)
    light_object.location = location
    light_object.rotation_euler = (
        target - light_object.location
    ).to_track_quat("-Z", "Y").to_euler()


def render_proof(
    camera: bpy.types.Object,
    target: Vector,
    ortho_scale: float,
    output_path: Path,
) -> None:
    camera.data.ortho_scale = ortho_scale
    look_at(camera, target)
    bpy.context.scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)


clear_scene()
if not SOURCE_OBJ.exists():
    raise FileNotFoundError(SOURCE_OBJ)

bpy.ops.wm.obj_import(
    filepath=str(SOURCE_OBJ),
    forward_axis="NEGATIVE_Z",
    up_axis="Y",
)
garment_objects = [
    obj for obj in bpy.context.selected_objects if obj.type == "MESH"
]
if not garment_objects:
    raise RuntimeError("Houdini OBJ import produced no mesh objects")

navy_material = bpy.data.materials.new("Navy Satin Proof")
navy_material.use_nodes = True
principled = navy_material.node_tree.nodes.get("Principled BSDF")
principled.inputs["Base Color"].default_value = (0.012, 0.018, 0.065, 1.0)
principled.inputs["Roughness"].default_value = 0.68
principled.inputs["Metallic"].default_value = 0.0
if "Coat Weight" in principled.inputs:
    principled.inputs["Coat Weight"].default_value = 0.0
if "Coat Roughness" in principled.inputs:
    principled.inputs["Coat Roughness"].default_value = 0.8
if "Sheen Weight" in principled.inputs:
    principled.inputs["Sheen Weight"].default_value = 0.08
if "Sheen Roughness" in principled.inputs:
    principled.inputs["Sheen Roughness"].default_value = 0.78

# A very fine roughness variation breaks up the broad plastic-looking
# highlights without changing the simulated silhouette.
noise = navy_material.node_tree.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 115.0
noise.inputs["Detail"].default_value = 2.0
noise.inputs["Roughness"].default_value = 0.72
noise.inputs["Distortion"].default_value = 0.08
noise.location = (-520, 40)

roughness_ramp = navy_material.node_tree.nodes.new("ShaderNodeValToRGB")
roughness_ramp.color_ramp.elements[0].position = 0.22
roughness_ramp.color_ramp.elements[0].color = (0.54, 0.54, 0.54, 1.0)
roughness_ramp.color_ramp.elements[1].position = 0.78
roughness_ramp.color_ramp.elements[1].color = (0.78, 0.78, 0.78, 1.0)
roughness_ramp.location = (-300, 65)

bump = navy_material.node_tree.nodes.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.055
bump.inputs["Distance"].default_value = 0.012
bump.location = (-75, -100)

navy_material.node_tree.links.new(
    noise.outputs["Fac"], roughness_ramp.inputs["Fac"]
)
navy_material.node_tree.links.new(
    roughness_ramp.outputs["Color"], principled.inputs["Roughness"]
)
navy_material.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
navy_material.node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])

for garment in garment_objects:
    garment.name = f"Houdini_Vellum_{garment.name}"
    garment.data.materials.clear()
    garment.data.materials.append(navy_material)
    for polygon in garment.data.polygons:
        polygon.use_smooth = True

minimum, maximum = combined_bounds(garment_objects)
extent = maximum - minimum
center = (minimum + maximum) * 0.5

# Lift the simulated garment slightly above a white studio floor without
# changing its solved shape.
lift = -minimum.z + 0.08
for garment in garment_objects:
    garment.location.z += lift
minimum.z += lift
maximum.z += lift
center.z += lift

floor_material = bpy.data.materials.new("White Studio")
floor_material.use_nodes = True
floor_principled = floor_material.node_tree.nodes.get("Principled BSDF")
floor_principled.inputs["Base Color"].default_value = (0.92, 0.92, 0.90, 1.0)
floor_principled.inputs["Roughness"].default_value = 0.68

floor_size = max(extent.x, extent.y, extent.z) * 24.0
bpy.ops.mesh.primitive_plane_add(
    size=floor_size,
    location=(center.x, center.y, 0.0),
)
floor = bpy.context.object
floor.name = "White_Studio_Floor"
floor.data.materials.append(floor_material)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1280
scene.render.resolution_y = 1280
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.film_transparent = False
scene.render.image_settings.color_depth = "8"
scene.render.use_file_extension = True
scene.render.resolution_percentage = 100
scene.world = bpy.data.worlds.new("White Proof World")
scene.world.use_nodes = True
world_background = scene.world.node_tree.nodes.get("Background")
world_background.inputs["Color"].default_value = (0.97, 0.97, 0.97, 1.0)
world_background.inputs["Strength"].default_value = 0.65
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass

camera_data = bpy.data.cameras.new("Proof Camera")
camera_data.type = "ORTHO"
camera = bpy.data.objects.new("Proof Camera", camera_data)
bpy.context.collection.objects.link(camera)
scene.camera = camera

view_extent = max(extent.x, extent.y, extent.z)
camera.location = center + Vector((view_extent * 1.5, -view_extent * 2.9, view_extent * 1.15))
camera.data.lens = 55

light_target = center + Vector((0.0, 0.0, extent.z * 0.04))
add_area_light(
    "Key Softbox",
    tuple(center + Vector((-2.6, -3.2, 3.2)) * view_extent),
    920.0,
    view_extent * 2.2,
    (1.0, 0.94, 0.88),
    light_target,
)
add_area_light(
    "Fill Softbox",
    tuple(center + Vector((2.8, -1.2, 1.7)) * view_extent),
    560.0,
    view_extent * 2.6,
    (0.77, 0.86, 1.0),
    light_target,
)
add_area_light(
    "Rim Softbox",
    tuple(center + Vector((0.5, 2.8, 2.6)) * view_extent),
    760.0,
    view_extent * 1.8,
    (0.82, 0.89, 1.0),
    light_target,
)

medium_target = center + Vector((0.0, 0.0, extent.z * 0.02))
medium_scale = max(extent.x, extent.z) * 1.27
render_proof(camera, medium_target, medium_scale, MEDIUM_PATH)

closeup_target = Vector(
    (
        center.x,
        center.y,
        minimum.z + extent.z * 0.64,
    )
)
closeup_scale = medium_scale * 0.59
render_proof(camera, closeup_target, closeup_scale, CLOSEUP_PATH)

bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

metadata = json.loads(METADATA_PATH.read_text())
metadata["render"] = {
    "renderer": "Blender Eevee",
    "resolution": [1280, 1280],
    "medium": f"/{MEDIUM_PATH.relative_to(ROOT / 'public').as_posix()}",
    "closeup": f"/{CLOSEUP_PATH.relative_to(ROOT / 'public').as_posix()}",
    "scene": f"/{BLEND_PATH.relative_to(ROOT / 'public').as_posix()}",
    "garmentObjects": len(garment_objects),
    "vertices": sum(len(obj.data.vertices) for obj in garment_objects),
    "polygons": sum(len(obj.data.polygons) for obj in garment_objects),
}
METADATA_PATH.write_text(f"{json.dumps(metadata, indent=2)}\n")

print(
    json.dumps(
        {
            "medium": str(MEDIUM_PATH),
            "closeup": str(CLOSEUP_PATH),
            "scene": str(BLEND_PATH),
            "garmentObjects": len(garment_objects),
            "vertices": metadata["render"]["vertices"],
            "polygons": metadata["render"]["polygons"],
        },
        indent=2,
    )
)
