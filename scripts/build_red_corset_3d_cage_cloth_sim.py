import math
import os

import bmesh
import bpy
from mathutils import Vector


ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance"
SOURCE = os.path.join(
    ROOT, "public/archive/objects/3d/red-corset-top-v1.glb"
)
STOOL_SOURCE = os.path.join(
    ROOT, "public/archive/objects/3d/piano-stool-v1.glb"
)
SIM_TARGET = os.environ.get("RED_CORSET_SIM_TARGET", "stool")
if SIM_TARGET not in {"stool", "sphere"}:
    raise ValueError(
        "RED_CORSET_SIM_TARGET must be either 'stool' or 'sphere'"
    )
IS_SPHERE = SIM_TARGET == "sphere"
OUTPUT_STEM = (
    "red-corset-3d-sphere-sim"
    if IS_SPHERE
    else "red-corset-3d-stool-sim"
)
OUTPUT = os.path.join(
    ROOT, "public/archive/objects/3d/tests", OUTPUT_STEM
)
FRAME_END = 80


def set_if_present(target, attribute, value):
    if hasattr(target, attribute):
        setattr(target, attribute, value)


def look_at(obj, point):
    obj.rotation_euler = (
        Vector(point) - obj.location
    ).to_track_quat("-Z", "Y").to_euler()


def add_material(name, base_color, roughness=0.6):
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (*base_color, 1.0)
    principled.inputs["Roughness"].default_value = roughness
    return material


def keep_largest_mesh_island(obj):
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

    largest = max(islands, key=len)
    delete_vertices = [vertex for vertex in bm.verts if vertex not in largest]
    if delete_vertices:
        bmesh.ops.delete(bm, geom=delete_vertices, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(islands), len(largest)


os.makedirs(OUTPUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SOURCE)

render_corset = next(
    obj for obj in bpy.context.scene.objects if obj.type == "MESH"
)
render_corset.name = "Red_Corset_Render_Mesh"
bpy.context.view_layer.objects.active = render_corset
render_corset.select_set(True)

# Keep the actual generated geometry, UVs, buttons, collar and sleeves, but
# reduce it enough that a live deformation modifier remains responsive.
render_decimate = render_corset.modifiers.new(
    name="Render_Mesh_Decimate", type="DECIMATE"
)
render_decimate.ratio = 0.14
render_decimate.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=render_decimate.name)

# Build a unified watertight cage from the real garment volume. This removes
# the hundreds of disconnected generated shells that caused the direct cloth
# solve to explode.
cage = render_corset.copy()
cage.data = render_corset.data.copy()
cage.animation_data_clear()
bpy.context.collection.objects.link(cage)
cage.name = "Red_Corset_Unified_Cloth_Cage"

for obj in bpy.context.selected_objects:
    obj.select_set(False)
cage.select_set(True)
bpy.context.view_layer.objects.active = cage
cage.data.remesh_voxel_size = 0.042
cage.data.remesh_voxel_adaptivity = 0.0
bpy.ops.object.voxel_remesh()

island_count, largest_island_vertices = keep_largest_mesh_island(cage)

cage_decimate = cage.modifiers.new(
    name="Cage_Decimate", type="DECIMATE"
)
cage_decimate.ratio = 0.80
cage_decimate.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=cage_decimate.name)

# Keep the fitted bodice and collar more structured while allowing the puff
# sleeves, gathers and upper panels to fold more freely.
structure_group = cage.vertex_groups.new(name="Corset_Structure")
for vertex in cage.data.vertices:
    x, _depth, z = vertex.co
    if z < 0.20:
        weight = 1.0
    elif abs(x) < 0.38:
        weight = 0.82
    elif z > 0.56 and abs(x) < 0.48:
        weight = 0.9
    else:
        weight = 0.12
    structure_group.add([vertex.index], weight, "REPLACE")

# Lay both meshes horizontally above the collision target and apply identical
# transforms.
for obj in (render_corset, cage):
    obj.rotation_euler = (
        math.radians(90.0),
        0.0,
        math.radians(-5.0),
    )
    obj.scale = (1.08, 1.08, 1.08)
    bpy.context.view_layer.objects.active = obj
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.ops.object.transform_apply(
        location=False, rotation=True, scale=True
    )
    obj.location = (0.0, 0.0, 3.08 if IS_SPHERE else 2.56)

# Bind the real corset to the clean cage in the undistorted rest pose.
for obj in bpy.context.selected_objects:
    obj.select_set(False)
render_corset.select_set(True)
bpy.context.view_layer.objects.active = render_corset
surface = render_corset.modifiers.new(
    name="Follow_3D_Cloth_Cage", type="SURFACE_DEFORM"
)
surface.target = cage
surface.falloff = 4.0
bpy.ops.object.surfacedeform_bind(modifier=surface.name)
if not surface.is_bound:
    raise RuntimeError("Surface Deform failed to bind the corset to its cage")

cloth = cage.modifiers.new(name="Corset_3D_Cloth", type="CLOTH")
settings = cloth.settings
settings.quality = 9
settings.mass = 0.28
settings.air_damping = 3.0
set_if_present(settings, "tension_stiffness", 7.0)
set_if_present(settings, "tension_stiffness_max", 30.0)
set_if_present(settings, "compression_stiffness", 7.0)
set_if_present(settings, "compression_stiffness_max", 30.0)
set_if_present(settings, "shear_stiffness", 5.0)
set_if_present(settings, "shear_stiffness_max", 18.0)
set_if_present(settings, "bending_stiffness", 0.32)
set_if_present(settings, "bending_stiffness_max", 8.0)
set_if_present(settings, "tension_damping", 10.0)
set_if_present(settings, "compression_damping", 10.0)
set_if_present(settings, "shear_damping", 8.0)
set_if_present(settings, "bending_damping", 1.4)
settings.vertex_group_structural_stiffness = structure_group.name
settings.vertex_group_shear_stiffness = structure_group.name
settings.vertex_group_bending = structure_group.name

collision = cloth.collision_settings
collision.use_collision = True
collision.distance_min = 0.014
collision.collision_quality = 6
collision.use_self_collision = False
cloth.point_cache.frame_start = 1
cloth.point_cache.frame_end = FRAME_END
cage.display_type = "WIRE"
cage.hide_render = True

if IS_SPHERE:
    # The collider shapes the drape but remains completely invisible in the
    # white-background render.
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=96,
        ring_count=64,
        radius=0.92,
        location=(0.0, 0.0, 1.36),
    )
    prop = bpy.context.active_object
    prop.name = "Invisible_Sphere_Collision"
    bpy.ops.object.shade_smooth()
    prop.hide_render = True
    prop_collision = prop.modifiers.new(name="Collision", type="COLLISION")
    prop_collision.settings.thickness_outer = 0.014
    set_if_present(prop_collision.settings, "cloth_friction", 16.0)
else:
    # Use the existing piano stool as a believable wardrobe-dressing target.
    objects_before_stool = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=STOOL_SOURCE)
    stool_parts = [
        obj
        for obj in bpy.context.scene.objects
        if obj not in objects_before_stool and obj.type == "MESH"
    ]
    stool = max(stool_parts, key=lambda obj: len(obj.data.polygons))
    stool.name = "Piano_Stool_Render"
    stool_decimate = stool.modifiers.new(
        name="Stool_Render_Decimate", type="DECIMATE"
    )
    stool_decimate.ratio = 0.20
    stool_decimate.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = stool
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    stool.select_set(True)
    bpy.ops.object.modifier_apply(modifier=stool_decimate.name)

    stool_world_corners = [
        stool.matrix_world @ Vector(corner) for corner in stool.bound_box
    ]
    stool.location.z -= min(point.z for point in stool_world_corners)

    # A clean seat-only collider avoids the ornate stool geometry creating
    # cloth snags while the render still shows the complete original object.
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64,
        radius=0.72,
        depth=0.34,
        location=(0.0, 0.0, 1.76),
    )
    prop = bpy.context.active_object
    prop.name = "Piano_Stool_Seat_Collision_Proxy"
    bevel = prop.modifiers.new(name="Rounded_Seat_Edge", type="BEVEL")
    bevel.width = 0.10
    bevel.segments = 6
    bpy.context.view_layer.objects.active = prop
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    bpy.ops.object.shade_smooth()
    prop.hide_render = True
    prop_collision = prop.modifiers.new(name="Collision", type="COLLISION")
    prop_collision.settings.thickness_outer = 0.018
    set_if_present(prop_collision.settings, "cloth_friction", 18.0)

bpy.ops.mesh.primitive_plane_add(
    size=40.0 if IS_SPHERE else 12.0,
    location=(0.0, 0.0, -0.02),
)
floor = bpy.context.active_object
floor.name = "Floor"
floor.data.materials.append(
    add_material(
        "Floor_Material",
        (0.94, 0.94, 0.94) if IS_SPHERE else (0.052, 0.048, 0.045),
        roughness=0.72,
    )
)
floor_collision = floor.modifiers.new(name="Collision", type="COLLISION")
floor_collision.settings.thickness_outer = 0.012
set_if_present(floor_collision.settings, "cloth_friction", 12.0)

bpy.ops.mesh.primitive_plane_add(
    size=40.0 if IS_SPHERE else 12.0,
    location=(0.0, 2.9, 3.0),
)
backdrop = bpy.context.active_object
backdrop.name = "Backdrop"
backdrop.rotation_euler = (math.radians(90.0), 0.0, 0.0)
backdrop.data.materials.append(floor.data.materials[0])

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = FRAME_END
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 720
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("Corset_3D_Cloth_World")
scene.world.color = (
    (0.80, 0.80, 0.80) if IS_SPHERE else (0.018, 0.018, 0.022)
)

bpy.ops.object.camera_add(
    location=(3.8, -6.2, 3.05) if IS_SPHERE else (4.2, -6.0, 3.35)
)
camera = bpy.context.active_object
camera.data.lens = 42 if IS_SPHERE else 58
look_at(camera, (0.0, 0.0, 2.10 if IS_SPHERE else 1.10))
scene.camera = camera
if IS_SPHERE:
    # As the corset collapses over the hidden sphere its screen-space footprint
    # shrinks dramatically. A gentle lens push keeps the garment framed without
    # changing the simulated motion.
    for frame, lens in ((1, 42), (16, 52), (32, 76), (48, 92), (80, 100)):
        camera.data.lens = lens
        camera.data.keyframe_insert(data_path="lens", frame=frame)
    if camera.data.animation_data and camera.data.animation_data.action:
        for fcurve in camera.data.animation_data.action.fcurves:
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = "LINEAR"

lights = (
    (
        ("Key", (-3.4, -3.0, 5.0), 1100.0, 4.2, (1.0, 0.97, 0.94)),
        ("Fill", (3.6, -1.2, 3.2), 820.0, 3.8, (0.94, 0.97, 1.0)),
        ("Rim", (0.0, 3.4, 4.0), 760.0, 3.0, (1.0, 0.94, 0.90)),
    )
    if IS_SPHERE
    else (
        ("Key", (-3.4, -3.0, 5.0), 1180.0, 4.0, (1.0, 0.84, 0.74)),
        ("Fill", (3.6, -1.2, 3.2), 780.0, 3.2, (0.62, 0.80, 1.0)),
        ("Rim", (0.0, 3.4, 4.0), 930.0, 2.7, (1.0, 0.36, 0.24)),
    )
)
for name, location, energy, size, color in lights:
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size
    light.data.color = color
    look_at(light, (0.0, 0.0, 1.15))

scene.frame_set(1)
bpy.context.view_layer.objects.active = cage
for obj in bpy.context.selected_objects:
    obj.select_set(False)
cage.select_set(True)
bpy.ops.ptcache.bake_all(bake=True)

bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(
    filepath=os.path.join(OUTPUT, f"{OUTPUT_STEM}.blend")
)

scene.frame_set(FRAME_END)
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath = os.path.join(
    OUTPUT, f"{OUTPUT_STEM}-final.png"
)
bpy.ops.render.render(write_still=True)

scene.frame_set(1)
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
scene.render.filepath = os.path.join(
    OUTPUT, f"{OUTPUT_STEM}.mp4"
)
bpy.ops.render.render(animation=True)

print(
    "CORSET_3D_CAGE_SIM_COMPLETE",
    "render_faces",
    len(render_corset.data.polygons),
    "cage_faces",
    len(cage.data.polygons),
    "cage_islands_before_cleanup",
    island_count,
    "largest_island_vertices",
    largest_island_vertices,
    "target",
    SIM_TARGET,
    "output",
    OUTPUT,
)
