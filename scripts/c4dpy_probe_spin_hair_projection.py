"""Measure exact Spin hair geometry in world and active-camera space."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import c4d


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def bounds(points):
    return {
        "min": [
            min(point.x for point in points),
            min(point.y for point in points),
            min(point.z for point in points),
        ],
        "max": [
            max(point.x for point in points),
            max(point.y for point in points),
            max(point.z for point in points),
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--hair-name", default="Hair - Exact Blender Spin f0170"
    )
    parser.add_argument(
        "--camera-name", default="RS Camera - Abby Spin Full Body f0170 v001"
    )
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        objects = list(walk(doc.GetFirstObject()))
        hair = next(
            (
                item
                for item in objects
                if item.GetName() == args.hair_name
                and isinstance(item, c4d.PolygonObject)
            ),
            None,
        )
        camera = next(
            (item for item in objects if item.GetName() == args.camera_name),
            None,
        )
        if hair is None or camera is None:
            raise RuntimeError("Could not resolve exact Spin hair/camera")
        world = [hair.GetMg() * point for point in hair.GetAllPoints()]
        total_area = 0.0
        nonzero_polygons = 0
        front_facing_polygons = 0
        camera_position = camera.GetMg().off
        for polygon in hair.GetAllPolygons():
            first = world[polygon.a]
            second = world[polygon.b]
            third = world[polygon.c]
            normal = (second - first).Cross(third - first)
            area = normal.GetLength() * 0.5
            center = (first + second + third) / 3.0
            if normal.Dot(camera_position - center) > 0.0:
                front_facing_polygons += 1
            if polygon.c != polygon.d:
                fourth = world[polygon.d]
                area += (
                    (third - first).Cross(fourth - first).GetLength() * 0.5
                )
            total_area += area
            if area > 1.0e-12:
                nonzero_polygons += 1
        inverse_camera = ~camera.GetMg()
        camera_points = [inverse_camera * point for point in world]
        render_data = doc.GetActiveRenderData()
        settings = render_data.GetDataInstance()
        width = float(settings[c4d.RDATA_XRES])
        height = float(settings[c4d.RDATA_YRES])
        focal = float(camera[500] or camera[7003] or 50.0)
        sensor_width = 36.0
        aspect = width / height
        sensor_height = sensor_width / aspect
        tan_horizontal = math.tan(
            2.0 * math.atan(sensor_width / (2.0 * focal)) * 0.5
        )
        tan_vertical = math.tan(
            2.0 * math.atan(sensor_height / (2.0 * focal)) * 0.5
        )
        projected = [
            c4d.Vector(
                point.x / max(point.z * tan_horizontal, 1.0e-9),
                point.y / max(point.z * tan_vertical, 1.0e-9),
                point.z,
            )
            for point in camera_points
            if point.z > 0.0
        ]
        tags = []
        for tag in hair.GetTags():
            tags.append(
                {
                    "name": tag.GetName(),
                    "type": int(tag.GetType()),
                    "material": (
                        tag[c4d.TEXTURETAG_MATERIAL].GetName()
                        if tag.CheckType(c4d.Ttexture)
                        and tag[c4d.TEXTURETAG_MATERIAL] is not None
                        else None
                    ),
                    "restriction": (
                        str(tag[c4d.TEXTURETAG_RESTRICTION] or "")
                        if tag.CheckType(c4d.Ttexture)
                        else None
                    ),
                }
            )
        print(
            "SPIN_HAIR_PROJECTION="
            + json.dumps(
                {
                    "source": str(project),
                    "pointCount": hair.GetPointCount(),
                    "polygonCount": hair.GetPolygonCount(),
                    "nonzeroPolygonCount": nonzero_polygons,
                    "frontFacingPolygonCount": front_facing_polygons,
                    "surfaceArea": total_area,
                    "editorMode": int(hair.GetEditorMode()),
                    "renderMode": int(hair.GetRenderMode()),
                    "worldBounds": bounds(world),
                    "cameraBounds": bounds(camera_points),
                    "projectedBounds": bounds(projected),
                    "frontPointCount": len(projected),
                    "tags": tags,
                }
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
