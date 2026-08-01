"""Export Abby's sparse Blender facial weights for C4D repair.

Run inside Blender with the canonical retarget source open. Coordinates are
written in the C4D object's local-axis convention (X, Y, -Z).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    payload = {"source": bpy.data.filepath, "objects": {}}
    for object_name in ("Face.001", "Eye_Lashes.001"):
        item = bpy.data.objects.get(object_name)
        if item is None or item.type != "MESH":
            raise RuntimeError(f"Missing mesh {object_name}")

        groups = {
            group.index: group.name
            for group in item.vertex_groups
            if group.name.startswith("FACIAL_")
        }
        sparse = {name: [] for name in groups.values()}
        for vertex in item.data.vertices:
            for membership in vertex.groups:
                group_name = groups.get(membership.group)
                if group_name and membership.weight > 0.0:
                    sparse[group_name].append(
                        [vertex.index, round(float(membership.weight), 9)]
                    )
        sparse = {name: values for name, values in sparse.items() if values}
        payload["objects"][object_name] = {
            "vertexCount": len(item.data.vertices),
            "vertices": [
                [
                    round(float(vertex.co.x), 7),
                    round(float(vertex.co.y), 7),
                    round(float(-vertex.co.z), 7),
                ]
                for vertex in item.data.vertices
            ],
            "groups": sparse,
            "groupCount": len(sparse),
            "weightCount": sum(len(values) for values in sparse.values()),
        }

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, separators=(",", ":"))
    print(
        "ABBY_BLENDER_FACE_WEIGHTS="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "output": str(output),
                "objects": {
                    name: {
                        "vertexCount": data["vertexCount"],
                        "groupCount": data["groupCount"],
                        "weightCount": data["weightCount"],
                    }
                    for name, data in payload["objects"].items()
                },
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


main()
