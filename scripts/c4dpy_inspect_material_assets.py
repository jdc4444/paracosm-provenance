"""Read-only inspection of one Cinema 4D material and its shader data.

This helper is intentionally diagnostic. It loads a document, searches the
selected material's classic description/container data, walks its shader tree,
and inventories node spaces. It never saves or mutates the document.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d
import maxon


def safe_text(value) -> str:
    try:
        return str(value)
    except Exception as error:
        return f"<{type(value).__name__}: {type(error).__name__}>"


def value_record(value) -> dict[str, object]:
    return {
        "type": type(value).__name__,
        "value": safe_text(value),
    }


def description_records(node, terms: tuple[str, ...]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        description = node.GetDescription(c4d.DESCFLAGS_DESC_0)
    except Exception:
        return records
    for container, desc_id, _group_id in description:
        levels = [
            int(desc_id[index].id)
            for index in range(desc_id.GetDepth())
        ]
        try:
            value = node.GetParameter(desc_id, c4d.DESCFLAGS_GET_0)
        except Exception as error:
            value = f"<GetParameter {type(error).__name__}: {error}>"
        name = safe_text(container.GetString(c4d.DESC_NAME))
        haystack = f"{name} {safe_text(value)}".casefold()
        if terms and not any(term in haystack for term in terms):
            continue
        records.append(
            {
                "levels": levels,
                "name": name,
                **value_record(value),
            }
        )
    return records


def container_records(
    container,
    terms: tuple[str, ...],
    prefix: str = "",
    depth: int = 0,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    if container is None or depth > 8:
        return records
    try:
        count = int(container.GetContainerSize())
    except Exception:
        return records
    for index in range(count):
        try:
            item_id = int(container.GetIndexId(index))
            value = container.GetIndexData(index)
        except Exception:
            continue
        path = f"{prefix}/{item_id}" if prefix else str(item_id)
        if isinstance(value, c4d.BaseContainer):
            records.extend(
                container_records(value, terms, path, depth + 1)
            )
            continue
        text = safe_text(value)
        if terms and not any(term in text.casefold() for term in terms):
            continue
        records.append({"containerPath": path, **value_record(value)})
    return records


def walk_shaders(shader, prefix: str = ""):
    current = shader
    while current:
        name = current.GetName() or f"type-{current.GetType()}"
        path = f"{prefix}/{name}" if prefix else name
        yield current, path
        child = current.GetDown()
        if child:
            yield from walk_shaders(child, path)
        current = current.GetNext()


def linked_asset_records(
    shader, terms: tuple[str, ...]
) -> list[dict[str, object]]:
    """Inspect BaseList2D assets linked from shader parameters.

    Substance shaders keep the source .sbsar path on a linked Substance Asset
    object, not on the shader itself. Keeping this traversal read-only exposes
    that otherwise-hidden path without changing the document.
    """

    records: list[dict[str, object]] = []
    try:
        description = shader.GetDescription(c4d.DESCFLAGS_DESC_0)
    except Exception:
        return records
    seen: set[int] = set()
    for _container, desc_id, _group_id in description:
        try:
            value = shader.GetParameter(desc_id, c4d.DESCFLAGS_GET_0)
        except Exception:
            continue
        if not isinstance(value, c4d.BaseList2D):
            continue
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        description_matches = description_records(value, terms)
        container_matches = container_records(
            value.GetDataInstance(), terms
        )
        if terms and not description_matches and not container_matches:
            continue
        records.append(
            {
                "name": value.GetName(),
                "typeId": int(value.GetType()),
                "typeName": safe_text(value.GetTypeName()),
                "descriptionMatches": description_matches,
                "containerMatches": container_matches,
            }
        )
    return records


def shader_records(material, terms: tuple[str, ...]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for shader, path in walk_shaders(material.GetFirstShader()):
        description = description_records(shader, terms)
        container = container_records(shader.GetDataInstance(), terms)
        if terms and not description and not container:
            continue
        records.append(
            {
                "path": path,
                "name": shader.GetName(),
                "typeId": int(shader.GetType()),
                "typeName": safe_text(shader.GetTypeName()),
                "descriptionMatches": description,
                "containerMatches": container,
                "linkedAssets": linked_asset_records(shader, terms),
            }
        )
    return records


def node_space_records(
    material, terms: tuple[str, ...]
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    node_material = material.GetNodeMaterialReference()
    known_spaces = [
        "com.redshift3d.redshift4c4d.class.nodespace",
        "net.maxon.nodespace.standard",
    ]
    for space_id in known_spaces:
        space = maxon.Id(space_id)
        try:
            if not node_material.HasSpace(space):
                continue
            graph = node_material.GetGraph(space)
            root = graph.GetRoot()
            matches: list[dict[str, object]] = []
            for node in root.GetInnerNodes(
                maxon.NODE_KIND.ALL_MASK, True
            ):
                try:
                    value = node.GetPortValue()
                except Exception:
                    continue
                text = safe_text(value)
                if terms and not any(term in text.casefold() for term in terms):
                    continue
                matches.append(
                    {
                        "path": safe_text(node.GetPath()),
                        "kind": safe_text(node.GetKind()),
                        "value": text,
                    }
                )
            result.append(
                {
                    "id": space_id,
                    "rootValid": bool(root),
                    "rootPath": safe_text(root.GetPath()) if root else "",
                    "valueMatches": matches,
                }
            )
        except Exception as error:
            result.append(
                {
                    "id": space_id,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    return result


def collect_assets(doc) -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    try:
        c4d.documents.GetAllAssetsNew(doc, False, "", flags, assets)
    except Exception:
        pass
    return assets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--material", required=True)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument(
        "--asset",
        help="Restrict matching materials to the exact collector filename.",
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    terms = tuple(item.casefold() for item in args.term if item)
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        matches = []
        materials = []
        material = doc.GetFirstMaterial()
        while material:
            materials.append(material)
            material = material.GetNext()
        assets = collect_assets(doc)
        collector_assets = [
            asset
            for asset in assets
            if (
                not args.asset
                or str(asset.get("filename") or "") == args.asset
            )
        ]
        for index, material in enumerate(materials):
            owner_asset = next(
                (
                    asset
                    for asset in collector_assets
                    if asset.get("owner") == material
                ),
                None,
            )
            if material.GetName() == args.material and (
                not args.asset or owner_asset is not None
            ):
                matches.append(
                    {
                        "index": index,
                        "name": material.GetName(),
                        "typeId": int(material.GetType()),
                        "typeName": safe_text(material.GetTypeName()),
                        "collectorAsset": (
                            {
                                "filename": str(
                                    owner_asset.get("filename") or ""
                                ),
                                "exists": bool(owner_asset.get("exists")),
                                "parameterId": int(
                                    owner_asset.get("paramId", -1) or -1
                                ),
                                "nodePath": str(
                                    owner_asset.get("nodePath") or ""
                                ),
                                "nodeSpace": str(
                                    owner_asset.get("nodeSpace") or ""
                                ),
                            }
                            if owner_asset
                            else None
                        ),
                        "descriptionMatches": description_records(
                            material, terms
                        ),
                        "containerMatches": container_records(
                            material.GetDataInstance(), terms
                        ),
                        "shaders": shader_records(material, terms),
                        "nodeSpaces": node_space_records(material, terms),
                    }
                )
        print(
            "PARACOSM_MATERIAL_ASSET_INSPECTION_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "material": args.material,
                    "terms": list(terms),
                    "matchCount": len(matches),
                    "matches": matches,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_MATERIAL_ASSET_INSPECTION_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
