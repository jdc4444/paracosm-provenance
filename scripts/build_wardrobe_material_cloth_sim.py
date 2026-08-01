#!/usr/bin/env python3
"""Build one material-aware Wardrobe cloth solve in Blender."""

import argparse
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector


ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance"
PLAN_PATH = os.path.join(
    ROOT, "data/wardrobe-cloth-simulation-plan-20260728.json"
)
PROOF_MODE = "--proof-static" in sys.argv
FRAME_END = 64 if PROOF_MODE else 48
SIMULATION_ID = "material-aware-sphere-v1"
PROOF_ID = "construction-static-proof-v1"


PRESETS = {
    "rigid-adornment": {
        "mass": 0.42,
        "air": 4.0,
        "tension": 30.0,
        "tension_max": 80.0,
        "compression": 30.0,
        "compression_max": 80.0,
        "shear": 22.0,
        "shear_max": 60.0,
        "bend": 4.0,
        "bend_max": 20.0,
        "damping": 14.0,
        "bend_damping": 4.0,
        "friction": 22.0,
        "quality": 8,
        "render_faces": 100_000,
        "voxel_divisor": 44.0,
    },
    "rigid-corsetry": {
        "mass": 0.35,
        "air": 3.2,
        "tension": 16.0,
        "tension_max": 55.0,
        "compression": 16.0,
        "compression_max": 55.0,
        "shear": 12.0,
        "shear_max": 40.0,
        "bend": 1.8,
        "bend_max": 15.0,
        "damping": 12.0,
        "bend_damping": 3.2,
        "friction": 20.0,
        "quality": 8,
        "render_faces": 100_000,
        "voxel_divisor": 44.0,
    },
    "structured-ruffle": {
        "mass": 0.24,
        "air": 2.6,
        "tension": 6.0,
        "tension_max": 38.0,
        "compression": 5.5,
        "compression_max": 32.0,
        "shear": 4.5,
        "shear_max": 26.0,
        "bend": 0.18,
        "bend_max": 10.0,
        "damping": 9.0,
        "bend_damping": 2.0,
        "friction": 16.0,
        "quality": 8,
        "render_faces": 110_000,
        "voxel_divisor": 46.0,
    },
    "sheer-lightweight": {
        "mass": 0.09,
        "air": 1.8,
        "tension": 3.0,
        "tension_max": 14.0,
        "compression": 3.0,
        "compression_max": 14.0,
        "shear": 2.0,
        "shear_max": 10.0,
        "bend": 0.02,
        "bend_max": 2.0,
        "damping": 5.0,
        "bend_damping": 0.8,
        "friction": 8.0,
        "quality": 7,
        "render_faces": 75_000,
        "voxel_divisor": 46.0,
    },
    "stretch-jersey": {
        "mass": 0.12,
        "air": 1.9,
        "tension": 3.0,
        "tension_max": 18.0,
        "compression": 2.5,
        "compression_max": 14.0,
        "shear": 2.0,
        "shear_max": 12.0,
        "bend": 0.04,
        "bend_max": 3.0,
        "damping": 6.0,
        "bend_damping": 1.0,
        "friction": 11.0,
        "quality": 7,
        "render_faces": 80_000,
        "voxel_divisor": 46.0,
    },
    "knit-fuzzy": {
        "mass": 0.22,
        "air": 2.9,
        "tension": 5.0,
        "tension_max": 20.0,
        "compression": 4.0,
        "compression_max": 18.0,
        "shear": 3.0,
        "shear_max": 15.0,
        "bend": 0.15,
        "bend_max": 4.0,
        "damping": 8.0,
        "bend_damping": 1.6,
        "friction": 16.0,
        "quality": 7,
        "render_faces": 85_000,
        "voxel_divisor": 44.0,
    },
    "satin-fluid": {
        "mass": 0.20,
        "air": 1.5,
        "tension": 4.0,
        "tension_max": 22.0,
        "compression": 4.0,
        "compression_max": 18.0,
        "shear": 3.0,
        "shear_max": 14.0,
        "bend": 0.06,
        "bend_max": 3.0,
        "damping": 5.0,
        "bend_damping": 0.9,
        "friction": 8.0,
        "quality": 7,
        "render_faces": 90_000,
        "voxel_divisor": 46.0,
    },
    "tulle-ruffle": {
        "mass": 0.11,
        "air": 3.2,
        "tension": 3.5,
        "tension_max": 18.0,
        "compression": 3.0,
        "compression_max": 15.0,
        "shear": 2.5,
        "shear_max": 12.0,
        "bend": 0.035,
        "bend_max": 2.5,
        "damping": 6.0,
        "bend_damping": 1.1,
        "friction": 12.0,
        "quality": 7,
        "render_faces": 95_000,
        "voxel_divisor": 46.0,
    },
    "crisp-woven": {
        "mass": 0.28,
        "air": 2.4,
        "tension": 8.0,
        "tension_max": 28.0,
        "compression": 7.0,
        "compression_max": 25.0,
        "shear": 6.0,
        "shear_max": 20.0,
        "bend": 0.70,
        "bend_max": 7.0,
        "damping": 9.0,
        "bend_damping": 2.2,
        "friction": 16.0,
        "quality": 7,
        "render_faces": 95_000,
        "voxel_divisor": 44.0,
    },
    "tailored-heavy": {
        "mass": 0.38,
        "air": 3.0,
        "tension": 12.0,
        "tension_max": 35.0,
        "compression": 10.0,
        "compression_max": 30.0,
        "shear": 8.0,
        "shear_max": 25.0,
        "bend": 1.10,
        "bend_max": 9.0,
        "damping": 11.0,
        "bend_damping": 2.8,
        "friction": 18.0,
        "quality": 8,
        "render_faces": 100_000,
        "voxel_divisor": 44.0,
    },
    "felt-structured": {
        "mass": 0.25,
        "air": 3.0,
        "tension": 18.0,
        "tension_max": 40.0,
        "compression": 18.0,
        "compression_max": 40.0,
        "shear": 14.0,
        "shear_max": 30.0,
        "bend": 2.8,
        "bend_max": 12.0,
        "damping": 12.0,
        "bend_damping": 3.5,
        "friction": 20.0,
        "quality": 8,
        "render_faces": 90_000,
        "voxel_divisor": 44.0,
    },
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--proof-static", action="store_true")
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(arguments)


def set_if_present(target, attribute, value):
    if hasattr(target, attribute):
        setattr(target, attribute, value)


def look_at(obj, point):
    obj.rotation_euler = (
        Vector(point) - obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def add_material(name, base_color, roughness=0.65):
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (*base_color, 1.0)
    principled.inputs["Roughness"].default_value = roughness
    return material


def local_bounds(obj):
    coordinates = [vertex.co for vertex in obj.data.vertices]
    return (
        Vector(
            (
                min(point.x for point in coordinates),
                min(point.y for point in coordinates),
                min(point.z for point in coordinates),
            )
        ),
        Vector(
            (
                max(point.x for point in coordinates),
                max(point.y for point in coordinates),
                max(point.z for point in coordinates),
            )
        ),
    )


def evaluated_world_bounds(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    coordinates = [
        evaluated.matrix_world @ vertex.co
        for vertex in evaluated.data.vertices
    ]
    return (
        Vector(
            (
                min(point.x for point in coordinates),
                min(point.y for point in coordinates),
                min(point.z for point in coordinates),
            )
        ),
        Vector(
            (
                max(point.x for point in coordinates),
                max(point.y for point in coordinates),
                max(point.z for point in coordinates),
            )
        ),
    )


def normalize_mesh(obj, target_extent=2.20):
    minimum, maximum = local_bounds(obj)
    center = (minimum + maximum) * 0.5
    extent = maximum - minimum
    scale = target_extent / max(extent)
    for vertex in obj.data.vertices:
        vertex.co = (vertex.co - center) * scale
    obj.data.update()
    return extent, scale


def keep_significant_islands(obj, maximum_islands=None):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    remaining = set(bm.verts)
    islands = []
    while remaining:
        seed = remaining.pop()
        island = {seed}
        stack = [seed]
        while stack:
            vertex = stack.pop()
            for edge in vertex.link_edges:
                neighbor = edge.other_vert(vertex)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    island.add(neighbor)
                    stack.append(neighbor)
        islands.append(island)

    islands.sort(key=len, reverse=True)
    largest_size = len(islands[0]) if islands else 0
    minimum_size = max(18, int(largest_size * 0.0025))
    retained = [
        island for island in islands if len(island) >= minimum_size
    ]
    if maximum_islands is not None:
        retained = retained[:maximum_islands]
    keep = set().union(*retained)
    delete_vertices = [vertex for vertex in bm.verts if vertex not in keep]
    if delete_vertices:
        bmesh.ops.delete(bm, geom=delete_vertices, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(islands), len(retained)


def structure_weight(mode, point, minimum, maximum):
    height = max(0.0001, maximum.z - minimum.z)
    normalized_z = (point.z - minimum.z) / height
    if mode == "uniform-structured":
        return 1.0
    if mode == "structured-bodice":
        if normalized_z >= 0.58:
            return 1.0
        if normalized_z >= 0.45:
            return 0.55
        return 0.08
    if mode == "structured-waistband":
        if normalized_z >= 0.82:
            return 1.0
        if normalized_z >= 0.68:
            return 0.45
        return 0.08
    if mode == "structured-upper":
        if normalized_z >= 0.62:
            return 0.92
        if normalized_z >= 0.42:
            return 0.40
        return 0.10
    if mode == "structured-cuff":
        edge_distance = min(normalized_z, 1.0 - normalized_z)
        return 0.75 if edge_distance < 0.16 else 0.12
    if mode == "structured-accessory":
        return 0.70
    if mode == "structured-collar":
        if normalized_z >= 0.80:
            return 0.90
        if normalized_z >= 0.60:
            return 0.35
        return 0.08
    return 0.10


def export_settled_glb(render_object, output_path):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = render_object.evaluated_get(depsgraph)
    settled_mesh = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    settled_object = bpy.data.objects.new(
        f"{render_object.name}_Settled_Export", settled_mesh
    )
    bpy.context.collection.objects.link(settled_object)
    settled_object.matrix_world = render_object.matrix_world.copy()
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    settled_object.select_set(True)
    bpy.context.view_layer.objects.active = settled_object
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_materials="EXPORT",
    )
    bpy.data.objects.remove(settled_object, do_unlink=True)


args = parse_args()
with open(PLAN_PATH, "r", encoding="utf-8") as plan_file:
    plan = json.load(plan_file)
entry = next(
    (item for item in plan["objects"] if item["objectId"] == args.object_id),
    None,
)
if entry is None:
    raise ValueError(f"Object {args.object_id} is not cloth eligible.")
if entry["existingSimulation"] and not args.proof_static:
    raise ValueError(
        f"Object {args.object_id} already uses {entry['existingSimulation']}."
    )

object_id = entry["objectId"]
material_class = entry["materialClass"]
structure_mode = entry["structureMode"]
preset = dict(PRESETS[material_class])
proof_overrides = {
    "burgundy-button-corset": {
        "mass": 0.34,
        "air": 3.8,
        "tension": 26.0,
        "tension_max": 72.0,
        "compression": 24.0,
        "compression_max": 68.0,
        "shear": 20.0,
        "shear_max": 58.0,
        "bend": 3.2,
        "bend_max": 24.0,
        "damping": 15.0,
        "bend_damping": 4.0,
        "friction": 22.0,
        "quality": 10,
        "voxel_divisor": 48.0,
    },
    "teal-pleated-skirt": {
        "mass": 0.30,
        "air": 3.4,
        "tension": 24.0,
        "tension_max": 72.0,
        "compression": 22.0,
        "compression_max": 68.0,
        "shear": 18.0,
        "shear_max": 56.0,
        "bend": 5.5,
        "bend_max": 32.0,
        "damping": 16.0,
        "bend_damping": 5.0,
        "friction": 24.0,
        "quality": 10,
        "voxel_divisor": 52.0,
    },
    "white-lilac-corset-dress": {
        "mass": 0.22,
        "air": 3.6,
        "tension": 13.0,
        "tension_max": 48.0,
        "compression": 12.0,
        "compression_max": 44.0,
        "shear": 10.0,
        "shear_max": 36.0,
        "bend": 1.1,
        "bend_max": 14.0,
        "damping": 13.0,
        "bend_damping": 3.0,
        "friction": 20.0,
        "quality": 10,
        "voxel_divisor": 50.0,
    },
    "gray-opera-gloves": {
        "mass": 0.14,
        "air": 2.4,
        "tension": 8.0,
        "tension_max": 28.0,
        "compression": 7.0,
        "compression_max": 24.0,
        "shear": 6.0,
        "shear_max": 20.0,
        "bend": 0.22,
        "bend_max": 5.0,
        "damping": 9.0,
        "bend_damping": 1.8,
        "friction": 15.0,
        "quality": 9,
        "voxel_divisor": 50.0,
    },
    "olive-crochet-bag": {
        "mass": 0.28,
        "air": 3.2,
        "tension": 16.0,
        "tension_max": 48.0,
        "compression": 14.0,
        "compression_max": 44.0,
        "shear": 12.0,
        "shear_max": 38.0,
        "bend": 1.8,
        "bend_max": 14.0,
        "damping": 13.0,
        "bend_damping": 3.2,
        "friction": 22.0,
        "quality": 10,
        "voxel_divisor": 48.0,
    },
}
if args.proof_static:
    preset.update(proof_overrides.get(object_id, {}))
source_model_public = entry["sourceModel"]
source_path = os.path.join(ROOT, "public", source_model_public.lstrip("/"))
output_directory = os.path.join(
    ROOT, "public/archive/objects/3d/simulations", object_id
)
output_stem = (
    f"{object_id}-cloth-static-proof-v1"
    if args.proof_static
    else f"{object_id}-cloth-sphere-v1"
)
proof_frames = {
    "red-corset-top": 20,
    "burgundy-button-corset": 20,
    "teal-pleated-skirt": 28,
    "white-lilac-corset-dress": 30,
    "gray-opera-gloves": 36,
    "olive-crochet-bag": 24,
}
material_proof_frames = {
    "rigid-adornment": 14,
    "rigid-corsetry": 16,
    "structured-ruffle": 20,
    "sheer-lightweight": 20,
    "stretch-jersey": 22,
    "knit-fuzzy": 22,
    "satin-fluid": 20,
    "tulle-ruffle": 22,
    "crisp-woven": 22,
    "tailored-heavy": 18,
    "felt-structured": 16,
}
output_frame = (
    proof_frames.get(object_id, material_proof_frames[material_class])
    if args.proof_static
    else FRAME_END
)
os.makedirs(output_directory, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=source_path)
mesh_objects = [
    obj for obj in bpy.context.scene.objects if obj.type == "MESH"
]
if not mesh_objects:
    raise RuntimeError(f"No mesh imported from {source_path}.")
for obj in bpy.context.scene.objects:
    obj.select_set(False)
for obj in mesh_objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = max(
    mesh_objects, key=lambda obj: len(obj.data.polygons)
)
if len(mesh_objects) > 1:
    bpy.ops.object.join()
render_object = bpy.context.view_layer.objects.active
render_object.name = f"{object_id}_Render_Mesh"
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
source_faces = len(render_object.data.polygons)
source_extent, normalization_scale = normalize_mesh(render_object)

if source_faces > preset["render_faces"]:
    render_decimate = render_object.modifiers.new(
        name="Render_Mesh_Decimate", type="DECIMATE"
    )
    render_decimate.ratio = preset["render_faces"] / source_faces
    render_decimate.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = render_object
    bpy.ops.object.modifier_apply(modifier=render_decimate.name)

render_islands_before_cleanup = None
render_islands_retained = None

cage = render_object.copy()
cage.data = render_object.data.copy()
cage.animation_data_clear()
bpy.context.collection.objects.link(cage)
cage.name = f"{object_id}_Unified_Cloth_Cage"
cage.data.remesh_voxel_size = 2.20 / preset["voxel_divisor"]
cage.data.remesh_voxel_adaptivity = 0.0
for selected in bpy.context.selected_objects:
    selected.select_set(False)
cage.select_set(True)
bpy.context.view_layer.objects.active = cage
bpy.ops.object.voxel_remesh()
paired_keywords = ("glove", "tight", "trouser", "culotte", "sock")
maximum_cage_islands = None
if args.proof_static:
    if any(keyword in object_id for keyword in paired_keywords):
        maximum_cage_islands = 2
    elif material_class in {"structured-ruffle", "tulle-ruffle"}:
        maximum_cage_islands = 4
    elif material_class == "rigid-adornment":
        maximum_cage_islands = 6
    elif structure_mode == "structured-accessory":
        maximum_cage_islands = 3
    else:
        maximum_cage_islands = 2
island_count, retained_islands = keep_significant_islands(
    cage, maximum_islands=maximum_cage_islands
)

cage_decimate = cage.modifiers.new(name="Cage_Decimate", type="DECIMATE")
cage_decimate.ratio = 0.84
cage_decimate.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=cage_decimate.name)

cage_minimum, cage_maximum = local_bounds(cage)
structure_group = cage.vertex_groups.new(name="Construction_Structure")
for vertex in cage.data.vertices:
    structure_group.add(
        [vertex.index],
        structure_weight(
            structure_mode, vertex.co, cage_minimum, cage_maximum
        ),
        "REPLACE",
    )

upright_proof_modes = {
    "structured-bodice",
    "structured-collar",
    "structured-upper",
    "structured-waistband",
    "uniform-structured",
}
is_upright_proof = (
    args.proof_static
    and structure_mode in upright_proof_modes
    and object_id not in {"gray-opera-gloves"}
)
long_axis_yaw = (
    -6.0
    if is_upright_proof
    else 84.0
    if source_extent.z > source_extent.x * 1.60
    else -6.0
)
placement_matrix = Matrix.Rotation(
    math.radians(long_axis_yaw), 4, "Z"
)
if not is_upright_proof:
    placement_matrix = (
        placement_matrix
        @ Matrix.Rotation(math.radians(90.0), 4, "X")
    )
for obj in (render_object, cage):
    for vertex in obj.data.vertices:
        vertex.co = placement_matrix @ vertex.co
    obj.data.update()
    obj.location = (
        (0.0, 0.0, 3.34)
        if is_upright_proof
        else (0.0, 0.0, 2.82)
    )

for selected in bpy.context.selected_objects:
    selected.select_set(False)
render_object.select_set(True)
bpy.context.view_layer.objects.active = render_object
surface = render_object.modifiers.new(
    name="Follow_Material_Cloth_Cage", type="SURFACE_DEFORM"
)
surface.target = cage
surface.falloff = 4.0
bpy.ops.object.surfacedeform_bind(modifier=surface.name)
if not surface.is_bound:
    raise RuntimeError(
        "Surface Deform failed to bind the garment to its cage."
    )

cloth = cage.modifiers.new(name="Material_Aware_Cloth", type="CLOTH")
settings = cloth.settings
settings.quality = preset["quality"]
settings.mass = preset["mass"]
settings.air_damping = preset["air"]
set_if_present(settings, "tension_stiffness", preset["tension"])
set_if_present(
    settings, "tension_stiffness_max", preset["tension_max"]
)
set_if_present(
    settings, "compression_stiffness", preset["compression"]
)
set_if_present(
    settings,
    "compression_stiffness_max",
    preset["compression_max"],
)
set_if_present(settings, "shear_stiffness", preset["shear"])
set_if_present(settings, "shear_stiffness_max", preset["shear_max"])
set_if_present(settings, "bending_stiffness", preset["bend"])
set_if_present(settings, "bending_stiffness_max", preset["bend_max"])
set_if_present(settings, "tension_damping", preset["damping"])
set_if_present(settings, "compression_damping", preset["damping"])
set_if_present(settings, "shear_damping", preset["damping"] * 0.75)
set_if_present(settings, "bending_damping", preset["bend_damping"])
settings.vertex_group_structural_stiffness = structure_group.name
settings.vertex_group_shear_stiffness = structure_group.name
settings.vertex_group_bending = structure_group.name
collision = cloth.collision_settings
collision.use_collision = True
collision.distance_min = 0.014
collision.collision_quality = 5
collision.use_self_collision = False
cloth.point_cache.frame_start = 1
cloth.point_cache.frame_end = output_frame
cage.display_type = "WIRE"
cage.hide_render = True

bpy.ops.mesh.primitive_uv_sphere_add(
    segments=64,
    ring_count=48,
    radius=0.84,
    location=(0.0, 0.0, 1.28),
)
sphere = bpy.context.active_object
sphere.name = "Invisible_Sphere_Collision"
bpy.ops.object.shade_smooth()
sphere.hide_render = True
sphere_collision = sphere.modifiers.new(name="Collision", type="COLLISION")
sphere_collision.settings.thickness_outer = 0.015
set_if_present(
    sphere_collision.settings, "cloth_friction", preset["friction"]
)

bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, -0.02))
floor = bpy.context.active_object
floor.name = "White_Studio_Floor"
floor.data.materials.append(
    add_material("White_Studio_Material", (0.965, 0.965, 0.965), 0.72)
)
floor_collision = floor.modifiers.new(name="Collision", type="COLLISION")
floor_collision.settings.thickness_outer = 0.012
set_if_present(floor_collision.settings, "cloth_friction", 12.0)

bpy.ops.mesh.primitive_plane_add(
    size=40.0, location=(0.0, 3.2, 3.0)
)
backdrop = bpy.context.active_object
backdrop.name = "White_Studio_Backdrop"
backdrop.rotation_euler = (math.radians(90.0), 0.0, 0.0)
backdrop.data.materials.append(floor.data.materials[0])

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = output_frame
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1280 if args.proof_static else 480
scene.render.resolution_y = 1280 if args.proof_static else 480
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.render.image_settings.color_mode = "RGBA"
scene.render.fps = 24
scene.render.image_settings.file_format = "PNG"
scene.world = bpy.data.worlds.new("Wardrobe_Cloth_World")
scene.world.color = (0.82, 0.82, 0.82)
if args.proof_static:
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass

bpy.ops.object.camera_add(
    location=(
        (3.8, -6.2, 3.7)
        if is_upright_proof
        else (3.8, -5.8, 7.2)
        if args.proof_static
        else (3.5, -5.6, 3.20)
    )
)
camera = bpy.context.active_object
camera.data.type = "ORTHO"
camera.data.ortho_scale = 3.05 if args.proof_static else 3.35
look_at(camera, (0.0, 0.0, 1.28))
scene.camera = camera

for name, location, energy, size, color in (
    ("Key", (-3.2, -3.0, 5.2), 1050.0, 4.4, (1.0, 0.97, 0.94)),
    ("Fill", (3.5, -1.0, 3.3), 760.0, 4.0, (0.94, 0.97, 1.0)),
    ("Rim", (0.0, 3.5, 4.2), 720.0, 3.2, (1.0, 0.95, 0.92)),
):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size
    light.data.color = color
    look_at(light, (0.0, 0.0, 1.20))

scene.frame_set(1)
bpy.context.view_layer.objects.active = cage
for selected in bpy.context.selected_objects:
    selected.select_set(False)
cage.select_set(True)
bpy.ops.ptcache.bake_all(bake=True)

scene.frame_set(output_frame)
closeup_path = None
if args.proof_static:
    bpy.context.view_layer.update()
    proof_minimum, proof_maximum = evaluated_world_bounds(render_object)
    proof_center = (proof_minimum + proof_maximum) * 0.5
    proof_extent = proof_maximum - proof_minimum
    look_at(camera, proof_center)
    medium_ortho_scale = max(2.35, max(proof_extent) * 1.32)
    camera.data.ortho_scale = medium_ortho_scale
poster_path = os.path.join(
    output_directory, f"{output_stem}-final.png"
)
scene.render.filepath = poster_path
bpy.ops.render.render(write_still=True)

if args.proof_static:
    closeup_height = {
        "structured-bodice": 0.70,
        "structured-collar": 0.70,
        "structured-upper": 0.66,
        "structured-waistband": 0.70,
        "uniform-structured": 0.56,
    }.get(structure_mode, 0.50)
    closeup_center = proof_center.copy()
    if is_upright_proof:
        closeup_center.z = (
            proof_minimum.z + proof_extent.z * closeup_height
        )
    look_at(camera, closeup_center)
    camera.data.ortho_scale = max(
        0.88,
        min(medium_ortho_scale * 0.48, max(proof_extent) * 0.72),
    )
    closeup_path = os.path.join(
        output_directory, f"{output_stem}-closeup.png"
    )
    scene.render.filepath = closeup_path
    bpy.ops.render.render(write_still=True)
    look_at(camera, proof_center)
    camera.data.ortho_scale = medium_ortho_scale
    scene.render.filepath = poster_path

settled_model_path = os.path.join(
    output_directory, f"{output_stem}-settled.glb"
)
export_settled_glb(
    render_object,
    settled_model_path,
)

bpy.ops.file.pack_all()
blend_path = os.path.join(output_directory, f"{output_stem}.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)

forward_video_path = None
if not args.proof_static:
    scene.frame_set(1)
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "GOOD"
    forward_video_path = os.path.join(
        output_directory, f"{output_stem}.mp4"
    )
    scene.render.filepath = forward_video_path
    bpy.ops.render.render(animation=True)

metadata = {
    "objectId": object_id,
    "simulationId": PROOF_ID if args.proof_static else SIMULATION_ID,
    "outputMode": "static-proof" if args.proof_static else "animation",
    "materialClass": material_class,
    "structureMode": structure_mode,
    "settledFrame": output_frame,
    "sourceModel": source_model_public,
    "sourceFaces": source_faces,
    "renderFaces": len(render_object.data.polygons),
    "cageFaces": len(cage.data.polygons),
    "cageIslandsBeforeCleanup": island_count,
    "cageIslandsRetained": retained_islands,
    "renderIslandsBeforeCleanup": render_islands_before_cleanup,
    "renderIslandsRetained": render_islands_retained,
    "normalizationScale": normalization_scale,
    "sourceExtent": list(source_extent),
    "longAxisYaw": long_axis_yaw,
    "assets": {
        "poster": os.path.relpath(poster_path, ROOT),
        "settledModel": os.path.relpath(settled_model_path, ROOT),
        "scene": os.path.relpath(blend_path, ROOT),
    },
}
if closeup_path:
    metadata["assets"]["closeup"] = os.path.relpath(
        closeup_path, ROOT
    )
if forward_video_path:
    metadata["assets"]["forwardVideo"] = os.path.relpath(
        forward_video_path, ROOT
    )
metadata_path = os.path.join(
    output_directory, f"{output_stem}-metadata.json"
)
with open(metadata_path, "w", encoding="utf-8") as metadata_file:
    json.dump(metadata, metadata_file, indent=2)
    metadata_file.write("\n")

print("WARDROBE_CLOTH_SIM_COMPLETE")
print(json.dumps(metadata))
