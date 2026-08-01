#!/usr/bin/env python3
"""Cut a continuous fitted wearable cavity through the Meshy corset exterior."""

from __future__ import annotations

import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


ROOT = Path("/Users/alphaone/Documents/Code/paracosm-provenance")
SOURCE = ROOT / "public/archive/objects/3d/burgundy-button-corset-v4.glb"
OUTPUT = ROOT / "public/archive/objects/3d/burgundy-button-corset-v5.glb"
SCENE = (
    ROOT
    / "public/archive/objects/3d/source"
    / "burgundy-button-corset-meshy-hollow-v5.blend"
)
METADATA = (
    ROOT
    / "data"
    / "burgundy-button-corset-meshy-hollow-v5-20260728.json"
)


def world_bounds(item: bpy.types.Object) -> tuple[Vector, Vector]:
    points = [item.matrix_world @ Vector(corner) for corner in item.bound_box]
    return (
        Vector(
            tuple(min(point[index] for point in points) for index in range(3))
        ),
        Vector(
            tuple(max(point[index] for point in points) for index in range(3))
        ),
    )


def smoothstep(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def fitted_radius(
    t: float,
    bottom: float,
    waist: float,
    top: float,
) -> float:
    if t <= 0.5:
        blend = smoothstep(t * 2.0)
        return bottom + (waist - bottom) * blend
    blend = smoothstep((t - 0.5) * 2.0)
    return waist + (top - waist) * blend


def make_cavity_cutter(
    name: str,
    center: Vector,
    minimum: Vector,
    maximum: Vector,
) -> bpy.types.Object:
    segments = 96
    rings = 31
    margin = (maximum.z - minimum.z) * 0.06
    z_min = minimum.z - margin
    z_max = maximum.z + margin
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    for ring_index in range(rings):
        z_t = ring_index / (rings - 1)
        z = z_min + (z_max - z_min) * z_t
        source_t = max(
            0.0,
            min(1.0, (z - minimum.z) / (maximum.z - minimum.z)),
        )
        # The lower front finishes in a sharp point. Keep the through-cavity
        # narrow there so the cutter opens the hem without breaking through
        # the visible front panel.
        radius_x = fitted_radius(source_t, 0.38, 0.365, 0.64)
        radius_y = fitted_radius(source_t, 0.17, 0.205, 0.365)
        for segment_index in range(segments):
            angle = math.tau * segment_index / segments
            vertices.append(
                (
                    center.x + math.cos(angle) * radius_x,
                    center.y + math.sin(angle) * radius_y,
                    z,
                )
            )

    for ring_index in range(rings - 1):
        for segment_index in range(segments):
            next_segment = (segment_index + 1) % segments
            a = ring_index * segments + segment_index
            b = ring_index * segments + next_segment
            c = (ring_index + 1) * segments + next_segment
            d = (ring_index + 1) * segments + segment_index
            faces.append((a, b, c, d))
    faces.append(tuple(reversed(range(segments))))
    top_start = (rings - 1) * segments
    faces.append(tuple(top_start + index for index in range(segments)))

    mesh = bpy.data.meshes.new(f"{name} mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    cutter = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(cutter)
    return cutter


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(SOURCE))
mesh_objects = [
    item for item in bpy.context.scene.objects if item.type == "MESH"
]
if len(mesh_objects) != 1:
    raise RuntimeError(
        f"Expected one Meshy mesh, found {len(mesh_objects)}"
    )
corset = mesh_objects[0]
minimum, maximum = world_bounds(corset)
center = (minimum + maximum) * 0.5
before_faces = len(corset.data.polygons)
before_vertices = len(corset.data.vertices)

cutter = make_cavity_cutter("Fitted wearable cavity cutter", center, minimum, maximum)
bpy.context.view_layer.objects.active = corset
corset.select_set(True)
modifier = corset.modifiers.new("Open the top and lower hem", type="BOOLEAN")
modifier.operation = "DIFFERENCE"
modifier.solver = "EXACT"
modifier.object = cutter
if hasattr(modifier, "use_hole_tolerant"):
    modifier.use_hole_tolerant = True
bpy.ops.object.modifier_apply(modifier=modifier.name)
bpy.data.objects.remove(cutter, do_unlink=True)

mesh = corset.data
editable = bmesh.new()
editable.from_mesh(mesh)
bmesh.ops.recalc_face_normals(editable, faces=editable.faces)
editable.to_mesh(mesh)
editable.free()
mesh.update()

after_faces = len(corset.data.polygons)
after_vertices = len(corset.data.vertices)

SCENE.parent.mkdir(parents=True, exist_ok=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(SCENE))

bpy.ops.object.select_all(action="DESELECT")
corset.select_set(True)
bpy.context.view_layer.objects.active = corset
bpy.ops.export_scene.gltf(
    filepath=str(OUTPUT),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_image_format="AUTO",
)

metadata = {
    "schemaVersion": 1,
    "createdAt": "2026-07-28",
    "objectId": "burgundy-button-corset",
    "sourceModel": f"/{SOURCE.relative_to(ROOT / 'public').as_posix()}",
    "outputModel": f"/{OUTPUT.relative_to(ROOT / 'public').as_posix()}",
    "scene": f"/{SCENE.relative_to(ROOT / 'public').as_posix()}",
    "method": (
        "Exact boolean difference using a smooth waist-fitted elliptical "
        "cavity extending through both garment openings, tapered tightly at "
        "the pointed lower front to preserve the hem silhouette."
    ),
    "sourceFaces": before_faces,
    "sourceVertices": before_vertices,
    "outputFaces": after_faces,
    "outputVertices": after_vertices,
    "bounds": {
        "minimum": list(minimum),
        "maximum": list(maximum),
        "dimensions": list(maximum - minimum),
    },
}
METADATA.write_text(json.dumps(metadata, indent=2) + "\n")
print(json.dumps(metadata, indent=2))
