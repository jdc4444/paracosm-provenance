"""Collect C4D dependencies from one document in an isolated read-only process."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import c4d


REDSHIFT_PROXY_OBJECT_ID = 1038649
REDSHIFT_RSFILE_DATATYPE_ID = 1036765


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def redshift_proxy_filename(op) -> str:
    """Read the private RS Proxy path without coercing its RSFILE container."""
    desc_id = c4d.DescID(
        c4d.DescLevel(
            10000,
            REDSHIFT_RSFILE_DATATYPE_ID,
            op.GetType(),
        ),
        c4d.DescLevel(
            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
            c4d.DTYPE_FILENAME,
            0,
        ),
    )
    try:
        return str(
            op.GetParameter(
                desc_id,
                getattr(c4d, "DESCFLAGS_GET_0", 0),
            )
            or ""
        )
    except Exception:
        return ""


def resolve_asset_path(
    project: Path, filename: str, collector_exists: bool
) -> tuple[bool, str | None]:
    if collector_exists:
        return True, filename or None
    local_value = (
        unquote(urlparse(filename).path)
        if filename.startswith("file://")
        else filename
    )
    candidate = Path(local_value).expanduser()
    if candidate.is_absolute():
        return candidate.is_file(), str(candidate) if candidate.is_file() else None
    candidates = (
        project.parent / candidate,
        project.parent / "tex" / candidate,
        project.parent / "tex" / candidate.name,
    )
    for item in candidates:
        if item.is_file():
            return True, str(item.resolve())
    return False, None


def object_path(owner) -> str | None:
    if owner is None:
        return None
    if isinstance(owner, c4d.BaseObject):
        names = []
        current = owner
        while current:
            names.insert(0, current.GetName())
            current = current.GetUp()
        return "/".join(names)
    if isinstance(owner, c4d.BaseTag):
        prefix = object_path(owner.GetObject())
        return f"{prefix}/{owner.GetName()}" if prefix else owner.GetName()
    try:
        return owner.GetName()
    except Exception:
        return None


def owner_kind(owner) -> str:
    if owner is None:
        return "document"
    if isinstance(owner, c4d.BaseObject):
        return "object"
    if isinstance(owner, c4d.BaseMaterial):
        return "material"
    if isinstance(owner, c4d.BaseTag):
        return "tag"
    if isinstance(owner, c4d.BaseShader):
        return "shader"
    return "other"


def affects_picture_render(filename: str) -> bool:
    """Exclude timeline-only audio from picture-render linkage counts."""
    return Path(filename).suffix.casefold() not in {
        ".aac",
        ".aif",
        ".aiff",
        ".flac",
        ".m4a",
        ".mp3",
        ".ogg",
        ".wav",
    }


def render_enabled(op) -> bool | None:
    if op is None or not isinstance(op, c4d.BaseObject):
        return None
    current = op
    while current:
        if current.GetRenderMode() == c4d.MODE_OFF:
            return False
        current = current.GetUp()
    # The generator switch is local to the object: disabling a generator
    # suppresses that object's generated cache but does not render-disable its
    # authored children.  Applying an ancestor's switch recursively hid every
    # texture below disabled legacy RS Proxy and subdivision objects.
    enabled_desc = c4d.DescID(
        c4d.DescLevel(
            getattr(c4d, "ID_BASEOBJECT_GENERATOR_FLAG", 906),
            getattr(c4d, "DTYPE_BOOL", 400006001),
            getattr(c4d, "Obase", 5155),
        )
    )
    try:
        enabled = op.GetParameter(
            enabled_desc, getattr(c4d, "DESCFLAGS_GET_0", 0)
        )
        if enabled is not None and not bool(enabled):
            return False
    except Exception:
        pass
    return True


def material_usage(doc) -> dict[object, dict[str, int]]:
    """Count texture-tag assignments by native Cinema atom identity.

    ``GetAllAssetsNew`` and ``BaseTag.GetMaterial`` can return distinct Python
    wrapper objects for the same native material. Python's ``id()`` therefore
    cannot join collector owners back to their assignments. C4DAtom implements
    equality and hashing from its native unique ID, so the atom itself is the
    stable key across wrappers.
    """

    usage: dict[object, dict[str, int]] = {}

    def walk(op) -> None:
        while op:
            tag = op.GetFirstTag()
            while tag:
                if tag.CheckType(c4d.Ttexture):
                    material = tag.GetMaterial()
                    if material:
                        record = usage.setdefault(
                            material,
                            {
                                "assignments": 0,
                                "renderEnabledAssignments": 0,
                            },
                        )
                        record["assignments"] += 1
                        if render_enabled(op):
                            record["renderEnabledAssignments"] += 1
                tag = tag.GetNext()
            child = op.GetDown()
            if child:
                walk(child)
            op = op.GetNext()

    walk(doc.GetFirstObject())
    return usage


def walk_takes(take, result: dict[str, object]) -> None:
    current = take
    while current:
        result[current.GetName()] = current
        child = current.GetDown()
        if child:
            walk_takes(child, result)
        current = current.GetNext()


def evaluate(doc) -> None:
    try:
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional path for the complete structured dependency audit.",
    )
    parser.add_argument("--owner-prefix")
    parser.add_argument("--filename-term", action="append", default=[])
    parser.add_argument(
        "--take",
        default="Main",
        help="Evaluate this take before collecting dependencies.",
    )
    parser.add_argument(
        "--frame",
        type=int,
        help="Evaluate this source frame before collecting dependencies.",
    )
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument(
        "--counts-only",
        action="store_true",
        help="Omit the potentially very large unique-missing path list.",
    )
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
    try:
        take_data = doc.GetTakeData()
        original_take = take_data.GetCurrentTake() if take_data else None
        take_lookup: dict[str, object] = {}
        if take_data:
            walk_takes(take_data.GetMainTake(), take_lookup)
        selected_take = take_lookup.get(args.take)
        if selected_take is None and args.take == "Main" and take_data:
            selected_take = take_data.GetMainTake()
        if args.take and selected_take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        if take_data and selected_take:
            take_data.SetCurrentTake(selected_take)
        if args.frame is not None:
            doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        evaluate(doc)
        usage = material_usage(doc)
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
        records = []
        filename_terms = tuple(
            item.casefold() for item in args.filename_term if item
        )
        for asset in assets:
            filename = str(asset.get("filename") or "")
            if filename.startswith("asset:///") and "db=Builtin" in filename:
                continue
            if filename_terms and not any(
                term in filename.casefold() for term in filename_terms
            ):
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
                enabled = bool(
                    material_record.get("renderEnabledAssignments", 0)
                ) if assigned else False
            elif kind == "shader":
                try:
                    material = owner.GetMain()
                except Exception:
                    material = None
                if isinstance(material, c4d.BaseMaterial):
                    material_record = usage.get(material, {})
                    assigned = bool(
                        material_record.get("assignments", 0)
                    )
                    enabled = (
                        bool(
                            material_record.get(
                                "renderEnabledAssignments", 0
                            )
                        )
                        if assigned
                        else False
                    )
            record = {
                "filename": filename,
                "assetName": str(asset.get("assetname") or ""),
                "exists": exists,
                "collectorExists": collector_exists,
                "resolvedPath": resolved_path,
                "ownerName": owner.GetName() if owner else None,
                "owner": object_path(owner),
                "ownerPath": object_path(owner),
                "ownerKind": kind,
                "ownerTypeId": owner.GetType() if owner else None,
                "renderEnabled": enabled,
                "ownerAssigned": assigned,
                "parameterId": int(asset.get("paramId", -1) or -1),
                "nodePath": str(asset.get("nodePath") or ""),
                "nodeSpace": str(asset.get("nodeSpace") or ""),
                "affectsPictureRender": affects_picture_render(filename),
            }
            record["linkStatus"] = (
                "linked"
                if collector_exists
                else "exact_relink_required"
                if exists
                else "missing"
            )
            if args.owner_prefix and not (
                record["owner"] or ""
            ).startswith(args.owner_prefix):
                continue
            records.append(record)
        # GetAllAssetsNew does not expose Redshift Proxy paths stored inside
        # Redshift's private RSFILE datatype. An active proxy can therefore be
        # absent while the generic collector reports zero render-critical
        # misses. Read that stable nested filename field explicitly so a
        # character/proxy render can never be labeled fully linked by mistake.
        redshift_proxy_records = []
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
            proxy_owner_path = object_path(proxy)
            proxy_key = (filename, str(proxy_owner_path or ""))
            if proxy_key in existing_proxy_keys:
                continue
            collector_exists = False
            exists, resolved_path = resolve_asset_path(
                project, filename, collector_exists
            )
            record = {
                "filename": filename,
                "assetName": Path(filename).name,
                "exists": exists,
                "collectorExists": collector_exists,
                "resolvedPath": resolved_path,
                "ownerName": proxy.GetName(),
                "owner": proxy_owner_path,
                "ownerPath": proxy_owner_path,
                "ownerKind": "redshift_proxy",
                "ownerTypeId": proxy.GetType(),
                "renderEnabled": render_enabled(proxy),
                "ownerAssigned": True,
                "parameterId": 10000,
                "nodePath": "RSFILE/filename",
                "nodeSpace": "com.redshift3d.redshift4c4d.proxy",
                "affectsPictureRender": True,
                "dependencySource": "redshift_proxy_private_parameter",
            }
            record["linkStatus"] = (
                "exact_relink_required" if exists else "missing"
            )
            if args.owner_prefix and not (
                record["owner"] or ""
            ).startswith(args.owner_prefix):
                continue
            records.append(record)
            redshift_proxy_records.append(record)
            existing_proxy_keys.add(proxy_key)
        unique_missing = sorted(
            {
                item["filename"]
                for item in records
                if not item["exists"] and item["filename"]
            }
        )
        render_critical_missing = [
            item
            for item in records
            if not item["exists"]
            and item.get("affectsPictureRender") is not False
            and item.get("renderEnabled") is not False
        ]
        unique_render_critical_missing = sorted(
            {
                item["filename"]
                for item in render_critical_missing
                if item["filename"]
            }
        )
        relink_required = [
            item
            for item in records
            if item["exists"] and not item["collectorExists"]
        ]
        render_critical_relink_required = [
            item
            for item in relink_required
            if item.get("affectsPictureRender") is not False
            if item.get("renderEnabled") is not False
        ]
        render_critical_unresolved = [
            item
            for item in records
            if not item["exists"]
            and item.get("affectsPictureRender") is not False
            and item.get("renderEnabled") is not False
        ]
        payload = {
            "project": str(project),
            "take": args.take,
            "frame": args.frame,
            "renderEnabledPolicy": (
                "ancestor render modes plus owner-local generator switch"
            ),
            "collectorResult": int(collector),
            "dependencyReferences": len(records),
            "collectorLinkedReferences": sum(
                item["collectorExists"] for item in records
            ),
            "linkedReferences": sum(item["exists"] for item in records),
            "resolvableReferences": sum(item["exists"] for item in records),
            "relinkRequiredReferences": len(relink_required),
            "missingReferences": sum(not item["exists"] for item in records),
            "uniqueMissingFiles": len(unique_missing),
            "renderCriticalMissingReferences": len(
                render_critical_missing
            ),
            "renderCriticalMissingFiles": len(
                unique_render_critical_missing
            ),
            "renderCriticalRelinkRequiredReferences": len(
                render_critical_relink_required
            ),
            "renderCriticalRelinkRequiredFiles": len(
                {
                    item["filename"]
                    for item in render_critical_relink_required
                    if item["filename"]
                }
            ),
            "renderCriticalRelinkRequiredPaths": sorted(
                {
                    item["filename"]
                    for item in render_critical_relink_required
                    if item["filename"]
                }
            ),
            "renderCriticalUnresolvedReferences": len(
                render_critical_unresolved
            ),
            "renderCriticalUnresolvedFiles": len(
                {
                    item["filename"]
                    for item in render_critical_unresolved
                    if item["filename"]
                }
            ),
            "renderCriticalUnresolvedPaths": sorted(
                {
                    item["filename"]
                    for item in render_critical_unresolved
                    if item["filename"]
                }
            ),
            "redshiftProxyReferences": len(redshift_proxy_records),
            "redshiftProxyPaths": sorted(
                {
                    item["filename"]
                    for item in redshift_proxy_records
                    if item["filename"]
                }
            ),
            "missingFiles": [] if args.counts_only else unique_missing,
            "renderCriticalMissingPaths": (
                []
                if args.counts_only
                else unique_render_critical_missing
            ),
            "dependencies": [] if args.summary_only else records,
        }
        if args.result_json:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        print(
            "PARACOSM_DEPENDENCY_AUDIT_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_DEPENDENCY_AUDIT_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        if take_data and original_take:
            take_data.SetCurrentTake(original_take)
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
