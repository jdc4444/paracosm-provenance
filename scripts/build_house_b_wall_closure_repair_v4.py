import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_source_faithful_repairs import (
    add_box,
    clear_scene,
    export_glb,
    flat_material,
    object_bounds,
    render_preview,
    save_blend,
)


ROOT = Path(__file__).resolve().parent.parent
MODEL_DIRECTORY = ROOT / "public/archive/objects/3d"
SOURCE_GLB = MODEL_DIRECTORY / "house-b-original-v1-max.glb"
OUTPUT_STEM = "house-b-wall-closure-repair-v4"
OUTPUT_GLB = MODEL_DIRECTORY / f"{OUTPUT_STEM}.glb"
OUTPUT_BLEND = MODEL_DIRECTORY / f"{OUTPUT_STEM}.blend"
OUTPUT_POSTER = MODEL_DIRECTORY / f"{OUTPUT_STEM}.png"
REVIEW_DIRECTORY = MODEL_DIRECTORY / f"{OUTPUT_STEM}-review"


def mesh_stats(objects):
    meshes = [item for item in objects if item.type == "MESH"]
    return {
        "meshes": len(meshes),
        "vertices": sum(len(item.data.vertices) for item in meshes),
        "faces": sum(len(item.data.polygons) for item in meshes),
    }


def add_timber_frame_front(material):
    pieces = [
        ("FRONT__BEAM__LEFT", (0.015, 0.020, -0.030), (0.030, 0.020, 0.520)),
        ("FRONT__BEAM__CENTER", (0.170, 0.020, -0.030), (0.026, 0.020, 0.520)),
        ("FRONT__BEAM__RIGHT", (0.325, 0.020, -0.030), (0.030, 0.020, 0.520)),
        ("FRONT__BEAM__LOW", (0.170, 0.019, -0.205), (0.340, 0.022, 0.034)),
        ("FRONT__BEAM__MID", (0.170, 0.019, 0.045), (0.340, 0.022, 0.034)),
        ("FRONT__BEAM__HIGH", (0.170, 0.019, 0.205), (0.340, 0.022, 0.034)),
    ]
    return [
        add_box(name, location, dimensions, material, bevel=0.004)
        for name, location, dimensions in pieces
    ]


def add_timber_frame_side(material):
    pieces = [
        ("SIDE__BEAM__FRONT", (0.375, 0.035, -0.030), (0.020, 0.030, 0.520)),
        ("SIDE__BEAM__CENTER", (0.375, 0.170, -0.030), (0.020, 0.026, 0.520)),
        ("SIDE__BEAM__REAR", (0.375, 0.305, -0.030), (0.020, 0.030, 0.520)),
        ("SIDE__BEAM__LOW", (0.376, 0.170, -0.205), (0.022, 0.300, 0.034)),
        ("SIDE__BEAM__MID", (0.376, 0.170, 0.045), (0.022, 0.300, 0.034)),
        ("SIDE__BEAM__HIGH", (0.376, 0.170, 0.205), (0.022, 0.300, 0.034)),
    ]
    return [
        add_box(name, location, dimensions, material, bevel=0.004)
        for name, location, dimensions in pieces
    ]


def main():
    clear_scene()
    REVIEW_DIRECTORY.mkdir(parents=True, exist_ok=True)

    bpy.ops.import_scene.gltf(filepath=str(SOURCE_GLB))
    imported = list(bpy.context.scene.objects)
    original_meshes = [item for item in imported if item.type == "MESH"]
    for item in original_meshes:
        item.name = "HOUSE_B__ORIGINAL_MESHY_SHELL"
        item["assembly_role"] = "Untouched Original palette v1 Meshy house"

    plaster = flat_material(
        "House B recessed plaster",
        (0.62, 0.50, 0.49),
        roughness=0.72,
    )
    side_plaster = flat_material(
        "House B recessed side plaster",
        (0.48, 0.42, 0.56),
        roughness=0.72,
    )
    timber = flat_material(
        "House B recessed timber",
        (0.145, 0.075, 0.055),
        roughness=0.64,
    )

    repairs = [
        add_box(
            "INFILL__FRONT_CONNECTOR_WALL",
            (0.170, 0.050, -0.030),
            (0.340, 0.060, 0.520),
            plaster,
            bevel=0.008,
        ),
        add_box(
            "INFILL__SIDE_CONNECTOR_WALL",
            (0.345, 0.170, -0.030),
            (0.060, 0.300, 0.520),
            side_plaster,
            bevel=0.008,
        ),
        add_box(
            "INFILL__INNER_CORNER",
            (0.315, 0.080, -0.085),
            (0.100, 0.100, 0.400),
            plaster,
            bevel=0.008,
        ),
    ]
    repairs.extend(add_timber_frame_front(timber))
    repairs.extend(add_timber_frame_side(timber))
    for item in repairs:
        item["assembly_role"] = (
            "Structural wall closure recessed beneath existing roof geometry"
        )
        item["source_asset"] = str(SOURCE_GLB.relative_to(ROOT))

    scene = bpy.context.scene
    scene["asset_name"] = "House B wall closure repair v4"
    scene["base_asset"] = str(SOURCE_GLB.relative_to(ROOT))
    scene["cut1_window_untouched"] = True
    scene["facade_untouched"] = True
    scene["roof_geometry_untouched"] = True
    scene["repair_note"] = (
        "Keeps the Original palette v1 Meshy shell intact. Adds only recessed "
        "wall enclosure and timber framing beneath the overlapping roof volumes "
        "behind the entrance gable, closing the transparent structural void."
    )

    save_blend(OUTPUT_BLEND)
    exportable = original_meshes + repairs
    export_glb(OUTPUT_GLB, exportable)

    views = {
        "front": (0.0, -4.0, 0.30),
        "front-right": (1.45, -3.8, 1.30),
        "high-front-right": (1.70, -3.40, 2.40),
        "right": (4.0, 0.0, 0.45),
        "high-right": (4.0, 0.0, 2.20),
        "rear-right": (2.20, 3.20, 1.60),
    }
    review_images = {}
    all_visible = original_meshes + repairs
    for view, direction in views.items():
        output = REVIEW_DIRECTORY / f"{OUTPUT_STEM}-{view}.png"
        render_preview(
            output,
            all_visible,
            view_direction=direction,
            orthographic_padding=1.10,
        )
        review_images[view] = str(output.relative_to(ROOT))

    OUTPUT_POSTER.write_bytes(
        (
            REVIEW_DIRECTORY
            / f"{OUTPUT_STEM}-high-front-right.png"
        ).read_bytes()
    )

    minimum, maximum = object_bounds(all_visible)
    result = {
        "outputModel": str(OUTPUT_GLB.relative_to(ROOT)),
        "outputBlend": str(OUTPUT_BLEND.relative_to(ROOT)),
        "outputPoster": str(OUTPUT_POSTER.relative_to(ROOT)),
        "reviewImages": review_images,
        "baseModel": str(SOURCE_GLB.relative_to(ROOT)),
        "repairObjects": [item.name for item in repairs],
        "cut1WindowUntouched": True,
        "facadeUntouched": True,
        "roofGeometryUntouched": True,
        "bounds": {
            "min": list(minimum),
            "max": list(maximum),
        },
        "stats": mesh_stats(all_visible),
    }
    print("HOUSE_B_WALL_REPAIR=" + json.dumps(result))


if __name__ == "__main__":
    main()
