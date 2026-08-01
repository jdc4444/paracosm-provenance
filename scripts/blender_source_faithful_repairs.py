import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def clear_scene():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
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
    return [
        item
        for item in bpy.context.scene.objects
        if item.type in {"MESH", "CURVE", "EMPTY"}
    ]


def object_bounds(objects):
    minimum = Vector((float("inf"),) * 3)
    maximum = Vector((float("-inf"),) * 3)
    for item in objects:
        if item.type not in {"MESH", "CURVE", "FONT"} or item.hide_render:
            continue
        for corner in item.bound_box:
            point = item.matrix_world @ Vector(corner)
            for axis in range(3):
                minimum[axis] = min(minimum[axis], point[axis])
                maximum[axis] = max(maximum[axis], point[axis])
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
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = True
    scene.render.filepath = str(output_path)
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
    camera.location = center + direction * scale * 4.0
    look_at(camera, center)
    scene.camera = camera

    world = bpy.data.worlds.new("Preview World")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.035,
        0.035,
        0.04,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.65

    key_data = bpy.data.lights.new("Key Light", type="AREA")
    key_data.energy = 1100
    key_data.shape = "DISK"
    key_data.size = scale * 2.3
    key = bpy.data.objects.new("Key Light", key_data)
    scene.collection.objects.link(key)
    key.location = center + Vector((-2.8, -3.4, 4.2)) * scale
    look_at(key, center)

    fill_data = bpy.data.lights.new("Fill Light", type="AREA")
    fill_data.energy = 650
    fill_data.size = scale * 2.0
    fill = bpy.data.objects.new("Fill Light", fill_data)
    scene.collection.objects.link(fill)
    fill.location = center + Vector((3.2, -1.6, 1.4)) * scale
    look_at(fill, center)

    rim_data = bpy.data.lights.new("Rim Light", type="AREA")
    rim_data.energy = 850
    rim_data.size = scale * 1.6
    rim = bpy.data.objects.new("Rim Light", rim_data)
    scene.collection.objects.link(rim)
    rim.location = center + Vector((0.5, 2.7, 3.0)) * scale
    look_at(rim, center)

    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)
    bpy.data.lights.remove(key_data, do_unlink=True)
    bpy.data.lights.remove(fill_data, do_unlink=True)
    bpy.data.lights.remove(rim_data, do_unlink=True)


def export_glb(output_path, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for item in objects:
        if item and item.name in bpy.data.objects:
            item.hide_set(False)
            item.hide_render = False
            item.select_set(True)
    bpy.context.view_layer.objects.active = next(
        item for item in objects if item and item.type == "MESH"
    )
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_image_format="AUTO",
    )


def save_blend(output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))


def flat_material(name, color, roughness=0.5):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1.0)
    result.use_nodes = True
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = roughness
    return result


def image_material(name, image_path):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    nodes = result.node_tree.nodes
    links = result.node_tree.links
    shader = nodes.get("Principled BSDF")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = bpy.data.images.load(str(image_path))
    texture.image.pack()
    texture.interpolation = "Linear"
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    shader.inputs["Roughness"].default_value = 0.43
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


def add_image_panel(name, location, dimensions, image_path):
    width, height = dimensions
    vertices = [
        (-width / 2.0, 0.0, -height / 2.0),
        (width / 2.0, 0.0, -height / 2.0),
        (width / 2.0, 0.0, height / 2.0),
        (-width / 2.0, 0.0, height / 2.0),
    ]
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], [(0, 1, 2, 3)])
    mesh.update()
    panel = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(panel)
    panel.location = location
    uv_layer = mesh.uv_layers.new(name="Source artwork UV")
    for loop, uv in zip(
        mesh.polygons[0].loop_indices,
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
    ):
        uv_layer.data[loop].uv = uv
    mesh.materials.append(image_material(f"{name} source artwork", image_path))
    return panel


SHOP_DECALS = {
    "cafe-model": [
        {
            "name": "Source main cafe fascia",
            "crop": "cafe-main-fascia-v3.png",
            "location": (0.0, -0.642, 0.55),
            "dimensions": (1.55, 0.39),
            "cover": ((0.0, -0.617, 0.55), (1.56, 0.045, 0.40), "ivory"),
        },
        {
            "name": "Source cafe OPEN plaque",
            "crop": "cafe-open-plaque-v3.png",
            "location": (0.105, -0.779, -0.235),
            "dimensions": (0.25, 0.10),
            "cover": ((0.105, -0.765, -0.235), (0.27, 0.018, 0.12), "ivory"),
        },
        {
            "name": "Source cafe sidewalk board",
            "crop": "cafe-sidewalk-board-v3.png",
            "location": (-0.66, -0.964, -0.36),
            "dimensions": (0.26, 0.30),
            "cover": ((-0.66, -0.949, -0.36), (0.27, 0.02, 0.31), "black"),
        },
    ],
    "ice-cream-shop": [
        {
            "name": "Source ice cream fascia art",
            "crop": "ice-cream-main-fascia-v3.png",
            "location": (0.0, -0.203, 0.50),
            "dimensions": (1.42, 0.43),
            "cover": ((0.0, -0.177, 0.50), (1.46, 0.04, 0.44), "bluegray"),
        },
        {
            "name": "Source ice cream date plaque",
            "crop": "ice-cream-date-plaque-v3.png",
            "location": (0.0, -0.209, 0.79),
            "dimensions": (0.52, 0.13),
            "cover": ((0.0, -0.18, 0.79), (0.54, 0.045, 0.14), "bluegray"),
        },
        {
            "name": "Source ice cream OPEN plaque",
            "crop": "ice-cream-open-plaque-v3.png",
            "location": (0.0, -0.219, -0.245),
            "dimensions": (0.17, 0.075),
            "cover": ((0.0, -0.206, -0.245), (0.18, 0.018, 0.08), "ivory"),
        },
        {
            "name": "Source left window lettering",
            "crop": "ice-cream-left-window-v3.png",
            "location": (-0.49, -0.223, -0.13),
            "dimensions": (0.43, 0.19),
            "cover": ((-0.49, -0.211, -0.13), (0.44, 0.018, 0.20), "black"),
        },
        {
            "name": "Source right window lettering",
            "crop": "ice-cream-right-window-v3.png",
            "location": (0.49, -0.223, -0.13),
            "dimensions": (0.43, 0.19),
            "cover": ((0.49, -0.211, -0.13), (0.44, 0.018, 0.20), "black"),
        },
    ],
}


def repair_shop_from_source(root, object_id):
    imported = import_glb(
        root / "public/archive/objects/3d" / f"{object_id}-v1.glb"
    )
    original_meshes = [item for item in imported if item.type == "MESH"]
    materials = {
        "ivory": flat_material("Source sign backing ivory", (0.86, 0.84, 0.78)),
        "black": flat_material("Source sign backing black", (0.018, 0.015, 0.014)),
        "bluegray": flat_material(
            "Source sign backing blue gray", (0.45, 0.52, 0.55)
        ),
    }
    repairs = []
    texture_root = root / "public/archive/objects/3d/source-textures"
    for decal in SHOP_DECALS[object_id]:
        cover_location, cover_dimensions, material_key = decal["cover"]
        repairs.append(
            add_box(
                f"{decal['name']} backing",
                cover_location,
                cover_dimensions,
                materials[material_key],
                bevel=0.006,
            )
        )
        repairs.append(
            add_image_panel(
                decal["name"],
                decal["location"],
                decal["dimensions"],
                texture_root / decal["crop"],
            )
        )

    version = "v3"
    source_path = (
        root
        / "public/archive/objects/3d/source"
        / f"{object_id}-source-artwork-repair-{version}.blend"
    )
    save_blend(source_path)
    export_objects = original_meshes + repairs
    output_glb = root / "public/archive/objects/3d" / f"{object_id}-{version}.glb"
    output_png = root / "public/archive/objects/3d" / f"{object_id}-{version}.png"
    export_glb(output_glb, export_objects)
    render_preview(
        output_png,
        export_objects,
        view_direction=(1.15, -4.2, 1.25),
        orthographic_padding=1.15,
    )
    return {
        "objectId": object_id,
        "model": output_glb.name,
        "thumbnail": output_png.name,
        "source": str(source_path.relative_to(root)),
        "sourceDecals": [item["crop"] for item in SHOP_DECALS[object_id]],
    }


def create_profile_cutter(name, rings, radial_segments=64):
    vertices = []
    for z, x_radius, y_radius in rings:
        for segment in range(radial_segments):
            angle = 2.0 * math.pi * segment / radial_segments
            vertices.append(
                (
                    math.cos(angle) * x_radius,
                    math.sin(angle) * y_radius,
                    z,
                )
            )
    faces = []
    for ring_index in range(len(rings) - 1):
        start = ring_index * radial_segments
        next_start = (ring_index + 1) * radial_segments
        for segment in range(radial_segments):
            following = (segment + 1) % radial_segments
            faces.append(
                (
                    start + segment,
                    start + following,
                    next_start + following,
                    next_start + segment,
                )
            )
    bottom_center = len(vertices)
    vertices.append((0.0, 0.0, rings[0][0]))
    top_center = len(vertices)
    vertices.append((0.0, 0.0, rings[-1][0]))
    for segment in range(radial_segments):
        following = (segment + 1) % radial_segments
        faces.append((bottom_center, following, segment))
        top_start = (len(rings) - 1) * radial_segments
        faces.append((top_center, top_start + segment, top_start + following))

    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    cutter = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(cutter)
    return cutter


def create_ellipsoid_cutter(name, location, radii):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64,
        ring_count=32,
        location=location,
    )
    cutter = bpy.context.object
    cutter.name = name
    cutter.scale = radii
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return cutter


def boolean_difference(target, cutter):
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    cutter.select_set(False)
    modifier = target.modifiers.new(name=f"Carve {cutter.name}", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.material_mode = "TRANSFER"
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def interpolate_profile(profiles, t):
    if t <= profiles[0][0]:
        return profiles[0][1], profiles[0][2]
    if t >= profiles[-1][0]:
        return profiles[-1][1], profiles[-1][2]
    for left, right in zip(profiles, profiles[1:]):
        if left[0] <= t <= right[0]:
            blend = (t - left[0]) / (right[0] - left[0])
            return (
                left[1] + (right[1] - left[1]) * blend,
                left[2] + (right[2] - left[2]) * blend,
            )
    raise RuntimeError(f"Could not interpolate profile at {t}")


def create_hollow_torso_shell(
    name,
    profiles,
    bottom_z,
    top_z,
    thickness,
    source_image,
    outer_color,
    interior_color,
    radial_segments=128,
    vertical_segments=24,
):
    vertices = []
    vertex_uvs = []
    maximum_x = max(profile[1] for profile in profiles)
    global_minimum_z = min(bottom_z(theta) for theta in [
        2.0 * math.pi * index / radial_segments
        for index in range(radial_segments)
    ])
    global_maximum_z = max(top_z(theta) for theta in [
        2.0 * math.pi * index / radial_segments
        for index in range(radial_segments)
    ])

    for surface in ("outer", "inner"):
        for level in range(vertical_segments + 1):
            t = level / vertical_segments
            x_radius, y_radius = interpolate_profile(profiles, t)
            if surface == "inner":
                x_radius -= thickness
                y_radius -= thickness
            for segment in range(radial_segments):
                theta = 2.0 * math.pi * segment / radial_segments
                low = bottom_z(theta)
                high = top_z(theta)
                z = low + (high - low) * t
                x = math.cos(theta) * x_radius
                y = math.sin(theta) * y_radius
                vertices.append((x, y, z))
                vertex_uvs.append(
                    (
                        max(0.0, min(1.0, x / (2.0 * maximum_x) + 0.5)),
                        max(
                            0.0,
                            min(
                                1.0,
                                (z - global_minimum_z)
                                / (global_maximum_z - global_minimum_z),
                            ),
                        ),
                    )
                )

    ring_size = radial_segments
    surface_size = (vertical_segments + 1) * ring_size
    faces = []
    material_indices = []

    for surface_index, surface in enumerate(("outer", "inner")):
        surface_offset = surface_index * surface_size
        for level in range(vertical_segments):
            start = surface_offset + level * ring_size
            next_start = start + ring_size
            for segment in range(radial_segments):
                following = (segment + 1) % radial_segments
                if surface == "outer":
                    face = (
                        start + segment,
                        start + following,
                        next_start + following,
                        next_start + segment,
                    )
                    middle_theta = (
                        2.0 * math.pi * (segment + 0.5) / radial_segments
                    )
                    material_index = (
                        0 if math.sin(middle_theta) < 0.2 else 1
                    )
                else:
                    face = (
                        start + segment,
                        next_start + segment,
                        next_start + following,
                        start + following,
                    )
                    material_index = 2
                faces.append(face)
                material_indices.append(material_index)

    inner_offset = surface_size
    for segment in range(radial_segments):
        following = (segment + 1) % radial_segments
        faces.append(
            (
                segment,
                inner_offset + segment,
                inner_offset + following,
                following,
            )
        )
        material_indices.append(2)
        outer_top = vertical_segments * ring_size
        inner_top = inner_offset + vertical_segments * ring_size
        faces.append(
            (
                outer_top + segment,
                outer_top + following,
                inner_top + following,
                inner_top + segment,
            )
        )
        material_indices.append(2)

    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    shell = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(shell)

    source_material = image_material(f"{name} source image", source_image)
    outside_material = flat_material(f"{name} back fabric", outer_color, 0.68)
    inside_material = flat_material(
        f"{name} hollow interior", interior_color, 0.82
    )
    mesh.materials.append(source_material)
    mesh.materials.append(outside_material)
    mesh.materials.append(inside_material)
    for polygon, material_index in zip(mesh.polygons, material_indices):
        polygon.material_index = material_index
        polygon.use_smooth = True

    uv_layer = mesh.uv_layers.new(name="Source image projection")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = vertex_uvs[vertex_index]
    return shell


def add_button(name, location, radius, button_material, hole_material):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48,
        radius=radius,
        depth=radius * 0.34,
        location=location,
        rotation=(math.pi / 2.0, 0.0, 0.0),
    )
    button = bpy.context.object
    button.name = name
    button.data.materials.append(button_material)
    bevel = button.modifiers.new(name="Rounded button rim", type="BEVEL")
    bevel.width = radius * 0.16
    bevel.segments = 3
    holes = []
    for x_offset in (-radius * 0.22, radius * 0.22):
        for z_offset in (-radius * 0.22, radius * 0.22):
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=20,
                radius=radius * 0.08,
                depth=radius * 0.40,
                location=(
                    location[0] + x_offset,
                    location[1] - radius * 0.18,
                    location[2] + z_offset,
                ),
                rotation=(math.pi / 2.0, 0.0, 0.0),
            )
            hole = bpy.context.object
            hole.name = f"{name} hole"
            hole.data.materials.append(hole_material)
            holes.append(hole)
    return [button, *holes]


def add_polyline_curve(name, points, curve_material, bevel_depth=0.014):
    curve_data = bpy.data.curves.new(name=f"{name} Curve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 4
    curve_data.bevel_depth = bevel_depth
    curve_data.bevel_resolution = 3
    spline = curve_data.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, coordinate in zip(spline.bezier_points, points):
        point.co = coordinate
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    curve = bpy.data.objects.new(name, curve_data)
    bpy.context.scene.collection.objects.link(curve)
    curve_data.materials.append(curve_material)
    return curve


def create_elliptical_collar(
    name,
    center_z,
    height,
    outer_radii,
    inner_radii,
    outer_material,
    interior_material,
    radial_segments=96,
):
    vertices = []
    for z in (center_z - height / 2.0, center_z + height / 2.0):
        for x_radius, y_radius in (outer_radii, inner_radii):
            for segment in range(radial_segments):
                theta = 2.0 * math.pi * segment / radial_segments
                vertices.append(
                    (
                        math.cos(theta) * x_radius,
                        math.sin(theta) * y_radius,
                        z,
                    )
                )
    outer_bottom = 0
    inner_bottom = radial_segments
    outer_top = radial_segments * 2
    inner_top = radial_segments * 3
    faces = []
    material_indices = []
    for segment in range(radial_segments):
        following = (segment + 1) % radial_segments
        faces.extend(
            [
                (
                    outer_bottom + segment,
                    outer_bottom + following,
                    outer_top + following,
                    outer_top + segment,
                ),
                (
                    inner_bottom + segment,
                    inner_top + segment,
                    inner_top + following,
                    inner_bottom + following,
                ),
                (
                    outer_top + segment,
                    outer_top + following,
                    inner_top + following,
                    inner_top + segment,
                ),
                (
                    outer_bottom + segment,
                    inner_bottom + segment,
                    inner_bottom + following,
                    outer_bottom + following,
                ),
            ]
        )
        material_indices.extend([0, 1, 1, 1])
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(outer_material)
    mesh.materials.append(interior_material)
    for polygon, material_index in zip(mesh.polygons, material_indices):
        polygon.material_index = material_index
        polygon.use_smooth = True
    collar = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(collar)
    return collar


def create_curved_shoulder_bridge(
    name,
    x_center,
    y_extent,
    width,
    endpoint_z,
    crown_z,
    thickness,
    bridge_material,
    segments=24,
):
    vertices = []
    for index in range(segments + 1):
        fraction = index / segments
        y = -y_extent + 2.0 * y_extent * fraction
        normalized_y = y / y_extent
        center_z = endpoint_z + (crown_z - endpoint_z) * (
            1.0 - normalized_y * normalized_y
        )
        for x_offset, z_offset in (
            (-width / 2.0, -thickness / 2.0),
            (width / 2.0, -thickness / 2.0),
            (width / 2.0, thickness / 2.0),
            (-width / 2.0, thickness / 2.0),
        ):
            vertices.append((x_center + x_offset, y, center_z + z_offset))
    faces = []
    for index in range(segments):
        current = index * 4
        following = (index + 1) * 4
        faces.extend(
            [
                (current, current + 1, following + 1, following),
                (
                    current + 3,
                    following + 3,
                    following + 2,
                    current + 2,
                ),
                (current, following, following + 3, current + 3),
                (
                    current + 1,
                    current + 2,
                    following + 2,
                    following + 1,
                ),
            ]
        )
    faces.extend(
        [
            (0, 3, 2, 1),
            (
                segments * 4,
                segments * 4 + 1,
                segments * 4 + 2,
                segments * 4 + 3,
            ),
        ]
    )
    mesh = bpy.data.meshes.new(f"{name} Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(bridge_material)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    bridge = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(bridge)
    bevel = bridge.modifiers.new(name="Soft shoulder edges", type="BEVEL")
    bevel.width = 0.018
    bevel.segments = 3
    return bridge


CORSET_REPAIRS = {
    "burgundy-button-corset": {
        "outputVersion": "v3",
        "sourceTexture": "burgundy-button-corset-fabric-v3.png",
    },
    "navy-corset-vest": {
        "outputVersion": "v2",
        "sourceTexture": "navy-corset-vest-fabric-v2.png",
    },
}


def repair_corset_shell(root, object_id):
    spec = CORSET_REPAIRS[object_id]
    clear_scene()
    texture_path = (
        root
        / "public/archive/objects/3d/source-textures"
        / spec["sourceTexture"]
    )
    export_objects = []
    if object_id == "burgundy-button-corset":
        shell = create_hollow_torso_shell(
            "Burgundy source-faithful hollow corset",
            profiles=[
                (0.0, 0.48, 0.30),
                (0.32, 0.39, 0.24),
                (0.62, 0.40, 0.25),
                (1.0, 0.59, 0.35),
            ],
            bottom_z=lambda theta: -0.74
            - 0.20 * max(0.0, -math.sin(theta)) ** 4,
            top_z=lambda theta: 0.80
            - 0.20 * max(0.0, -math.sin(theta)) ** 5,
            thickness=0.045,
            source_image=texture_path,
            outer_color=(0.23, 0.012, 0.035),
            interior_color=(0.045, 0.004, 0.012),
        )
        export_objects.append(shell)
        burgundy = flat_material(
            "Burgundy strap material", (0.30, 0.012, 0.045), 0.55
        )
        button_material = flat_material(
            "Burgundy wood buttons", (0.14, 0.025, 0.02), 0.42
        )
        hole_material = flat_material(
            "Burgundy button holes", (0.008, 0.004, 0.004), 0.8
        )
        for index, z in enumerate((0.30, 0.03, -0.25, -0.53), start=1):
            export_objects.extend(
                add_button(
                    f"Burgundy source button {index}",
                    (0.0, -0.348, z),
                    0.055,
                    button_material,
                    hole_material,
                )
            )
        for side in (-1.0, 1.0):
            x = side * 0.46
            export_objects.append(
                add_polyline_curve(
                    f"Burgundy shoulder tie {side:+.0f}",
                    [
                        (x, -0.31, 0.68),
                        (x, -0.32, 0.96),
                        (x + side * 0.02, -0.32, 1.19),
                    ],
                    burgundy,
                    0.012,
                )
            )
            export_objects.append(
                add_polyline_curve(
                    f"Burgundy bow loop {side:+.0f}",
                    [
                        (x, -0.32, 1.16),
                        (x + side * 0.11, -0.33, 1.25),
                        (x + side * 0.18, -0.33, 1.14),
                        (x, -0.32, 1.16),
                        (x - side * 0.10, -0.33, 1.25),
                        (x - side * 0.15, -0.33, 1.14),
                        (x, -0.32, 1.16),
                    ],
                    burgundy,
                    0.012,
                )
            )
    else:
        shell = create_hollow_torso_shell(
            "Navy source-faithful hollow vest body",
            profiles=[
                (0.0, 0.49, 0.31),
                (0.38, 0.38, 0.25),
                (0.72, 0.40, 0.26),
                (1.0, 0.55, 0.32),
            ],
            bottom_z=lambda theta: -0.90
            + 0.03 * math.sin(theta) ** 2,
            top_z=lambda theta: 0.74
            - 0.30 * abs(math.cos(theta)) ** 4,
            thickness=0.045,
            source_image=texture_path,
            outer_color=(0.018, 0.028, 0.085),
            interior_color=(0.004, 0.007, 0.024),
        )
        export_objects.append(shell)
        navy = flat_material("Navy shoulder fabric", (0.018, 0.028, 0.09), 0.64)
        black = flat_material("Navy vest glossy trim", (0.006, 0.007, 0.012), 0.28)
        interior = flat_material(
            "Navy vest interior edge", (0.003, 0.005, 0.018), 0.82
        )
        for side in (-1.0, 1.0):
            export_objects.append(
                create_curved_shoulder_bridge(
                    f"Navy shoulder bridge {side:+.0f}",
                    side * 0.38,
                    0.28,
                    0.18,
                    0.62,
                    0.74,
                    0.075,
                    navy,
                )
            )
        export_objects.append(
            create_elliptical_collar(
                "Navy open collar ring",
                0.78,
                0.18,
                (0.25, 0.21),
                (0.19, 0.15),
                black,
                interior,
            )
        )
        export_objects.append(
            add_box(
                "Navy front placket",
                (0.0, -0.331, -0.04),
                (0.075, 0.025, 1.47),
                black,
                bevel=0.012,
            )
        )
        button_material = flat_material(
            "Navy black buttons", (0.004, 0.004, 0.006), 0.30
        )
        hole_material = flat_material(
            "Navy button holes", (0.001, 0.001, 0.002), 0.9
        )
        for index, z in enumerate((0.62, 0.35, 0.07, -0.22, -0.51), start=1):
            export_objects.extend(
                add_button(
                    f"Navy source button {index}",
                    (0.0, -0.351, z),
                    0.040,
                    button_material,
                    hole_material,
                )
            )

    output_version = spec["outputVersion"]
    source_path = (
        root
        / "public/archive/objects/3d/source"
        / f"{object_id}-true-hollow-{output_version}.blend"
    )
    save_blend(source_path)
    output_glb = (
        root
        / "public/archive/objects/3d"
        / f"{object_id}-{output_version}.glb"
    )
    output_png = (
        root
        / "public/archive/objects/3d"
        / f"{object_id}-{output_version}.png"
    )
    export_glb(output_glb, export_objects)
    render_preview(
        output_png,
        export_objects,
        view_direction=(1.45, -3.8, 1.95),
        orthographic_padding=1.2,
    )
    review_png = (
        root
        / "public/archive/objects/3d/source"
        / f"{object_id}-{output_version}-rear-interior-check.png"
    )
    render_preview(
        review_png,
        export_objects,
        view_direction=(-1.7, 3.6, 2.0),
        orthographic_padding=1.2,
    )
    face_count = sum(
        len(item.data.polygons) for item in export_objects if item.type == "MESH"
    )
    vertex_count = sum(
        len(item.data.vertices) for item in export_objects if item.type == "MESH"
    )
    return {
        "objectId": object_id,
        "model": output_glb.name,
        "thumbnail": output_png.name,
        "source": str(source_path.relative_to(root)),
        "interiorCheck": str(review_png.relative_to(root)),
        "faces": face_count,
        "vertices": vertex_count,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--only",
        choices=[
            "all",
            "shops",
            "corsets",
            "cafe-model",
            "ice-cream-shop",
            "burgundy-button-corset",
            "navy-corset-vest",
        ],
        default="all",
    )
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(script_args)
    root = args.root.resolve()
    results = {"shops": [], "corsets": []}

    if args.only in {"all", "shops", "cafe-model", "ice-cream-shop"}:
        shop_ids = (
            ["cafe-model", "ice-cream-shop"]
            if args.only in {"all", "shops"}
            else [args.only]
        )
        for object_id in shop_ids:
            results["shops"].append(repair_shop_from_source(root, object_id))

    if args.only in {
        "all",
        "corsets",
        "burgundy-button-corset",
        "navy-corset-vest",
    }:
        corset_ids = (
            ["burgundy-button-corset", "navy-corset-vest"]
            if args.only in {"all", "corsets"}
            else [args.only]
        )
        for object_id in corset_ids:
            results["corsets"].append(repair_corset_shell(root, object_id))

    print("REPAIR_RESULTS=" + json.dumps(results))


if __name__ == "__main__":
    main()
