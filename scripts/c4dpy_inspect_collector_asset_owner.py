#!/usr/bin/env python3
"""Inspect the concrete owner of an exact Cinema 4D collector asset."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_inspect_material_assets import (
    container_records,
    description_records,
    safe_text,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--term", required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    term = args.term.casefold()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        assets: list[dict[str, object]] = []
        flags = (
            c4d.ASSETDATA_FLAG_WITHCACHES
            | c4d.ASSETDATA_FLAG_WITHFONTS
            | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
            | c4d.ASSETDATA_FLAG_MULTIPLEUSE
        )
        collector = c4d.documents.GetAllAssetsNew(
            doc, False, "", flags, assets
        )
        matches = []
        for asset in assets:
            filename = str(asset.get("filename") or "")
            if term not in filename.casefold():
                continue
            owner = asset.get("owner")
            operator_container = None
            if owner is not None and hasattr(
                owner, "GetOperatorContainer"
            ):
                try:
                    operator_container = owner.GetOperatorContainer()
                except Exception:
                    operator_container = None
            operator_instance = None
            if owner is not None and hasattr(
                owner, "GetOpContainerInstance"
            ):
                try:
                    operator_instance = owner.GetOpContainerInstance()
                except Exception:
                    operator_instance = None
            try:
                owner_main = owner.GetMain() if owner else None
            except Exception:
                owner_main = None
            try:
                node_master = owner.GetNodeMaster() if owner else None
                node_master_owner = (
                    node_master.GetOwner() if node_master else None
                )
            except Exception:
                node_master = None
                node_master_owner = None
            ports = []
            if owner is not None:
                for direction, getter_name in (
                    ("input", "GetInPorts"),
                    ("output", "GetOutPorts"),
                ):
                    getter = getattr(owner, getter_name, None)
                    if getter is None:
                        continue
                    try:
                        node_ports = getter()
                    except Exception:
                        continue
                    for port in node_ports:
                        record = {
                            "direction": direction,
                            "pythonType": type(port).__name__,
                        }
                        for key, method_name in (
                            ("name", "GetName"),
                            ("userId", "GetUserID"),
                            ("valueType", "GetValueType"),
                            ("io", "GetIO"),
                            ("userData", "GetUserData"),
                        ):
                            method = getattr(port, method_name, None)
                            if method is None:
                                continue
                            try:
                                record[key] = safe_text(method())
                            except Exception as error:
                                record[key] = (
                                    f"<{type(error).__name__}: {error}>"
                                )
                        ports.append(record)
            matches.append(
                {
                    "filename": filename,
                    "exists": bool(asset.get("exists")),
                    "collectorFields": {
                        str(key): {
                            "pythonType": type(value).__name__,
                            "value": safe_text(value),
                        }
                        for key, value in asset.items()
                        if key != "owner"
                    },
                    "parameterId": int(
                        asset.get("paramId", -1) or -1
                    ),
                    "ownerPythonType": type(owner).__name__,
                    "ownerName": (
                        owner.GetName() if owner else None
                    ),
                    "ownerTypeId": (
                        int(owner.GetType()) if owner else None
                    ),
                    "ownerTypeName": (
                        safe_text(owner.GetTypeName())
                        if owner
                        else None
                    ),
                    "ownerMainPythonType": type(owner_main).__name__,
                    "ownerMainName": (
                        owner_main.GetName() if owner_main else None
                    ),
                    "nodeMasterOwnerPythonType": (
                        type(node_master_owner).__name__
                    ),
                    "nodeMasterOwnerName": (
                        node_master_owner.GetName()
                        if node_master_owner
                        else None
                    ),
                    "descriptionMatches": description_records(
                        owner, (term,)
                    )
                    if owner
                    else [],
                    "dataMatches": container_records(
                        owner.GetDataInstance(), (term,)
                    )
                    if owner
                    else [],
                    "operatorContainerMatches": container_records(
                        operator_container, (term,)
                    ),
                    "operatorContainerAll": container_records(
                        operator_container, ()
                    ),
                    "operatorInstanceMatches": container_records(
                        operator_instance, (term,)
                    ),
                    "operatorInstanceAll": container_records(
                        operator_instance, ()
                    ),
                    "ports": ports,
                }
            )
        print(
            "PARACOSM_COLLECTOR_OWNER_INSPECTION_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "term": args.term,
                    "collectorResult": int(collector),
                    "matches": matches,
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
