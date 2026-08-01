#!/usr/bin/env python3
"""Render a textured, floor-draped Houdini Vellum v4 proof in Blender."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path("/Users/alphaone/Documents/Code/paracosm-provenance")
MATERIAL_ROUGHNESS = {
    "rigid-corsetry": 0.60,
    "structured-ruffle": 0.66,
    "sheer-lightweight": 0.64,
    "stretch-jersey": 0.70,
    "knit-fuzzy": 0.78,
    "satin-fluid": 0.61,
    "tulle-ruffle": 0.73,
    "crisp-woven": 0.68,
    "tailored-heavy": 0.72,
}


def parse_args() -> argparse.Namespace:
    arguments = sys.argv
    if "--" in arguments:
        arguments = arguments[arguments.index("--") + 1 :]
    else:
        arguments = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", required=True)
    parser.add_argument(
        "--surface-mode",
        choices=("source-deform", "proxy-uv"),
        default="source-deform",
    )
    parser.add_argument(
        "--compression-mode",
        choices=("gates", "drop-only"),
        default="gates",
    )
    parser.add_argument(
        "--neutral-diagnostic",
        action="store_true",
        help="Render the same geometry in neutral gray to isolate deformation.",
    )
    return parser.parse_args(arguments)


def clear_objects() -> None:
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
        "-Z",
        "Y",
    ).to_euler()


def add_area_light(
    name: str,
    location: Vector,
    energy: float,
    size: float,
    color: tuple[float, float, float],
    target: Vector,
) -> None:
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    item = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(item)
    item.location = location
    look_at(item, target)


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


def copy_source_material(source_path: Path, material_class: str) -> bpy.types.Material:
    clear_objects()
    bpy.ops.import_scene.gltf(filepath=str(source_path))
    source_objects = [
        obj for obj in bpy.context.scene.objects if obj.type == "MESH"
    ]
    source_material = next(
        (
            material
            for obj in source_objects
            for material in obj.data.materials
            if material is not None
        ),
        None,
    )
    if source_material is None:
        raise RuntimeError(f"No source material in {source_path}")
    material = source_material.copy()
    material.name = f"{source_path.stem} Source Texture Matte"
    material.use_nodes = True
    for node in material.node_tree.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        roughness = node.inputs.get("Roughness")
        if roughness is not None:
            for link in list(roughness.links):
                material.node_tree.links.remove(link)
            roughness.default_value = MATERIAL_ROUGHNESS[material_class]
        metallic = node.inputs.get("Metallic")
        if metallic is not None:
            for link in list(metallic.links):
                material.node_tree.links.remove(link)
            metallic.default_value = 0.0
        coat = node.inputs.get("Coat Weight")
        if coat is not None:
            for link in list(coat.links):
                material.node_tree.links.remove(link)
            coat.default_value = 0.0
        sheen = node.inputs.get("Sheen Weight")
        if sheen is not None:
            sheen.default_value = (
                0.12 if material_class in {"knit-fuzzy", "tailored-heavy"} else 0.05
            )
    clear_objects()
    return material


def neutral_diagnostic_material() -> bpy.types.Material:
    material = bpy.data.materials.new("Neutral Geometry Diagnostic")
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (0.50, 0.52, 0.54, 1.0)
    principled.inputs["Roughness"].default_value = 0.82
    principled.inputs["Metallic"].default_value = 0.0
    return material


args = parse_args()
if args.surface_mode == "proxy-uv":
    variant = "houdini-floor-v4-proxy"
elif args.compression_mode == "drop-only":
    variant = "houdini-floor-v4-drop"
else:
    variant = "houdini-floor-v4"
output_dir = (
    ROOT / f"public/archive/objects/3d/simulations/{args.object_id}/{variant}"
)
stem = f"{args.object_id}-{variant}"
metadata_path = output_dir / f"{stem}-metadata.json"
if not metadata_path.exists():
    raise FileNotFoundError(metadata_path)
metadata = json.loads(metadata_path.read_text())
frame = metadata["frame"]
source_obj = output_dir / f"{stem}-frame{frame}.obj"
render_suffix = "-neutral" if args.neutral_diagnostic else ""
medium_path = output_dir / f"{stem}{render_suffix}-medium.png"
closeup_path = output_dir / f"{stem}{render_suffix}-closeup.png"
blend_path = output_dir / f"{stem}{render_suffix}-render.blend"
source_glb = ROOT / "public" / metadata["source"].lstrip("/")
material_class = metadata["materialClass"]

source_material = (
    neutral_diagnostic_material()
    if args.neutral_diagnostic
    else copy_source_material(source_glb, material_class)
)
if args.neutral_diagnostic:
    clear_objects()
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
if not all(len(obj.data.uv_layers) > 0 for obj in garment_objects):
    raise RuntimeError("Houdini v4 OBJ lost its UV coordinates")
for garment in garment_objects:
    garment.data.materials.clear()
    garment.data.materials.append(source_material)
    for polygon in garment.data.polygons:
        polygon.use_smooth = True

minimum, maximum = combined_bounds(garment_objects)
extent = maximum - minimum
center = (minimum + maximum) * 0.5
lift = -minimum.z + 0.025
for garment in garment_objects:
    garment.location.z += lift
minimum.z += lift
maximum.z += lift
center.z += lift

floor_material = bpy.data.materials.new("Warm White Floor")
floor_material.use_nodes = True
floor_principled = floor_material.node_tree.nodes.get("Principled BSDF")
floor_principled.inputs["Base Color"].default_value = (0.94, 0.935, 0.92, 1.0)
floor_principled.inputs["Roughness"].default_value = 0.76
floor_size = max(extent.x, extent.y, extent.z) * 24.0
bpy.ops.mesh.primitive_plane_add(
    size=floor_size,
    location=(center.x, center.y, 0.0),
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
scene.world = bpy.data.worlds.new("Soft White Proof World")
scene.world.use_nodes = True
background = scene.world.node_tree.nodes.get("Background")
background.inputs["Color"].default_value = (0.97, 0.97, 0.965, 1.0)
background.inputs["Strength"].default_value = 0.72
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass

camera_data = bpy.data.cameras.new("Floor Proof Camera")
camera_data.type = "ORTHO"
camera = bpy.data.objects.new("Floor Proof Camera", camera_data)
bpy.context.collection.objects.link(camera)
scene.camera = camera

horizontal_extent = max(extent.x, extent.y)
view_extent = max(horizontal_extent, extent.z)
# The medium is a low floor-profile proof. The closeup switches to a steep
# plan-view angle so compression folds and texture distortion can be judged.
camera.location = center + Vector(
    (view_extent * 0.80, -view_extent * 2.75, view_extent * 0.82)
)
light_target = center + Vector((0.0, 0.0, extent.z * 0.08))
add_area_light(
    "Large Key",
    center + Vector((-2.4, -2.8, 4.2)) * view_extent,
    1050.0,
    view_extent * 2.7,
    (1.0, 0.95, 0.90),
    light_target,
)
add_area_light(
    "Soft Fill",
    center + Vector((2.6, -0.8, 2.6)) * view_extent,
    560.0,
    view_extent * 3.0,
    (0.80, 0.88, 1.0),
    light_target,
)
add_area_light(
    "Fold Rim",
    center + Vector((-0.5, 2.8, 2.0)) * view_extent,
    760.0,
    view_extent * 2.2,
    (0.88, 0.91, 1.0),
    light_target,
)

medium_scale = max(horizontal_extent * 1.46, extent.z * 1.18)
render_still(
    camera,
    center,
    medium_scale,
    medium_path,
)
camera.location = center + Vector(
    (view_extent * 0.52, -view_extent * 0.70, view_extent * 3.20)
)
floor_detail_target = center.copy()
floor_detail_target.z = minimum.z + min(
    extent.z * 0.18,
    horizontal_extent * 0.25,
)
render_still(
    camera,
    floor_detail_target,
    max(horizontal_extent * 0.92, extent.z * 0.42),
    closeup_path,
)

bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
render_metadata = {
    "renderer": "Blender Eevee",
    "material": (
        "neutral gray geometry diagnostic"
        if args.neutral_diagnostic
        else "source GLB texture with material-class matte override"
    ),
    "texturePreserved": not args.neutral_diagnostic,
    "uvPreserved": True,
    "surfaceMode": args.surface_mode,
    "compressionMode": args.compression_mode,
    "presentation": "settled floor drape with visible fold and bunching review",
    "resolution": [1280, 1280],
    "medium": f"/{medium_path.relative_to(ROOT / 'public').as_posix()}",
    "closeup": f"/{closeup_path.relative_to(ROOT / 'public').as_posix()}",
    "scene": f"/{blend_path.relative_to(ROOT / 'public').as_posix()}",
    "garmentObjects": len(garment_objects),
    "vertices": sum(len(obj.data.vertices) for obj in garment_objects),
    "polygons": sum(len(obj.data.polygons) for obj in garment_objects),
}
if args.neutral_diagnostic:
    metadata["neutralDiagnostic"] = render_metadata
else:
    metadata["render"] = render_metadata
metadata_path.write_text(f"{json.dumps(metadata, indent=2)}\n")
print(json.dumps(render_metadata, indent=2))
