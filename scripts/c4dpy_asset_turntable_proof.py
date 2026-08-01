"""Render isolated grey turntable proofs for one C4D hierarchy.

This is a read-only visual diagnostic. It frames the evaluated hierarchy from
four directions so a dependency candidate can be compared with canonical shot
thumbnails before anything is accepted as a recovery source.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def walk_subtree(op):
    yield op
    child = op.GetDown()
    while child:
        yield from walk_subtree(child)
        child = child.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def find_path(doc, path: str):
    return next(
        (
            op
            for op in walk_objects(doc.GetFirstObject())
            if object_path(op) == path
        ),
        None,
    )


def bounds(root):
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for op in walk_subtree(root):
        cache = op.GetDeformCache() or op.GetCache()
        points = (
            cache.GetAllPoints()
            if isinstance(cache, c4d.PolygonObject)
            else op.GetAllPoints()
            if isinstance(op, c4d.PolygonObject)
            else []
        )
        matrix = (
            cache.GetMg()
            if isinstance(cache, c4d.PolygonObject)
            else op.GetMg()
        )
        for point in points:
            world = matrix * point
            for index, value in enumerate((world.x, world.y, world.z)):
                low[index] = min(low[index], value)
                high[index] = max(high[index], value)
    if low[0] == float("inf"):
        raise RuntimeError("Hierarchy produced no evaluated points")
    return (
        c4d.Vector(*low),
        c4d.Vector(*high),
    )


def camera_matrix(position, target):
    view = (target - position).GetNormalized()
    # Cinema 4D's native scene camera evaluates along its positive local
    # Z-axis in the Hardware Preview renderer used by this helper.
    z_axis = view
    up = c4d.Vector(0, 1, 0)
    if abs(up.Dot(z_axis)) > 0.98:
        up = c4d.Vector(0, 0, 1)
    x_axis = up.Cross(z_axis).GetNormalized()
    y_axis = z_axis.Cross(x_axis).GetNormalized()
    return c4d.Matrix(position, x_axis, y_axis, z_axis)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object-path", required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_prefix = args.output_prefix.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    results = []
    try:
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        root = find_path(doc, args.object_path)
        if root is None:
            raise RuntimeError(f"Object path not found: {args.object_path}")
        allowed = set(walk_subtree(root))
        parent = root
        while parent:
            allowed.add(parent)
            parent = parent.GetUp()
        for op in walk_objects(doc.GetFirstObject()):
            if op not in allowed:
                op.SetRenderMode(c4d.MODE_OFF)
                op.SetEditorMode(c4d.MODE_OFF)
            else:
                op[c4d.ID_BASEOBJECT_USECOLOR] = (
                    c4d.ID_BASEOBJECT_USECOLOR_ALWAYS
                )
                op[c4d.ID_BASEOBJECT_COLOR] = c4d.Vector(
                    0.72, 0.72, 0.72
                )

        low, high = bounds(root)
        center = (low + high) * 0.5
        extent = high - low
        radius = max(extent.x, extent.y, extent.z) * 1.35
        views = {
            "front": c4d.Vector(0, 0, radius),
            "rear": c4d.Vector(0, 0, -radius),
            "left": c4d.Vector(-radius, 0, 0),
            "right": c4d.Vector(radius, 0, 0),
        }
        settings = c4d.BaseContainer()
        settings[c4d.RDATA_RENDERENGINE] = (
            c4d.RDATA_RENDERENGINE_PREVIEWHARDWARE
        )
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_FRAMEFROM] = doc.GetTime()
        settings[c4d.RDATA_FRAMETO] = doc.GetTime()
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        settings[c4d.VP_PREVIEWHARDWARE_ENHANCEDOPENGL] = True
        settings[c4d.VP_PREVIEWHARDWARE_ONLY_GEOMETRY] = True
        settings[c4d.VP_PREVIEWHARDWARE_GEOMETRY_ONLY] = True
        settings[c4d.VP_PREVIEWHARDWARE_SHADOW] = False
        settings[c4d.VP_PREVIEWHARDWARE_POSTEFFECT] = False
        settings[c4d.VP_PREVIEWHARDWARE_TRANSPARENCY] = False
        base_draw = doc.GetRenderBaseDraw()
        base_draw[c4d.BASEDRAW_DATA_SDISPLAYACTIVE] = (
            c4d.BASEDRAW_SDISPLAY_GOURAUD
        )
        base_draw[c4d.BASEDRAW_DATA_SDISPLAYINACTIVE] = (
            c4d.BASEDRAW_SDISPLAY_GOURAUD
        )
        light = c4d.BaseObject(c4d.Olight)
        light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        light[c4d.LIGHT_BRIGHTNESS] = 1.5
        light[c4d.LIGHT_SHADOWTYPE] = 0
        doc.InsertObject(light)

        output_prefix.parent.mkdir(parents=True, exist_ok=True)
        for name, offset in views.items():
            camera = c4d.BaseObject(c4d.Ocamera)
            camera.SetName(f"PARACOSM_ASSET_PROOF_{name}")
            position = center + offset + c4d.Vector(0, extent.y * 0.05, 0)
            camera.SetMg(camera_matrix(position, center))
            camera[c4d.CAMERA_FOCUS] = 50.0
            doc.InsertObject(camera)
            base_draw.SetSceneCamera(camera)
            light.SetAbsPos(position)
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
            bitmap = c4d.bitmaps.MultipassBitmap(
                args.width, args.height, c4d.COLORMODE_RGB
            )
            bitmap.AddChannel(True, True)
            render_result = c4d.documents.RenderDocument(
                doc,
                settings,
                bitmap,
                c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
            )
            output = Path(str(output_prefix) + f"__{name}.png")
            result = {
                "view": name,
                "outputPath": str(output),
                "renderResult": int(render_result),
            }
            if render_result == c4d.RENDERRESULT_OK:
                save_bitmap = (
                    bitmap.GetLayerNum(0)
                    if bitmap.GetLayerCount() > 0
                    else bitmap
                )
                result["saveResult"] = int(
                    save_bitmap.Save(
                        str(output),
                        c4d.FILTER_PNG,
                        c4d.BaseContainer(),
                    )
                )
            results.append(result)
            camera.Remove()
        print(
            "PARACOSM_ASSET_TURNTABLE_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "objectPath": args.object_path,
                    "frame": args.frame,
                    "bounds": {
                        "min": [low.x, low.y, low.z],
                        "max": [high.x, high.y, high.z],
                    },
                    "results": results,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
