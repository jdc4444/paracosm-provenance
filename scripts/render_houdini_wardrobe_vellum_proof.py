#!/usr/bin/env python3
"""Render one Houdini Vellum rescue OBJ as medium and closeup proof stills."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path("/Users/alphaone/Documents/Code/paracosm-provenance")

BASE_COLORS = {
    "black-deconstructed-coat-dress": (0.012, 0.012, 0.014, 1.0),
    "burgundy-button-corset": (0.13, 0.018, 0.035, 1.0),
    "navy-taffeta-dress": (0.012, 0.018, 0.065, 1.0),
    "purple-ruffle-skirt": (0.16, 0.045, 0.24, 1.0),
    "teal-pleated-skirt": (0.018, 0.18, 0.18, 1.0),
    "white-lilac-corset-dress": (0.56, 0.49, 0.67, 1.0),
    "black-tiered-tulle-skirt": (0.008, 0.008, 0.011, 1.0),
    "champagne-ruffle-corset-dress": (0.63, 0.47, 0.29, 1.0),
    "pink-striped-shag-sweater": (0.58, 0.15, 0.26, 1.0),
    "burgundy-sheer-column-dress": (0.18, 0.018, 0.045, 1.0),
    "pink-tie-dye-tights": (0.63, 0.20, 0.42, 1.0),
    "olive-cropped-military-jacket": (0.15, 0.18, 0.055, 1.0),
    "black-culottes": (0.01, 0.01, 0.014, 1.0),
    "bronze-abstract-gown": (0.32, 0.13, 0.045, 1.0),
    "multicolor-ribbed-top": (0.32, 0.11, 0.24, 1.0),
    "multicolor-mesh-top": (0.24, 0.12, 0.34, 1.0),
    "navy-pinstripe-ruffle-dress": (0.012, 0.02, 0.075, 1.0),
    "burgundy-orange-circle-dress": (0.33, 0.055, 0.035, 1.0),
    "burgundy-cape-keyhole-top": (0.17, 0.018, 0.042, 1.0),
    "navy-corset-vest": (0.012, 0.018, 0.06, 1.0),
    "navy-bubble-skirt": (0.012, 0.018, 0.065, 1.0),
    "navy-striped-velvet-skirt": (0.01, 0.022, 0.07, 1.0),
}

MATERIAL_ROUGHNESS = {
    "rigid-corsetry": 0.56,
    "structured-ruffle": 0.64,
    "sheer-lightweight": 0.58,
    "stretch-jersey": 0.68,
    "knit-fuzzy": 0.78,
    "satin-fluid": 0.57,
    "tulle-ruffle": 0.72,
    "crisp-woven": 0.62,
    "tailored-heavy": 0.70,
}


def parse_args() -> argparse.Namespace:
    arguments = sys.argv
    if "--" in arguments:
        arguments = arguments[arguments.index("--") + 1 :]
    else:
        arguments = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", required=True)
    return parser.parse_args(arguments)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


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
    location: Vector,
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
    look_at(light_object, target)


def render_still(
    camera: bpy.types.Object,
    target: Vector,
    scale: float,
    output_path: Path,
) -> None:
    camera.data.ortho_scale = scale
    look_at(camera, target)
    bpy.context.scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)


args = parse_args()
output_dir = (
    ROOT
    / f"public/archive/objects/3d/simulations/{args.object_id}/houdini-vellum-v1"
)
stem = f"{args.object_id}-houdini-vellum-v1"
source_obj = output_dir / f"{stem}-frame28.obj"
metadata_path = output_dir / f"{stem}-metadata.json"
medium_path = output_dir / f"{stem}-medium.png"
closeup_path = output_dir / f"{stem}-closeup.png"
blend_path = output_dir / f"{stem}-render.blend"

if not source_obj.exists() or not metadata_path.exists():
    raise FileNotFoundError(source_obj)
metadata = json.loads(metadata_path.read_text())
material_class = metadata["materialClass"]
proxy_kind = metadata["proxyKind"]

clear_scene()
bpy.ops.wm.obj_import(
    filepath=str(source_obj),
    forward_axis="NEGATIVE_Z",
    up_axis="Y",
)
garment_objects = [
    obj for obj in bpy.context.selected_objects if obj.type == "MESH"
]
if not garment_objects:
    raise RuntimeError("Houdini OBJ import produced no mesh objects")

material = bpy.data.materials.new(
    f"{args.object_id.replace('-', ' ').title()} Matte Proof"
)
material.use_nodes = True
principled = material.node_tree.nodes.get("Principled BSDF")
principled.inputs["Base Color"].default_value = BASE_COLORS[args.object_id]
principled.inputs["Roughness"].default_value = MATERIAL_ROUGHNESS[material_class]
principled.inputs["Metallic"].default_value = 0.0
if "Coat Weight" in principled.inputs:
    principled.inputs["Coat Weight"].default_value = 0.0
if "Sheen Weight" in principled.inputs:
    principled.inputs["Sheen Weight"].default_value = (
        0.13 if material_class in {"knit-fuzzy", "tailored-heavy"} else 0.07
    )
if "Sheen Roughness" in principled.inputs:
    principled.inputs["Sheen Roughness"].default_value = 0.78

noise = material.node_tree.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = (
    145.0 if material_class in {"crisp-woven", "rigid-corsetry"} else 105.0
)
noise.inputs["Detail"].default_value = 2.0
noise.inputs["Roughness"].default_value = 0.72
noise.location = (-520, 40)
roughness_ramp = material.node_tree.nodes.new("ShaderNodeValToRGB")
base_roughness = MATERIAL_ROUGHNESS[material_class]
roughness_ramp.color_ramp.elements[0].color = (
    max(0.35, base_roughness - 0.09),
) * 3 + (1.0,)
roughness_ramp.color_ramp.elements[1].color = (
    min(0.88, base_roughness + 0.10),
) * 3 + (1.0,)
roughness_ramp.location = (-300, 65)
bump = material.node_tree.nodes.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = (
    0.075 if material_class == "knit-fuzzy" else 0.035
)
bump.inputs["Distance"].default_value = 0.009
bump.location = (-75, -100)
material.node_tree.links.new(noise.outputs["Fac"], roughness_ramp.inputs["Fac"])
material.node_tree.links.new(
    roughness_ramp.outputs["Color"], principled.inputs["Roughness"]
)
material.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
material.node_tree.links.new(bump.outputs["Normal"], principled.inputs["Normal"])

for garment in garment_objects:
    garment.data.materials.clear()
    garment.data.materials.append(material)
    for polygon in garment.data.polygons:
        polygon.use_smooth = True

minimum, maximum = combined_bounds(garment_objects)
extent = maximum - minimum
center = (minimum + maximum) * 0.5
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
floor_principled.inputs["Roughness"].default_value = 0.72
floor_size = max(extent.x, extent.y, extent.z) * 24.0
bpy.ops.mesh.primitive_plane_add(
    size=floor_size, location=(center.x, center.y, 0.0)
)
bpy.context.object.data.materials.append(floor_material)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1280
scene.render.resolution_y = 1280
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "8"
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("White Proof World")
scene.world.use_nodes = True
background = scene.world.node_tree.nodes.get("Background")
background.inputs["Color"].default_value = (0.97, 0.97, 0.97, 1.0)
background.inputs["Strength"].default_value = 0.65
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.color_depth = "8"
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.use_file_extension = True

camera_data = bpy.data.cameras.new("Proof Camera")
camera_data.type = "ORTHO"
camera = bpy.data.objects.new("Proof Camera", camera_data)
bpy.context.collection.objects.link(camera)
scene.camera = camera

view_extent = max(extent.x, extent.y, extent.z)
camera.location = center + Vector(
    (view_extent * 1.45, -view_extent * 2.9, view_extent * 1.12)
)
light_target = center + Vector((0.0, 0.0, extent.z * 0.04))
add_area_light(
    "Key Softbox",
    center + Vector((-2.6, -3.2, 3.2)) * view_extent,
    900.0,
    view_extent * 2.3,
    (1.0, 0.94, 0.88),
    light_target,
)
add_area_light(
    "Fill Softbox",
    center + Vector((2.8, -1.2, 1.7)) * view_extent,
    520.0,
    view_extent * 2.7,
    (0.77, 0.86, 1.0),
    light_target,
)
add_area_light(
    "Rim Softbox",
    center + Vector((0.5, 2.8, 2.6)) * view_extent,
    700.0,
    view_extent * 1.9,
    (0.82, 0.89, 1.0),
    light_target,
)

medium_scale = max(extent.x, extent.z) * 1.27
render_still(
    camera,
    center + Vector((0.0, 0.0, extent.z * 0.02)),
    medium_scale,
    medium_path,
)

closeup_fraction = 0.62 if proxy_kind in {"skirt", "dress"} else 0.56
closeup_target = Vector(
    (center.x, center.y, minimum.z + extent.z * (0.63 if proxy_kind != "legs" else 0.70))
)
render_still(
    camera,
    closeup_target,
    medium_scale * closeup_fraction,
    closeup_path,
)

bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
metadata["render"] = {
    "renderer": "Blender Eevee",
    "material": f"matte {material_class} construction proof",
    "resolution": [1280, 1280],
    "medium": f"/{medium_path.relative_to(ROOT / 'public').as_posix()}",
    "closeup": f"/{closeup_path.relative_to(ROOT / 'public').as_posix()}",
    "scene": f"/{blend_path.relative_to(ROOT / 'public').as_posix()}",
    "garmentObjects": len(garment_objects),
    "vertices": sum(len(obj.data.vertices) for obj in garment_objects),
    "polygons": sum(len(obj.data.polygons) for obj in garment_objects),
}
metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n")
print(json.dumps(metadata["render"], indent=2))
