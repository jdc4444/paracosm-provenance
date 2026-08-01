"""Read-only source-era inventory for one Cinema 4D project.

This helper is intentionally compact enough to run across large candidate
projects.  It reports every take, effective camera/render setting, render
output path, camera, shot-local hair hierarchy, and external Alembic/cache
reference without saving or changing the document.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import (
    LEGACY_RS_CAMERA_OBJECT_ID,
    effective_item,
    object_path,
    walk_objects,
    walk_takes,
)


RELEVANT_OBJECT_TERMS = (
    "hair",
    "bodymesh",
    "facemesh",
    "ripping wallpaper",
    "carousel",
)


def vector(value: c4d.Vector) -> dict[str, float]:
    return {"x": value.x, "y": value.y, "z": value.z}


def render_enabled(op) -> bool:
    current = op
    while current:
        if current.GetRenderMode() == c4d.MODE_OFF:
            return False
        current = current.GetUp()
    return True


def render_data_payload(item, fps: int) -> dict[str, object]:
    data = item.GetData()

    def frame(parameter):
        value = data[parameter]
        return value.GetFrame(fps) if isinstance(value, c4d.BaseTime) else None

    return {
        "name": item.GetName(),
        "rendererId": data[c4d.RDATA_RENDERENGINE],
        "outputPath": str(data[c4d.RDATA_PATH] or ""),
        "frameFrom": frame(c4d.RDATA_FRAMEFROM),
        "frameTo": frame(c4d.RDATA_FRAMETO),
        "width": data[c4d.RDATA_XRES],
        "height": data[c4d.RDATA_YRES],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")

    report = {"project": str(project), "saved": False}
    try:
        c4d.documents.SetActiveDocument(doc)
        fps = doc.GetFps()
        report.update(
            {
                "fps": fps,
                "minFrame": doc.GetMinTime().GetFrame(fps),
                "maxFrame": doc.GetMaxTime().GetFrame(fps),
                "currentFrame": doc.GetTime().GetFrame(fps),
            }
        )
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        objects = list(walk_objects(doc.GetFirstObject()))
        cameras = []
        for item in objects:
            if not (
                item.CheckType(c4d.Ocamera)
                or item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
            ):
                continue
            matrix = item.GetMg()
            try:
                focal = float(item[c4d.CAMERA_FOCUS])
            except Exception:
                try:
                    focal = float(item[500])
                except Exception:
                    focal = None
            cameras.append(
                {
                    "name": item.GetName(),
                    "path": object_path(item),
                    "typeId": item.GetType(),
                    "legacyRedshift": (
                        item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                    ),
                    "position": vector(matrix.off),
                    "focalLength": focal,
                    "trackCount": len(item.GetCTracks()),
                    "renderEnabled": render_enabled(item),
                }
            )
        report["cameras"] = cameras

        render_data = []
        current_render = doc.GetFirstRenderData()
        while current_render:
            render_data.append(render_data_payload(current_render, fps))
            current_render = current_render.GetNext()
        report["renderData"] = render_data

        take_data = doc.GetTakeData()
        takes = []
        if take_data:
            original_take = take_data.GetCurrentTake()
            for take in walk_takes(take_data.GetMainTake()):
                take_data.SetCurrentTake(take)
                doc.ExecutePasses(
                    None,
                    True,
                    True,
                    True,
                    getattr(c4d, "BUILDFLAGS_NONE", 0),
                )
                camera = effective_item(take.GetEffectiveCamera(take_data))
                settings = effective_item(
                    take.GetEffectiveRenderData(take_data)
                )
                takes.append(
                    {
                        "name": take.GetName(),
                        "checked": take.IsChecked(),
                        "camera": (
                            {
                                "name": camera.GetName(),
                                "path": object_path(camera),
                                "typeId": camera.GetType(),
                            }
                            if camera is not None
                            else None
                        ),
                        "renderData": (
                            render_data_payload(settings, fps)
                            if settings is not None
                            else None
                        ),
                    }
                )
            take_data.SetCurrentTake(original_take)
        report["takes"] = takes

        report["relevantObjects"] = [
            {
                "name": item.GetName(),
                "path": object_path(item),
                "typeId": item.GetType(),
                "renderEnabled": render_enabled(item),
            }
            for item in objects
            if any(
                term in object_path(item).casefold()
                for term in RELEVANT_OBJECT_TERMS
            )
        ]

        assets = []
        collector_flags = (
            c4d.ASSETDATA_FLAG_WITHCACHES
            | c4d.ASSETDATA_FLAG_WITHFONTS
            | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
            | c4d.ASSETDATA_FLAG_MULTIPLEUSE
        )
        collector = c4d.documents.GetAllAssetsNew(
            doc, False, "", collector_flags, assets
        )
        report["collectorResult"] = int(collector)
        report["dependencyReferences"] = len(assets)
        report["linkedReferences"] = sum(
            bool(asset.get("exists")) for asset in assets
        )
        report["missingReferences"] = sum(
            not bool(asset.get("exists")) for asset in assets
        )
        relevant_dependencies = []
        for asset in assets:
            filename = str(asset.get("filename") or "")
            if not filename:
                continue
            owner = asset.get("owner")
            owner_path = object_path(owner) if owner is not None else None
            folded = f"{filename} {owner_path or ''}".casefold()
            if not (
                filename.casefold().endswith((".abc", ".fbx", ".rs"))
                or any(term in folded for term in RELEVANT_OBJECT_TERMS)
                or "03thi" in folded
                or "subdivision_surface" in folded
            ):
                continue
            relevant_dependencies.append(
                {
                    "filename": filename,
                    "exists": bool(asset.get("exists")),
                    "ownerName": (
                        owner.GetName()
                        if owner is not None
                        and hasattr(owner, "GetName")
                        else None
                    ),
                    "ownerPath": owner_path,
                    "ownerTypeId": (
                        owner.GetType()
                        if owner is not None
                        and hasattr(owner, "GetType")
                        else None
                    ),
                    "renderEnabled": (
                        render_enabled(owner)
                        if isinstance(owner, c4d.BaseObject)
                        else None
                    ),
                }
            )
        report["relevantDependencies"] = relevant_dependencies
        if args.output:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
        print(
            "PARACOSM_PROJECT_SOURCE_INVENTORY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_PROJECT_SOURCE_INVENTORY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
