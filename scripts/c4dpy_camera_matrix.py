"""Render a read-only grey matrix for every camera in one C4D document."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import c4d

from c4dpy_camera_proof import (
    LEGACY_RS_CAMERA_OBJECT_ID,
    clean_base_draw,
    find_active_base_draw_camera,
    find_take,
    object_path,
    render_record,
    walk_objects,
)


def slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result or "camera"


def polygon_world_bounds(obj: c4d.PolygonObject) -> dict | None:
    points = obj.GetAllPoints()
    if not points:
        return None
    matrix = obj.GetMg()
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    for point in points:
        world = matrix * point
        for index, value in enumerate((world.x, world.y, world.z)):
            low[index] = min(low[index], value)
            high[index] = max(high[index], value)
    return {
        "min": {"x": low[0], "y": low[1], "z": low[2]},
        "max": {"x": high[0], "y": high[1], "z": high[2]},
        "center": {
            "x": (low[0] + high[0]) * 0.5,
            "y": (low[1] + high[1]) * 0.5,
            "z": (low[2] + high[2]) * 0.5,
        },
    }


def plain_polygon_clone(source: c4d.PolygonObject) -> c4d.PolygonObject:
    clone = c4d.PolygonObject(
        source.GetPointCount(), source.GetPolygonCount()
    )
    clone.SetAllPoints(source.GetAllPoints())
    for index in range(source.GetPolygonCount()):
        clone.SetPolygon(index, source.GetPolygon(index))
    clone.Message(c4d.MSG_UPDATE)
    return clone


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--take")
    parser.add_argument("--render-data")
    parser.add_argument("--camera", action="append", default=[])
    parser.add_argument(
        "--enable-object",
        action="append",
        default=[],
        help=(
            "Temporarily force a named object or exact hierarchy path on for "
            "the in-memory proof render. The source document is never saved."
        ),
    )
    parser.add_argument(
        "--bake-object",
        action="append",
        default=[],
        help=(
            "Clone evaluated polygon caches from a named hierarchy into "
            "temporary visible proof geometry. This is useful when a saved "
            "proxy is offline and the editable hierarchy is disabled. The "
            "source document is never saved."
        ),
    )
    parser.add_argument(
        "--bake-world-offset",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        default=(0.0, 0.0, 0.0),
        help="World-space translation applied to temporary baked objects.",
    )
    parser.add_argument(
        "--keep-root",
        action="append",
        default=[],
        help=(
            "For memory-bounded diagnostics, remove every other top-level "
            "object from the in-memory document before rendering. Include "
            "the root that owns the requested cameras. The source document "
            "is never saved."
        ),
    )
    parser.add_argument(
        "--remove-root",
        action="append",
        default=[],
        help=(
            "Remove one named top-level object from the in-memory diagnostic "
            "before evaluation. Repeat for multiple roots. This is useful "
            "for legacy simulation containers that abort current hardware "
            "preview rendering; the source document is never saved."
        ),
    )
    parser.add_argument(
        "--proxy-object",
        help=(
            "Name or exact hierarchy path of an offline proxy whose saved "
            "transform should place temporary source-component geometry."
        ),
    )
    parser.add_argument(
        "--proxy-component",
        action="append",
        type=Path,
        default=[],
        help=(
            "FBX, Alembic, C4D, or other C4D-readable source component to "
            "evaluate at the target time and place through --proxy-object."
        ),
    )
    parser.add_argument(
        "--proxy-frame-offset",
        type=int,
        default=0,
        help=(
            "Frame offset applied after mapping target seconds into each "
            "proxy component document. Useful for proxies whose filename "
            "records a nonzero sequence start."
        ),
    )
    parser.add_argument(
        "--proxy-world-offset",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        default=(0.0, 0.0, 0.0),
        help=(
            "Diagnostic world-space translation applied after the saved proxy "
            "transform. This is useful for recovering an omitted export-origin "
            "normalization without editing the source document."
        ),
    )
    parser.add_argument(
        "--debug-cube",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help="Insert a temporary 2x6x2 cube at a world position.",
    )
    parser.add_argument("--width", type=int, default=360)
    parser.add_argument("--height", type=int, default=203)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), load_flags)
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")
    component_documents = []
    try:
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        clean_base_draw(base_draw)
        removed_roots = []
        remove_roots = set(args.remove_root)
        if remove_roots:
            roots = []
            current_root = doc.GetFirstObject()
            while current_root:
                roots.append(current_root)
                current_root = current_root.GetNext()
            for root in roots:
                if root.GetName() in remove_roots:
                    removed_roots.append(root.GetName())
                    root.Remove()
        if args.keep_root:
            keep_roots = set(args.keep_root)
            roots = []
            current_root = doc.GetFirstObject()
            while current_root:
                roots.append(current_root)
                current_root = current_root.GetNext()
            for root in roots:
                if root.GetName() not in keep_roots:
                    removed_roots.append(root.GetName())
                    root.Remove()
        cameras = [
            item
            for item in walk_objects(doc.GetFirstObject())
            if item.CheckType(c4d.Ocamera)
            or item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
        ]
        hierarchy_camera_guids = {str(item.GetGUID()) for item in cameras}
        active_base_draw_camera = find_active_base_draw_camera(doc)
        active_base_draw_camera_is_external = bool(
            active_base_draw_camera
            and str(active_base_draw_camera.GetGUID())
            not in hierarchy_camera_guids
        )
        if active_base_draw_camera_is_external:
            cameras.insert(0, active_base_draw_camera)
        selected = set(args.camera)
        if selected:
            cameras = [
                item
                for item in cameras
                if item.GetName() in selected or object_path(item) in selected
            ]
        enabled_targets = set(args.enable_object)
        enabled_objects = []
        enabled_layers = []
        if enabled_targets:
            for scene_object in walk_objects(doc.GetFirstObject()):
                if (
                    scene_object.GetName() in enabled_targets
                    or object_path(scene_object) in enabled_targets
                ):
                    scene_object.SetRenderMode(c4d.MODE_ON)
                    scene_object.SetEditorMode(c4d.MODE_ON)
                    enabled_objects.append(object_path(scene_object))
                    branch_objects = [scene_object]
                    child = scene_object.GetDown()
                    if child:
                        branch_objects.extend(walk_objects(child))
                    parent = scene_object.GetUp()
                    while parent:
                        branch_objects.append(parent)
                        parent = parent.GetUp()
                    for branch_object in branch_objects:
                        layer = branch_object.GetLayerObject(doc)
                        if layer is None or layer.GetName() in enabled_layers:
                            continue
                        layer_data = layer.GetLayerData(doc)
                        for parameter in (
                            c4d.ID_LAYER_VIEW,
                            c4d.ID_LAYER_RENDER,
                            c4d.ID_LAYER_GENERATORS,
                            c4d.ID_LAYER_DEFORMERS,
                            c4d.ID_LAYER_EXPRESSIONS,
                            c4d.ID_LAYER_ANIMATION,
                        ):
                            layer_data[parameter] = True
                        layer.SetLayerData(doc, layer_data)
                        enabled_layers.append(layer.GetName())
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        baked_targets = set(args.bake_object)
        baked_objects = []
        if baked_targets:
            doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        rebuilt_proxy_components = []
        if args.proxy_component:
            if not args.proxy_object:
                raise RuntimeError(
                    "--proxy-object is required with --proxy-component"
                )
            proxy_object = next(
                (
                    item
                    for item in walk_objects(doc.GetFirstObject())
                    if item.GetName() == args.proxy_object
                    or object_path(item) == args.proxy_object
                ),
                None,
            )
            if proxy_object is None:
                raise RuntimeError(
                    f"Proxy object not found: {args.proxy_object}"
                )
            target_seconds = args.frame / doc.GetFps()
            proxy_matrix = proxy_object.GetMg()
            proxy_matrix.off += c4d.Vector(*args.proxy_world_offset)
            proxy_object.SetRenderMode(c4d.MODE_OFF)
            proxy_object.SetEditorMode(c4d.MODE_OFF)
            for component_path in args.proxy_component:
                component_path = component_path.expanduser().resolve()
                component = c4d.documents.LoadDocument(
                    str(component_path),
                    c4d.SCENEFILTER_OBJECTS
                    | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
                )
                if component is None:
                    raise RuntimeError(
                        f"Could not load proxy component: {component_path}"
                    )
                component_documents.append(component)
                component_frame = round(
                    target_seconds * component.GetFps()
                ) + args.proxy_frame_offset
                component.SetTime(
                    c4d.BaseTime(component_frame, component.GetFps())
                )
                component.ExecutePasses(
                    None,
                    True,
                    True,
                    True,
                    getattr(c4d, "BUILDFLAGS_NONE", 0),
                )
                component_record = {
                    "path": str(component_path),
                    "fps": component.GetFps(),
                    "frame": component_frame,
                    "frameOffset": args.proxy_frame_offset,
                    "worldOffset": list(args.proxy_world_offset),
                    "minFrame": component.GetMinTime().GetFrame(
                        component.GetFps()
                    ),
                    "maxFrame": component.GetMaxTime().GetFrame(
                        component.GetFps()
                    ),
                    "meshes": [],
                }
                for source_object in walk_objects(
                    component.GetFirstObject()
                ):
                    evaluated = (
                        source_object.GetDeformCache()
                        or source_object.GetCache()
                        or source_object
                    )
                    if not isinstance(evaluated, c4d.PolygonObject):
                        continue
                    clone = plain_polygon_clone(evaluated)
                    clone.SetName(
                        "PARACOSM_PROXY_COMPONENT_"
                        + source_object.GetName()
                    )
                    clone.SetMg(proxy_matrix * evaluated.GetMg())
                    clone.SetRenderMode(c4d.MODE_ON)
                    clone.SetEditorMode(c4d.MODE_ON)
                    clone.SetLayerObject(None)
                    doc.InsertObject(clone)
                    component_record["meshes"].append(
                        {
                            "sourcePath": object_path(source_object),
                            "pointCount": clone.GetPointCount(),
                            "polygonCount": clone.GetPolygonCount(),
                            "worldBounds": polygon_world_bounds(clone),
                        }
                    )
                rebuilt_proxy_components.append(component_record)
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        for root in list(walk_objects(doc.GetFirstObject())):
            if (
                root.GetName() not in baked_targets
                and object_path(root) not in baked_targets
            ):
                continue
            candidates = [root]
            child = root.GetDown()
            if child:
                candidates.extend(walk_objects(child))
            for source_object in candidates:
                evaluated = (
                    source_object.GetDeformCache()
                    or source_object.GetCache()
                    or source_object
                )
                if not isinstance(evaluated, c4d.PolygonObject):
                    continue
                clone = plain_polygon_clone(evaluated)
                clone.SetName(
                    "PARACOSM_BAKED_PROOF_"
                    + source_object.GetName()
                )
                baked_matrix = evaluated.GetMg()
                baked_matrix.off += c4d.Vector(*args.bake_world_offset)
                clone.SetMg(baked_matrix)
                clone.SetRenderMode(c4d.MODE_ON)
                clone.SetEditorMode(c4d.MODE_ON)
                clone.SetLayerObject(None)
                doc.InsertObject(clone)
                baked_objects.append(
                    {
                        "sourcePath": object_path(source_object),
                        "pointCount": clone.GetPointCount(),
                        "polygonCount": clone.GetPolygonCount(),
                    }
                )
        if baked_objects:
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        if args.debug_cube:
            cube = c4d.BaseObject(c4d.Ocube)
            cube.SetName("PARACOSM_DEBUG_CUBE")
            cube[c4d.PRIM_CUBE_LEN] = c4d.Vector(2.0, 6.0, 2.0)
            cube.SetAbsPos(c4d.Vector(*args.debug_cube))
            cube.SetRenderMode(c4d.MODE_ON)
            cube.SetEditorMode(c4d.MODE_ON)
            doc.InsertObject(cube)

        for scene_object in walk_objects(doc.GetFirstObject()):
            tag = scene_object.GetFirstTag()
            while tag:
                next_tag = tag.GetNext()
                if tag.CheckType(c4d.Ttexture):
                    tag.Remove()
                tag = next_tag
            if scene_object.CheckType(c4d.Olight):
                scene_object[c4d.LIGHT_BRIGHTNESS] = 0.0
            else:
                scene_object[c4d.ID_BASEOBJECT_USECOLOR] = (
                    c4d.ID_BASEOBJECT_USECOLOR_ALWAYS
                )
                scene_object[c4d.ID_BASEOBJECT_COLOR] = c4d.Vector(
                    0.72, 0.72, 0.72
                )
        proof_light = c4d.BaseObject(c4d.Olight)
        proof_light.SetName("PARACOSM_CAMERA_MATRIX_LIGHT")
        proof_light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        proof_light[c4d.LIGHT_COLOR] = c4d.Vector(1.0, 1.0, 1.0)
        proof_light[c4d.LIGHT_BRIGHTNESS] = 2.0
        proof_light[c4d.LIGHT_SHADOWTYPE] = 0
        doc.InsertObject(proof_light)

        records = []
        used_names: dict[str, int] = {}
        for camera in cameras:
            name_slug = slug(camera.GetName())
            used_names[name_slug] = used_names.get(name_slug, 0) + 1
            suffix = (
                f"-{used_names[name_slug]}"
                if used_names[name_slug] > 1
                else ""
            )
            output = output_dir / (
                f"{args.prefix}__{name_slug}{suffix}__f{args.frame:04d}.png"
            )
            records.append(
                {
                    "sourceId": f"{args.prefix}__{name_slug}{suffix}",
                    "targetFrame": args.frame,
                    "cameraName": camera.GetName(),
                    "cameraObject": {"objectPath": object_path(camera)},
                    "cameraTake": args.take,
                    "cameraRenderData": args.render_data,
                    "useActiveBaseDrawCamera": bool(
                        active_base_draw_camera_is_external
                        and camera is active_base_draw_camera
                    ),
                    "outputPath": str(output),
                }
            )
        results = [
            render_record(
                doc,
                take_data,
                base_draw,
                proof_light,
                record,
                args.width,
                args.height,
            )
            for record in records
        ]
        print(
            "PARACOSM_CAMERA_MATRIX_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "frame": args.frame,
                    "cameraCount": len(cameras),
                    "temporarilyEnabledObjects": enabled_objects,
                    "temporarilyEnabledLayers": enabled_layers,
                    "removedTopLevelObjects": removed_roots,
                    "temporarilyBakedObjects": baked_objects,
                    "rebuiltProxyComponents": rebuilt_proxy_components,
                    "results": results,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        for component in component_documents:
            c4d.documents.KillDocument(component)
        c4d.documents.KillDocument(doc)
    os._exit(0)


if __name__ == "__main__":
    main()
