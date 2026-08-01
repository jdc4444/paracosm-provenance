"""Build an exact node-path relink manifest from a source-authored sibling.

The target and donor documents are opened read-only.  Redshift material graphs
are paired by material index, name, type, and graph-item path.  When the target
port contains an unavailable historical path and the identical donor port
contains an existing local file, the donor file becomes an evidence-rich exact
mapping.  An optional existing manifest supplies non-material scene mappings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import OrderedDict
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import c4d
import maxon


NODE_SPACE_ID = "com.redshift3d.redshift4c4d.class.nodespace"
NODE_SPACE = maxon.Id(NODE_SPACE_ID)
PATH_EXTENSIONS = {
    ".bmp",
    ".exr",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".png",
    ".psd",
    ".tga",
    ".tif",
    ".tiff",
    ".tx",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def material_list(doc) -> list[c4d.BaseMaterial]:
    result = []
    material = doc.GetFirstMaterial()
    while material is not None:
        result.append(material)
        material = material.GetNext()
    return result


def graph_values(material) -> dict[str, str]:
    reference = material.GetNodeMaterialReference()
    if reference is None or not reference.HasSpace(NODE_SPACE):
        return {}
    graph = reference.GetGraph(NODE_SPACE)
    result: dict[str, str] = {}
    for item in graph.GetRoot().GetInnerNodes(
        maxon.NODE_KIND.ALL_MASK,
        True,
    ):
        try:
            value = str(item.GetPortValue() or "")
        except Exception:
            continue
        if value:
            result[str(item.GetPath())] = value
    return result


def local_file(value: str, project: Path) -> Path | None:
    text = value.strip()
    relative_url = False
    if text.startswith("file:///"):
        text = unquote(text[7:])
        if not text.startswith("/"):
            text = "/" + text
    elif text.startswith("file://"):
        text = unquote(text[7:])
    elif text.startswith("relative:///"):
        text = unquote(text[len("relative:///") :])
        relative_url = True
    candidate = Path(text).expanduser()
    candidates = (
        [candidate]
        if candidate.is_absolute() and not relative_url
        else [
            project.parent / candidate,
            project.parent / "tex" / candidate,
        ]
    )
    for item in candidates:
        try:
            item = item.resolve()
        except OSError:
            continue
        if item.is_file():
            return item
    return None


def path_like(value: str) -> bool:
    text = value.strip()
    if not text or text == "scheme://":
        return False
    suffix = Path(text.replace("\\", "/")).suffix.casefold()
    return (
        suffix in PATH_EXTENSIONS
        or text.startswith(("file://", "relative:///"))
        or "/" in text
        or "\\" in text
        or (
            len(text) > 2
            and text[0].isalpha()
            and text[1] == ":"
            and text[2] in {"/", "\\"}
        )
    )


def asset_basename(value: str) -> str:
    if value.startswith("asset:///"):
        names = parse_qs(urlparse(value).query).get("name")
        if names:
            return names[0]
    return Path(value.replace("\\", "/")).name


def unambiguous_file(paths: list[Path]) -> Path | None:
    unique = sorted({path.resolve() for path in paths})
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    hashes = {sha256(path) for path in unique}
    return unique[0] if len(hashes) == 1 else None


def udim_payload(
    value: str,
    candidates: list[Path],
) -> tuple[Path | None, list[Path]]:
    basename = asset_basename(value)
    if "<UDIM>" not in basename.upper():
        return None, []
    expression = re.escape(basename).replace(
        re.escape("<UDIM>"),
        r"[0-9]{4}",
    )
    matches = sorted(
        {
            path.resolve()
            for path in candidates
            if re.fullmatch(expression, path.name, flags=re.IGNORECASE)
        }
    )
    parents = {path.parent for path in matches}
    if not matches or len(parents) != 1:
        return None, matches
    return matches[0].parent / basename, matches


def collector_node_path(graph_item_path: str) -> str:
    """Return the owning graph node path used by the asset collector.

    Graph value traversal identifies a texture filename port with a path such
    as ``texturesampler@id<...tex0/path``.  Cinema's asset collector reports
    that same asset against the owning node only, ``texturesampler@id``.
    """
    return graph_item_path.split("<", 1)[0].split(">", 1)[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-project", type=Path, required=True)
    parser.add_argument("--donor-project", type=Path, required=True)
    parser.add_argument(
        "--donor-audit",
        type=Path,
        required=True,
        help=(
            "Material-usage audit of the donor under the same runtime. "
            "Cinema can resolve relative node URLs through its tex search "
            "path without rewriting the stored port value; this audit "
            "provides that resolved existing filename."
        ),
    )
    parser.add_argument("--base-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    target_project = args.target_project.expanduser().resolve()
    donor_project = args.donor_project.expanduser().resolve()
    donor_audit_path = args.donor_audit.expanduser().resolve()
    output = args.output.expanduser().resolve()
    donor_audit = json.loads(
        donor_audit_path.read_text(encoding="utf-8")
    )
    donor_audit_files: dict[tuple[int, str, str], Path] = {}
    donor_audit_files_by_name: dict[
        tuple[int, str], list[Path]
    ] = defaultdict(list)
    donor_audit_files_by_material: dict[int, list[Path]] = defaultdict(list)
    donor_audit_resolved_urls: set[tuple[int, str]] = set()
    for material_record in donor_audit.get("materials", []):
        material_index = int(material_record.get("index", -1))
        for asset in material_record.get("assets", []):
            if not asset.get("exists"):
                continue
            filename_text = str(asset.get("filename") or "")
            donor_audit_resolved_urls.add((material_index, filename_text))
            filename = Path(filename_text)
            if not filename.is_file():
                continue
            resolved_filename = filename.resolve()
            folded_basename = filename.name.casefold()
            key = (
                material_index,
                str(asset.get("nodePath") or ""),
                folded_basename,
            )
            donor_audit_files[key] = resolved_filename
            donor_audit_files_by_name[
                (material_index, folded_basename)
            ].append(resolved_filename)
            donor_audit_files_by_material[material_index].append(
                resolved_filename
            )
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    target_doc = c4d.documents.LoadDocument(str(target_project), flags)
    donor_doc = c4d.documents.LoadDocument(str(donor_project), flags)
    if target_doc is None or donor_doc is None:
        raise RuntimeError("Could not load target and donor documents")

    try:
        mappings: OrderedDict[str, dict[str, object]] = OrderedDict()
        if args.base_manifest is not None:
            base_manifest_path = args.base_manifest.expanduser().resolve()
            base_manifest = json.loads(
                base_manifest_path.read_text(encoding="utf-8")
            )
            for record in base_manifest.get("mappings", []):
                required = str(record.get("requiredPath") or "")
                target = Path(
                    str(record.get("targetPath") or "")
                ).expanduser()
                if required and target.is_file():
                    enriched = dict(record)
                    enriched["sourceManifest"] = str(base_manifest_path)
                    mappings[required] = enriched

        target_materials = material_list(target_doc)
        donor_materials = material_list(donor_doc)
        if len(target_materials) != len(donor_materials):
            raise RuntimeError(
                "Material count differs between target and donor: "
                f"{len(target_materials)} != {len(donor_materials)}"
            )

        material_pairs = []
        node_mappings = []
        unresolved = []
        resolved_unchanged_assets = []
        for index, (target_material, donor_material) in enumerate(
            zip(target_materials, donor_materials)
        ):
            identity = {
                "index": index,
                "targetName": target_material.GetName(),
                "donorName": donor_material.GetName(),
                "targetTypeId": int(target_material.GetType()),
                "donorTypeId": int(donor_material.GetType()),
            }
            if (
                identity["targetName"] != identity["donorName"]
                or identity["targetTypeId"] != identity["donorTypeId"]
            ):
                raise RuntimeError(
                    "Material identity differs at index "
                    f"{index}: {identity}"
                )
            target_values = graph_values(target_material)
            donor_values = graph_values(donor_material)
            material_pairs.append(
                {
                    **identity,
                    "targetGraphValueCount": len(target_values),
                    "donorGraphValueCount": len(donor_values),
                }
            )
            for node_path, required in target_values.items():
                if not path_like(required):
                    continue
                donor_value = donor_values.get(node_path)
                selection_basis = (
                    "source_authored_sibling_identical_material_index_"
                    "name_type_and_redshift_node_path"
                )
                donor_evidence_files: list[Path] = []
                donor_file = (
                    local_file(donor_value, donor_project)
                    if donor_value is not None
                    else None
                )
                if donor_file is None and donor_value is not None:
                    donor_basename = Path(
                        donor_value.replace("\\", "/")
                    ).name.casefold()
                    donor_file = donor_audit_files.get(
                        (
                            index,
                            collector_node_path(node_path),
                            donor_basename,
                        )
                    )
                    if donor_file is not None:
                        selection_basis += "_collector_resolved"
                if donor_file is None and donor_value is not None:
                    donor_basename = asset_basename(
                        donor_value
                    ).casefold()
                    donor_file = unambiguous_file(
                        donor_audit_files_by_name.get(
                            (index, donor_basename),
                            [],
                        )
                    )
                    if donor_file is not None:
                        selection_basis = (
                            "source_authored_sibling_identical_material_"
                            "index_name_type_and_unique_collector_basename"
                        )
                if donor_file is None and donor_value is not None:
                    donor_file, donor_evidence_files = udim_payload(
                        donor_value,
                        donor_audit_files_by_material.get(index, []),
                    )
                    if donor_file is not None:
                        selection_basis = (
                            "source_authored_sibling_identical_material_"
                            "index_name_type_and_complete_local_udim_set"
                        )
                target_file = local_file(required, target_project)
                if donor_file is None:
                    existing_mapping = mappings.get(required)
                    if existing_mapping is not None and Path(
                        str(existing_mapping.get("targetPath") or "")
                    ).is_file():
                        continue
                    if (
                        donor_value == required
                        and required.startswith("asset:///")
                    ):
                        resolved_unchanged_assets.append(
                            {
                                "materialIndex": index,
                                "material": target_material.GetName(),
                                "nodePath": node_path,
                                "requiredPath": required,
                                "selectionBasis": (
                                    "source_authored_sibling_identical_"
                                    "immutable_maxon_asset_identifier"
                                ),
                            }
                        )
                        continue
                    if (
                        donor_value == required
                        and (index, donor_value)
                        in donor_audit_resolved_urls
                    ):
                        resolved_unchanged_assets.append(
                            {
                                "materialIndex": index,
                                "material": target_material.GetName(),
                                "nodePath": node_path,
                                "requiredPath": required,
                                "selectionBasis": (
                                    "source_authored_sibling_collector_"
                                    "confirmed_resolved_unchanged_asset"
                                ),
                            }
                        )
                        continue
                    if target_file is None:
                        unresolved.append(
                            {
                                "materialIndex": index,
                                "material": target_material.GetName(),
                                "nodePath": node_path,
                                "requiredPath": required,
                                "donorValue": donor_value,
                            }
                        )
                    continue
                if target_file is not None and (
                    target_file == donor_file
                    or (
                        donor_file.is_file()
                        and sha256(target_file) == sha256(donor_file)
                    )
                ):
                    continue
                record = {
                    "requiredPath": required,
                    "targetPath": str(donor_file),
                    "basename": donor_file.name,
                    "selectionBasis": selection_basis,
                    "materialIndex": index,
                    "materialName": target_material.GetName(),
                    "nodeSpace": NODE_SPACE_ID,
                    "nodePath": node_path,
                    "donorPortValue": donor_value,
                    "donorProject": str(donor_project),
                    "donorAudit": str(donor_audit_path),
                }
                if donor_file.is_file():
                    stat = donor_file.stat()
                    record["targetBytes"] = stat.st_size
                    record["targetSha256"] = sha256(donor_file)
                else:
                    record["targetIsUdimPattern"] = True
                    record["targetEvidenceFiles"] = [
                        {
                            "path": str(path),
                            "bytes": path.stat().st_size,
                            "sha256": sha256(path),
                        }
                        for path in donor_evidence_files
                    ]
                existing = mappings.get(required)
                if (
                    existing is not None
                    and existing.get("targetPath") != record["targetPath"]
                ):
                    record["supersedesTargetPath"] = existing.get(
                        "targetPath"
                    )
                mappings[required] = record
                node_mappings.append(record)

        mapping_targets_by_basename: dict[
            str, list[dict[str, object]]
        ] = defaultdict(list)
        for record in mappings.values():
            basename = str(record.get("basename") or "").casefold()
            target = Path(str(record.get("targetPath") or ""))
            if basename and target.is_file():
                mapping_targets_by_basename[basename].append(record)
        target_assets: list[dict[str, object]] = []
        collector_flags = (
            c4d.ASSETDATA_FLAG_WITHCACHES
            | c4d.ASSETDATA_FLAG_WITHFONTS
            | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
            | c4d.ASSETDATA_FLAG_MULTIPLEUSE
        )
        c4d.documents.GetAllAssetsNew(
            target_doc,
            False,
            "",
            collector_flags,
            target_assets,
        )
        collector_aliases = []
        for asset in target_assets:
            required = str(asset.get("filename") or "")
            if not required or asset.get("exists") or required in mappings:
                continue
            basename = asset_basename(required).casefold()
            candidates = mapping_targets_by_basename.get(basename, [])
            unique_targets = {
                str(candidate.get("targetPath") or "")
                for candidate in candidates
            }
            if len(unique_targets) != 1:
                continue
            source_record = candidates[0]
            target = Path(next(iter(unique_targets)))
            alias_record = {
                "requiredPath": required,
                "targetPath": str(target),
                "basename": target.name,
                "selectionBasis": (
                    "target_source_collector_exact_unresolved_path_"
                    "plus_unique_sha_verified_source_authored_basename"
                ),
                "collectorOwnerName": (
                    asset.get("owner").GetName()
                    if asset.get("owner") is not None
                    else None
                ),
                "collectorNodePath": str(asset.get("nodePath") or ""),
                "sourceMappingRequiredPath": source_record.get(
                    "requiredPath"
                ),
                "donorProject": str(donor_project),
                "donorAudit": str(donor_audit_path),
                "targetBytes": target.stat().st_size,
                "targetSha256": sha256(target),
            }
            mappings[required] = alias_record
            collector_aliases.append(alias_record)

        payload = {
            "schemaVersion": 1,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "targetProject": str(target_project),
            "donorProject": str(donor_project),
            "authority": (
                "Source-authored sibling material graphs matched by material "
                "index, name, type, Redshift node space, and exact node path; "
                "each selected donor payload exists locally and is SHA-256 "
                "recorded. The target source remains untouched."
            ),
            "summary": {
                "materialPairCount": len(material_pairs),
                "baseAndSiblingMappingCount": len(mappings),
                "siblingNodeMappingCount": len(node_mappings),
                "resolvedUnchangedAssetCount": len(
                    resolved_unchanged_assets
                ),
                "collectorAliasMappingCount": len(collector_aliases),
                "unresolvedSiblingNodePathCount": len(unresolved),
            },
            "materialPairs": material_pairs,
            "resolvedUnchangedAssets": resolved_unchanged_assets,
            "collectorAliasMappings": collector_aliases,
            "mappings": list(mappings.values()),
            "unresolved": unresolved,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            "PARACOSM_SIBLING_NODE_RELINK_MANIFEST="
            + json.dumps(
                {
                    "status": "built",
                    "output": str(output),
                    **payload["summary"],
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(target_doc)
        c4d.documents.KillDocument(donor_doc)
        os._exit(0)


if __name__ == "__main__":
    main()
