"""Render neutral front-view silhouette proofs for explicit OBJ candidates.

The OBJ files are loaded into isolated documents. Nothing is saved back to a
source file. Each proof receives a temporary native camera, light, and hardware
render setting so differently authored hair meshes can be compared quickly.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import c4d


HARDWARE_RENDERER_ID = 300001061


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def world_bounds(doc):
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    points = 0
    polygons = 0
    for op in walk_objects(doc.GetFirstObject()):
        if not isinstance(op, c4d.PointObject):
            continue
        matrix = op.GetMg()
        for point in op.GetAllPoints():
            world = matrix * point
            for index, value in enumerate((world.x, world.y, world.z)):
                low[index] = min(low[index], value)
                high[index] = max(high[index], value)
            points += 1
        if isinstance(op, c4d.PolygonObject):
            polygons += op.GetPolygonCount()
    if points == 0:
        raise RuntimeError("Document contains no point geometry")
    return c4d.Vector(*low), c4d.Vector(*high), points, polygons


def neutralize(doc):
    for op in walk_objects(doc.GetFirstObject()):
        op[c4d.ID_BASEOBJECT_USECOLOR] = c4d.ID_BASEOBJECT_USECOLOR_ALWAYS
        op[c4d.ID_BASEOBJECT_COLOR] = c4d.Vector(0.4, 0.18, 0.08)
        tag = op.GetFirstTag()
        while tag:
            next_tag = tag.GetNext()
            if tag.CheckType(c4d.Ttexture):
                tag.Remove()
            tag = next_tag


def render_one(source: Path, output: Path, width: int, height: int):
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(source), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {source}")
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        low, high, point_count, polygon_count = world_bounds(doc)
        center = (low + high) * 0.5
        extent = high - low
        neutralize(doc)

        camera = c4d.BaseObject(c4d.Ocamera)
        camera.SetName("PARACOSM CODEX SILHOUETTE CAMERA")
        camera[c4d.CAMERAOBJECT_FOV_VERTICAL] = math.radians(40.0)
        vertical_extent = max(extent.y, extent.x * height / width, 1.0)
        distance = vertical_extent * 0.5 / math.tan(math.radians(20.0)) * 1.18
        camera.SetAbsPos(c4d.Vector(center.x, center.y, low.z - distance))
        doc.InsertObject(camera)
        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        base_draw.SetSceneCamera(camera)

        light = c4d.BaseObject(c4d.Olight)
        light.SetName("PARACOSM CODEX SILHOUETTE LIGHT")
        light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        light[c4d.LIGHT_BRIGHTNESS] = 1.6
        light[c4d.LIGHT_SHADOWTYPE] = 0
        light.SetAbsPos(
            c4d.Vector(
                center.x - extent.x,
                center.y + extent.y,
                low.z - distance * 0.5,
            )
        )
        doc.InsertObject(light)

        render_data = doc.GetActiveRenderData()
        if render_data is None:
            raise RuntimeError("Document has no render data")
        data = render_data.GetData().GetClone(c4d.COPYFLAGS_NONE)
        data[c4d.RDATA_RENDERENGINE] = HARDWARE_RENDERER_ID
        data[c4d.RDATA_XRES] = float(width)
        data[c4d.RDATA_YRES] = float(height)
        data[c4d.RDATA_PIXELRESOLUTION] = 72.0
        data[c4d.RDATA_FILMASPECT] = width / height
        data[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        data[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(0)
        data[c4d.RDATA_FRAMETO] = c4d.BaseTime(0)
        data[c4d.VP_PREVIEWHARDWARE_ENHANCEDOPENGL] = True
        data[c4d.VP_PREVIEWHARDWARE_ONLY_GEOMETRY] = True
        data[c4d.VP_PREVIEWHARDWARE_GEOMETRY_ONLY] = True

        bitmap = c4d.bitmaps.MultipassBitmap(width, height, c4d.COLORMODE_RGB)
        bitmap.AddChannel(True, True)
        result = c4d.documents.RenderDocument(
            doc,
            data,
            bitmap,
            c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
            None,
        )
        if result != c4d.RENDERRESULT_OK:
            raise RuntimeError(f"RenderDocument returned {result}")
        output.parent.mkdir(parents=True, exist_ok=True)
        saved = bitmap.Save(str(output), c4d.FILTER_PNG, c4d.BaseContainer())
        if saved != c4d.IMAGERESULT_OK:
            raise RuntimeError(f"Bitmap save returned {saved}")
        return {
            "source": str(source),
            "output": str(output),
            "status": "rendered",
            "pointCount": point_count,
            "polygonCount": polygon_count,
            "bounds": {
                "low": [low.x, low.y, low.z],
                "high": [high.x, high.y, high.z],
            },
        }
    finally:
        c4d.documents.KillDocument(doc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=360)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    records = []
    for index, raw_source in enumerate(args.sources, start=1):
        source = raw_source.expanduser().resolve()
        output = (
            args.output_dir.expanduser().resolve()
            / f"{index:02d}-{source.stem}.png"
        )
        try:
            records.append(
                render_one(source, output, args.width, args.height)
            )
        except Exception as error:
            records.append(
                {
                    "source": str(source),
                    "output": str(output),
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    print(
        "PARACOSM_HAIR_SILHOUETTES_JSON="
        + json.dumps(records, separators=(",", ":")),
        flush=True,
    )
    os._exit(0)


if __name__ == "__main__":
    main()
