import argparse
import json
import sys

import bpy
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    script_arguments = (
        sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    )
    return parser.parse_args(script_arguments)


def world_bounds(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return {
        "min": [min(point[index] for point in corners) for index in range(3)],
        "max": [max(point[index] for point in corners) for index in range(3)],
    }


args = parse_args()
results = []
for input_path in args.inputs:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=input_path)
    objects = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        objects.append(
            {
                "name": obj.name,
                "vertices": len(obj.data.vertices),
                "polygons": len(obj.data.polygons),
                "bounds": world_bounds(obj),
            }
        )
    results.append({"input": input_path, "objects": objects})

print("PARACOSM_GLTF_COMPONENTS_BEGIN")
print(json.dumps(results, indent=2))
print("PARACOSM_GLTF_COMPONENTS_END")
