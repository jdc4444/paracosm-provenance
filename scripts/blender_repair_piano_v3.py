import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_repair_object_assets import (
    add_animatable_key,
    add_box,
    export_glb,
    import_glb,
    look_at,
    material,
    object_bounds,
    render_preview,
    save_editable_blend,
)


def remove_generated_keyboard(target):
    bpy.ops.mesh.primitive_cube_add(location=(0.0, -0.32, 0.05))
    cutter = bpy.context.object
    cutter.name = "Generated keyboard removal volume"
    cutter.dimensions = (1.50, 0.30, 0.16)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    modifier = target.modifiers.new(
        name="Remove generated keyboard",
        type="BOOLEAN",
    )
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def render_keyboard_detail(
    output_path,
    objects,
    view_direction=(1.05, -3.8, 1.45),
):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 576
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.render.filepath = str(output_path)
    scene.view_settings.look = "AgX - Medium High Contrast"

    camera_data = bpy.data.cameras.new("Keyboard Detail Camera")
    camera = bpy.data.objects.new("Keyboard Detail Camera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 1.72
    focus = Vector((0.0, -0.31, 0.01))
    direction = Vector(view_direction).normalized()
    camera.location = focus + direction * 5.0
    look_at(camera, focus)
    scene.camera = camera

    world = bpy.data.worlds.new("Keyboard Detail World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (
        0.92,
        0.94,
        0.98,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.72
    scene.world = world

    for index, (location, energy, size) in enumerate(
        [
            ((-2.2, -3.2, 3.2), 800.0, 3.2),
            ((3.0, -1.2, 1.8), 500.0, 2.8),
            ((0.0, 2.5, 2.7), 450.0, 2.4),
        ]
    ):
        light_data = bpy.data.lights.new(
            f"Keyboard Detail Light {index}",
            type="AREA",
        )
        light_data.energy = energy
        light_data.size = size
        light = bpy.data.objects.new(
            f"Keyboard Detail Light {index}",
            light_data,
        )
        light.location = focus + Vector(location)
        look_at(light, focus)
        scene.collection.objects.link(light)

    for item in objects:
        item.hide_render = False
    bpy.ops.render.render(write_still=True)


def build_piano(root):
    imported = import_glb(root / "public/archive/objects/3d/piano-v1.glb")
    original_meshes = [item for item in imported if item.type == "MESH"]
    target = max(original_meshes, key=lambda item: len(item.data.polygons))
    remove_generated_keyboard(target)

    ivory = material("Aged ivory key", (0.88, 0.855, 0.76), roughness=0.36)
    ebony = material(
        "Ebony key",
        (0.0018, 0.0012, 0.0010),
        roughness=0.20,
    )
    keywell = material(
        "Recessed black keywell",
        (0.012, 0.009, 0.008),
        roughness=0.50,
    )
    wood = material(
        "Keyboard surround dark walnut",
        (0.026, 0.007, 0.0025),
        roughness=0.36,
    )
    felt = material(
        "Rear key felt",
        (0.018, 0.0012, 0.0010),
        roughness=0.88,
    )

    supports = [
        add_box(
            "Recessed keyboard bed",
            (0.0, -0.32, -0.027),
            (1.46, 0.255, 0.026),
            keywell,
            bevel=0.003,
        ),
        add_box(
            "Front key slip",
            (0.0, -0.445, -0.035),
            (1.48, 0.035, 0.055),
            wood,
            bevel=0.006,
        ),
        add_box(
            "Rear fallboard lip",
            (0.0, -0.181, 0.018),
            (1.48, 0.034, 0.070),
            wood,
            bevel=0.006,
        ),
        add_box(
            "Rear red felt strip",
            (0.0, -0.204, 0.002),
            (1.355, 0.016, 0.018),
            felt,
            bevel=0.002,
        ),
        add_box(
            "Left inner cheek block",
            (-0.705, -0.32, -0.006),
            (0.070, 0.255, 0.066),
            wood,
            bevel=0.006,
        ),
        add_box(
            "Right inner cheek block",
            (0.705, -0.32, -0.006),
            (0.070, 0.255, 0.066),
            wood,
            bevel=0.006,
        ),
    ]

    white_midi = [
        note for note in range(21, 109) if note % 12 not in {1, 3, 6, 8, 10}
    ]
    black_midi = [
        note for note in range(21, 109) if note % 12 in {1, 3, 6, 8, 10}
    ]
    span = 1.34
    white_width = span / len(white_midi)
    left = -span / 2.0
    keys = []
    parent = bpy.data.objects.new("Piano Keys - 88 Animatable v3", None)
    bpy.context.scene.collection.objects.link(parent)

    for index, midi_note in enumerate(white_midi):
        key = add_animatable_key(
            f"WhiteKey_{index + 1:02d}_MIDI_{midi_note}",
            left + white_width * (index + 0.5),
            -0.205,
            -0.013,
            white_width * 0.935,
            0.215,
            0.025,
            ivory,
            midi_note,
        )
        key.parent = parent
        keys.append(key)

    for index, midi_note in enumerate(black_midi):
        preceding_white = sum(note < midi_note for note in white_midi)
        key = add_animatable_key(
            f"BlackKey_{index + 1:02d}_MIDI_{midi_note}",
            left + white_width * preceding_white,
            -0.207,
            0.009,
            white_width * 0.57,
            0.125,
            0.011,
            ebony,
            midi_note,
        )
        key.parent = parent
        keys.append(key)

    all_objects = original_meshes + supports + keys
    source_path = (
        root
        / "public/archive/objects/3d/source/piano-integrated-keyboard-v3.blend"
    )
    save_editable_blend(source_path)
    output_glb = root / "public/archive/objects/3d/piano-v3.glb"
    output_png = root / "public/archive/objects/3d/piano-v3.png"
    detail_png = (
        root
        / "public/archive/objects/3d/source/piano-v3-keyboard-check.png"
    )
    front_check_png = (
        root
        / "public/archive/objects/3d/source/piano-v3-keyboard-front-check.png"
    )
    export_glb(output_glb, all_objects)
    render_preview(
        output_png,
        all_objects,
        view_direction=(1.65, -4.2, 1.45),
    )
    render_keyboard_detail(detail_png, all_objects)
    render_keyboard_detail(
        front_check_png,
        all_objects,
        view_direction=(0.0, -4.0, 0.35),
    )

    return {
        "schemaVersion": 1,
        "createdAt": "2026-07-28",
        "objectId": "piano",
        "model": output_glb.name,
        "thumbnail": output_png.name,
        "source": str(source_path.relative_to(root)),
        "keyboardCheck": str(detail_png.relative_to(root)),
        "keyboardFrontCheck": str(front_check_png.relative_to(root)),
        "keys": len(keys),
        "whiteKeys": len(white_midi),
        "blackKeys": len(black_midi),
        "whiteSpan": span,
        "whiteDepth": 0.215,
        "blackDepth": 0.125,
        "blackHeight": 0.011,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(script_args)
    result = build_piano(args.root.resolve())
    manifest_path = (
        args.root.resolve() / "data/piano-keyboard-repair-20260728.json"
    )
    manifest_path.write_text(json.dumps(result, indent=2) + "\n")
    print("PIANO_REPAIR=" + json.dumps(result))


if __name__ == "__main__":
    main()
