"""Verify an exact relink manifest in memory without rendering or saving.

The source project is opened read-only at one cut's take and frame. Exact
scene/classic/node-material mappings are applied, the document is evaluated,
and the same strict picture-dependency collector used by the native package
gate is rerun. No Cinema 4D document is ever saved.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take
from c4dpy_audit_dependencies import (
    REDSHIFT_PROXY_OBJECT_ID,
    affects_picture_render,
    material_usage,
    object_path,
    owner_kind,
    redshift_proxy_filename,
    render_enabled,
    resolve_asset_path,
    walk_objects,
)
from c4dpy_redshift_frame_test import (
    collect_post_relink_assets,
    relink_material_assets,
    relink_node_material_assets,
    relink_scene_assets,
)
from c4d_relink_safety import safe_manifest_mappings


def collect_active_render_dependencies(doc, project: Path) -> dict[str, object]:
    """Repeat the frame-specific audit after in-memory relinking.

    The package collector intentionally reports every reference still stored in
    the document, including materials on disabled/unassigned objects. Camera
    proof safety is narrower: it must reject every unresolved dependency that
    can affect the evaluated take/frame, while retaining project-wide residue
    separately for forensic completeness.
    """

    usage = material_usage(doc)
    assets: list[dict[str, object]] = []
    collector_flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    collector = c4d.documents.GetAllAssetsNew(
        doc, False, "", collector_flags, assets
    )
    records: list[dict[str, object]] = []
    for asset in assets:
        filename = str(asset.get("filename") or "")
        if filename.startswith("asset:///") and "db=Builtin" in filename:
            continue
        owner = asset.get("owner")
        collector_exists = bool(asset.get("exists"))
        exists, resolved_path = resolve_asset_path(
            project, filename, collector_exists
        )
        kind = owner_kind(owner)
        enabled = render_enabled(owner)
        assigned = None
        if kind == "tag":
            enabled = render_enabled(owner.GetObject())
        elif kind == "material":
            material_record = usage.get(owner, {})
            assigned = bool(material_record.get("assignments", 0))
            enabled = (
                bool(material_record.get("renderEnabledAssignments", 0))
                if assigned
                else False
            )
        elif kind == "shader":
            try:
                material = owner.GetMain()
            except Exception:
                material = None
            if isinstance(material, c4d.BaseMaterial):
                material_record = usage.get(material, {})
                assigned = bool(material_record.get("assignments", 0))
                enabled = (
                    bool(
                        material_record.get(
                            "renderEnabledAssignments", 0
                        )
                    )
                    if assigned
                    else False
                )
        records.append(
            {
                "filename": filename,
                "exists": exists,
                "collectorExists": collector_exists,
                "resolvedPath": resolved_path,
                "owner": object_path(owner),
                "ownerKind": kind,
                "renderEnabled": enabled,
                "ownerAssigned": assigned,
                "affectsPictureRender": affects_picture_render(filename),
            }
        )

    existing_proxy_keys = {
        (str(item.get("filename") or ""), str(item.get("owner") or ""))
        for item in records
    }
    for proxy in walk_objects(doc.GetFirstObject()):
        if proxy.GetType() != REDSHIFT_PROXY_OBJECT_ID:
            continue
        filename = redshift_proxy_filename(proxy)
        if not filename:
            continue
        proxy_owner = str(object_path(proxy) or "")
        key = (filename, proxy_owner)
        if key in existing_proxy_keys:
            continue
        exists, resolved_path = resolve_asset_path(
            project, filename, False
        )
        records.append(
            {
                "filename": filename,
                "exists": exists,
                "collectorExists": False,
                "resolvedPath": resolved_path,
                "owner": proxy_owner,
                "ownerKind": "redshift_proxy",
                "renderEnabled": render_enabled(proxy),
                "ownerAssigned": True,
                "affectsPictureRender": True,
            }
        )
        existing_proxy_keys.add(key)

    unresolved = [
        item
        for item in records
        if not item["exists"]
        and item.get("affectsPictureRender") is not False
        and item.get("renderEnabled") is not False
    ]
    unresolved_paths = sorted(
        {
            str(item.get("filename") or "")
            for item in unresolved
            if item.get("filename")
        }
    )
    relink_required = [
        item
        for item in records
        if item["exists"]
        and not item["collectorExists"]
        and item.get("affectsPictureRender") is not False
        and item.get("renderEnabled") is not False
    ]
    return {
        "collectorResult": int(collector),
        "dependencyReferences": len(records),
        "renderCriticalUnresolvedReferences": len(unresolved),
        "renderCriticalUnresolvedFiles": len(unresolved_paths),
        "renderCriticalUnresolvedPaths": unresolved_paths,
        "renderCriticalRelinkRequiredReferences": len(relink_required),
        "renderCriticalRelinkRequiredFiles": len(
            {
                str(item.get("filename") or "")
                for item in relink_required
                if item.get("filename")
            }
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--take", default="Main")
    parser.add_argument("--frame", type=int, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    result_json = args.result_json.expanduser().resolve()
    report: dict[str, object] = {
        "status": "failed",
        "project": str(project),
        "manifest": str(manifest_path),
        "take": args.take,
        "frame": args.frame,
        "sourcePreserved": True,
    }
    doc = None
    try:
        if not project.is_file():
            raise FileNotFoundError(project)
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        mappings, unsafe_manifest_mappings = safe_manifest_mappings(
            manifest
        )
        if unsafe_manifest_mappings:
            raise RuntimeError(
                "Unsafe relink manifest targets rejected: "
                + json.dumps(
                    unsafe_manifest_mappings[:12],
                    separators=(",", ":"),
                )
            )

        doc = c4d.documents.LoadDocument(
            str(project),
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
        )
        if doc is None:
            raise RuntimeError("Cinema 4D could not load the source project")
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        take_data.SetCurrentTake(take)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))

        first_material = relink_material_assets(doc, mappings)
        first_material.extend(
            relink_node_material_assets(doc, mappings)
        )
        first_scene = relink_scene_assets(doc, mappings)
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        second_material = relink_material_assets(doc, mappings)
        second_material.extend(
            relink_node_material_assets(doc, mappings)
        )
        second_scene = relink_scene_assets(doc, mappings)
        active_audit = collect_active_render_dependencies(doc, project)
        project_wide_audit = collect_post_relink_assets(doc, project)
        strict_dependency_render_safe = (
            not manifest.get("unresolved")
            and not active_audit.get(
                "renderCriticalUnresolvedFiles"
            )
        )
        report.update(
            {
                "status": "verified",
                "mappingCount": len(mappings),
                "manifestUnresolved": manifest.get("unresolved", []),
                "firstMaterialRelinks": first_material,
                "firstSceneRelinks": first_scene,
                "postEvaluationMaterialRelinks": second_material,
                "postEvaluationSceneRelinks": second_scene,
                "postRelinkDependencyAudit": active_audit,
                "projectWidePostRelinkDependencyAudit": project_wide_audit,
                "strictDependencyRenderSafe": bool(
                    strict_dependency_render_safe
                ),
            }
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        result_json.parent.mkdir(parents=True, exist_ok=True)
        result_json.write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(
            "PARACOSM_RELINK_VERIFICATION_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        if doc is not None:
            c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
