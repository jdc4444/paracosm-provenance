import argparse
import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector


FOOTWEAR_IDS = [
    "black-lace-up-platform-boots",
    "red-knee-boots",
    "brown-lace-up-boots",
    "white-mega-platform-sneakers",
    "lavender-check-fuzzy-shoes",
    "green-platform-sneakers",
    "pink-lace-up-boots",
    "black-mary-jane-flats",
    "black-mary-jane-wedges",
    "black-knee-boots",
]
PLATE_IDS = [
    "green-wall-plate",
    "lavender-wall-plate",
    "orange-wall-plate",
    "purple-wall-plate",
]


def clear_scene():
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.materials,
        bpy.data.images,
    ):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def import_glb(file_path):
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(file_path))
    imported = [
        item
        for item in bpy.context.scene.objects
        if item.type in {"MESH", "CURVE", "EMPTY"}
    ]
    for item in imported:
        item.select_set(False)
    return imported


def material(name, color, metallic=0.0, roughness=0.45):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1.0)
    result.use_nodes = True
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return result


def image_material(name, image_path, roughness=0.34):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    nodes = result.node_tree.nodes
    links = result.node_tree.links
    shader = nodes.get("Principled BSDF")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(image_path))
    texture.interpolation = "Linear"
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = 0.05
    return result


def add_box(name, location, dimensions, box_material, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=location)
    item = bpy.context.object
    item.name = name
    item.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        modifier = item.modifiers.new(name="Soft edges", type="BEVEL")
        modifier.width = bevel
        modifier.segments = 3
    item.data.materials.append(box_material)
    return item


def add_text(
    name,
    body,
    location,
    size,
    text_material,
    extrusion=0.008,
    bevel=0.0015,
):
    bpy.ops.object.text_add(
        location=location,
        rotation=(math.pi / 2.0, 0.0, 0.0),
    )
    item = bpy.context.object
    item.name = name
    item.data.body = body
    item.data.align_x = "CENTER"
    item.data.align_y = "CENTER"
    item.data.size = size
    item.data.extrude = extrusion
    item.data.bevel_depth = bevel
    item.data.bevel_resolution = 2
    item.data.materials.append(text_material)
    return item


def object_bounds(objects):
    minimum = Vector((float("inf"),) * 3)
    maximum = Vector((float("-inf"),) * 3)
    for item in objects:
        if item.type not in {"MESH", "CURVE", "FONT"} or item.hide_render:
            continue
        for corner in item.bound_box:
            point = item.matrix_world @ Vector(corner)
            minimum.x = min(minimum.x, point.x)
            minimum.y = min(minimum.y, point.y)
            minimum.z = min(minimum.z, point.z)
            maximum.x = max(maximum.x, point.x)
            maximum.y = max(maximum.y, point.y)
            maximum.z = max(maximum.z, point.z)
    return minimum, maximum


def look_at(item, target):
    direction = Vector(target) - item.location
    item.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def render_preview(
    output_path,
    objects,
    view_direction=(1.5, -3.8, 1.5),
    orthographic_padding=1.22,
):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.render.filepath = str(output_path)
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.look = "AgX - Medium High Contrast"

    minimum, maximum = object_bounds(objects)
    center = (minimum + maximum) * 0.5
    dimensions = maximum - minimum
    scale = max(dimensions.x, dimensions.y, dimensions.z)

    camera_data = bpy.data.cameras.new("Preview Camera")
    camera = bpy.data.objects.new("Preview Camera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(
        dimensions.z * orthographic_padding,
        dimensions.x * orthographic_padding,
        scale * 0.7,
    )
    direction = Vector(view_direction).normalized()
    camera.location = center + direction * max(scale * 3.2, 4.0)
    look_at(camera, center)
    scene.camera = camera

    world = bpy.data.worlds.new("Preview World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.92,
        0.94,
        0.98,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.75
    scene.world = world

    for index, (offset, energy, size) in enumerate(
        [
            ((-3.5, -4.5, 5.0), 850.0, 4.0),
            ((4.5, -2.0, 2.0), 600.0, 3.5),
            ((0.0, 4.0, 4.0), 500.0, 3.0),
        ]
    ):
        light_data = bpy.data.lights.new(f"Preview Light {index}", type="AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = size
        light = bpy.data.objects.new(f"Preview Light {index}", light_data)
        light.location = center + Vector(offset)
        look_at(light, center)
        scene.collection.objects.link(light)

    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)
    for light in [
        item for item in list(bpy.data.objects) if item.name.startswith("Preview Light")
    ]:
        bpy.data.objects.remove(light, do_unlink=True)


def export_glb(output_path, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for item in objects:
        if item.name in bpy.context.scene.objects:
            item.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_materials="EXPORT",
        export_texcoords=True,
        export_normals=True,
        export_yup=True,
    )


def save_editable_blend(output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path), compress=True)


def convert_text_to_mesh(items):
    converted = []
    for item in items:
        if item.type != "FONT":
            converted.append(item)
            continue
        bpy.ops.object.select_all(action="DESELECT")
        item.select_set(True)
        bpy.context.view_layer.objects.active = item
        bpy.ops.object.convert(target="MESH")
        converted.append(bpy.context.object)
    return converted


def add_animatable_key(
    name,
    x,
    y_back,
    z,
    width,
    depth,
    thickness,
    key_material,
    midi_note,
):
    vertices = [
        (-width / 2, -depth, 0),
        (width / 2, -depth, 0),
        (width / 2, 0, 0),
        (-width / 2, 0, 0),
        (-width / 2, -depth, thickness),
        (width / 2, -depth, thickness),
        (width / 2, 0, thickness),
        (-width / 2, 0, thickness),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (4, 0, 3, 7),
    ]
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    item = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(item)
    item.location = (x, y_back, z)
    item.data.materials.append(key_material)
    item["midi_note"] = midi_note
    item["press_rotation_x"] = math.radians(-4.0)
    item["animatable_key"] = True
    modifier = item.modifiers.new(name="Key edge", type="BEVEL")
    modifier.width = min(width * 0.06, 0.0012)
    modifier.segments = 2
    return item


def repair_piano(root):
    model_path = root / "public/archive/objects/3d/piano-v1.glb"
    imported = import_glb(model_path)
    original_meshes = [item for item in imported if item.type == "MESH"]
    white = material("Ivory key", (0.92, 0.9, 0.82), roughness=0.32)
    black = material("Ebony key", (0.018, 0.014, 0.012), roughness=0.24)
    bed = material("Keyboard bed", (0.025, 0.018, 0.015), roughness=0.42)
    add_box(
        "Keyboard bed",
        (0.0, -0.405, -0.045),
        (1.48, 0.29, 0.035),
        bed,
        bevel=0.006,
    )

    white_midi = [
        note for note in range(21, 109) if note % 12 not in {1, 3, 6, 8, 10}
    ]
    black_midi = [
        note for note in range(21, 109) if note % 12 in {1, 3, 6, 8, 10}
    ]
    span = 1.42
    white_width = span / len(white_midi)
    left = -span / 2
    keys = []
    parent = bpy.data.objects.new("Piano Keys - 88 Animatable", None)
    bpy.context.scene.collection.objects.link(parent)
    for index, midi_note in enumerate(white_midi):
        key = add_animatable_key(
            f"WhiteKey_{index + 1:02d}_MIDI_{midi_note}",
            left + white_width * (index + 0.5),
            -0.31,
            -0.025,
            white_width * 0.94,
            0.255,
            0.026,
            white,
            midi_note,
        )
        key.parent = parent
        keys.append(key)
    for index, midi_note in enumerate(black_midi):
        preceding_white = sum(note < midi_note for note in white_midi)
        key = add_animatable_key(
            f"BlackKey_{index + 1:02d}_MIDI_{midi_note}",
            left + white_width * preceding_white,
            -0.305,
            0.001,
            white_width * 0.58,
            0.158,
            0.042,
            black,
            midi_note,
        )
        key.parent = parent
        keys.append(key)

    all_objects = original_meshes + [
        item
        for item in bpy.context.scene.objects
        if item.name == "Keyboard bed" or item.parent == parent
    ]
    source_path = (
        root
        / "public/archive/objects/3d/source/piano-blender-repair-v2.blend"
    )
    save_editable_blend(source_path)
    output_glb = root / "public/archive/objects/3d/piano-v2.glb"
    output_png = root / "public/archive/objects/3d/piano-v2.png"
    export_glb(output_glb, all_objects)
    render_preview(output_png, all_objects, view_direction=(1.7, -4.2, 1.55))
    return {
        "objectId": "piano",
        "model": output_glb.name,
        "thumbnail": output_png.name,
        "source": str(source_path.relative_to(root)),
        "keys": len(keys),
    }


def repair_shop(root, object_id):
    imported = import_glb(
        root / "public/archive/objects/3d" / f"{object_id}-v1.glb"
    )
    original_meshes = [item for item in imported if item.type == "MESH"]
    warm_white = material("Sign ivory", (0.92, 0.9, 0.84), roughness=0.52)
    blue = material("Paracosm blue lettering", (0.08, 0.34, 0.52), roughness=0.35)
    pink = material("Ice cream pink lettering", (0.78, 0.16, 0.28), roughness=0.34)
    black = material("Sign black", (0.015, 0.012, 0.01), roughness=0.42)
    sign_objects = []
    if object_id == "cafe-model":
        sign_objects.extend(
            [
                add_box(
                    "Cafe clean fascia",
                    (0.0, -0.615, 0.55),
                    (1.55, 0.045, 0.39),
                    warm_white,
                    bevel=0.018,
                ),
                add_text(
                    "Cafe PARACOSM text",
                    "PARACOSM",
                    (0.0, -0.642, 0.655),
                    0.145,
                    blue,
                ),
                add_text(
                    "Cafe TEA DREAM text",
                    "TEA DREAM",
                    (0.0, -0.643, 0.475),
                    0.215,
                    blue,
                ),
                add_box(
                    "Cafe OPEN plaque",
                    (0.105, -0.765, -0.235),
                    (0.28, 0.018, 0.12),
                    warm_white,
                    bevel=0.006,
                ),
                add_text(
                    "Cafe OPEN text",
                    "OPEN",
                    (0.105, -0.778, -0.235),
                    0.052,
                    black,
                    extrusion=0.004,
                    bevel=0.0005,
                ),
                add_box(
                    "Cafe COFFEE board",
                    (-0.66, -0.948, -0.36),
                    (0.27, 0.02, 0.31),
                    black,
                    bevel=0.008,
                ),
                add_text(
                    "Cafe COFFEE text",
                    "COFFEE",
                    (-0.66, -0.963, -0.36),
                    0.058,
                    warm_white,
                    extrusion=0.004,
                    bevel=0.0005,
                ),
            ]
        )
    else:
        sign_objects.extend(
            [
                add_box(
                    "Ice cream clean fascia",
                    (0.0, -0.175, 0.50),
                    (1.46, 0.04, 0.42),
                    warm_white,
                    bevel=0.015,
                ),
                add_text(
                    "Ice cream SUZYS text",
                    "SUZY'S",
                    (0.0, -0.201, 0.605),
                    0.105,
                    black,
                    extrusion=0.006,
                ),
                add_text(
                    "Ice cream main text",
                    "ICE CREAM",
                    (0.0, -0.202, 0.435),
                    0.20,
                    pink,
                ),
                add_box(
                    "Ice cream date plaque",
                    (0.0, -0.178, 0.79),
                    (0.54, 0.045, 0.13),
                    blue,
                    bevel=0.014,
                ),
                add_text(
                    "Ice cream date text",
                    "SINCE 1895",
                    (0.0, -0.208, 0.79),
                    0.075,
                    warm_white,
                    extrusion=0.005,
                ),
                add_box(
                    "Ice cream OPEN plaque",
                    (0.0, -0.205, -0.245),
                    (0.18, 0.018, 0.075),
                    warm_white,
                    bevel=0.005,
                ),
                add_text(
                    "Ice cream OPEN text",
                    "OPEN",
                    (0.0, -0.218, -0.245),
                    0.05,
                    black,
                    extrusion=0.004,
                    bevel=0.0005,
                ),
                add_box(
                    "Ice cream left window sign",
                    (-0.49, -0.21, -0.13),
                    (0.43, 0.018, 0.19),
                    black,
                    bevel=0.008,
                ),
                add_text(
                    "Ice cream left window text",
                    "ICE CREAM\nSHOP",
                    (-0.49, -0.223, -0.13),
                    0.052,
                    warm_white,
                    extrusion=0.004,
                    bevel=0.0005,
                ),
                add_box(
                    "Ice cream right window sign",
                    (0.49, -0.21, -0.13),
                    (0.43, 0.018, 0.19),
                    black,
                    bevel=0.008,
                ),
                add_text(
                    "Ice cream right window text",
                    "ICE CREAM\nSHOP",
                    (0.49, -0.223, -0.13),
                    0.052,
                    warm_white,
                    extrusion=0.004,
                    bevel=0.0005,
                ),
            ]
        )

    source_path = (
        root
        / "public/archive/objects/3d/source"
        / f"{object_id}-blender-repair-v2.blend"
    )
    save_editable_blend(source_path)
    converted_signs = convert_text_to_mesh(sign_objects)
    export_objects = original_meshes + converted_signs
    output_glb = root / "public/archive/objects/3d" / f"{object_id}-v2.glb"
    output_png = root / "public/archive/objects/3d" / f"{object_id}-v2.png"
    export_glb(output_glb, export_objects)
    render_preview(output_png, export_objects, view_direction=(1.65, -4.0, 1.55))
    return {
        "objectId": object_id,
        "model": output_glb.name,
        "thumbnail": output_png.name,
        "source": str(source_path.relative_to(root)),
        "editableText": True,
    }


def create_plate_mesh(name, texture_material):
    segments = 128
    rings = [
        (0.0, -0.010),
        (0.68, -0.006),
        (0.82, 0.000),
        (0.91, -0.014),
        (0.97, -0.035),
        (1.0, -0.052),
    ]
    vertices = []
    uvs = []
    for radius, depth in rings:
        for index in range(segments):
            angle = index / segments * math.tau
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            vertices.append((x, depth, z))
            uvs.append((0.5 + x * 0.42, 0.5 + z * 0.42))
    faces = []
    for ring_index in range(len(rings) - 1):
        for index in range(segments):
            next_index = (index + 1) % segments
            a = ring_index * segments + index
            b = ring_index * segments + next_index
            c = (ring_index + 1) * segments + next_index
            d = (ring_index + 1) * segments + index
            faces.append((a, b, c, d))
    back_start = len(vertices)
    for radius, _depth in reversed(rings):
        for index in range(segments):
            angle = index / segments * math.tau
            x = radius * math.cos(angle)
            z = radius * math.sin(angle)
            vertices.append((x, 0.07, z))
            uvs.append((0.5 + x * 0.42, 0.5 + z * 0.42))
    for ring_index in range(len(rings) - 1):
        for index in range(segments):
            next_index = (index + 1) % segments
            a = back_start + ring_index * segments + index
            b = back_start + (ring_index + 1) * segments + index
            c = back_start + (ring_index + 1) * segments + next_index
            d = back_start + ring_index * segments + next_index
            faces.append((a, b, c, d))
    front_outer = (len(rings) - 1) * segments
    back_outer = back_start
    for index in range(segments):
        next_index = (index + 1) % segments
        faces.append(
            (
                front_outer + index,
                front_outer + next_index,
                back_outer + next_index,
                back_outer + index,
            )
        )

    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="Artwork UV")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = uvs[vertex_index]
    item = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(item)
    item.data.materials.append(texture_material)
    bevel = item.modifiers.new(name="Soft ceramic edge", type="BEVEL")
    bevel.width = 0.008
    bevel.segments = 3
    weighted = item.modifiers.new(name="Weighted normals", type="WEIGHTED_NORMAL")
    weighted.keep_sharp = True
    return item


def build_plate(root, object_id):
    clear_scene()
    texture_path = (
        root / "public/archive/objects/split" / f"{object_id}.png"
    )
    plate_material = image_material(
        f"{object_id} artwork",
        texture_path,
        roughness=0.28,
    )
    plate = create_plate_mesh(object_id, plate_material)
    source_path = (
        root
        / "public/archive/objects/3d/source"
        / f"{object_id}-blender-v2.blend"
    )
    save_editable_blend(source_path)
    output_glb = root / "public/archive/objects/3d" / f"{object_id}-v2.glb"
    output_png = root / "public/archive/objects/3d" / f"{object_id}-v2.png"
    export_glb(output_glb, [plate])
    render_preview(
        output_png,
        [plate],
        view_direction=(0.12, -4.0, 0.06),
        orthographic_padding=1.15,
    )
    return {
        "objectId": object_id,
        "model": output_glb.name,
        "thumbnail": output_png.name,
        "source": str(source_path.relative_to(root)),
    }


def split_threshold(mesh_object):
    count = len(mesh_object.data.vertices)
    coordinates = np.empty(count * 3, dtype=np.float32)
    mesh_object.data.vertices.foreach_get("co", coordinates)
    x_values = coordinates[0::3]
    center_a = float(np.quantile(x_values, 0.25))
    center_b = float(np.quantile(x_values, 0.75))
    for _ in range(20):
        midpoint = (center_a + center_b) * 0.5
        group_a = x_values[x_values <= midpoint]
        group_b = x_values[x_values > midpoint]
        if len(group_a) == 0 or len(group_b) == 0:
            break
        next_a = float(group_a.mean())
        next_b = float(group_b.mean())
        if abs(next_a - center_a) + abs(next_b - center_b) < 1e-7:
            center_a, center_b = next_a, next_b
            break
        center_a, center_b = next_a, next_b
    return (center_a + center_b) * 0.5


def delete_vertices_for_side(item, threshold, side, margin):
    count = len(item.data.vertices)
    coordinates = np.empty(count * 3, dtype=np.float32)
    item.data.vertices.foreach_get("co", coordinates)
    x_values = coordinates[0::3]
    if side == "left":
        delete_selection = x_values >= threshold - margin
    else:
        delete_selection = x_values <= threshold + margin
    bpy.ops.object.select_all(action="DESELECT")
    item.select_set(True)
    bpy.context.view_layer.objects.active = item
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    item.data.vertices.foreach_set(
        "select",
        delete_selection.astype(np.bool_),
    )
    item.data.update()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.delete(type="VERT")
    bpy.ops.object.mode_set(mode="OBJECT")
    item.data.update()


def center_and_ground(item):
    minimum, maximum = object_bounds([item])
    center = (minimum + maximum) * 0.5
    item.location -= Vector((center.x, center.y, minimum.z))
    bpy.ops.object.select_all(action="DESELECT")
    item.select_set(True)
    bpy.context.view_layer.objects.active = item
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)


def split_footwear(root, object_id):
    source_suffix = "v2" if object_id == "lavender-check-fuzzy-shoes" else "v1"
    source_path = (
        root
        / "public/archive/objects/3d"
        / f"{object_id}-{source_suffix}.glb"
    )
    imported = import_glb(source_path)
    source_meshes = [item for item in imported if item.type == "MESH"]
    if len(source_meshes) != 1:
        bpy.ops.object.select_all(action="DESELECT")
        for item in source_meshes:
            item.select_set(True)
        bpy.context.view_layer.objects.active = source_meshes[0]
        bpy.ops.object.join()
        source = bpy.context.object
    else:
        source = source_meshes[0]
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    threshold = split_threshold(source)
    source.hide_render = True
    source.hide_viewport = True
    outputs = []
    for side in ("left", "right"):
        item = source.copy()
        item.data = source.data.copy()
        item.name = f"{object_id} {side.title()} Shoe"
        bpy.context.scene.collection.objects.link(item)
        item.hide_render = False
        item.hide_viewport = False
        margin = 0.012 if object_id == "black-knee-boots" else 0.0
        delete_vertices_for_side(item, threshold, side, margin)
        center_and_ground(item)
        item["asset_side"] = side
        item["source_pair"] = source_path.name
        item["midline_artifacts_removed"] = object_id == "black-knee-boots"
        output_glb = (
            root
            / "public/archive/objects/3d"
            / f"{object_id}-v3-{side}.glb"
        )
        output_png = (
            root
            / "public/archive/objects/3d"
            / f"{object_id}-v3-{side}.png"
        )
        export_glb(output_glb, [item])
        render_preview(
            output_png,
            [item],
            view_direction=(1.45, -3.8, 1.2),
            orthographic_padding=1.2,
        )
        outputs.append(
            {
                "side": side,
                "model": output_glb.name,
                "thumbnail": output_png.name,
                "vertices": len(item.data.vertices),
                "faces": len(item.data.polygons),
            }
        )
        bpy.data.objects.remove(item, do_unlink=True)
    return {
        "objectId": object_id,
        "source": source_path.name,
        "threshold": threshold,
        "outputs": outputs,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--mode",
        choices=(
            "manual",
            "cafe",
            "split-one",
            "split-footwear",
            "split-lavender",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--object-id")
    arguments = parser.parse_args(
        [
            argument
            for argument in __import__("sys").argv[
                __import__("sys").argv.index("--") + 1 :
            ]
        ]
    )
    root = Path(arguments.root).resolve()
    results = {
        "schemaVersion": 1,
        "createdAt": "2026-07-28",
        "manualRepairs": [],
        "footwearSplits": [],
    }
    if arguments.mode in {"manual", "all"}:
        results["manualRepairs"].append(repair_piano(root))
        results["manualRepairs"].append(repair_shop(root, "cafe-model"))
        results["manualRepairs"].append(repair_shop(root, "ice-cream-shop"))
        for object_id in PLATE_IDS:
            results["manualRepairs"].append(build_plate(root, object_id))
    if arguments.mode == "cafe":
        results["manualRepairs"].append(repair_shop(root, "cafe-model"))
    if arguments.mode in {"split-footwear", "all"}:
        for object_id in FOOTWEAR_IDS:
            if object_id == "lavender-check-fuzzy-shoes":
                continue
            print(f"[split] {object_id}", flush=True)
            results["footwearSplits"].append(split_footwear(root, object_id))
    if arguments.mode in {"split-lavender", "all"}:
        print("[split] lavender-check-fuzzy-shoes", flush=True)
        results["footwearSplits"].append(
            split_footwear(root, "lavender-check-fuzzy-shoes")
        )
    if arguments.mode == "split-one":
        if arguments.object_id not in FOOTWEAR_IDS:
            raise ValueError("--object-id must name a configured footwear asset.")
        print(f"[split] {arguments.object_id}", flush=True)
        results["footwearSplits"].append(
            split_footwear(root, arguments.object_id)
        )
    output_path = root / "data/blender-object-repairs-20260728.json"
    output_path.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
