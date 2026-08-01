import json
import math
import sys
from pathlib import Path

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_source_faithful_repairs import (
    clear_scene,
    export_glb,
    flat_material,
    object_bounds,
    render_preview,
    save_blend,
)


ROOT = Path(__file__).resolve().parent.parent
MODEL_DIRECTORY = ROOT / "public/archive/objects/3d"
OUTPUT_STEM = "house-b-clean-component-composite-v3"
OUTPUT_GLB = MODEL_DIRECTORY / f"{OUTPUT_STEM}.glb"
OUTPUT_BLEND = MODEL_DIRECTORY / f"{OUTPUT_STEM}.blend"
OUTPUT_POSTER = MODEL_DIRECTORY / f"{OUTPUT_STEM}.png"
REVIEW_DIRECTORY = MODEL_DIRECTORY / f"{OUTPUT_STEM}-review"

SOURCES = {
    "house": MODEL_DIRECTORY / "house-b-original-v1-max.glb",
    "chimney": MODEL_DIRECTORY / "chimney-v1.glb",
}


def import_module(
    module_id,
    file_path,
    *,
    location=(0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
    rotation=(0.0, 0.0, 0.0),
    role,
):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(file_path))
    imported = [item for item in bpy.data.objects if item not in before]

    root = bpy.data.objects.new(f"MODULE__{module_id.upper()}", None)
    bpy.context.scene.collection.objects.link(root)
    root.location = location
    root.scale = scale
    root.rotation_euler = rotation
    root["module_id"] = module_id
    root["source_asset"] = str(file_path.relative_to(ROOT))
    root["assembly_role"] = role

    imported_set = set(imported)
    for item in imported:
        item["module_id"] = module_id
        item["source_asset"] = str(file_path.relative_to(ROOT))
        item["assembly_role"] = role
        if item.parent not in imported_set:
            world_matrix = item.matrix_world.copy()
            item.parent = root
            item.matrix_world = world_matrix
        if item.type == "MESH":
            item.name = f"{module_id.upper()}__HIGH_RES"

    return {
        "id": module_id,
        "role": role,
        "root": root,
        "objects": imported,
        "source": str(file_path.relative_to(ROOT)),
        "location": list(location),
        "scale": list(scale),
        "rotationDegrees": [math.degrees(value) for value in rotation],
    }


def add_box(name, location, dimensions, material, role):
    bpy.ops.mesh.primitive_cube_add(location=location)
    item = bpy.context.object
    item.name = name
    item.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    item.data.materials.append(material)
    item["assembly_role"] = role
    return item


def remove_generated_chimney(objects):
    removed_faces = 0
    for item in objects:
        if item.type != "MESH":
            continue
        mesh = item.data
        editable = bmesh.new()
        editable.from_mesh(mesh)
        targets = []
        for face in editable.faces:
            center = item.matrix_world @ face.calc_center_median()
            if (
                -0.56 <= center.x <= -0.26
                and 0.02 <= center.y <= 0.40
                and 0.29 <= center.z <= 0.63
            ):
                targets.append(face)
        removed_faces += len(targets)
        bmesh.ops.delete(editable, geom=targets, context="FACES")
        editable.to_mesh(mesh)
        editable.free()
        mesh.update()
    return removed_faces


def mesh_stats(objects):
    meshes = [item for item in objects if item.type == "MESH"]
    return {
        "meshes": len(meshes),
        "vertices": sum(len(item.data.vertices) for item in meshes),
        "faces": sum(len(item.data.polygons) for item in meshes),
    }


def glb_stats(file_path):
    payload = file_path.read_bytes()
    json_length = int.from_bytes(payload[12:16], "little")
    document = json.loads(
        payload[20 : 20 + json_length].rstrip(b"\x00").decode("utf8")
    )
    faces = 0
    vertices = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            position_accessor = document["accessors"][
                primitive["attributes"]["POSITION"]
            ]
            vertices += position_accessor["count"]
            if "indices" in primitive:
                index_count = document["accessors"][
                    primitive["indices"]
                ]["count"]
                faces += index_count // 3
            else:
                faces += position_accessor["count"] // 3
    return {
        "bytes": len(payload),
        "meshes": len(document.get("meshes", [])),
        "faces": faces,
        "vertices": vertices,
        "materials": len(document.get("materials", [])),
        "images": len(document.get("images", [])),
    }


def main():
    clear_scene()
    REVIEW_DIRECTORY.mkdir(parents=True, exist_ok=True)

    modules = [
        import_module(
            "house_base",
            SOURCES["house"],
            role="Original palette v1 Meshy shell; massing and material base",
        )
    ]
    removed_chimney_faces = remove_generated_chimney(
        modules[0]["objects"]
    )
    modules.append(
        import_module(
            "chimney",
            SOURCES["chimney"],
            location=(-0.410, 0.195, 0.460),
            scale=(0.145, 0.145, 0.145),
            role="Source-faithful roof chimney replacing deleted base geometry",
        )
    )

    charcoal = flat_material(
        "House B integration charcoal",
        (0.055, 0.045, 0.055),
        roughness=0.68,
    )
    integration_geometry = [
        add_box(
            "CHIMNEY__FLASHING",
            (-0.410, 0.195, 0.325),
            (0.235, 0.245, 0.035),
            charcoal,
            "Roof flashing under the source-faithful chimney module",
        ),
    ]

    all_objects = list(bpy.context.scene.objects)
    scene = bpy.context.scene
    scene["asset_name"] = "House B clean component composite v3"
    scene["base_asset"] = str(SOURCES["house"].relative_to(ROOT))
    scene["palette"] = "Original palette v1"
    scene["cut1_window_untouched"] = True
    scene["removed_generated_chimney_faces"] = removed_chimney_faces
    scene["assembly_note"] = (
        "The rejected overlay approach was removed. The Cut 1 window and "
        "entrance canopy remain exactly as generated in the approved Original "
        "palette v1 shell. Only the original chimney faces were cut from the "
        "base mesh and replaced by the source-derived high-resolution chimney."
    )

    # Save an editable source scene before export. Module roots and mesh names
    # preserve provenance and make every upgraded component independently
    # replaceable.
    save_blend(OUTPUT_BLEND)

    exportable = [
        item
        for item in bpy.context.scene.objects
        if item.type in {"MESH", "EMPTY"}
    ]
    export_glb(OUTPUT_GLB, exportable)

    views = {
        "front": (0.0, -4.0, 0.25),
        "front-right": (1.45, -3.8, 1.3),
        "front-left": (-1.45, -3.8, 1.3),
        "right": (4.0, 0.0, 0.35),
        "rear": (0.0, 4.0, 0.35),
    }
    outputs = {}
    for view, direction in views.items():
        output_path = REVIEW_DIRECTORY / f"{OUTPUT_STEM}-{view}.png"
        render_preview(
            output_path,
            all_objects,
            view_direction=direction,
            orthographic_padding=1.16,
        )
        outputs[view] = str(output_path.relative_to(ROOT))

    # The front-right review clearly shows the replaced chimney while keeping
    # the untouched Cut 1 facade and entrance canopy visible.
    OUTPUT_POSTER.write_bytes(
        (REVIEW_DIRECTORY / f"{OUTPUT_STEM}-front-right.png").read_bytes()
    )

    minimum, maximum = object_bounds(all_objects)
    result = {
        "outputModel": str(OUTPUT_GLB.relative_to(ROOT)),
        "outputBlend": str(OUTPUT_BLEND.relative_to(ROOT)),
        "outputPoster": str(OUTPUT_POSTER.relative_to(ROOT)),
        "reviewImages": outputs,
        "modules": [
            {
                key: value
                for key, value in module.items()
                if key not in {"root", "objects"}
            }
            for module in modules
        ],
        "removedGeneratedChimneyFaces": removed_chimney_faces,
        "cut1WindowUntouched": True,
        "integrationGeometry": [item.name for item in integration_geometry],
        "bounds": {
            "min": list(minimum),
            "max": list(maximum),
        },
        "blenderStats": mesh_stats(all_objects),
        "stats": glb_stats(OUTPUT_GLB),
    }
    print("HOUSE_B_COMPONENT_COMPOSITE=" + json.dumps(result))


if __name__ == "__main__":
    main()
