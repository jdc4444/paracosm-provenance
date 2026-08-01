"""Dry-run a Redshift node texture relink without saving the C4D document.

This is deliberately diagnostic. It changes only the in-memory document,
re-runs Cinema 4D's asset collector, reports whether the requested dependency
resolved, and kills the document without writing it.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d
import maxon


def collect_assets(doc):
    assets = []
    flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    result = c4d.documents.GetAllAssetsNew(doc, False, "", flags, assets)
    return int(result), assets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--required", required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    target = args.target.expanduser().resolve()
    if not target.is_file():
        raise RuntimeError(f"Target is not a file: {target}")
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    report = {
        "project": str(project),
        "required": args.required,
        "target": str(target),
        "attempts": [],
        "saved": False,
    }
    try:
        collector_before, assets = collect_assets(doc)
        matches = [
            asset
            for asset in assets
            if str(asset.get("filename") or "") == args.required
        ]
        report["collectorBefore"] = collector_before
        report["matchCount"] = len(matches)
        for asset in matches:
            owner = asset.get("owner")
            node_space = str(asset.get("nodeSpace") or "")
            node_path = str(asset.get("nodePath") or "")
            attempt = {
                "owner": owner.GetName() if owner else None,
                "ownerTypeId": owner.GetType() if owner else None,
                "nodeSpace": node_space,
                "nodePath": node_path,
            }
            try:
                if not isinstance(owner, c4d.BaseMaterial):
                    raise RuntimeError("owner is not a BaseMaterial")
                node_material = owner.GetNodeMaterialReference()
                graph = node_material.GetGraph(maxon.Id(node_space))
                graph_node = graph.GetNode(maxon.NodePath(node_path))
                attempt["graphNodeValid"] = bool(graph_node)
                attempt["graphNodeKind"] = str(graph_node.GetKind())
                attempt["valueBefore"] = str(graph_node.GetPortValue())
                with graph.BeginTransaction() as transaction:
                    graph_node.SetPortValue(maxon.Url(str(target)))
                    transaction.Commit()
                attempt["valueAfter"] = str(graph_node.GetPortValue())
                attempt["changed"] = True
            except Exception as error:
                attempt["changed"] = False
                attempt["error"] = f"{type(error).__name__}: {error}"
            report["attempts"].append(attempt)
        c4d.EventAdd()
        collector_after, after_assets = collect_assets(doc)
        report["collectorAfter"] = collector_after
        report["unresolvedAfter"] = sum(
            not asset.get("exists")
            and str(asset.get("filename") or "") == args.required
            for asset in after_assets
        )
        report["unresolvedDetails"] = [
            {
                "owner": (
                    asset.get("owner").GetName()
                    if asset.get("owner")
                    else None
                ),
                "nodePath": str(asset.get("nodePath") or ""),
                "assetName": str(asset.get("assetname") or ""),
            }
            for asset in after_assets
            if not asset.get("exists")
            and str(asset.get("filename") or "") == args.required
        ]
        report["targetReferencesAfter"] = sum(
            asset.get("exists")
            and str(asset.get("filename") or "") == str(target)
            for asset in after_assets
        )
        print(
            "PARACOSM_NODE_RELINK_DRY_RUN_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
