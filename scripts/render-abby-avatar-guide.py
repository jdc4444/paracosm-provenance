"""Render high-resolution Abby face studies from the canonical Blender rig.

Run this script through Blender:

    Blender -b <abby.blend> --python render-abby-avatar-guide.py -- \
      --output-dir <directory>

The source file is opened read-only. Cameras, lights, and any repaired image
paths exist only in memory for the duration of the render.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def script_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=3200)
    parser.add_argument("--height", type=int, default=4000)
    parser.add_argument("--frame", type=int, default=0)
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(arguments)


def point_at(scene_object: bpy.types.Object, target: Vector) -> None:
    direction = target - scene_object.location
    scene_object.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_area_light(
    name: str,
    location: tuple[float, float, float],
    energy: float,
    size: float,
    color: tuple[float, float, float],
    target: Vector,
) -> None:
    light_data = bpy.data.lights.new(name=name, type="AREA")
    light_data.energy = energy
    light_data.shape = "DISK"
    light_data.size = size
    light_data.color = color
    light = bpy.data.objects.new(name, light_data)
    bpy.context.collection.objects.link(light)
    light.location = location
    point_at(light, target)


def repair_missing_images(avatar_root: Path) -> None:
    search_roots = [
        avatar_root / "Asset",
        avatar_root / "2_Textures",
        avatar_root / "0_C4D" / "tex",
    ]
    by_name: dict[str, Path] = {}
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for root, _, filenames in os.walk(search_root):
            for filename in filenames:
                by_name.setdefault(filename.casefold(), Path(root) / filename)

    for image in bpy.data.images:
        if image.source != "FILE" or image.has_data:
            continue
        filename = Path(bpy.path.abspath(image.filepath)).name
        replacement = by_name.get(filename.casefold())
        if replacement is None:
            continue
        image.filepath = str(replacement)
        try:
            image.reload()
        except RuntimeError:
            pass


def studio_material(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float,
    metallic: float = 0.0,
) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = color
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    return material


def apply_studio_materials() -> None:
    """Use a legible in-memory material diagnostic for the Blender views."""

    skin = studio_material("ABBY_GUIDE_SKIN", (0.12, 0.033, 0.016, 1), 0.48)
    skin_body = studio_material(
        "ABBY_GUIDE_SKIN_BODY", (0.09, 0.021, 0.012, 1), 0.56
    )
    hair = studio_material("ABBY_GUIDE_HAIR", (0.055, 0.004, 0.002, 1), 0.5)
    lashes = studio_material(
        "ABBY_GUIDE_LASHES", (0.004, 0.002, 0.002, 1), 0.6
    )
    teeth = studio_material("ABBY_GUIDE_TEETH", (0.42, 0.32, 0.22, 1), 0.32)
    gums = studio_material("ABBY_GUIDE_GUMS", (0.09, 0.008, 0.006, 1), 0.42)
    iris = studio_material("ABBY_GUIDE_IRIS", (0.012, 0.002, 0.001, 1), 0.2)
    sclera = studio_material(
        "ABBY_GUIDE_SCLERA", (0.38, 0.32, 0.25, 1), 0.25
    )
    saliva = studio_material("ABBY_GUIDE_SALIVA", (0.07, 0.006, 0.004, 1), 0.16)
    garment = studio_material(
        "ABBY_GUIDE_GARMENT", (0.035, 0.002, 0.006, 1), 0.72
    )
    shoe = studio_material("ABBY_GUIDE_SHOE", (0.08, 0.012, 0.009, 1), 0.64)

    object_materials: dict[str, list[bpy.types.Material]] = {
        "Body.001": [skin_body],
        "Eye_Lashes.001": [lashes, lashes],
        "Face.001": [skin, teeth, gums, iris, iris, sclera, saliva, saliva],
        "Hair": [hair],
        "garments.001": [garment],
        "Shoes.001": [shoe],
    }
    for object_name, materials in object_materials.items():
        scene_object = bpy.data.objects.get(object_name)
        if scene_object is None or not hasattr(scene_object.data, "materials"):
            continue
        slots = scene_object.data.materials
        for index, material in enumerate(materials):
            if index < len(slots):
                slots[index] = material
            else:
                slots.append(material)


def main() -> None:
    args = script_arguments()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(bpy.data.filepath).resolve()
    avatar_root = source_path.parent.parent
    repair_missing_images(avatar_root)
    apply_studio_materials()

    scene = bpy.context.scene
    scene.frame_set(args.frame)
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 28

    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = -0.55

    world = scene.world or bpy.data.worlds.new("ABBY_AVATAR_GUIDE_WORLD")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.006, 0.009, 0.014, 1)
        background.inputs["Strength"].default_value = 0.55

    for scene_object in list(scene.objects):
        if scene_object.type in {"LIGHT", "CAMERA"}:
            bpy.data.objects.remove(scene_object, do_unlink=True)

    target = Vector((0.0, -0.025, 1.485))
    add_area_light(
        "ABBY_GUIDE_KEY",
        (-0.58, -0.62, 2.08),
        42.0,
        0.72,
        (1.0, 0.74, 0.61),
        target,
    )
    add_area_light(
        "ABBY_GUIDE_FILL",
        (0.62, -0.34, 1.55),
        18.0,
        0.62,
        (0.58, 0.72, 1.0),
        target,
    )
    add_area_light(
        "ABBY_GUIDE_RIM",
        (0.42, 0.38, 1.98),
        28.0,
        0.5,
        (1.0, 0.28, 0.16),
        target,
    )
    add_area_light(
        "ABBY_GUIDE_EYE",
        (0.0, -0.46, 1.59),
        7.0,
        0.2,
        (1.0, 0.96, 0.9),
        target,
    )

    camera_data = bpy.data.cameras.new("ABBY_AVATAR_GUIDE_CAMERA")
    camera_data.lens = 72
    camera_data.sensor_width = 36
    camera_data.dof.use_dof = False
    camera = bpy.data.objects.new("ABBY_AVATAR_GUIDE_CAMERA", camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera

    views = {
        "blender-face-front-4k": Vector((0.0, -1.02, 1.49)),
        "blender-face-three-quarter-4k": Vector((0.62, -0.82, 1.51)),
    }
    for filename, location in views.items():
        camera.location = location
        point_at(camera, target)
        scene.render.filepath = str(output_dir / f"{filename}.png")
        bpy.ops.render.render(write_still=True)

    print(
        "ABBY_AVATAR_GUIDE_RENDERED="
        + ",".join(str(output_dir / f"{name}.png") for name in views),
        flush=True,
    )


if __name__ == "__main__":
    main()
