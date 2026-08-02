"""Inspect cameras, takes, and render visibility in a C4D document read-only.

Run with Maxon's bundled c4dpy. The document is loaded into an isolated process,
never saved, and destroyed before the process exits.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


LEGACY_RS_CAMERA_OBJECT_ID = 1057516
REDSHIFT_PROXY_OBJECT_ID = 1038649

ASSET_TERMS = {
    "character": (
        "abby",
        "character",
        "metahuman",
        "bodymesh",
        "facemesh",
    ),
    "hair": ("hair", "groom", "guide"),
    "wardrobe": (
        "cloth",
        "wardrobe",
        "garment",
        "dress",
        "jacket",
        "pants",
        "shoe",
        "skirt",
        "sleeve",
        "outfit",
    ),
    "proxy": ("proxy",),
}


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    current = op
    while current:
        names.insert(0, current.GetName())
        current = current.GetUp()
    return "/".join(names)


def vector(value) -> dict[str, float]:
    return {"x": value.x, "y": value.y, "z": value.z}


def render_mode_name(value: int) -> str:
    mapping = {
        int(getattr(c4d, "MODE_UNDEF", 0)): "inherit",
        int(getattr(c4d, "MODE_OFF", 1)): "off",
        int(getattr(c4d, "MODE_ON", 2)): "on",
    }
    return mapping.get(int(value), str(value))


def effective_render_enabled(op) -> bool:
    current = op
    while current:
        mode = int(current.GetRenderMode())
        if mode == int(getattr(c4d, "MODE_OFF", 1)):
            return False
        current = current.GetUp()
    return True


def camera_payload(op) -> dict[str, object]:
    matrix = op.GetMg()
    focal = None
    if op.CheckType(c4d.Ocamera):
        try:
            focal = float(op[c4d.CAMERA_FOCUS])
        except Exception:
            pass
    elif op.GetType() == LEGACY_RS_CAMERA_OBJECT_ID:
        try:
            focal = float(op[500])
        except Exception:
            pass
    return {
        "name": op.GetName(),
        "path": object_path(op),
        "typeId": op.GetType(),
        "legacyRedshift": op.GetType() == LEGACY_RS_CAMERA_OBJECT_ID,
        "focalLength": focal,
        "position": vector(matrix.off),
        "matrix": {
            "v1": vector(matrix.v1),
            "v2": vector(matrix.v2),
            "v3": vector(matrix.v3),
        },
    }


def visibility_payload(op, doc=None) -> dict[str, object]:
    generator_enabled = None
    try:
        enabled_desc = c4d.DescID(
            c4d.DescLevel(
                getattr(c4d, "ID_BASEOBJECT_GENERATOR_FLAG", 906),
                getattr(c4d, "DTYPE_BOOL", 400006001),
                getattr(c4d, "Obase", 5155),
            )
        )
        value = op.GetParameter(
            enabled_desc, getattr(c4d, "DESCFLAGS_GET_0", 0)
        )
        generator_enabled = bool(value) if value is not None else None
    except Exception:
        pass
    layer = None
    if doc is not None:
        try:
            layer_object = op.GetLayerObject(doc)
            if layer_object is not None:
                layer_data = layer_object.GetLayerData(doc)
                layer = {
                    "name": layer_object.GetName(),
                    "render": bool(layer_data[c4d.ID_LAYER_RENDER]),
                    "generators": bool(
                        layer_data[c4d.ID_LAYER_GENERATORS]
                    ),
                }
        except Exception:
            pass
    local_bounds_center = None
    local_bounds_radius = None
    world_bounds_center = None
    try:
        local_center = op.GetMp()
        local_radius = op.GetRad()
        local_bounds_center = vector(local_center)
        local_bounds_radius = vector(local_radius)
        world_bounds_center = vector(op.GetMg() * local_center)
    except Exception:
        pass
    return {
        "name": op.GetName(),
        "path": object_path(op),
        "typeId": op.GetType(),
        "renderMode": render_mode_name(op.GetRenderMode()),
        "editorMode": render_mode_name(op.GetEditorMode()),
        "effectiveRenderEnabled": effective_render_enabled(op),
        "generatorEnabled": generator_enabled,
        "layer": layer,
        "localBoundsCenter": local_bounds_center,
        "localBoundsRadius": local_bounds_radius,
        "worldBoundsCenter": world_bounds_center,
        "animationOffBit": bool(op.GetBit(c4d.BIT_ANIM_OFF)),
        "tracks": [
            {
                "description": [
                    int(track.GetDescriptionID()[index].id)
                    for index in range(track.GetDescriptionID().GetDepth())
                ],
                "keyCount": (
                    track.GetCurve().GetKeyCount()
                    if track.GetCurve() is not None
                    else 0
                ),
                "animationOff": bool(track[c4d.ID_CTRACK_ANIMOFF]),
            }
            for track in op.GetCTracks()
        ],
    }


def render_data_payload(item, fps: int) -> dict[str, object] | None:
    if item is None:
        return None
    return {
        "name": item.GetName(),
        "outputPath": str(item[c4d.RDATA_PATH] or ""),
        "frameFrom": item[c4d.RDATA_FRAMEFROM].GetFrame(fps),
        "frameTo": item[c4d.RDATA_FRAMETO].GetFrame(fps),
        "width": item[c4d.RDATA_XRES],
        "height": item[c4d.RDATA_YRES],
        "renderer": item[c4d.RDATA_RENDERENGINE],
    }


def take_records(
    doc, terms: tuple[str, ...], *, evaluate: bool = True
) -> list[dict[str, object]]:
    take_data = doc.GetTakeData()
    if not take_data:
        return []
    fps = doc.GetFps()
    original = take_data.GetCurrentTake()
    records = []

    def visit(take, depth: int = 0, parent: str | None = None) -> None:
        current = take
        while current:
            take_data.SetCurrentTake(current)
            if evaluate:
                doc.ExecutePasses(
                    None,
                    True,
                    True,
                    True,
                    getattr(c4d, "BUILDFLAGS_NONE", 0),
                )
            camera_result = current.GetEffectiveCamera(take_data)
            camera = (
                camera_result[0]
                if isinstance(camera_result, tuple)
                else camera_result
            )
            render_result = current.GetEffectiveRenderData(take_data)
            render_data = (
                render_result[0]
                if isinstance(render_result, tuple)
                else render_result
            )
            base_draw = doc.GetRenderBaseDraw()
            scene_camera = (
                base_draw.GetSceneCamera(doc) if base_draw is not None else None
            )
            matched = []
            ancestors = {}
            for op in walk_objects(doc.GetFirstObject()):
                value = f"{op.GetName()} {object_path(op)}".casefold()
                if not any(term in value for term in terms):
                    continue
                matched.append(visibility_payload(op, doc))
                ancestor = op.GetUp()
                while ancestor:
                    ancestors[object_path(ancestor)] = visibility_payload(
                        ancestor, doc
                    )
                    ancestor = ancestor.GetUp()
            records.append(
                {
                    "name": current.GetName(),
                    "depth": depth,
                    "parent": parent,
                    "checked": bool(current.IsChecked()),
                    "effectiveCamera": (
                        camera_payload(camera) if camera is not None else None
                    ),
                    "sceneCamera": (
                        camera_payload(scene_camera)
                        if scene_camera is not None
                        else None
                    ),
                    "renderData": render_data_payload(render_data, fps),
                    "matchingObjects": matched,
                    "matchingAncestors": [
                        ancestors[key] for key in sorted(ancestors)
                    ],
                }
            )
            child = current.GetDown()
            if child:
                visit(child, depth + 1, current.GetName())
            current = current.GetNext()

    try:
        visit(take_data.GetMainTake())
    finally:
        take_data.SetCurrentTake(original)
        if evaluate:
            doc.ExecutePasses(
                None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
            )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--camera-only", action="store_true")
    parser.add_argument(
        "--skip-evaluation",
        action="store_true",
        help="Inspect saved take overrides without ExecutePasses.",
    )
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    terms = tuple(
        item.casefold()
        for item in (
            args.term
            or [
                "abby",
                "character",
                "hair",
                "cloth",
                "wardrobe",
                "garment",
                "dress",
                "jacket",
                "pants",
                "shoe",
            ]
        )
    )
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    if not args.skip_evaluation:
        flags |= c4d.SCENEFILTER_MATERIALS
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        fps = doc.GetFps()
        if not args.skip_evaluation:
            doc.SetTime(c4d.BaseTime(args.frame, fps))
            doc.ExecutePasses(
                None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
            )
        cameras = [
            camera_payload(op)
            for op in walk_objects(doc.GetFirstObject())
            if op.CheckType(c4d.Ocamera)
            or op.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
        ]
        if args.camera_only:
            print(
                "PARACOSM_SCENE_STATE_JSON="
                + json.dumps(
                    {
                        "project": str(project),
                        "frame": args.frame,
                        "fps": fps,
                        "cameraCount": len(cameras),
                        "cameras": cameras,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
            return
        scene_objects = list(walk_objects(doc.GetFirstObject()))
        asset_groups = {}
        asset_roots = {}
        for category, category_terms in ASSET_TERMS.items():
            matched_objects = [
                op
                for op in scene_objects
                if not (
                    op.CheckType(c4d.Ocamera)
                    or op.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                )
                and any(
                    op.GetName().casefold().startswith(term)
                    or f" {term}" in op.GetName().casefold()
                    or f"_{term}" in op.GetName().casefold()
                    for term in category_terms
                )
            ]
            asset_groups[category] = [
                visibility_payload(op, doc)
                for op in matched_objects
            ]
            roots = {}
            for op in matched_objects:
                root = op
                while root.GetUp():
                    root = root.GetUp()
                roots[object_path(root)] = visibility_payload(root, doc)
            asset_roots[category] = [
                roots[key] for key in sorted(roots, key=str.casefold)
            ]
        redshift_proxies = [
            {
                **visibility_payload(op, doc),
                "sourcePath": str(op[c4d.DescID(1000)] or ""),
                "matrix": {
                    "position": vector(op.GetMg().off),
                    "v1": vector(op.GetMg().v1),
                    "v2": vector(op.GetMg().v2),
                    "v3": vector(op.GetMg().v3),
                },
            }
            for op in scene_objects
            if op.GetType() == REDSHIFT_PROXY_OBJECT_ID
        ]
        payload = {
            "project": str(project),
            "frame": args.frame,
            "fps": fps,
            "minFrame": doc.GetMinTime().GetFrame(fps),
            "maxFrame": doc.GetMaxTime().GetFrame(fps),
            "cameraCount": len(cameras),
            "cameras": cameras,
            "redshiftProxies": redshift_proxies,
            "assetGroups": asset_groups,
            "assetRoots": asset_roots,
            "topLevelObjects": [
                visibility_payload(op, doc)
                for op in walk_objects(doc.GetFirstObject())
                if object_path(op).count("/") <= 1
            ],
            "takes": take_records(
                doc, terms, evaluate=not args.skip_evaluation
            ),
        }
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        print(
            "PARACOSM_SCENE_STATE_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_SCENE_STATE_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
