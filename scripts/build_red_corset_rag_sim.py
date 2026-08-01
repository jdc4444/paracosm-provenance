import math
import os

import bpy
from mathutils import Vector


ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance"
SOURCE = os.path.join(ROOT, "public/archive/objects/3d/red-corset-top-v1.glb")
OUTPUT = os.path.join(
    ROOT, "public/archive/objects/3d/tests/red-corset-rag-sim"
)
FRAME_END = 90


def set_if_present(target, attribute, value):
    if hasattr(target, attribute):
        setattr(target, attribute, value)


def look_at(obj, point):
    direction = Vector(point) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_material(name, base_color, roughness=0.6, metallic=0.0):
    material = bpy.data.materials.new(name=name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (*base_color, 1.0)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    return material


os.makedirs(OUTPUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SOURCE)

corset = next(obj for obj in bpy.context.scene.objects if obj.type == "MESH")
corset.name = "Red_Corset_Rag_Sim"
bpy.context.view_layer.objects.active = corset
corset.select_set(True)

# The source is a dense Meshy render mesh. Preserve its UV/material, but reduce it
# to a tractable shell for this first cloth experiment.
decimate = corset.modifiers.new(name="Simulation_Decimate", type="DECIMATE")
decimate.ratio = 0.018
decimate.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=decimate.name)

# Lay the upright garment on its back above the collision object.
corset.rotation_euler = (math.radians(90.0), 0.0, math.radians(-7.0))
corset.scale = (1.15, 1.15, 1.15)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
corset.location = (0.0, 0.0, 2.25)

cloth = corset.modifiers.new(name="Corset_Cloth", type="CLOTH")
settings = cloth.settings
settings.quality = 7
settings.mass = 0.32
settings.air_damping = 2.0
set_if_present(settings, "tension_stiffness", 8.0)
set_if_present(settings, "compression_stiffness", 8.0)
set_if_present(settings, "shear_stiffness", 5.0)
set_if_present(settings, "bending_stiffness", 0.12)
set_if_present(settings, "tension_damping", 8.0)
set_if_present(settings, "compression_damping", 8.0)
set_if_present(settings, "shear_damping", 5.0)
set_if_present(settings, "bending_damping", 0.5)
settings.use_sewing_springs = False
settings.vertex_group_mass = ""

collision = cloth.collision_settings
collision.use_collision = True
collision.distance_min = 0.012
collision.collision_quality = 5
collision.use_self_collision = True
collision.self_distance_min = 0.01
collision.self_friction = 8.0

cloth.point_cache.frame_start = 1
cloth.point_cache.frame_end = FRAME_END

# Subtle smoothing stays after the simulation and does not change the solve.
smooth = corset.modifiers.new(name="Post_Sim_Smooth", type="CORRECTIVE_SMOOTH")
smooth.factor = 0.25
smooth.iterations = 2

# Rounded ottoman-like collision object: enough curvature to test whether the
# corset stops behaving like a rigid display form.
bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.55))
prop = bpy.context.active_object
prop.name = "Rounded_Drape_Prop"
prop.scale = (0.72, 0.58, 0.55)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
bevel = prop.modifiers.new(name="Rounded_Edges", type="BEVEL")
bevel.width = 0.24
bevel.segments = 8
bpy.context.view_layer.objects.active = prop
bpy.ops.object.modifier_apply(modifier=bevel.name)
bpy.ops.object.shade_smooth()
prop.data.materials.append(
    add_material("Drape_Prop_Material", (0.18, 0.23, 0.24), roughness=0.82)
)
prop_collision = prop.modifiers.new(name="Collision", type="COLLISION")
prop_collision.settings.thickness_outer = 0.018
set_if_present(prop_collision.settings, "cloth_friction", 8.0)

bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0.0, 0.0, -0.02))
floor = bpy.context.active_object
floor.name = "Floor"
floor.data.materials.append(
    add_material("Floor_Material", (0.055, 0.052, 0.05), roughness=0.72)
)
floor_collision = floor.modifiers.new(name="Collision", type="COLLISION")
floor_collision.settings.thickness_outer = 0.012
set_if_present(floor_collision.settings, "cloth_friction", 10.0)

# Studio cyclorama backdrop.
bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0.0, 2.8, 3.0))
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
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.render.image_settings.color_mode = "RGBA"
scene.world = bpy.data.worlds.new("Rag_Sim_World")
scene.world.color = (0.018, 0.018, 0.022)

# Camera and simple soft lighting.
bpy.ops.object.camera_add(location=(4.2, -5.5, 3.35))
camera = bpy.context.active_object
camera.data.lens = 54
look_at(camera, (0.0, 0.0, 0.8))
scene.camera = camera

for name, location, energy, size, color in (
    ("Key", (-3.3, -3.0, 5.2), 1150.0, 4.0, (1.0, 0.83, 0.72)),
    ("Fill", (3.7, -1.0, 3.1), 800.0, 3.2, (0.62, 0.78, 1.0)),
    ("Rim", (0.0, 3.5, 4.2), 950.0, 2.8, (1.0, 0.42, 0.28)),
):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size
    light.data.color = color
    look_at(light, (0.0, 0.0, 0.75))

# Bake once so the .blend, still and video all use the identical simulation.
scene.frame_set(1)
bpy.context.view_layer.objects.active = corset
corset.select_set(True)
bpy.ops.ptcache.bake_all(bake=True)

bpy.ops.file.pack_all()
blend_path = os.path.join(OUTPUT, "red-corset-rag-sim.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)

scene.frame_set(FRAME_END)
scene.render.filepath = os.path.join(OUTPUT, "red-corset-rag-sim-final.png")
bpy.ops.render.render(write_still=True)

# Export the settled state as a standalone GLB for use in the mockup/object UI.
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated = corset.evaluated_get(depsgraph)
settled_mesh = bpy.data.meshes.new_from_object(
    evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
)
settled = bpy.data.objects.new("Red_Corset_Rag_Settled", settled_mesh)
bpy.context.collection.objects.link(settled)
settled.matrix_world = corset.matrix_world.copy()
for obj in bpy.context.selected_objects:
    obj.select_set(False)
settled.select_set(True)
bpy.context.view_layer.objects.active = settled
bpy.ops.export_scene.gltf(
    filepath=os.path.join(OUTPUT, "red-corset-rag-sim-final.glb"),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
)

# Render a compact review movie after the cached simulation is available.
corset.hide_render = False
settled.hide_render = True
scene.frame_start = 1
scene.frame_end = FRAME_END
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
scene.render.filepath = os.path.join(OUTPUT, "red-corset-rag-sim.mp4")
bpy.ops.render.render(animation=True)

print(
    "RAG_SIM_COMPLETE",
    "source_faces",
    1158560,
    "simulation_faces",
    len(corset.data.polygons),
    "final_faces",
    len(settled_mesh.polygons),
    "output",
    OUTPUT,
)
