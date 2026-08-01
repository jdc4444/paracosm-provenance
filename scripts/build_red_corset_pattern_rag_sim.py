import math
import os

import bpy
from mathutils import Vector


ROOT = "/Users/alphaone/Documents/Code/paracosm-provenance"
SOURCE_IMAGE = os.path.join(
    ROOT, "public/archive/objects/wardrobe/red-corset-top.png"
)
OUTPUT = os.path.join(
    ROOT, "public/archive/objects/3d/tests/red-corset-pattern-rail-sim"
)
FRAME_END = 72


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


def sample_pixel(pixels, width, height, u, v_from_top):
    x = min(width - 1, max(0, int(u * (width - 1))))
    y = min(height - 1, max(0, int((1.0 - v_from_top) * (height - 1))))
    index = (y * width + x) * 4
    return pixels[index], pixels[index + 1], pixels[index + 2]


def is_garment_pixel(rgb):
    red, green, blue = rgb
    saturation = max(rgb) - min(rgb)
    # The catalog background is neutral white/near-white. Keep saturated red,
    # dark buttons and shaded fabric, while discarding the white cutout.
    return saturation > 0.10 or min(rgb) < 0.52 or (
        red > 0.48 and red > green * 1.18 and red > blue * 1.18
    )


os.makedirs(OUTPUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)

image = bpy.data.images.load(SOURCE_IMAGE, check_existing=False)
width, height = image.size
pixels = list(image.pixels)

# Build a clean, evenly spaced front pattern from the source silhouette. The
# holes in the collar/keyhole remain genuine holes in the simulation mesh.
columns = 72
rows = 96
garment_height = 2.25
garment_width = garment_height * (width / height)
vertices = []
uvs = []
faces = []
vertex_indices = {}


def vertex_for(column, row):
    key = (column, row)
    if key in vertex_indices:
        return vertex_indices[key]
    u = column / columns
    v = row / rows
    x = (u - 0.5) * garment_width
    y = (0.5 - v) * garment_height
    index = len(vertices)
    vertices.append((x, y, 0.0))
    uvs.append((u, 1.0 - v))
    vertex_indices[key] = index
    return index


for row in range(rows):
    for column in range(columns):
        center_u = (column + 0.5) / columns
        center_v = (row + 0.5) / rows
        if not is_garment_pixel(
            sample_pixel(pixels, width, height, center_u, center_v)
        ):
            continue
        faces.append(
            (
                vertex_for(column, row),
                vertex_for(column + 1, row),
                vertex_for(column + 1, row + 1),
                vertex_for(column, row + 1),
            )
        )

mesh = bpy.data.meshes.new("Red_Corset_Pattern_Mesh")
mesh.from_pydata(vertices, [], faces)
mesh.update()

uv_layer = mesh.uv_layers.new(name="UVMap")
for polygon in mesh.polygons:
    for loop_index in polygon.loop_indices:
        vertex_index = mesh.loops[loop_index].vertex_index
        uv_layer.data[loop_index].uv = uvs[vertex_index]

corset = bpy.data.objects.new("Red_Corset_Pattern_Rag", mesh)
bpy.context.collection.objects.link(corset)
corset.location = (0.0, 0.0, 1.58)

material = bpy.data.materials.new(name="Red_Corset_Image_Material")
material.use_nodes = True
nodes = material.node_tree.nodes
links = material.node_tree.links
principled = nodes.get("Principled BSDF")
texture = nodes.new("ShaderNodeTexImage")
texture.image = image
texture.interpolation = "Linear"
links.new(texture.outputs["Color"], principled.inputs["Base Color"])
principled.inputs["Roughness"].default_value = 0.48
principled.inputs["Metallic"].default_value = 0.0
corset.data.materials.append(material)

cloth = corset.modifiers.new(name="Corset_Cloth", type="CLOTH")
settings = cloth.settings
settings.quality = 9
settings.mass = 0.24
settings.air_damping = 2.5
set_if_present(settings, "tension_stiffness", 16.0)
set_if_present(settings, "compression_stiffness", 16.0)
set_if_present(settings, "shear_stiffness", 10.0)
set_if_present(settings, "bending_stiffness", 2.5)
set_if_present(settings, "tension_damping", 8.0)
set_if_present(settings, "compression_damping", 8.0)
set_if_present(settings, "shear_damping", 6.0)
set_if_present(settings, "bending_damping", 1.5)

collision = cloth.collision_settings
collision.use_collision = True
collision.distance_min = 0.012
collision.collision_quality = 6
collision.use_self_collision = False
collision.self_distance_min = 0.014
collision.self_friction = 10.0
cloth.point_cache.frame_start = 1
cloth.point_cache.frame_end = FRAME_END

solidify = corset.modifiers.new(name="Post_Sim_Thickness", type="SOLIDIFY")
solidify.thickness = 0.009
solidify.offset = 0.0

subdivision = corset.modifiers.new(name="Post_Sim_Subdivision", type="SUBSURF")
subdivision.levels = 1
subdivision.render_levels = 1

# A rounded rail/chair-back proxy. It gives the garment a controlled fold line
# and keeps this test focused on whether the fabric can hang naturally.
bpy.ops.mesh.primitive_cylinder_add(
    vertices=64,
    radius=0.28,
    depth=1.36,
    location=(0.0, 0.0, 0.92),
    rotation=(0.0, math.radians(90.0), 0.0),
)
prop = bpy.context.active_object
prop.name = "Rounded_Chair_Back_Proxy"
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
bevel = prop.modifiers.new(name="Rounded_Edges", type="BEVEL")
bevel.width = 0.045
bevel.segments = 4
bpy.context.view_layer.objects.active = prop
bpy.ops.object.modifier_apply(modifier=bevel.name)
bpy.ops.object.shade_smooth()
prop.data.materials.append(
    add_material("Drape_Prop_Material", (0.12, 0.17, 0.18), roughness=0.82)
)
prop_collision = prop.modifiers.new(name="Collision", type="COLLISION")
prop_collision.settings.thickness_outer = 0.018
set_if_present(prop_collision.settings, "cloth_friction", 12.0)

bpy.ops.mesh.primitive_plane_add(size=12.0, location=(0.0, 0.0, -0.02))
floor = bpy.context.active_object
floor.name = "Floor"
floor.data.materials.append(
    add_material("Floor_Material", (0.052, 0.048, 0.045), roughness=0.7)
)
floor_collision = floor.modifiers.new(name="Collision", type="COLLISION")
floor_collision.settings.thickness_outer = 0.012
set_if_present(floor_collision.settings, "cloth_friction", 12.0)

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
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("Pattern_Rag_Sim_World")
scene.world.color = (0.018, 0.018, 0.022)

bpy.ops.object.camera_add(location=(4.0, -5.2, 3.2))
camera = bpy.context.active_object
camera.data.lens = 54
look_at(camera, (0.0, 0.0, 0.72))
scene.camera = camera

for name, location, energy, size, color in (
    ("Key", (-3.4, -3.0, 5.0), 1150.0, 4.0, (1.0, 0.84, 0.74)),
    ("Fill", (3.6, -1.2, 3.2), 760.0, 3.2, (0.62, 0.80, 1.0)),
    ("Rim", (0.0, 3.4, 4.0), 900.0, 2.7, (1.0, 0.36, 0.24)),
):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size
    light.data.color = color
    look_at(light, (0.0, 0.0, 0.75))

scene.frame_set(1)
bpy.context.view_layer.objects.active = corset
corset.select_set(True)
bpy.ops.ptcache.bake_all(bake=True)

bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(
    filepath=os.path.join(OUTPUT, "red-corset-pattern-rail-sim.blend")
)

scene.frame_set(FRAME_END)
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath = os.path.join(
    OUTPUT, "red-corset-pattern-rail-sim-final.png"
)
bpy.ops.render.render(write_still=True)

depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated = corset.evaluated_get(depsgraph)
settled_mesh = bpy.data.meshes.new_from_object(
    evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
)
settled = bpy.data.objects.new("Red_Corset_Pattern_Rag_Settled", settled_mesh)
bpy.context.collection.objects.link(settled)
settled.matrix_world = corset.matrix_world.copy()
for obj in bpy.context.selected_objects:
    obj.select_set(False)
settled.select_set(True)
bpy.context.view_layer.objects.active = settled
bpy.ops.export_scene.gltf(
    filepath=os.path.join(OUTPUT, "red-corset-pattern-rail-sim-final.glb"),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
)

corset.hide_render = False
settled.hide_render = True
scene.frame_set(1)
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
scene.render.filepath = os.path.join(
    OUTPUT, "red-corset-pattern-rail-sim.mp4"
)
bpy.ops.render.render(animation=True)

print(
    "PATTERN_RAG_SIM_COMPLETE",
    "simulation_faces",
    len(mesh.polygons),
    "final_faces",
    len(settled_mesh.polygons),
    "output",
    OUTPUT,
)
