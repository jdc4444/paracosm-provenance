"""Export Spin face basis, UV triangles and per-frame shape deformation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--face", default="abby_basemesh_FACE")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    face = bpy.data.objects.get(args.face)
    if face is None or face.type != "MESH":
        raise RuntimeError(f"Missing face mesh {args.face!r}")
    if face.data.shape_keys is None:
        raise RuntimeError("Spin face has no shape keys")

    armature_modifiers = [
        modifier for modifier in face.modifiers if modifier.type == "ARMATURE"
    ]
    modifier_states = [
        (modifier, modifier.show_viewport, modifier.show_render)
        for modifier in armature_modifiers
    ]
    for modifier, _viewport, _render in modifier_states:
        modifier.show_viewport = False
        modifier.show_render = False

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    frames = np.arange(args.start, args.end + 1, dtype=np.int32)
    basis = np.asarray(
        [[point.co.x, point.co.y, point.co.z] for point in face.data.shape_keys.key_blocks[0].data],
        dtype=np.float32,
    )
    positions = np.empty((len(frames), len(basis), 3), dtype=np.float32)
    triangles = None
    triangle_uvs = None
    try:
        for frame_index, frame in enumerate(frames):
            scene.frame_set(int(frame))
            bpy.context.view_layer.update()
            evaluated = face.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
            try:
                if len(mesh.vertices) != len(basis):
                    raise RuntimeError("Face topology changed during evaluation")
                positions[frame_index] = np.asarray(
                    [[vertex.co.x, vertex.co.y, vertex.co.z] for vertex in mesh.vertices],
                    dtype=np.float32,
                )
                if triangles is None:
                    mesh.calc_loop_triangles()
                    uv_layer = mesh.uv_layers.active
                    if uv_layer is None:
                        raise RuntimeError("Source face has no active UV layer")
                    triangles = np.asarray(
                        [triangle.vertices[:] for triangle in mesh.loop_triangles],
                        dtype=np.int32,
                    )
                    triangle_uvs = np.asarray(
                        [
                            [
                                [
                                    uv_layer.data[loop_index].uv.x,
                                    uv_layer.data[loop_index].uv.y,
                                ]
                                for loop_index in triangle.loops
                            ]
                            for triangle in mesh.loop_triangles
                        ],
                        dtype=np.float32,
                    )
            finally:
                evaluated.to_mesh_clear()
    finally:
        for modifier, viewport, render in modifier_states:
            modifier.show_viewport = viewport
            modifier.show_render = render

    np.savez_compressed(
        output,
        frames=frames,
        basis=basis,
        positions=positions,
        triangles=triangles,
        triangle_uvs=triangle_uvs,
    )
    print(
        "ABBY_SPIN_FACE_GEOMETRY="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "output": str(output),
                "frames": [args.start, args.end],
                "points": int(len(basis)),
                "triangles": int(len(triangles)),
                "bytes": output.stat().st_size,
            }
        ),
        flush=True,
    )


main()
