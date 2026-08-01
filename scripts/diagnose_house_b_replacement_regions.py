import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_source_faithful_repairs import (
    clear_scene,
    flat_material,
    render_preview,
)


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "public/archive/objects/3d/house-b-original-v1-max.glb"
OUTPUT = ROOT / "tmp/house-b-region-diagnostics"


def face_world_center(obj, polygon):
    return obj.matrix_world @ polygon.center


def in_canopy_region(point):
    return (
        0.34 <= point.x <= 0.70
        and point.y <= -0.625
        and -0.34 <= point.z <= 0.06
    )


def in_chimney_region(point):
    return (
        -0.56 <= point.x <= -0.26
        and 0.02 <= point.y <= 0.40
        and 0.29 <= point.z <= 0.63
    )


clear_scene()
bpy.ops.import_scene.gltf(filepath=str(SOURCE))
meshes = [item for item in bpy.context.scene.objects if item.type == "MESH"]
canopy_material = flat_material("CANOPY CUT REGION", (1.0, 0.02, 0.01), 0.3)
chimney_material = flat_material("CHIMNEY CUT REGION", (0.02, 1.0, 0.05), 0.3)

counts = {"canopyFaces": 0, "chimneyFaces": 0}
for item in meshes:
    item.data.materials.append(canopy_material)
    canopy_index = len(item.data.materials) - 1
    item.data.materials.append(chimney_material)
    chimney_index = len(item.data.materials) - 1
    for polygon in item.data.polygons:
        center = face_world_center(item, polygon)
        if in_canopy_region(center):
            polygon.material_index = canopy_index
            counts["canopyFaces"] += 1
        elif in_chimney_region(center):
            polygon.material_index = chimney_index
            counts["chimneyFaces"] += 1

OUTPUT.mkdir(parents=True, exist_ok=True)
for view, direction in {
    "front": (0.0, -4.0, 0.25),
    "front-right": (1.45, -3.8, 1.3),
    "right": (4.0, 0.0, 0.35),
}.items():
    render_preview(
        OUTPUT / f"house-b-regions-{view}.png",
        list(bpy.context.scene.objects),
        view_direction=direction,
        orthographic_padding=1.16,
    )

print("HOUSE_B_REGION_DIAGNOSTIC=" + json.dumps(counts))
