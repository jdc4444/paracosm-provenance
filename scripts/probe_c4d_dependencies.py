#!/usr/bin/env python3
"""Audit render-relevant external dependencies in the mapped C4D scenes.

The probe uses Cinema 4D's own GetAllAssetsNew collector, including node assets,
caches, fonts, and multiple uses. It never saves or closes a creative document.
When a shot names a take, the take is selected only long enough to collect its
effective assets and the original take is restored.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe_c4d_camera import send

APP_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = APP_ROOT / "public" / "data" / "state.json"
EXPORT_PATH = APP_ROOT / "data" / "c4d-dependency-export.json"

TEXTURE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".cin",
    ".dds",
    ".dpx",
    ".exr",
    ".gif",
    ".hdr",
    ".heic",
    ".ies",
    ".jpeg",
    ".jpg",
    ".pic",
    ".png",
    ".psb",
    ".psd",
    ".rat",
    ".sgi",
    ".tga",
    ".tif",
    ".tiff",
    ".tx",
    ".webp",
}
PROXY_EXTENSIONS = {".ass", ".rs", ".vrmesh"}
OBJECT_EXTENSIONS = {
    ".3ds",
    ".c4d",
    ".dae",
    ".fbx",
    ".gltf",
    ".glb",
    ".obj",
    ".ply",
    ".stl",
    ".usda",
    ".usdc",
    ".usdz",
}
CACHE_EXTENSIONS = {
    ".abc",
    ".bgeo",
    ".bin",
    ".geo",
    ".mc",
    ".mcx",
    ".mdd",
    ".pc2",
    ".pdc",
    ".vdb",
}
FONT_EXTENSIONS = {".otf", ".ttc", ".ttf", ".woff", ".woff2"}
CHARACTER_HINT = re.compile(
    r"(abby|character|avatar|skeleton|joint|skin|pose|walk|run|dance|hair)",
    re.IGNORECASE,
)


def normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def extract_take(detail: str) -> str:
    match = re.search(
        r"(?:^| · )(?:Take:|take) ([^·]+)",
        detail or "",
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else "Main"


def targets_from_state(path: Path = STATE_PATH) -> dict[str, list[str]]:
    state = json.loads(path.read_text(encoding="utf-8"))
    targets: dict[str, set[str]] = {}
    for cut in state.get("cuts", []):
        if cut.get("isGap"):
            continue
        for edge in cut.get("lineage", []):
            if (
                edge.get("kind") == "camera"
                and edge.get("evidence") == "confirmed"
                and edge.get("path")
            ):
                project_path = normalize_path(edge["path"])
                targets.setdefault(project_path, set()).add(
                    extract_take(edge.get("detail", ""))
                )
    return {path: sorted(takes) for path, takes in sorted(targets.items())}


C4D_AUDIT_SCRIPT = r"""
def _pa_path(item):
    if item is None:
        return None
    try:
        if isinstance(item, c4d.BaseObject):
            names = []
            current = item
            while current:
                names.insert(0, current.GetName())
                current = current.GetUp()
            return "/".join(names)
        if isinstance(item, c4d.BaseTag):
            op = item.GetObject()
            prefix = _pa_path(op)
            return ((prefix + "/") if prefix else "") + item.GetName()
    except Exception:
        pass
    try:
        return item.GetName()
    except Exception:
        return None


def _pa_type_name(item):
    if item is None:
        return None
    try:
        return item.GetTypeName()
    except Exception:
        return None


def _pa_owner_kind(item):
    if item is None:
        return "document"
    try:
        if isinstance(item, c4d.BaseObject):
            return "object"
        if isinstance(item, c4d.BaseMaterial):
            return "material"
        if isinstance(item, c4d.BaseTag):
            return "tag"
        if isinstance(item, c4d.BaseShader):
            return "shader"
    except Exception:
        pass
    return "other"


def _pa_render_enabled(op):
    if op is None or not isinstance(op, c4d.BaseObject):
        return None
    current = op
    while current:
        try:
            if current.GetRenderMode() == c4d.MODE_OFF:
                return False
        except Exception:
            pass
        current = current.GetUp()
    return True


def _pa_material_usage_for_doc(target_doc):
    usage = {}

    def walk(op):
        while op:
            tag = op.GetFirstTag()
            while tag:
                try:
                    if tag.CheckType(c4d.Ttexture):
                        material = tag.GetMaterial()
                        if material:
                            key = str(id(material))
                            record = usage.setdefault(
                                key,
                                {
                                    "assignments": 0,
                                    "renderEnabledAssignments": 0
                                }
                            )
                            record["assignments"] += 1
                            if _pa_render_enabled(op):
                                record["renderEnabledAssignments"] += 1
                except Exception:
                    pass
                tag = tag.GetNext()
            child = op.GetDown()
            if child:
                walk(child)
            op = op.GetNext()

    walk(target_doc.GetFirstObject())
    return usage


def _pa_asset_payload(asset, project_path):
    owner = asset.get("owner")
    filename = str(asset.get("filename", "") or "")
    assetname = str(asset.get("assetname", "") or "")
    owner_path = _pa_path(owner)
    owner_kind = _pa_owner_kind(owner)
    render_enabled = _pa_render_enabled(owner)
    owner_assigned = None
    if owner_kind == "tag":
        try:
            render_enabled = _pa_render_enabled(owner.GetObject())
        except Exception:
            pass
    elif owner_kind == "material":
        usage = _pa_material_usage.get(str(id(owner)), {})
        owner_assigned = bool(usage.get("assignments", 0))
        if owner_assigned:
            render_enabled = bool(
                usage.get("renderEnabledAssignments", 0)
            )
        else:
            render_enabled = False
    is_document = (
        owner is None
        and int(asset.get("paramId", -1) or -1) == -1
        and (
            filename == project_path
            or assetname == doc.GetDocumentName()
        )
    )
    return {
        "filename": filename,
        "assetName": assetname,
        "exists": bool(asset.get("exists", False)),
        "ownerName": owner.GetName() if owner else None,
        "ownerPath": owner_path,
        "ownerKind": owner_kind,
        "ownerType": _pa_type_name(owner),
        "ownerTypeId": owner.GetType() if owner else None,
        "renderEnabled": render_enabled,
        "ownerAssigned": owner_assigned,
        "parameterId": int(asset.get("paramId", -1) or -1),
        "channelId": int(asset.get("channelId", -1) or -1),
        "nodePath": str(asset.get("nodePath", "") or ""),
        "nodeSpace": str(asset.get("nodeSpace", "") or ""),
        "networkOnDemand": bool(asset.get("netRequestOnDemand", False)),
        "isDocument": is_document
    }


def _pa_collect_assets(target_doc, flags, project_path):
    assets = []
    status = c4d.documents.GetAllAssetsNew(
        target_doc, False, "", flags, assets
    )
    return {
        "collectorResult": int(status),
        "assets": [
            _pa_asset_payload(asset, project_path)
            for asset in assets
        ]
    }


def _pa_walk_objects(op, rows):
    while op:
        type_name = _pa_type_name(op) or ""
        name = op.GetName()
        try:
            type_id = op.GetType()
        except Exception:
            type_id = None
        rows.append({
            "name": name,
            "objectPath": _pa_path(op),
            "typeName": type_name,
            "typeId": type_id,
            "renderEnabled": _pa_render_enabled(op)
        })
        child = op.GetDown()
        if child:
            _pa_walk_objects(child, rows)
        op = op.GetNext()


def _pa_walk_takes(take, result):
    current = take
    while current:
        result[current.GetName()] = current
        child = current.GetDown()
        if child:
            _pa_walk_takes(child, result)
        current = current.GetNext()


def _pa_evaluate(target_doc):
    try:
        target_doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
    except Exception:
        pass


def _pa_audit_document(target_doc, project_path, requested_takes):
    global doc, _pa_material_usage
    doc = target_doc
    _pa_material_usage = _pa_material_usage_for_doc(target_doc)
    flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    full_scene = _pa_collect_assets(target_doc, flags, project_path)
    objects = []
    _pa_walk_objects(target_doc.GetFirstObject(), objects)
    take_data = target_doc.GetTakeData()
    active_take = take_data.GetCurrentTake() if take_data else None
    active_take_name = active_take.GetName() if active_take else None
    take_lookup = {}
    if take_data:
        _pa_walk_takes(take_data.GetMainTake(), take_lookup)
    takes = {}
    try:
        for requested_name in requested_takes:
            requested_take = take_lookup.get(requested_name)
            if requested_take is None and requested_name == "Main":
                requested_take = take_data.GetMainTake() if take_data else None
            if requested_take is None:
                takes[requested_name] = {
                    "found": False,
                    "collectorResult": None,
                    "assets": []
                }
                continue
            take_data.SetCurrentTake(requested_take)
            _pa_evaluate(target_doc)
            record = _pa_collect_assets(
                target_doc,
                flags | c4d.ASSETDATA_FLAG_CURRENTTAKEONLY,
                project_path
            )
            record["found"] = True
            takes[requested_name] = record
    finally:
        if take_data and active_take:
            take_data.SetCurrentTake(active_take)
            _pa_evaluate(target_doc)
    return {
        "projectPath": project_path,
        "document": target_doc.GetDocumentName(),
        "documentPath": target_doc.GetDocumentPath(),
        "activeTake": active_take_name,
        "requestedTakes": requested_takes,
        "fullScene": full_scene,
        "takes": takes,
        "objects": objects
    }


def _pa_run(targets):
    documents = {}
    candidate = c4d.documents.GetFirstDocument()
    while candidate:
        candidate_path = (
            str(candidate.GetDocumentPath()).rstrip("/\\")
            + "/"
            + candidate.GetDocumentName()
        )
        if candidate_path in targets and candidate_path not in documents:
            documents[candidate_path] = candidate
        candidate = candidate.GetNext()
    projects = []
    for project_path, requested_takes in targets.items():
        target_doc = documents.get(project_path)
        if target_doc is None:
            projects.append({
                "projectPath": project_path,
                "open": False,
                "error": "Mapped project is not open in Cinema 4D"
            })
            continue
        try:
            record = _pa_audit_document(
                target_doc, project_path, requested_takes
            )
            record["open"] = True
            projects.append(record)
        except Exception as error:
            projects.append({
                "projectPath": project_path,
                "open": True,
                "error": repr(error)
            })
    return projects


_pa_targets = PARACOSM_TARGETS
_pa_direct = PARACOSM_DIRECT_DOCUMENT
_pa_load = PARACOSM_LOAD_DOCUMENT


def _pa_load_and_audit(targets):
    project_path = list(targets.keys())[0]
    requested_takes = list(targets.values())[0]
    load_flags = c4d.SCENEFILTER_OBJECTS | c4d.SCENEFILTER_MATERIALS
    loaded_doc = c4d.documents.LoadDocument(project_path, load_flags)
    if loaded_doc is None:
        return [{
            "projectPath": project_path,
            "open": False,
            "error": "Cinema 4D could not fully load the mapped project"
        }]
    try:
        return [
            dict(
                _pa_audit_document(
                    loaded_doc, project_path, requested_takes
                ),
                open=False,
                temporaryFullLoad=True
            )
        ]
    finally:
        c4d.documents.KillDocument(loaded_doc)


print(
    "PARACOSM_DEPENDENCIES_JSON="
    + json.dumps(
        {
            "projects": (
                _pa_load_and_audit(_pa_targets)
                if _pa_load
                else [
                    dict(
                        _pa_audit_document(
                            doc,
                            list(_pa_targets.keys())[0],
                            list(_pa_targets.values())[0]
                        ),
                        open=True
                    )
                ]
                if _pa_direct
                else _pa_run(_pa_targets)
            )
        },
        separators=(",", ":")
    )
)
"""


def parse_result(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("error"):
        raise RuntimeError(response["error"])
    output = response.get("output") or ""
    marker = "PARACOSM_DEPENDENCIES_JSON="
    line = next((line for line in output.splitlines() if line.startswith(marker)), None)
    if not line:
        raise RuntimeError(
            f"Dependency marker missing from Cinema 4D response: {output[:1000]}"
        )
    return json.loads(line[len(marker) :])


def category_for(asset: dict[str, Any]) -> str:
    filename = asset.get("filename") or asset.get("assetName") or ""
    owner_text = " ".join(
        str(asset.get(key) or "")
        for key in ("ownerName", "ownerPath", "ownerType", "nodePath", "nodeSpace")
    )
    path_text = f"{filename} {owner_text}"
    extension = Path(filename).suffix.lower()
    if extension in PROXY_EXTENSIONS or re.search(
        r"\b(proxy|stand.?in|redshift proxy)\b", owner_text, re.IGNORECASE
    ):
        return "proxy"
    if extension in TEXTURE_EXTENSIONS:
        return "texture"
    if extension in CACHE_EXTENSIONS:
        return "cache"
    if CHARACTER_HINT.search(path_text):
        return "character"
    if extension in OBJECT_EXTENSIONS:
        return "object"
    if extension in FONT_EXTENSIONS:
        return "font"
    return "other"


def is_character_related(asset: dict[str, Any]) -> bool:
    return bool(
        CHARACTER_HINT.search(
            " ".join(
                str(asset.get(key) or "")
                for key in (
                    "filename",
                    "assetName",
                    "ownerName",
                    "ownerPath",
                    "ownerType",
                    "nodePath",
                )
            )
        )
    )


def enrich_summarized_collection(
    summary: dict[str, Any],
) -> dict[str, Any]:
    dependencies = [
        {
            **asset,
            "characterRelated": is_character_related(asset),
        }
        for asset in summary.get("dependencies", [])
    ]
    summary["dependencies"] = dependencies
    summary["missingCharacterRelatedCount"] = sum(
        1
        for asset in dependencies
        if not asset.get("exists") and asset.get("characterRelated")
    )
    summary["renderCriticalMissingCharacterCount"] = sum(
        1
        for asset in dependencies
        if (
            not asset.get("exists")
            and asset.get("characterRelated")
            and asset.get("renderEnabled") is not False
        )
    )
    return summary


def summarize_collection(collection: dict[str, Any]) -> dict[str, Any]:
    built_in_nodes = [
        asset
        for asset in collection.get("assets", [])
        if str(asset.get("filename") or "").startswith("asset:///")
        and "db=Builtin" in str(asset.get("filename") or "")
    ]
    dependencies = [
        {**asset, "category": category_for(asset)}
        for asset in collection.get("assets", [])
        if not asset.get("isDocument") and asset not in built_in_nodes
    ]
    missing = [asset for asset in dependencies if not asset.get("exists")]
    linked = [asset for asset in dependencies if asset.get("exists")]
    missing_by_category = Counter(asset["category"] for asset in missing)
    linked_by_category = Counter(asset["category"] for asset in linked)
    categories: dict[str, dict[str, Any]] = {}
    for category in (
        "object",
        "character",
        "texture",
        "proxy",
        "cache",
        "font",
        "other",
    ):
        category_missing = [
            asset for asset in missing if asset["category"] == category
        ]
        category_linked = [
            asset for asset in linked if asset["category"] == category
        ]
        if category_missing:
            status = "missing"
        elif category_linked:
            status = "linked"
        else:
            status = "none_external"
        categories[category] = {
            "status": status,
            "linked": len(category_linked),
            "missing": len(category_missing),
        }
    if missing:
        render_critical = [
            item for item in missing if item.get("renderEnabled") is not False
        ]
        status = (
            "missing_render_dependencies"
            if render_critical
            else "missing_in_disabled_components"
        )
    elif collection.get("collectorResult") in (1, 2):
        status = "fully_linked"
    else:
        status = "audit_failed"
    return enrich_summarized_collection({
        "status": status,
        "collectorResult": collection.get("collectorResult"),
        "builtinNodeCount": len(built_in_nodes),
        "dependencyCount": len(dependencies),
        "linkedCount": len(linked),
        "missingCount": len(missing),
        "renderCriticalMissingCount": sum(
            1 for item in missing if item.get("renderEnabled") is not False
        ),
        "linkedByCategory": dict(linked_by_category),
        "missingByCategory": dict(missing_by_category),
        "categories": categories,
        "dependencies": dependencies,
    })


def characterize_project(project: dict[str, Any]) -> dict[str, Any]:
    if project.get("error"):
        return project
    objects = project.pop("objects", [])
    character_objects = [
        item
        for item in objects
        if CHARACTER_HINT.search(
            f"{item.get('name', '')} {item.get('objectPath', '')} "
            f"{item.get('typeName', '')}"
        )
    ]
    project["objectInventory"] = {
        "total": len(objects),
        "renderEnabled": sum(
            1 for item in objects if item.get("renderEnabled") is not False
        ),
        "characterSignals": len(character_objects),
        "characterExamples": character_objects[:12],
    }
    project["fullScene"] = summarize_collection(project["fullScene"])
    project["takes"] = {
        name: (
            summarize_collection(record)
            | {"found": record.get("found", True)}
        )
        for name, record in project.get("takes", {}).items()
    }
    return project


def run_probe(
    targets: dict[str, list[str]],
    direct_document: bool = False,
    load_document: bool = False,
) -> dict[str, Any]:
    code = (
        C4D_AUDIT_SCRIPT.replace(
            "PARACOSM_TARGETS", json.dumps(targets, ensure_ascii=False)
        )
        .replace(
            "PARACOSM_DIRECT_DOCUMENT",
            "True" if direct_document else "False",
        )
        .replace(
            "PARACOSM_LOAD_DOCUMENT",
            "True" if load_document else "False",
        )
    )
    result = parse_result(
        send({"command": "execute_python", "code": code}, timeout=1800)
    )
    projects = [characterize_project(item) for item in result["projects"]]
    return {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "method": (
            "Cinema 4D GetAllAssetsNew with node assets, caches, fonts, "
            "multiple uses, and shot take selection"
        ),
        "projects": projects,
    }


def archive_payload(projects: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "method": (
            "Cinema 4D GetAllAssetsNew with node assets, caches, fonts, "
            "multiple uses, and shot take selection"
        ),
        "projects": projects,
    }


def probe_loaded_project(
    project_path: str, takes: list[str]
) -> dict[str, Any]:
    result = run_probe(
        {project_path: takes}, load_document=True
    )
    return result["projects"][0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="C4D projects to inspect; defaults to confirmed camera projects in state",
    )
    parser.add_argument(
        "--take",
        action="append",
        default=[],
        help=(
            "Take to evaluate for explicitly supplied projects; repeat for "
            "multiple takes. Defaults to Main."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EXPORT_PATH,
        help="Archive destination",
    )
    parser.add_argument(
        "--already-open",
        action="store_true",
        help=(
            "Inspect matching live documents without loading them. Only safe "
            "when the documents still contain their full object graphs."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep successful project records already present in the archive",
    )
    args = parser.parse_args()
    if args.files:
        selected_takes = args.take or ["Main"]
        targets = {
            normalize_path(str(path)): selected_takes for path in args.files
        }
    else:
        targets = targets_from_state()
    existing: dict[str, dict[str, Any]] = {}
    if args.resume and args.output.exists():
        prior = json.loads(args.output.read_text(encoding="utf-8"))
        existing = {
            item["projectPath"]: item
            for item in prior.get("projects", [])
            if item.get("projectPath") and not item.get("error")
        }
    if args.already_open:
        result = run_probe(targets)
        projects = result["projects"]
    else:
        projects = []
        total = len(targets)
        for index, (project_path, takes) in enumerate(targets.items(), start=1):
            if project_path in existing:
                projects.append(existing[project_path])
                print(
                    f"[{index}/{total}] resume {Path(project_path).name}",
                    flush=True,
                )
                continue
            print(
                f"[{index}/{total}] loading {Path(project_path).name}",
                flush=True,
            )
            try:
                project = probe_loaded_project(project_path, takes)
                print(
                    (
                        f"[{index}/{total}] audited "
                        f"{project.get('objectInventory', {}).get('total', 0)} "
                        f"objects, "
                        f"{project.get('fullScene', {}).get('dependencyCount', 0)} "
                        f"dependencies, "
                        f"{project.get('fullScene', {}).get('missingCount', 0)} "
                        "missing"
                    ),
                    flush=True,
                )
            except Exception as error:
                project = {
                    "projectPath": project_path,
                    "error": repr(error),
                }
                print(
                    f"[{index}/{total}] ERROR {error!r}",
                    flush=True,
                )
            projects.append(project)
            args.output.write_text(
                json.dumps(archive_payload(projects), indent=2),
                encoding="utf-8",
            )
        result = archive_payload(projects)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    audited = sum(1 for item in result["projects"] if not item.get("error"))
    missing = sum(
        1
        for item in result["projects"]
        if item.get("fullScene", {}).get("missingCount", 0)
    )
    print(
        json.dumps(
            {
                "projectsRequested": len(targets),
                "projectsAudited": audited,
                "projectsWithMissingDependencies": missing,
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
