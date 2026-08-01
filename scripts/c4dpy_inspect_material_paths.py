"""Inspect path-like parameters on one named Cinema 4D material.

This is a read-only recovery diagnostic. It never saves the loaded document.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import c4d


def walk_shaders(shader):
    current = shader
    while current:
        yield current
        child = current.GetDown()
        if child:
            yield from walk_shaders(child)
        current = current.GetNext()


def inspect_node(node, owner: str):
    records = []
    linked = []
    try:
        description = node.GetDescription(c4d.DESCFLAGS_DESC_0)
    except Exception:
        return records, linked
    for container, desc_id, _group_id in description:
        try:
            value = node.GetParameter(desc_id, c4d.DESCFLAGS_GET_0)
        except Exception:
            continue
        if isinstance(value, c4d.BaseList2D):
            linked.append((value, f"{owner}/linked/{value.GetName()}"))
            continue
        text = str(value or "")
        if (
            "/" not in text
            and "\\" not in text
            and ":" not in text
            and "tex" not in text.casefold()
        ):
            continue
        records.append(
            {
                "owner": owner,
                "parameter": str(
                    container.GetString(c4d.DESC_NAME) or desc_id
                ),
                "descId": str(desc_id),
                "value": text,
                "valueType": type(value).__name__,
            }
        )
    return records, linked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--material", required=True)
    args = parser.parse_args()

    doc = c4d.documents.LoadDocument(
        str(args.project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_MERGESCENE,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {args.project}")

    results = []
    material = doc.GetFirstMaterial()
    while material:
        if material.GetName() == args.material:
            owner = f"material/{material.GetName()}"
            records, linked = inspect_node(material, owner)
            results.extend(records)
            for shader in walk_shaders(material.GetFirstShader()):
                shader_records, shader_links = inspect_node(
                    shader, f"{owner}/shader/{shader.GetName()}"
                )
                results.extend(shader_records)
                linked.extend(shader_links)
            seen = set()
            while linked:
                linked_asset, linked_owner = linked.pop()
                identity = id(linked_asset)
                if identity in seen:
                    continue
                seen.add(identity)
                linked_records, nested = inspect_node(
                    linked_asset, linked_owner
                )
                results.extend(linked_records)
                linked.extend(nested)
        material = material.GetNext()

    print(
        "PARACOSM_MATERIAL_PATH_INSPECTION_JSON="
        + json.dumps(
            {
                "project": str(args.project),
                "material": args.material,
                "records": results,
            }
        )
    )


if __name__ == "__main__":
    main()
