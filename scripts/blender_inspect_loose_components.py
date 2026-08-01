import argparse
import json
import sys

import bpy
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
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
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=args.input)

mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
for obj in mesh_objects:
    obj.select_set(False)

for obj in mesh_objects:
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)

components = [
    {
        "name": obj.name,
        "vertices": len(obj.data.vertices),
        "polygons": len(obj.data.polygons),
        "bounds": world_bounds(obj),
    }
    for obj in bpy.context.scene.objects
    if obj.type == "MESH"
]
components.sort(key=lambda item: item["vertices"], reverse=True)

print("PARACOSM_LOOSE_COMPONENTS_BEGIN")
print(
    json.dumps(
        {
            "input": args.input,
            "componentCount": len(components),
            "components": components[:20],
        },
        indent=2,
    )
)
print("PARACOSM_LOOSE_COMPONENTS_END")
