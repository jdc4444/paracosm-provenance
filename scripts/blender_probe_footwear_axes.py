import json
import math
import sys
from pathlib import Path

import bpy
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


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.images,
    ):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def kmeans_score(values):
    if len(values) < 2:
        return {"centers": [0.0, 0.0], "threshold": 0.0, "score": 0.0}
    low = min(values)
    high = max(values)
    center_a = low + (high - low) * 0.25
    center_b = low + (high - low) * 0.75
    for _ in range(24):
        group_a = []
        group_b = []
        midpoint = (center_a + center_b) * 0.5
        for value in values:
            (group_a if value <= midpoint else group_b).append(value)
        if not group_a or not group_b:
            break
        next_a = sum(group_a) / len(group_a)
        next_b = sum(group_b) / len(group_b)
        if abs(next_a - center_a) + abs(next_b - center_b) < 1e-8:
            center_a, center_b = next_a, next_b
            break
        center_a, center_b = next_a, next_b
    group_a = [value for value in values if value <= (center_a + center_b) * 0.5]
    group_b = [value for value in values if value > (center_a + center_b) * 0.5]
    if not group_a or not group_b:
        return {
            "centers": [center_a, center_b],
            "threshold": (center_a + center_b) * 0.5,
            "score": 0.0,
        }

    def standard_deviation(group, center):
        return math.sqrt(
            sum((value - center) ** 2 for value in group) / max(1, len(group))
        )

    spread = standard_deviation(group_a, center_a) + standard_deviation(
        group_b, center_b
    )
    return {
        "centers": [center_a, center_b],
        "threshold": (center_a + center_b) * 0.5,
        "score": abs(center_b - center_a) / max(spread, 1e-8),
        "shares": [len(group_a) / len(values), len(group_b) / len(values)],
    }


def inspect_model(model_path):
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(model_path))
    mesh_objects = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    points = []
    total_vertices = sum(len(item.data.vertices) for item in mesh_objects)
    stride = max(1, total_vertices // 12000)
    global_index = 0
    bounds_min = Vector((float("inf"),) * 3)
    bounds_max = Vector((float("-inf"),) * 3)
    for item in mesh_objects:
        transform = item.matrix_world
        for vertex in item.data.vertices:
            point = transform @ vertex.co
            bounds_min.x = min(bounds_min.x, point.x)
            bounds_min.y = min(bounds_min.y, point.y)
            bounds_min.z = min(bounds_min.z, point.z)
            bounds_max.x = max(bounds_max.x, point.x)
            bounds_max.y = max(bounds_max.y, point.y)
            bounds_max.z = max(bounds_max.z, point.z)
            if global_index % stride == 0:
                points.append((point.x, point.y, point.z))
            global_index += 1
    axes = [kmeans_score([point[index] for point in points]) for index in range(3)]
    return {
        "vertices": total_vertices,
        "objects": len(mesh_objects),
        "bounds": {
            "min": [round(value, 6) for value in bounds_min],
            "max": [round(value, 6) for value in bounds_max],
            "dimensions": [
                round(bounds_max[index] - bounds_min[index], 6)
                for index in range(3)
            ],
        },
        "axes": [
            {
                "axis": axis_name,
                "centers": [round(value, 6) for value in result["centers"]],
                "threshold": round(result["threshold"], 6),
                "score": round(result["score"], 6),
                "shares": [
                    round(value, 4) for value in result.get("shares", [0.0, 0.0])
                ],
            }
            for axis_name, result in zip(("x", "y", "z"), axes)
        ],
    }


def main():
    root = Path(sys.argv[-1]).resolve()
    results = {}
    for object_id in FOOTWEAR_IDS:
        model_path = root / "public/archive/objects/3d" / f"{object_id}-v1.glb"
        results[object_id] = inspect_model(model_path)
        print(json.dumps({object_id: results[object_id]}), flush=True)
    print("RESULTS_BEGIN")
    print(json.dumps(results, indent=2))
    print("RESULTS_END")


if __name__ == "__main__":
    main()
