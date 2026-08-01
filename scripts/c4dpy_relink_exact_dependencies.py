"""Create a dated C4D copy with confirmed exact-path dependencies relinked.

Run with Maxon's bundled c4dpy. The source document is loaded read-only and is
never saved. Only recovery records classified as ``recovered_exact_path`` are
eligible, and the output filename/folder are required to differ from source.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d
import maxon


def collect_assets(doc) -> tuple[int, list[dict[str, object]]]:
    assets = []
    flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    result = c4d.documents.GetAllAssetsNew(doc, False, "", flags, assets)
    return int(result), assets


def set_classic_asset(owner, parameter_id: int, value: str) -> tuple[bool, str]:
    if owner is None or parameter_id < 0:
        return False, "asset has no classic owner/parameter"
    attempts = [value]
    filename_type = getattr(c4d, "Filename", None)
    if filename_type is not None:
        attempts.append(filename_type(value))
    errors = []
    for candidate in attempts:
        try:
            owner[c4d.DescID(parameter_id)] = candidate
            owner.Message(c4d.MSG_UPDATE)
            return True, ""
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
    return False, " | ".join(errors)


def set_node_asset(
    owner,
    node_space: str,
    node_path: str,
    required: str,
    value: str,
) -> tuple[bool, str]:
    if not isinstance(owner, c4d.BaseMaterial):
        return False, "node asset owner is not a BaseMaterial"
    if not node_space or not node_path:
        return False, "node asset has no node space/path"
    try:
        node_material = owner.GetNodeMaterialReference()
        graph = node_material.GetGraph(maxon.Id(node_space))
        graph_node = graph.GetNode(maxon.NodePath(node_path))
        if not graph_node:
            return False, "graph node/port is not valid"
        target_port = graph_node
        try:
            current_value = str(target_port.GetPortValue())
        except Exception:
            current_value = ""
        if required not in current_value:
            root = graph.GetRoot()
            target_port = next(
                (
                    item
                    for item in root.GetInnerNodes(
                        maxon.NODE_KIND.ALL_MASK, True
                    )
                    if str(item.GetPath()).startswith(node_path)
                    and required
                    in str(item.GetPortValue()).replace("file://", "")
                ),
                None,
            )
        if not target_port:
            return False, "asset-valued port beneath graph node not found"
        with graph.BeginTransaction() as transaction:
            target_port.SetPortValue(maxon.Url(value))
            transaction.Commit()
        return True, ""
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument(
        "--recovery-project",
        type=Path,
        help=(
            "Use recovery mappings indexed under this original project while "
            "editing an already dated recovery copy."
        ),
    )
    parser.add_argument("--suffix", default="_codex_072526")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Optional path for the complete structured relink report.",
    )
    parser.add_argument(
        "--all-exact",
        action="store_true",
        help="Relink inactive exact-path dependencies too.",
    )
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help=(
            "Skip one exact required path. Useful when a dependency uses a "
            "private plugin datatype that must be handled by a dedicated "
            "relinker."
        ),
    )
    parser.add_argument(
        "--exclude-from-report",
        type=Path,
        action="append",
        default=[],
        help=(
            "Exclude every path listed under unresolvedEligibleAfterRelink "
            "or failures in a prior relink report. This permits a second "
            "pass to save the exact subset that the current C4D runtime can "
            "actually write and verify."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apply and verify relinks in memory, but never save a document.",
    )
    parser.add_argument(
        "--update-existing-dated-copy",
        action="store_true",
        help=(
            "Save back to an existing Codex-dated recovery copy. Refused "
            "unless both the filename and an ancestor directory contain "
            "'_codex_'. Originals cannot pass this guard."
        ),
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    recovery_project = (
        args.recovery_project.expanduser().resolve()
        if args.recovery_project
        else project
    )
    recovery = json.loads(args.recovery.read_text(encoding="utf-8"))
    excluded_paths = set(args.exclude_path)
    for report_path in args.exclude_from_report:
        prior_report = json.loads(
            report_path.expanduser().read_text(encoding="utf-8")
        )
        excluded_paths.update(
            str(path)
            for path in prior_report.get("unresolvedEligibleAfterRelink", [])
        )
        excluded_paths.update(
            str(item.get("requiredPath") or "")
            for item in prior_report.get("failures", [])
            if item.get("requiredPath")
        )
    records = [
        item
        for item in recovery.get("projectDependencies", [])
        if Path(str(item.get("projectPath") or "")).expanduser().resolve()
        == recovery_project
        and item.get("status") == "recovered_exact_path"
        and (args.all_exact or item.get("renderCritical"))
        and item.get("candidates")
        and str(item.get("requiredPath") or "") not in excluded_paths
    ]
    mapping = {
        str(item["requiredPath"]): str(
            item["candidates"][0].get("udimTemplatePath")
            or item["candidates"][0]["path"]
        )
        for item in records
        if Path(str(item["candidates"][0]["path"])).is_file()
    }
    if not mapping:
        raise RuntimeError(f"No exact recovery records for {project}")

    if args.update_existing_dated_copy:
        if "_codex_" not in project.name.casefold() or not any(
            "_codex_" in parent.name.casefold() for parent in project.parents
        ):
            raise RuntimeError(
                "In-place update refused: project is not a Codex-dated copy"
            )
        output_dir = project.parent
        output = project
    else:
        output_dir = (
            args.output_dir.expanduser().resolve()
            if args.output_dir
            else project.parent / args.suffix
        )
        output = output_dir / f"{project.stem}{args.suffix}.c4d"
    if output == project and not args.update_existing_dated_copy:
        raise RuntimeError("Output path resolves to the source document")
    if output.exists() and not args.update_existing_dated_copy:
        raise RuntimeError(f"Refusing to overwrite existing repair copy: {output}")
    output_dir.mkdir(parents=True, exist_ok=True)

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    report: dict[str, object] = {
        "sourceProject": str(project),
        "outputProject": str(output),
        "suffix": args.suffix,
        "updatedExistingDatedCopy": args.update_existing_dated_copy,
        "eligibleMissingPaths": sorted(mapping),
        "changes": [],
        "failures": [],
        "preservedResourceLinks": [],
    }
    try:
        collector_before, assets = collect_assets(doc)
        for asset in assets:
            required = str(asset.get("filename") or "")
            target = mapping.get(required)
            if asset.get("exists") or not target:
                continue
            owner = asset.get("owner")
            parameter_id = int(asset.get("paramId", -1) or -1)
            node_path = str(asset.get("nodePath") or "")
            node_space = str(asset.get("nodeSpace") or "")
            if node_path:
                changed, error = set_node_asset(
                    owner, node_space, node_path, required, target
                )
            else:
                changed, error = set_classic_asset(
                    owner, parameter_id, target
                )
            item = {
                "requiredPath": required,
                "targetPath": target,
                "owner": owner.GetName() if owner else None,
                "ownerTypeId": owner.GetType() if owner else None,
                "parameterId": parameter_id,
                "nodePath": node_path,
                "nodeSpace": node_space,
            }
            if changed:
                report["changes"].append(item)
            else:
                report["failures"].append({**item, "reason": error})

        c4d.EventAdd()
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        collector_after, after_assets = collect_assets(doc)
        unresolved_after = sorted(
            {
                str(asset.get("filename") or "")
                for asset in after_assets
                if not asset.get("exists")
                and (
                    str(asset.get("filename") or "") in mapping
                    or str(asset.get("assetname") or "") in mapping
                )
            }
        )
        unresolved_classic_after = sorted(
            {
                str(asset.get("filename") or "")
                for asset in after_assets
                if not asset.get("exists")
                and not asset.get("nodePath")
                and (
                    str(asset.get("filename") or "") in mapping
                    or str(asset.get("assetname") or "") in mapping
                )
            }
        )
        unresolved_node_collector_after = sorted(
            set(unresolved_after) - set(unresolved_classic_after)
        )
        report["collectorBefore"] = collector_before
        report["collectorAfter"] = collector_after
        report["unresolvedEligibleAfterRelink"] = unresolved_after
        report["unresolvedClassicAfterRelink"] = unresolved_classic_after
        report["staleNodeCollectorPathsAfterRelink"] = (
            unresolved_node_collector_after
        )
        report["verifiedRelinkedPaths"] = sorted(
            set(mapping) - set(unresolved_after)
        )
        report["saved"] = False
        if report["failures"] or unresolved_classic_after:
            report["saveBlocked"] = (
                "Not all eligible exact dependencies verified after relink"
            )
        elif args.dry_run:
            report["saveBlocked"] = "dry run requested"
        else:
            resource_anchors: set[Path] = set()
            for asset in assets:
                if not asset.get("exists"):
                    continue
                resolved = Path(str(asset.get("filename") or ""))
                if not resolved.is_absolute() or not resolved.exists():
                    continue
                try:
                    relative = resolved.relative_to(project.parent)
                except ValueError:
                    continue
                if not relative.parts or relative.parts[0] == project.name:
                    continue
                resource_anchors.add(project.parent / relative.parts[0])
            for source_anchor in sorted(resource_anchors):
                link = output_dir / source_anchor.name
                if link.exists() or link.is_symlink():
                    continue
                link.symlink_to(
                    source_anchor, target_is_directory=source_anchor.is_dir()
                )
                report["preservedResourceLinks"].append(
                    {"link": str(link), "target": str(source_anchor)}
                )
            doc.GetDataInstance()[c4d.DOCUMENT_SECONDARYPATH] = maxon.Url(
                str(project.parent)
            )
            saved = c4d.documents.SaveDocument(
                doc,
                str(output),
                c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
                c4d.FORMAT_C4DEXPORT,
            )
            report["saved"] = bool(saved)
            if not saved:
                report["saveBlocked"] = "Cinema 4D SaveDocument returned false"
        if args.report_json:
            report_path = args.report_json.expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
        print(
            "PARACOSM_RELINK_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        if args.report_json:
            report_path = args.report_json.expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
        print(
            "PARACOSM_RELINK_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
