"""Render read-only closeups of the authored Blender Spin face for QA."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
import numpy as np


def evaluated_bounds(obj, depsgraph) -> tuple[Vector, float]:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    try:
        points = np.asarray(
            [
                tuple(evaluated.matrix_world @ vertex.co)
                for vertex in mesh.vertices
            ],
            dtype=np.float64,
        )
        # The delivered source contains a few non-facial outlier vertices.
        # Robust percentiles frame the visible head instead of allowing those
        # outliers to pull the QA camera back to a body-scale crop.
        low = np.percentile(points, 2.0, axis=0)
        high = np.percentile(points, 98.0, axis=0)
        center_np = (low + high) * 0.5
        center = Vector(center_np.tolist())
        radius = float(np.linalg.norm(high - low) * 0.5)
        return center, radius
    finally:
        evaluated.to_mesh_clear()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument("--face", default="abby_basemesh_FACE")
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--padding", type=float, default=1.35)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    scene = bpy.context.scene
    face = bpy.data.objects.get(args.face)
    if face is None or face.type != "MESH":
        raise RuntimeError(f"Missing face object {args.face!r}")
    if scene.camera is None:
        raise RuntimeError("Source scene has no active camera")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    camera = scene.camera.copy()
    camera.data = scene.camera.data.copy()
    camera.name = "CODEX_Spin_Face_QA_Camera"
    scene.collection.objects.link(camera)
    source_camera = scene.camera
    source_camera_world = source_camera.matrix_world.copy()
    camera.parent = None
    for constraint in list(camera.constraints):
        camera.constraints.remove(constraint)
    scene.camera = camera

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.studio_light = "rim.sl"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.background_type = "VIEWPORT"
    scene.display.shading.background_color = (0.06, 0.06, 0.06)
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    # Preserve the authored viewing direction while moving the camera to a
    # face-scale distance for each pose. Blender cameras look along local -Z.
    forward = source_camera_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    camera.rotation_mode = "QUATERNION"
    camera.rotation_quaternion = source_camera_world.to_quaternion()
    camera.data.lens = 70.0
    sensor_width = max(float(camera.data.sensor_width), 1.0e-6)
    half_fov = math.atan(sensor_width / (2.0 * camera.data.lens))

    outputs = []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for frame in sorted(set(args.frames)):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        center, radius = evaluated_bounds(face, depsgraph)
        distance = args.padding * radius / max(math.tan(half_fov), 1.0e-6)
        camera.location = center - forward * distance
        output = output_dir / f"blender_spin_face_f{frame:04d}.png"
        if output.exists():
            raise RuntimeError(f"Refusing to overwrite {output}")
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        outputs.append(str(output))
        print(
            "ABBY_SPIN_FACE_CLOSEUP="
            + json.dumps({"frame": frame, "output": str(output)}),
            flush=True,
        )

    print(
        "ABBY_SPIN_FACE_CLOSEUPS="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "camera": source_camera.name,
                "frames": sorted(set(args.frames)),
                "outputs": outputs,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
