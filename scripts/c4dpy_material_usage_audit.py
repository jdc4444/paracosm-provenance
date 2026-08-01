"""Audit material assignments and external assets in a Cinema 4D document.

Run with Maxon's bundled ``c4dpy``. The source document is opened read-only
and is never saved.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import c4d
import maxon


REDSHIFT_NODE_SPACE_ID = (
    "com.redshift3d.redshift4c4d.class.nodespace"
)


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    current = op
    while current:
        names.insert(0, current.GetName())
        current = current.GetUp()
    return "/".join(names)


def material_record(material) -> dict[str, object]:
    spaces: list[str] = []
    node_count = 0
    node_material = material.GetNodeMaterialReference()
    redshift_space = maxon.Id(REDSHIFT_NODE_SPACE_ID)
    try:
        if node_material.HasSpace(redshift_space):
            spaces.append(REDSHIFT_NODE_SPACE_ID)
            graph = node_material.GetGraph(redshift_space)
            node_count = len(
                list(
                    graph.GetRoot().GetInnerNodes(
                        maxon.NODE_KIND.NODE_MASK,
                        True,
                    )
                )
            )
    except Exception:
        pass
    return {
        "name": material.GetName(),
        "typeId": material.GetType(),
        "nodeSpaces": spaces,
        "redshiftNodeCount": node_count,
        "assignments": [],
        "assets": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load document: {project}")

    try:
        records: dict[object, dict[str, object]] = {}
        material = doc.GetFirstMaterial()
        material_index = 0
        while material:
            record = material_record(material)
            record["index"] = material_index
            records[material] = record
            material_index += 1
            material = material.GetNext()

        unlinked_tags: list[dict[str, object]] = []
        for scene_object in walk_objects(doc.GetFirstObject()):
            tag = scene_object.GetFirstTag()
            tag_index = 0
            while tag:
                if tag.CheckType(c4d.Ttexture):
                    linked = tag.GetMaterial()
                    assignment = {
                        "objectPath": object_path(scene_object),
                        "objectTypeId": scene_object.GetType(),
                        "objectEditorMode": scene_object.GetEditorMode(),
                        "objectRenderMode": scene_object.GetRenderMode(),
                        "tagIndex": tag_index,
                        "restriction": str(
                            tag[c4d.TEXTURETAG_RESTRICTION] or ""
                        ),
                        "projection": int(
                            tag[c4d.TEXTURETAG_PROJECTION]
                        ),
                    }
                    if linked in records:
                        records[linked]["assignments"].append(assignment)
                    else:
                        assignment["materialName"] = (
                            linked.GetName() if linked else None
                        )
                        unlinked_tags.append(assignment)
                tag = tag.GetNext()
                tag_index += 1

        flags = (
            c4d.ASSETDATA_FLAG_WITHCACHES
            | c4d.ASSETDATA_FLAG_WITHFONTS
            | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
            | c4d.ASSETDATA_FLAG_MULTIPLEUSE
        )
        assets: list[dict[str, object]] = []
        collector_result = c4d.documents.GetAllAssetsNew(
            doc,
            False,
            "",
            flags,
            assets,
        )
        orphan_assets: list[dict[str, object]] = []
        for asset in assets:
            owner = asset.get("owner")
            asset_record = {
                "filename": str(asset.get("filename") or ""),
                "assetName": str(asset.get("assetname") or ""),
                "exists": bool(asset.get("exists")),
                "nodePath": str(asset.get("nodePath") or ""),
            }
            if owner in records:
                records[owner]["assets"].append(asset_record)
            else:
                try:
                    owner_name = owner.GetName() if owner else None
                except Exception:
                    owner_name = None
                asset_record["ownerName"] = owner_name
                orphan_assets.append(asset_record)

        duplicate_names: dict[str, list[int]] = defaultdict(list)
        for record in records.values():
            duplicate_names[str(record["name"])].append(
                int(record["index"])
            )

        result = {
            "project": str(project),
            "collectorResult": int(collector_result),
            "materialCount": len(records),
            "assignedMaterialCount": sum(
                1 for record in records.values()
                if record["assignments"]
            ),
            "textureTagCount": sum(
                len(record["assignments"])
                for record in records.values()
            ) + len(unlinked_tags),
            "duplicateMaterialNames": {
                name: indexes
                for name, indexes in duplicate_names.items()
                if len(indexes) > 1
            },
            "materials": list(records.values()),
            "unlinkedTextureTags": unlinked_tags,
            "orphanAssets": orphan_assets,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )
        print("PARACOSM_MATERIAL_USAGE_AUDIT=" + json.dumps({
            "status": "audited",
            "output": str(output),
            "materialCount": result["materialCount"],
            "assignedMaterialCount": result["assignedMaterialCount"],
            "textureTagCount": result["textureTagCount"],
        }))
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
