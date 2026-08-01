"""Create a throwaway current-version Redshift material and inventory its graph."""

from __future__ import annotations

import json
import os

import c4d
import maxon


NODE_SPACE = maxon.Id(
    "com.redshift3d.redshift4c4d.class.nodespace"
)


def child_records(parent, depth=0):
    records = []
    for child in parent.GetChildren():
        item = {
            "path": str(child.GetPath()),
            "kind": str(child.GetKind()),
            "depth": depth,
        }
        keys = [("name", maxon.NODE.BASE.NAME)]
        asset_id_key = getattr(maxon.NODE.BASE, "ASSETID", None)
        if asset_id_key is not None:
            keys.append(("assetId", asset_id_key))
        for label, key in keys:
            try:
                item[label] = str(child.GetValue(key))
            except Exception:
                item[label] = None
        records.append(item)
        records.extend(child_records(child, depth + 1))
    return records


def main() -> None:
    doc = c4d.documents.BaseDocument()
    available_spaces = []
    try:
        get_spaces = getattr(
            c4d.NodeMaterial, "GetMaterialNodeSpaces", None
        )
        if get_spaces:
            try:
                available_spaces = [str(item) for item in get_spaces()]
            except Exception as error:
                available_spaces = [
                    f"{type(error).__name__}: {error}"
                ]
        material = c4d.BaseMaterial(c4d.Mmaterial)
        material.SetName("PARACOSM CURRENT RS PROBE")
        doc.InsertMaterial(material)
        node_material = material.GetNodeMaterialReference()
        created = node_material.CreateDefaultGraph(NODE_SPACE)
        graph = node_material.GetGraph(NODE_SPACE)
        payload = {
            "created": bool(created),
            "graphValid": bool(graph),
            "availableSpaces": available_spaces,
            "nodes": child_records(graph.GetRoot()),
        }
        print(
            "PARACOSM_CURRENT_RS_MATERIAL_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_CURRENT_RS_MATERIAL_ERROR="
            + json.dumps(
                {
                    "error": f"{type(error).__name__}: {error}",
                    "availableSpaces": available_spaces,
                    "nodeMaterialMethods": sorted(
                        name
                        for name in dir(c4d.NodeMaterial)
                        if "space" in name.casefold()
                        or "graph" in name.casefold()
                    ),
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
