"""Render one isolated Redshift test frame from an explicit C4D camera.

Run this script with Maxon's bundled ``c4dpy``. The source document is loaded
into the helper process, rendered from cloned render settings, and never saved.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import c4d
import maxon

from c4dpy_camera_proof import bridge_legacy_redshift_camera
from c4d_relink_safety import (
    safe_manifest_mappings,
    unsafe_relink_target_reason,
)


REDSHIFT_RENDERER_ID = 1036219
LEGACY_RS_CAMERA_OBJECT_ID = 1057516
REDSHIFT_RSFILE_DATATYPE_ID = 1036765
REDSHIFT_LIGHT_OBJECT_ID = 1036751
REDSHIFT_PROXY_OBJECT_ID = 1038649
REDSHIFT_VOLUME_OBJECT_ID = 1038655
REDSHIFT_NODE_SPACE_ID = (
    "com.redshift3d.redshift4c4d.class.nodespace"
)
CODEX_CAMERA_MATRIX_DRIVER_TAG = (
    "CODEX Exact Source Frame World Matrix Driver"
)


def write_raw_float_pfm(bitmap, output: Path) -> dict[str, object]:
    """Write the unprofiled RenderDocument RGB float buffer as a PFM file."""

    width = bitmap.GetBw()
    height = bitmap.GetBh()
    copied_rows = 0
    direct_rows = 0
    sample_values: list[float] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        stream.write(f"PF\n{width} {height}\n-1.0\n".encode("ascii"))
        # PFM stores rows bottom-to-top. RGBf GetPixelCnt returns native-endian
        # 32-bit floats when no ColorProfileConvert object is supplied.
        for y in range(height - 1, -1, -1):
            row = bytearray(width * 3 * 4)
            copied = bitmap.GetPixelCnt(
                0,
                y,
                width,
                row,
                12,
                c4d.COLORMODE_RGBf,
                getattr(c4d, "PIXELCNT_0", 0),
            )
            if not copied:
                # MultipassBitmap.GetPixelCnt can reject RGBf destination
                # buffers even when its beauty base is itself RGBf. The
                # direct accessor retains float precision and exposes values
                # on C4D's documented 0..255 scale.
                values = []
                for x in range(width):
                    pixel = bitmap.GetPixelDirect(x, y)
                    values.extend(
                        (
                            float(pixel.x) / 255.0,
                            float(pixel.y) / 255.0,
                            float(pixel.z) / 255.0,
                        )
                    )
                row = bytearray(
                    struct.pack(f"<{len(values)}f", *values)
                )
                direct_rows += 1
                if len(sample_values) < 4096:
                    sample_values.extend(
                        values[: 4096 - len(sample_values)]
                    )
            else:
                copied_rows += 1
                if len(sample_values) < 4096:
                    unpacked = struct.unpack(
                        f"<{width * 3}f", bytes(row)
                    )
                    sample_values.extend(
                        unpacked[: 4096 - len(sample_values)]
                    )
            stream.write(row)
    finite_samples = [
        value
        for value in sample_values
        if value == value and abs(value) != float("inf")
    ]
    quantized_samples = sum(
        1
        for value in finite_samples
        if abs(value * 255.0 - round(value * 255.0)) < 1e-7
    )
    return {
        "copiedRows": copied_rows,
        "directAccessorRows": direct_rows,
        "sampleCount": len(finite_samples),
        "samplesOn8BitGrid": quantized_samples,
        "allSamplesOn8BitGrid": bool(
            finite_samples
            and quantized_samples == len(finite_samples)
        ),
    }


def redshift_color_management(render_data) -> dict[str, object]:
    video_post = render_data.GetFirstVideoPost()
    while video_post is not None:
        if video_post.GetType() == REDSHIFT_RENDERER_ID:
            return {
                "configuration": str(video_post[1501]),
                "renderingColorSpace": str(video_post[1502]),
                "display": str(video_post[1503]),
                "view": str(video_post[1504]),
                "compensateForViewTransform": bool(video_post[1505]),
            }
        video_post = video_post.GetNext()
    return {}


def render_data_video_posts(render_data) -> list[dict[str, object]]:
    """Return the ordered VideoPost chain owned by one render setting."""

    result = []
    video_post = render_data.GetFirstVideoPost()
    while video_post is not None:
        result.append(
            {
                "name": video_post.GetName(),
                "typeId": video_post.GetType(),
            }
        )
        video_post = video_post.GetNext()
    return result


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


def pin_donor_node_assets(
    donor_doc,
    material_names: set[str],
) -> list[dict[str, object]]:
    """Make linked donor texture URLs absolute before cloning materials."""

    assets: list[dict[str, object]] = []
    flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    c4d.documents.GetAllAssetsNew(donor_doc, False, "", flags, assets)
    requested: dict[c4d.BaseMaterial, dict[str, str]] = {}
    for asset in assets:
        owner = asset.get("owner")
        filename = str(asset.get("filename") or "")
        asset_name = str(asset.get("assetname") or "")
        if (
            not isinstance(owner, c4d.BaseMaterial)
            or owner.GetName() not in material_names
            or not filename
            or not Path(filename).is_file()
        ):
            continue
        requested.setdefault(owner, {})[
            asset_name or Path(filename).name
        ] = filename

    node_space_id = "com.redshift3d.redshift4c4d.class.nodespace"
    node_space = maxon.Id(node_space_id)
    changes: list[dict[str, object]] = []
    for material, mappings in requested.items():
        node_material = material.GetNodeMaterialReference()
        try:
            if not node_material.HasSpace(node_space):
                continue
            graph = node_material.GetGraph(node_space)
            ports = list(
                graph.GetRoot().GetInnerNodes(
                    maxon.NODE_KIND.ALL_MASK, True
                )
            )
        except Exception:
            continue
        pending = []
        for port in ports:
            try:
                value = str(port.GetPortValue() or "")
            except Exception:
                continue
            normalized = value.replace("file://", "")
            target = next(
                (
                    path
                    for asset_name, path in mappings.items()
                    if asset_name
                    and (
                        asset_name in normalized
                        or Path(path).name in normalized
                    )
                ),
                None,
            )
            if target is not None and normalized != target:
                pending.append((port, value, target))
        if not pending:
            continue
        with graph.BeginTransaction() as transaction:
            for port, value, target in pending:
                port.SetPortValue(maxon.Url(target))
                changes.append(
                    {
                        "material": material.GetName(),
                        "nodePath": str(port.GetPath()),
                        "valueBefore": value,
                        "targetPath": target,
                    }
                )
            transaction.Commit()
    return changes


def import_and_assign_donor_materials(
    target_doc,
    donor_project: Path,
    material_names: list[str],
    replacement_specs: list[str],
    remove_replaced_materials: bool,
) -> dict[str, object]:
    """Clone selected donor materials and redirect exact target tags."""

    donor_doc = c4d.documents.LoadDocument(
        str(donor_project),
        c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if donor_doc is None:
        raise RuntimeError(
            f"Could not load donor material project: {donor_project}"
        )
    report: dict[str, object] = {
        "project": str(donor_project),
        "requestedMaterials": material_names,
        "pinnedNodeAssets": [],
        "clonedMaterials": [],
        "assignments": [],
        "removedReplacedMaterials": [],
    }
    try:
        requested_names = set(material_names)
        report["pinnedNodeAssets"] = pin_donor_node_assets(
            donor_doc, requested_names
        )
        source_materials: dict[str, c4d.BaseMaterial] = {}
        material = donor_doc.GetFirstMaterial()
        while material:
            if material.GetName() in requested_names:
                source_materials[material.GetName()] = material
            material = material.GetNext()
        missing = sorted(requested_names - set(source_materials))
        if missing:
            raise RuntimeError(
                "Donor materials not found: " + ", ".join(missing)
            )

        alias = c4d.AliasTrans()
        if not alias.Init(donor_doc):
            raise RuntimeError("Could not initialize donor alias translation")
        clones: dict[str, c4d.BaseMaterial] = {}
        for name in material_names:
            clone = source_materials[name].GetClone(
                c4d.COPYFLAGS_NONE, alias
            )
            clone.SetName(f"{name} [CUT-040 MODERN DONOR 20260729]")
            clones[name] = clone
        alias.Translate(True)
        for name in material_names:
            target_doc.InsertMaterial(clones[name])
            report["clonedMaterials"].append(clones[name].GetName())

        replaced_names: set[str] = set()
        for spec in replacement_specs:
            try:
                (
                    target_path,
                    restriction,
                    old_material_name,
                    donor_material_name,
                ) = spec.split("|", 3)
            except ValueError as error:
                raise RuntimeError(
                    "--replace-material-tag must be "
                    "OBJECT_PATH|RESTRICTION|OLD_MATERIAL|DONOR_MATERIAL; "
                    f"received {spec!r}"
                ) from error
            scene_object = find_object(target_doc, target_path)
            if scene_object is None:
                raise RuntimeError(
                    f"Replacement object not found: {target_path}"
                )
            replacement = clones.get(donor_material_name)
            if replacement is None:
                raise RuntimeError(
                    f"Replacement donor material not cloned: "
                    f"{donor_material_name}"
                )
            match_count = 0
            tag = scene_object.GetFirstTag()
            while tag:
                if tag.CheckType(c4d.Ttexture):
                    linked = tag.GetMaterial()
                    linked_name = linked.GetName() if linked else ""
                    tag_restriction = str(
                        tag[c4d.TEXTURETAG_RESTRICTION] or ""
                    )
                    if (
                        linked_name == old_material_name
                        and tag_restriction == restriction
                    ):
                        tag.SetMaterial(replacement)
                        tag.Message(c4d.MSG_UPDATE)
                        match_count += 1
                        report["assignments"].append(
                            {
                                "objectPath": object_path(scene_object),
                                "restriction": restriction,
                                "oldMaterial": old_material_name,
                                "newMaterial": replacement.GetName(),
                            }
                        )
                tag = tag.GetNext()
            if match_count != 1:
                raise RuntimeError(
                    f"Expected one matching material tag for {spec!r}; "
                    f"found {match_count}"
                )
            replaced_names.add(old_material_name)

        if remove_replaced_materials:
            still_linked: set[c4d.BaseMaterial] = set()
            for scene_object in walk_objects(target_doc.GetFirstObject()):
                tag = scene_object.GetFirstTag()
                while tag:
                    if tag.CheckType(c4d.Ttexture):
                        linked = tag.GetMaterial()
                        if linked is not None:
                            still_linked.add(linked)
                    tag = tag.GetNext()
            material = target_doc.GetFirstMaterial()
            while material:
                next_material = material.GetNext()
                if (
                    material.GetName() in replaced_names
                    and material not in still_linked
                ):
                    report["removedReplacedMaterials"].append(
                        material.GetName()
                    )
                    material.Remove()
                material = next_material
        c4d.EventAdd()
        return report
    finally:
        c4d.documents.KillDocument(donor_doc)


def replace_material_names_with_current_redshift(
    doc,
    material_names: list[str],
    color: tuple[float, float, float],
) -> dict[str, object] | None:
    """Redirect exact names to one temporary current Redshift material."""

    if not material_names:
        return None
    requested_names = set(material_names)
    replacement = c4d.BaseMaterial(c4d.Mmaterial)
    replacement.SetName(
        "PARACOSM CURRENT RS DIAGNOSTIC "
        f"{color[0]:.3f},{color[1]:.3f},{color[2]:.3f}"
    )
    node_material = replacement.GetNodeMaterialReference()
    node_space = maxon.Id(REDSHIFT_NODE_SPACE_ID)
    if not node_material.CreateDefaultGraph(node_space):
        raise RuntimeError(
            "Could not create current Redshift diagnostic material graph"
        )
    graph = node_material.GetGraph(node_space)
    standard_node = None
    for child in graph.GetRoot().GetChildren():
        if str(child.GetPath()).startswith("standardmaterial@"):
            standard_node = child
            break
    if standard_node is None:
        raise RuntimeError(
            "Current Redshift diagnostic graph has no Standard Material node"
        )
    base_color = None
    reflection_roughness = None
    for port in standard_node.GetInputs().GetChildren():
        port_path = str(port.GetPath())
        if port_path.endswith("standardmaterial.base_color"):
            base_color = port
        elif port_path.endswith("standardmaterial.refl_roughness"):
            reflection_roughness = port
    if base_color is None:
        raise RuntimeError(
            "Current Redshift Standard Material has no base-color port"
        )
    with graph.BeginTransaction() as transaction:
        base_color.SetPortValue(maxon.Vector(*color))
        if reflection_roughness is not None:
            reflection_roughness.SetPortValue(0.35)
        transaction.Commit()
    doc.InsertMaterial(replacement)

    assignments: list[dict[str, object]] = []
    replaced_counts = {name: 0 for name in material_names}
    for scene_object in walk_objects(doc.GetFirstObject()):
        tag = scene_object.GetFirstTag()
        tag_index = 0
        while tag:
            if tag.CheckType(c4d.Ttexture):
                linked = tag.GetMaterial()
                linked_name = linked.GetName() if linked else ""
                if linked_name in requested_names:
                    tag.SetMaterial(replacement)
                    tag.Message(c4d.MSG_UPDATE)
                    replaced_counts[linked_name] += 1
                    assignments.append(
                        {
                            "objectPath": object_path(scene_object),
                            "tagIndex": tag_index,
                            "restriction": str(
                                tag[c4d.TEXTURETAG_RESTRICTION] or ""
                            ),
                            "oldMaterial": linked_name,
                            "newMaterial": replacement.GetName(),
                        }
                    )
            tag = tag.GetNext()
            tag_index += 1
    missing = sorted(
        name for name, count in replaced_counts.items() if count == 0
    )
    if missing:
        raise RuntimeError(
            "No texture tags found for requested diagnostic materials: "
            + ", ".join(missing)
        )
    c4d.EventAdd()
    return {
        "material": replacement.GetName(),
        "nodeSpace": REDSHIFT_NODE_SPACE_ID,
        "color": list(color),
        "replacedCounts": replaced_counts,
        "assignmentCount": len(assignments),
        "assignments": assignments,
    }


def walk_graph_nodes(parent):
    """Yield every graph node and port below ``parent``."""

    for child in parent.GetChildren():
        yield child
        yield from walk_graph_nodes(child)


def value_connections(port, direction):
    """Return only authored value wires, excluding graph dependencies."""

    try:
        return [
            (target, wires)
            for target, wires in port.GetConnections(direction)
            if "Value:0" not in str(wires)
        ]
    except Exception:
        return []


def redshift_surface_candidate_score(port) -> int:
    """Rank shader outputs which can terminate a Redshift material graph."""

    path = str(port.GetPath()).casefold()
    suffix_scores = (
        ("materialblender.out", 100),
        ("standardmaterial.outcolor", 90),
        ("material.outcolor", 80),
        ("incandescent.outcolor", 75),
        ("sprite.out", 70),
    )
    return next(
        (
            score
            for suffix, score in suffix_scores
            if path.endswith(suffix)
        ),
        0,
    )


def repair_missing_redshift_surface_outputs(
    doc,
    requested_material_names: list[str],
    repair_all: bool,
) -> dict[str, object] | None:
    """Reconnect authored terminal shaders to empty RS surface outputs.

    Some recovered materials retain their full texture/shader graphs but load
    with the final shader-to-output value wire absent. Redshift marks those
    graphs invalid and renders its red fallback. This repair is deliberately
    narrow: it only touches an empty surface port, chooses a known shader
    output already present in that same graph, and exists only in memory.
    """

    if not repair_all and not requested_material_names:
        return None
    requested = set(requested_material_names)
    node_space = maxon.Id(REDSHIFT_NODE_SPACE_ID)
    report: dict[str, object] = {
        "repairAll": repair_all,
        "requestedMaterials": requested_material_names,
        "repairs": [],
        "alreadyConnected": [],
        "noCandidate": [],
        "noRedshiftGraph": [],
    }
    material = doc.GetFirstMaterial()
    material_index = 0
    while material:
        material_name = material.GetName()
        if not repair_all and material_name not in requested:
            material = material.GetNext()
            material_index += 1
            continue
        reference = material.GetNodeMaterialReference()
        try:
            if not reference.HasSpace(node_space):
                report["noRedshiftGraph"].append(
                    {
                        "materialIndex": material_index,
                        "material": material_name,
                    }
                )
                material = material.GetNext()
                material_index += 1
                continue
            graph = reference.GetGraph(node_space)
            items = list(walk_graph_nodes(graph.GetRoot()))
        except Exception as error:
            report["noRedshiftGraph"].append(
                {
                    "materialIndex": material_index,
                    "material": material_name,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            material = material.GetNext()
            material_index += 1
            continue
        surface_ports = [
            item
            for item in items
            if str(item.GetPath()).endswith("node.output.surface")
        ]
        if not surface_ports:
            report["noCandidate"].append(
                {
                    "materialIndex": material_index,
                    "material": material_name,
                    "reason": "no surface output port",
                }
            )
            material = material.GetNext()
            material_index += 1
            continue
        surface = surface_ports[0]
        existing = value_connections(surface, maxon.PORT_DIR.INPUT)
        if existing:
            report["alreadyConnected"].append(
                {
                    "materialIndex": material_index,
                    "material": material_name,
                    "sourcePath": str(existing[0][0].GetPath()),
                }
            )
            material = material.GetNext()
            material_index += 1
            continue
        candidates = [
            item
            for item in items
            if redshift_surface_candidate_score(item) > 0
        ]
        if not candidates:
            report["noCandidate"].append(
                {
                    "materialIndex": material_index,
                    "material": material_name,
                    "reason": "no known terminal shader output",
                }
            )
            material = material.GetNext()
            material_index += 1
            continue
        candidates.sort(
            key=lambda item: (
                redshift_surface_candidate_score(item),
                not bool(
                    value_connections(item, maxon.PORT_DIR.OUTPUT)
                ),
            ),
            reverse=True,
        )
        candidate = candidates[0]
        try:
            with graph.BeginTransaction() as transaction:
                candidate.Connect(surface)
                transaction.Commit()
        except Exception as error:
            report["noCandidate"].append(
                {
                    "materialIndex": material_index,
                    "material": material_name,
                    "reason": (
                        "connect failed: "
                        f"{type(error).__name__}: {error}"
                    ),
                    "candidatePath": str(candidate.GetPath()),
                }
            )
            material = material.GetNext()
            material_index += 1
            continue
        verified = value_connections(surface, maxon.PORT_DIR.INPUT)
        if not verified:
            report["noCandidate"].append(
                {
                    "materialIndex": material_index,
                    "material": material_name,
                    "reason": "connection did not verify",
                    "candidatePath": str(candidate.GetPath()),
                }
            )
        else:
            report["repairs"].append(
                {
                    "materialIndex": material_index,
                    "material": material_name,
                    "sourcePath": str(candidate.GetPath()),
                    "surfacePath": str(surface.GetPath()),
                }
            )
        material = material.GetNext()
        material_index += 1
    c4d.EventAdd()
    return report


def walk_shaders(shader):
    current = shader
    while current:
        yield current
        child = current.GetDown()
        if child:
            yield from walk_shaders(child)
        current = current.GetNext()


def relink_string_parameters(
    node,
    requested_relinks: dict[str, str],
    owner: str,
) -> tuple[list[dict[str, object]], list[c4d.BaseList2D]]:
    """Relink exact string/Filename parameters and expose linked assets."""

    changes: list[dict[str, object]] = []
    linked_assets: list[c4d.BaseList2D] = []
    try:
        description = node.GetDescription(c4d.DESCFLAGS_DESC_0)
    except Exception:
        return changes, linked_assets
    for container, desc_id, _group_id in description:
        try:
            current_value = node.GetParameter(
                desc_id, c4d.DESCFLAGS_GET_0
            )
        except Exception:
            continue
        if isinstance(current_value, c4d.BaseList2D):
            linked_assets.append(current_value)
            continue
        current_text = str(current_value)
        matched_required_path = current_text
        target_value = None
        for candidate in node_asset_value_candidates(current_text):
            target_value = requested_relinks.get(candidate)
            if target_value is not None:
                matched_required_path = candidate
                break
        if not target_value:
            continue
        filename_type = getattr(c4d, "Filename", None)
        replacement = (
            filename_type(target_value)
            if (
                filename_type is not None
                and isinstance(current_value, filename_type)
            )
            else target_value
        )
        try:
            changed = node.SetParameter(
                desc_id, replacement, c4d.DESCFLAGS_SET_0
            )
        except Exception:
            changed = False
        if not changed:
            continue
        changes.append(
            {
                "owner": owner,
                "parameter": str(
                    container.GetString(c4d.DESC_NAME) or desc_id
                ),
                "requiredPath": matched_required_path,
                "valueBefore": current_text,
                "targetPath": target_value,
            }
        )
    return changes, linked_assets


def relink_material_assets(
    doc, requested_relinks: dict[str, str]
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    linked_assets: list[tuple[c4d.BaseList2D, str]] = []
    material = doc.GetFirstMaterial()
    material_index = 0
    while material:
        owner = f"material[{material_index}]/{material.GetName()}"
        material_changes, material_links = relink_string_parameters(
            material, requested_relinks, owner
        )
        changes.extend(material_changes)
        linked_assets.extend((item, owner) for item in material_links)
        for shader in walk_shaders(material.GetFirstShader()):
            shader_owner = f"{owner}/shader/{shader.GetName()}"
            shader_changes, shader_links = relink_string_parameters(
                shader, requested_relinks, shader_owner
            )
            changes.extend(shader_changes)
            linked_assets.extend(
                (item, shader_owner) for item in shader_links
            )
        material = material.GetNext()
        material_index += 1
    seen: set[int] = set()
    for linked_asset, parent_owner in linked_assets:
        identity = id(linked_asset)
        if identity in seen:
            continue
        seen.add(identity)
        asset_changes, _asset_links = relink_string_parameters(
            linked_asset,
            requested_relinks,
            (
                f"{parent_owner}/linked-asset/"
                f"{linked_asset.GetName()}"
            ),
        )
        changes.extend(asset_changes)
    if changes:
        c4d.EventAdd()
    return changes


def node_asset_value_candidates(value: object) -> list[str]:
    """Return source spellings Redshift and the collector use for one URL."""

    text = str(value or "")
    candidates = [text]
    slash_text = text.replace("\\", "/")
    if slash_text != text:
        candidates.append(slash_text)
    if slash_text.startswith("//"):
        network_path = slash_text[2:]
        candidates.extend(
            (
                network_path,
                "/" + network_path,
                "./" + network_path,
            )
        )
    elif (
        len(slash_text) >= 3
        and slash_text[1] == ":"
        and slash_text[2] == "/"
    ):
        candidates.append("./" + slash_text)
    if text.startswith("relative:///"):
        relative = text[len("relative:///") :]
        candidates.extend((relative, "./" + relative))
    if text.startswith("file:///"):
        rooted_path = text[7:]
        unrooted_path = text[8:]
        candidates.extend(
            (
                rooted_path,
                unrooted_path,
                "./" + unrooted_path,
            )
        )
    elif text.startswith("file://"):
        network_path = text[len("file://") :]
        candidates.extend(
            (network_path, "/" + network_path, "./" + network_path)
        )
        if "/" in network_path:
            _host, path = network_path.split("/", 1)
            candidates.extend(("/" + path, path, "./" + path))
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def relink_node_material_assets(
    doc, requested_relinks: dict[str, str]
) -> list[dict[str, object]]:
    """Relink Redshift Texture Sampler URL ports in memory."""

    changes: list[dict[str, object]] = []
    if not requested_relinks:
        return changes
    node_space_id = "com.redshift3d.redshift4c4d.class.nodespace"
    node_space = maxon.Id(node_space_id)
    material = doc.GetFirstMaterial()
    while material:
        node_material = material.GetNodeMaterialReference()
        try:
            if not node_material.HasSpace(node_space):
                material = material.GetNext()
                continue
            graph = node_material.GetGraph(node_space)
            root = graph.GetRoot()
            ports = list(
                root.GetInnerNodes(maxon.NODE_KIND.ALL_MASK, True)
            )
        except Exception:
            material = material.GetNext()
            continue
        pending: list[tuple[object, str, str]] = []
        for port in ports:
            try:
                current_candidates = node_asset_value_candidates(
                    port.GetPortValue()
                )
            except Exception:
                continue
            current = current_candidates[0] if current_candidates else ""
            target = None
            matched_required_path = current
            for candidate in current_candidates:
                target = requested_relinks.get(candidate)
                if target is not None:
                    matched_required_path = candidate
                    break
            if target is None:
                continue
            pending.append((port, matched_required_path, target))
        if pending:
            with graph.BeginTransaction() as transaction:
                for port, current, target in pending:
                    port.SetPortValue(maxon.Url(target))
                    changes.append(
                        {
                            "owner": material.GetName(),
                            "nodeSpace": node_space_id,
                            "nodePath": str(port.GetPath()),
                            "requiredPath": current,
                            "targetPath": target,
                        }
                    )
                transaction.Commit()
        material = material.GetNext()
    if changes:
        c4d.EventAdd()
    return changes


def set_node_boolean_ports(
    doc, requested_overrides: list[str]
) -> list[dict[str, object]]:
    """Set explicitly requested existing boolean ports for one render.

    This is a narrow source-era compatibility diagnostic. It does not create
    nodes, ports, or connections, and callers must identify both the material
    index and the complete authored port path.
    """

    changes: list[dict[str, object]] = []
    if not requested_overrides:
        return changes
    parsed: list[tuple[int, str, bool]] = []
    for spec in requested_overrides:
        try:
            raw_index, port_path, raw_value = spec.split("|", 2)
            material_index = int(raw_index)
        except (ValueError, TypeError) as error:
            raise RuntimeError(
                "--set-node-bool must be "
                "MATERIAL_INDEX|PORT_PATH|true|false; "
                f"received {spec!r}"
            ) from error
        folded_value = raw_value.casefold()
        if folded_value not in {"true", "false"}:
            raise RuntimeError(
                "--set-node-bool value must be true or false; "
                f"received {spec!r}"
            )
        parsed.append((material_index, port_path, folded_value == "true"))

    node_space_id = "com.redshift3d.redshift4c4d.class.nodespace"
    node_space = maxon.Id(node_space_id)

    def parse_boolean_port_value(value) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value).strip().casefold()
        if text in {"true", "1"}:
            return True
        if text in {"false", "0"}:
            return False
        raise RuntimeError(
            "Could not parse Redshift boolean port value: "
            f"{type(value).__name__}({value!s})"
        )

    materials: list[c4d.BaseMaterial] = []
    material = doc.GetFirstMaterial()
    while material:
        materials.append(material)
        material = material.GetNext()
    for material_index, port_path, requested_value in parsed:
        if material_index < 0 or material_index >= len(materials):
            raise RuntimeError(
                f"Node-port material index not found: {material_index}"
            )
        material = materials[material_index]
        reference = material.GetNodeMaterialReference()
        if not reference.HasSpace(node_space):
            raise RuntimeError(
                "Requested node-port material has no Redshift graph: "
                f"material[{material_index}]/{material.GetName()}"
            )
        graph = reference.GetGraph(node_space)
        root = graph.GetRoot()
        port = next(
            (
                item
                for item in root.GetInnerNodes(
                    maxon.NODE_KIND.ALL_MASK, True
                )
                if str(item.GetPath()) == port_path
            ),
            None,
        )
        if port is None:
            raise RuntimeError(
                "Requested authored node port not found: "
                f"material[{material_index}]/{material.GetName()} · "
                f"{port_path}"
            )
        value_before = port.GetPortValue()
        with graph.BeginTransaction() as transaction:
            port.SetPortValue(requested_value)
            transaction.Commit()
        value_after = port.GetPortValue()
        parsed_value_before = parse_boolean_port_value(value_before)
        parsed_value_after = parse_boolean_port_value(value_after)
        if parsed_value_after != requested_value:
            raise RuntimeError(
                "Requested node boolean did not verify: "
                f"{port_path} -> {value_after!r}"
            )
        changes.append(
            {
                "materialIndex": material_index,
                "material": material.GetName(),
                "nodeSpace": node_space_id,
                "portPath": port_path,
                "valueBefore": parsed_value_before,
                "valueAfter": parsed_value_after,
                "rawValueBefore": str(value_before),
                "rawValueAfter": str(value_after),
                "rawValueTypeBefore": type(value_before).__name__,
                "rawValueTypeAfter": type(value_after).__name__,
            }
        )
    return changes


def disconnect_node_input_ports(
    doc, requested_ports: list[str]
) -> list[dict[str, object]]:
    """Temporarily remove existing value wires from exact input ports."""

    changes: list[dict[str, object]] = []
    if not requested_ports:
        return changes
    parsed: list[tuple[int, str]] = []
    for spec in requested_ports:
        try:
            raw_index, port_path = spec.split("|", 1)
            material_index = int(raw_index)
        except (ValueError, TypeError) as error:
            raise RuntimeError(
                "--disconnect-node-input must be MATERIAL_INDEX|PORT_PATH; "
                f"received {spec!r}"
            ) from error
        parsed.append((material_index, port_path))

    node_space_id = "com.redshift3d.redshift4c4d.class.nodespace"
    node_space = maxon.Id(node_space_id)
    materials: list[c4d.BaseMaterial] = []
    material = doc.GetFirstMaterial()
    while material:
        materials.append(material)
        material = material.GetNext()
    for material_index, port_path in parsed:
        if material_index < 0 or material_index >= len(materials):
            raise RuntimeError(
                f"Node-input material index not found: {material_index}"
            )
        material = materials[material_index]
        reference = material.GetNodeMaterialReference()
        if not reference.HasSpace(node_space):
            raise RuntimeError(
                "Requested node-input material has no Redshift graph: "
                f"material[{material_index}]/{material.GetName()}"
            )
        graph = reference.GetGraph(node_space)
        root = graph.GetRoot()
        port = next(
            (
                item
                for item in root.GetInnerNodes(
                    maxon.NODE_KIND.ALL_MASK, True
                )
                if str(item.GetPath()) == port_path
            ),
            None,
        )
        if port is None:
            raise RuntimeError(
                "Requested authored node input not found: "
                f"material[{material_index}]/{material.GetName()} · "
                f"{port_path}"
            )
        connections = [
            (source, wires)
            for source, wires in port.GetConnections(maxon.PORT_DIR.INPUT)
            if "Value:0" not in str(wires)
        ]
        if connections:
            with graph.BeginTransaction() as transaction:
                for source, _wires in connections:
                    maxon.GraphModelHelper.RemoveConnection(source, port)
                transaction.Commit()
        remaining = [
            (source, wires)
            for source, wires in port.GetConnections(maxon.PORT_DIR.INPUT)
            if "Value:0" not in str(wires)
        ]
        if remaining:
            raise RuntimeError(
                "Requested node input still has value connections: "
                f"{port_path}"
            )
        changes.append(
            {
                "materialIndex": material_index,
                "material": material.GetName(),
                "nodeSpace": node_space_id,
                "portPath": port_path,
                "removedSourcePaths": [
                    str(source.GetPath()) for source, _wires in connections
                ],
            }
        )
    return changes


def relink_scene_assets(
    doc, requested_relinks: dict[str, str]
) -> list[dict[str, object]]:
    """Relink exact Filename/string parameters on objects and tags."""

    changes: list[dict[str, object]] = []
    linked_assets: list[tuple[c4d.BaseList2D, str]] = []
    for scene_object in walk_objects(doc.GetFirstObject()):
        owner = f"object/{object_path(scene_object)}"
        object_changes, object_links = relink_string_parameters(
            scene_object, requested_relinks, owner
        )
        changes.extend(object_changes)
        linked_assets.extend((item, owner) for item in object_links)
        get_first_shader = getattr(scene_object, "GetFirstShader", None)
        if callable(get_first_shader):
            for shader in walk_shaders(get_first_shader()):
                shader_owner = f"{owner}/shader/{shader.GetName()}"
                shader_changes, shader_links = relink_string_parameters(
                    shader,
                    requested_relinks,
                    shader_owner,
                )
                changes.extend(shader_changes)
                linked_assets.extend(
                    (item, shader_owner) for item in shader_links
                )
        if scene_object.GetType() == REDSHIFT_PROXY_OBJECT_ID:
            desc_id = c4d.DescID(
                c4d.DescLevel(
                    10000,
                    REDSHIFT_RSFILE_DATATYPE_ID,
                    scene_object.GetType(),
                ),
                c4d.DescLevel(
                    getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                    c4d.DTYPE_FILENAME,
                    0,
                ),
            )
            try:
                original_value = scene_object.GetParameter(
                    desc_id, c4d.DESCFLAGS_GET_0
                )
            except Exception:
                original_value = None
            current = str(original_value or "")
            candidates = [
                current,
                "./" + current if current else "",
                current[2:] if current.startswith("./") else "",
            ]
            target = None
            matched_required_path = current
            for candidate in candidates:
                target = requested_relinks.get(candidate)
                if target:
                    matched_required_path = candidate
                    break
            if target:
                try:
                    changed = scene_object.SetParameter(
                        desc_id,
                        str(target),
                        c4d.DESCFLAGS_SET_0,
                    )
                    scene_object.Message(c4d.MSG_UPDATE)
                    verified = str(
                        scene_object.GetParameter(
                            desc_id, c4d.DESCFLAGS_GET_0
                        )
                        or ""
                    )
                except Exception:
                    changed = False
                    verified = ""
                if changed:
                    changes.append(
                        {
                            "owner": owner,
                            "parameter": "RS_PROXY_FILE/10000",
                            "requiredPath": matched_required_path,
                            "targetPath": target,
                            "verifiedPath": verified,
                        }
                    )
        if scene_object.GetType() == REDSHIFT_VOLUME_OBJECT_ID:
            desc_id = c4d.DescID(
                c4d.DescLevel(
                    10000,
                    REDSHIFT_RSFILE_DATATYPE_ID,
                    scene_object.GetType(),
                ),
                c4d.DescLevel(
                    getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                    c4d.DTYPE_FILENAME,
                    0,
                ),
            )
            try:
                original_value = scene_object.GetParameter(
                    desc_id, c4d.DESCFLAGS_GET_0
                )
            except Exception:
                original_value = None
            current = str(original_value or "")
            target = None
            matched_required_path = current
            candidates = node_asset_value_candidates(current)
            if current and not current.startswith(("./", "/")):
                candidates.append("./" + current)
            for candidate in candidates:
                target = requested_relinks.get(candidate)
                if target:
                    matched_required_path = candidate
                    break
            if target:
                try:
                    changed = scene_object.SetParameter(
                        desc_id,
                        str(target),
                        c4d.DESCFLAGS_SET_0,
                    )
                    scene_object.Message(c4d.MSG_UPDATE)
                    verified = str(
                        scene_object.GetParameter(
                            desc_id, c4d.DESCFLAGS_GET_0
                        )
                        or ""
                    )
                except Exception:
                    changed = False
                    verified = ""
                if changed:
                    changes.append(
                        {
                            "owner": owner,
                            "parameter": "RS_VOLUME_FILE/10000",
                            "requiredPath": matched_required_path,
                            "targetPath": target,
                            "verifiedPath": verified,
                        }
                    )
        if scene_object.GetType() == REDSHIFT_LIGHT_OBJECT_ID:
            for parameter_id in (
                11001,
                11026,
                12000,
                12008,
                13000,
            ):
                desc_id = c4d.DescID(
                    c4d.DescLevel(
                        parameter_id,
                        REDSHIFT_RSFILE_DATATYPE_ID,
                        scene_object.GetType(),
                    ),
                    c4d.DescLevel(
                        getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                        c4d.DTYPE_FILENAME,
                        0,
                    ),
                )
                try:
                    original_value = scene_object.GetParameter(
                        desc_id, c4d.DESCFLAGS_GET_0
                    )
                except Exception:
                    continue
                current = str(original_value or "")
                candidates = [
                    current,
                    "./" + current if current else "",
                    current[2:] if current.startswith("./") else "",
                ]
                target = None
                matched_required_path = current
                for candidate in candidates:
                    target = requested_relinks.get(candidate)
                    if target:
                        matched_required_path = candidate
                        break
                if not target:
                    continue
                try:
                    changed = scene_object.SetParameter(
                        desc_id,
                        str(target),
                        c4d.DESCFLAGS_SET_0,
                    )
                    scene_object.Message(c4d.MSG_UPDATE)
                    verified = str(
                        scene_object.GetParameter(
                            desc_id, c4d.DESCFLAGS_GET_0
                        )
                        or ""
                    )
                except Exception:
                    continue
                if not changed:
                    continue
                changes.append(
                    {
                        "owner": owner,
                        "parameter": f"RSFILE/{parameter_id}",
                        "requiredPath": matched_required_path,
                        "targetPath": target,
                        "verifiedPath": verified,
                    }
                )
        if scene_object.GetType() == LEGACY_RS_CAMERA_OBJECT_ID:
            parameter_id = 13003
            desc_id = c4d.DescID(
                c4d.DescLevel(
                    parameter_id,
                    REDSHIFT_RSFILE_DATATYPE_ID,
                    scene_object.GetType(),
                ),
                c4d.DescLevel(
                    getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                    c4d.DTYPE_FILENAME,
                    0,
                ),
            )
            try:
                original_value = scene_object.GetParameter(
                    desc_id, c4d.DESCFLAGS_GET_0
                )
            except Exception:
                original_value = None
            current = str(original_value or "")
            target = None
            matched_required_path = current
            for candidate in node_asset_value_candidates(current):
                target = requested_relinks.get(candidate)
                if target:
                    matched_required_path = candidate
                    break
            if target:
                try:
                    changed = scene_object.SetParameter(
                        desc_id,
                        str(target),
                        c4d.DESCFLAGS_SET_0,
                    )
                    scene_object.Message(c4d.MSG_UPDATE)
                    verified = str(
                        scene_object.GetParameter(
                            desc_id, c4d.DESCFLAGS_GET_0
                        )
                        or ""
                    )
                except Exception:
                    changed = False
                    verified = ""
                if changed:
                    changes.append(
                        {
                            "owner": owner,
                            "parameter": "RSFILE/13003",
                            "requiredPath": matched_required_path,
                            "targetPath": target,
                            "verifiedPath": verified,
                        }
                    )
        tag = scene_object.GetFirstTag()
        while tag:
            tag_owner = f"{owner}/tag/{tag.GetName()}"
            tag_changes, tag_links = relink_string_parameters(
                tag,
                requested_relinks,
                tag_owner,
            )
            changes.extend(tag_changes)
            linked_assets.extend(
                (item, tag_owner) for item in tag_links
            )
            tag = tag.GetNext()
    seen_linked_assets: set[int] = set()
    while linked_assets:
        linked_asset, parent_owner = linked_assets.pop(0)
        identity = id(linked_asset)
        if identity in seen_linked_assets:
            continue
        seen_linked_assets.add(identity)
        asset_owner = (
            f"{parent_owner}/linked-asset/{linked_asset.GetName()}"
        )
        asset_changes, nested_links = relink_string_parameters(
            linked_asset,
            requested_relinks,
            asset_owner,
        )
        changes.extend(asset_changes)
        linked_assets.extend(
            (item, asset_owner) for item in nested_links
        )
        get_first_shader = getattr(linked_asset, "GetFirstShader", None)
        if callable(get_first_shader):
            for shader in walk_shaders(get_first_shader()):
                shader_owner = (
                    f"{asset_owner}/shader/{shader.GetName()}"
                )
                shader_changes, shader_links = relink_string_parameters(
                    shader,
                    requested_relinks,
                    shader_owner,
                )
                changes.extend(shader_changes)
                linked_assets.extend(
                    (item, shader_owner) for item in shader_links
                )
    if changes:
        c4d.EventAdd()
    return changes


def freeze_redshift_proxy_frames(
    doc, specifications: list[str]
) -> list[dict[str, object]]:
    """Point exact Redshift proxy objects at single verified cache frames.

    This is an in-memory proof operation for sparse recovery: the proxy path
    is changed to one exact ``.rs`` file and animation mode is set to static.
    The loaded source document is never saved.
    """

    changes: list[dict[str, object]] = []
    for specification in specifications:
        try:
            target_object, target_value = specification.rsplit("|", 1)
        except ValueError as error:
            raise RuntimeError(
                "--freeze-redshift-proxy must be "
                "OBJECT_PATH|TARGET_RS_FILE; "
                f"received {specification!r}"
            ) from error
        target_path = Path(target_value).expanduser().resolve()
        unsafe_reason = unsafe_relink_target_reason(str(target_path))
        if unsafe_reason:
            raise RuntimeError(
                "Unsafe Redshift proxy target rejected "
                f"({unsafe_reason}): {target_path}"
            )
        if not target_path.is_file() or target_path.suffix.casefold() != ".rs":
            raise RuntimeError(
                "Frozen Redshift proxy target must be an existing .rs file: "
                f"{target_path}"
            )
        proxy = find_object(doc, target_object)
        if proxy is None:
            raise RuntimeError(
                f"Redshift proxy object {target_object!r} not found"
            )
        if proxy.GetType() != REDSHIFT_PROXY_OBJECT_ID:
            raise RuntimeError(
                f"Target is not a Redshift proxy: {object_path(proxy)}"
            )
        path_desc = c4d.DescID(
            c4d.DescLevel(
                10000,
                REDSHIFT_RSFILE_DATATYPE_ID,
                proxy.GetType(),
            ),
            c4d.DescLevel(
                getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                c4d.DTYPE_FILENAME,
                0,
            ),
        )
        mode_desc = c4d.DescID(
            c4d.DescLevel(
                10000,
                REDSHIFT_RSFILE_DATATYPE_ID,
                proxy.GetType(),
            ),
            c4d.DescLevel(
                getattr(c4d, "REDSHIFT_FILE_ANIMATION_MODE", 1001),
                c4d.DTYPE_LONG,
                0,
            ),
        )
        original_path = str(
            proxy.GetParameter(path_desc, c4d.DESCFLAGS_GET_0) or ""
        )
        original_mode = int(
            proxy.GetParameter(mode_desc, c4d.DESCFLAGS_GET_0) or 0
        )
        path_changed = proxy.SetParameter(
            path_desc,
            str(target_path),
            c4d.DESCFLAGS_SET_0,
        )
        mode_changed = proxy.SetParameter(
            mode_desc,
            0,
            c4d.DESCFLAGS_SET_0,
        )
        proxy.Message(c4d.MSG_UPDATE)
        verified_path = str(
            proxy.GetParameter(path_desc, c4d.DESCFLAGS_GET_0) or ""
        )
        verified_mode = int(
            proxy.GetParameter(mode_desc, c4d.DESCFLAGS_GET_0) or 0
        )
        verified_url = urlparse(verified_path)
        verified_local_value = (
            unquote(verified_url.path)
            if verified_url.scheme.casefold() == "file"
            else verified_path
        )
        verified_local_path = (
            Path(verified_local_value).expanduser().resolve()
        )
        if verified_local_path != target_path:
            raise RuntimeError(
                "Frozen Redshift proxy path did not verify: "
                f"{verified_path}"
            )
        if verified_mode != 0:
            raise RuntimeError(
                "Frozen Redshift proxy animation mode did not verify: "
                f"{verified_mode}"
            )
        changes.append(
            {
                "objectPath": object_path(proxy),
                "originalPath": original_path,
                "originalAnimationMode": original_mode,
                "targetPath": str(target_path),
                "targetBytes": target_path.stat().st_size,
                "pathChanged": bool(path_changed),
                "animationModeChanged": bool(mode_changed),
                "verifiedPath": verified_path,
                "verifiedLocalPath": str(verified_local_path),
                "verifiedAnimationMode": verified_mode,
                "sourceDocumentSaved": False,
            }
        )
    if changes:
        c4d.EventAdd()
    return changes


def collect_post_relink_assets(doc, project: Path) -> dict[str, object]:
    """Collect the exact asset URLs visible to Cinema after relinking.

    This is intentionally conservative: every unresolved picture dependency is
    reported, even when its owner later turns out to be hidden. A strict proof
    must never be promoted because an owner-usage heuristic hid a node-material
    dependency.
    """

    assets: list[dict[str, object]] = []
    collector_flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    collector_result = c4d.documents.GetAllAssetsNew(
        doc, False, "", collector_flags, assets
    )
    unresolved: list[dict[str, object]] = []
    linked_references = 0
    picture_references = 0
    for asset in assets:
        filename = str(asset.get("filename") or "")
        if not filename:
            continue
        if filename.startswith("asset:///") and "db=Builtin" in filename:
            continue
        suffix = Path(filename).suffix.casefold()
        affects_picture = suffix not in {
            ".aac",
            ".aif",
            ".aiff",
            ".flac",
            ".m4a",
            ".mp3",
            ".ogg",
            ".wav",
        }
        if affects_picture:
            picture_references += 1
        collector_exists = bool(asset.get("exists"))
        resolved_path: str | None = None
        exists = collector_exists
        if collector_exists:
            resolved_path = filename
        else:
            local_value = (
                unquote(urlparse(filename).path)
                if filename.startswith("file://")
                else filename
            )
            candidate = Path(local_value).expanduser()
            candidates = (
                (candidate,)
                if candidate.is_absolute()
                else (
                    project.parent / candidate,
                    project.parent / "tex" / candidate,
                    project.parent / "tex" / candidate.name,
                )
            )
            for item in candidates:
                if item.is_file():
                    exists = True
                    resolved_path = str(item.resolve())
                    break
        if exists:
            linked_references += 1
            continue
        if affects_picture:
            owner = asset.get("owner")
            try:
                owner_name = owner.GetName() if owner else None
            except Exception:
                owner_name = None
            try:
                owner_type_id = int(owner.GetType()) if owner else None
            except Exception:
                owner_type_id = None
            try:
                owner_type_name = str(owner.GetTypeName()) if owner else None
            except Exception:
                owner_type_name = None
            try:
                owner_main = owner.GetMain() if owner else None
                owner_main_name = (
                    owner_main.GetName() if owner_main else None
                )
            except Exception:
                owner_main_name = None
            unresolved.append(
                {
                    "filename": filename,
                    "ownerName": owner_name,
                    "ownerPythonType": type(owner).__name__,
                    "ownerTypeId": owner_type_id,
                    "ownerTypeName": owner_type_name,
                    "ownerMainName": owner_main_name,
                    "nodePath": str(asset.get("nodePath") or ""),
                    "nodeSpace": str(asset.get("nodeSpace") or ""),
                    "parameterId": int(asset.get("paramId", -1) or -1),
                }
            )
    unique_unresolved = sorted(
        {item["filename"] for item in unresolved if item["filename"]}
    )
    return {
        "collectorResult": int(collector_result),
        "assetReferences": len(assets),
        "pictureReferences": picture_references,
        "linkedReferences": linked_references,
        "unresolvedPictureReferences": len(unresolved),
        "unresolvedPictureFiles": len(unique_unresolved),
        "unresolvedPicturePaths": unique_unresolved,
        "unresolvedPictureDependencies": unresolved,
        "strictDependencyRenderSafe": not unresolved,
    }


def all_cameras(doc):
    return [
        op
        for op in walk_objects(doc.GetFirstObject())
        if op.CheckType(c4d.Ocamera)
        or op.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
    ]


def find_camera(
    doc,
    name: str,
    expected_path: str | None = None,
    expected_focal: float | None = None,
):
    cameras = all_cameras(doc)

    def focal_matches(camera) -> bool:
        if expected_focal is None:
            return True
        for parameter_id in (
            getattr(c4d, "RSCAMERAOBJECT_FOCAL_LENGTH", 500),
            getattr(c4d, "CAMERA_FOCUS", 500),
        ):
            try:
                return abs(float(camera[parameter_id]) - expected_focal) < 1e-6
            except Exception:
                continue
        return False

    if expected_path:
        exact_path = next(
            (
                op
                for op in cameras
                if object_path(op) == expected_path and focal_matches(op)
            ),
            None,
        )
        if exact_path:
            return exact_path
    exact = next(
        (
            op
            for op in cameras
            if op.GetName() == name and focal_matches(op)
        ),
        None,
    )
    if exact:
        return exact
    folded = name.casefold()
    return next(
        (
            op
            for op in cameras
            if op.GetName().casefold() == folded and focal_matches(op)
        ),
        None,
    )


def find_object(doc, target: str):
    exact_path = next(
        (
            op
            for op in walk_objects(doc.GetFirstObject())
            if object_path(op) == target
        ),
        None,
    )
    if exact_path:
        return exact_path
    return next(
        (
            op
            for op in walk_objects(doc.GetFirstObject())
            if op.GetName() == target
        ),
        None,
    )


def all_render_data(doc):
    result = []
    current = doc.GetFirstRenderData()
    while current:
        result.append(current)
        current = current.GetNext()
    return result


def find_render_data(doc, name: str):
    records = all_render_data(doc)
    exact = next((item for item in records if item.GetName() == name), None)
    if exact:
        return exact
    folded = name.casefold()
    return next(
        (item for item in records if item.GetName().casefold() == folded),
        None,
    )


def walk_takes(take):
    current = take
    while current:
        yield current
        child = current.GetDown()
        if child:
            yield from walk_takes(child)
        current = current.GetNext()


def find_take(take_data, name: str | None):
    if not take_data or not name:
        return None
    return next(
        (
            take
            for take in walk_takes(take_data.GetMainTake())
            if take.GetName() == name
        ),
        None,
    )


def enumerate_scene(doc) -> dict:
    scene_objects = list(walk_objects(doc.GetFirstObject()))
    top_level_objects = []
    root = doc.GetFirstObject()
    while root:
        top_level_objects.append(
            {
                "name": root.GetName(),
                "path": object_path(root),
                "typeId": root.GetType(),
                "editorMode": root.GetEditorMode(),
                "renderMode": root.GetRenderMode(),
            }
        )
        root = root.GetNext()
    render_records = []
    for item in all_render_data(doc):
        data = item.GetData()
        render_records.append(
            {
                "name": item.GetName(),
                "rendererId": data[c4d.RDATA_RENDERENGINE],
                "path": data[c4d.RDATA_PATH],
                "xres": data[c4d.RDATA_XRES],
                "yres": data[c4d.RDATA_YRES],
            }
        )
    return {
        "fps": doc.GetFps(),
        "cameras": [
            {"name": item.GetName(), "path": object_path(item)}
            for item in all_cameras(doc)
        ],
        "cameraLikeObjects": [
            {
                "name": item.GetName(),
                "path": object_path(item),
                "typeId": item.GetType(),
            }
            for item in scene_objects
            if item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
            or "camera" in item.GetName().casefold()
        ],
        "objectCount": len(scene_objects),
        "topLevelObjects": top_level_objects,
        "renderData": render_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--linear-float-output",
        type=Path,
        help=(
            "Optional 32-bit OpenEXR copy of the RenderDocument beauty "
            "buffer. This preserves the document render-space values for an "
            "exact OCIO display transform; it is never presented as a "
            "display-ready camera proof."
        ),
    )
    parser.add_argument(
        "--raw-render-buffer-output",
        type=Path,
        help=(
            "Optional PFM containing the unprofiled 32-bit RGB values read "
            "directly from the RenderDocument beauty buffer. This is the "
            "authoritative input for the saved Redshift display/view transform."
        ),
    )
    parser.add_argument(
        "--native-save-output",
        type=Path,
        help=(
            "Optional isolated output basename written by Cinema through the "
            "project's native image format and color-management pipeline. "
            "The source render path is never used or modified."
        ),
    )
    parser.add_argument(
        "--render-format-depth",
        type=int,
        choices=(8, 16, 32),
        help=(
            "Temporarily override the cloned render setting's output depth. "
            "This affects only the isolated in-memory render-data copy and is "
            "used to obtain an unquantized diagnostic beauty buffer."
        ),
    )
    parser.add_argument(
        "--bake-ocio-view",
        action="store_true",
        help=(
            "Bake the render data's saved OCIO display/view transform into the "
            "display-ready PNG using Cinema 4D's own color converter. Float and "
            "raw diagnostic outputs remain untouched."
        ),
    )
    parser.add_argument(
        "--render-with-ocio-bake-flag",
        action="store_true",
        help=(
            "Ask RenderDocument to apply Cinema 4D's saved OCIO display/view "
            "transform while producing the beauty bitmap. This diagnostic "
            "path uses RENDERFLAGS_OCIO_BAKE_RENDERING and skips the later "
            "BakeOcioViewToBitmap call to avoid a double transform."
        ),
    )
    parser.add_argument(
        "--render-without-document-clone",
        action="store_true",
        help=(
            "Pass Cinema's RENDERFLAGS_NODOCUMENTCLONE so Redshift consumes "
            "the already evaluated and audited in-memory scene. This is "
            "required when Cinema's internal render clone re-normalizes a "
            "recovered legacy camera after its exact matrix is applied."
        ),
    )
    parser.add_argument(
        "--render-with-source-render-data",
        action="store_true",
        help=(
            "Use the requested RenderData object directly in the isolated "
            "in-memory document instead of cloning it. This preserves "
            "legacy VideoPost-private asset state when cloning the exact "
            "chain makes Cinema report a false asset-missing result. Only "
            "single-frame/output overrides are changed, and the source "
            "document is never saved."
        ),
    )
    parser.add_argument(
        "--skip-post-relink-dependency-audit",
        action="store_true",
        help=(
            "Skip the final GetAllAssetsNew collector call immediately before "
            "RenderDocument. Some legacy documents retain the collector's "
            "non-picture asset-missing status and abort an otherwise valid "
            "picture render. Use only with a separately recorded active-frame "
            "dependency audit; the omission is recorded in the result."
        ),
    )
    parser.add_argument(
        "--save-error-buffer",
        action="store_true",
        help=(
            "When Cinema returns a non-OK render result, save the beauty "
            "buffer as diagnostic evidence before reporting failure. This "
            "never makes the frame proof-eligible."
        ),
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional path for the complete structured render-test result.",
    )
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--camera-path")
    parser.add_argument(
        "--camera-focal-match",
        type=float,
        help=(
            "Disambiguate duplicate authored camera names/paths by exact "
            "evaluated focal length."
        ),
    )
    parser.add_argument(
        "--reconstruct-camera-position",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help=(
            "Create a temporary native camera at this archived world-space "
            "position. Requires --reconstruct-camera-rotation. The source "
            "document is never saved."
        ),
    )
    parser.add_argument(
        "--reconstruct-camera-rotation",
        nargs=3,
        type=float,
        metavar=("H", "P", "B"),
        help=(
            "Set the temporary camera's archived absolute HPB rotation in "
            "radians. Requires --reconstruct-camera-position."
        ),
    )
    parser.add_argument(
        "--reconstruct-camera-focal",
        type=float,
        default=35.0,
        help="Focal length for a temporary reconstructed camera.",
    )
    parser.add_argument(
        "--reconstruct-camera-aperture",
        type=float,
        default=36.0,
        help="Film aperture for a temporary reconstructed camera.",
    )
    parser.add_argument(
        "--reconstruct-camera-from-requested-template",
        action="store_true",
        help=(
            "Clone the requested shot-authored camera before applying the "
            "archived position, rotation, focal length, and aperture. This "
            "retains legacy Redshift camera projection parameters that a "
            "new native camera cannot reproduce. The clone exists only in "
            "memory and all inherited animation tracks are removed."
        ),
    )
    parser.add_argument("--take", default="Main")
    parser.add_argument("--render-data", required=True)
    parser.add_argument(
        "--native-clone-legacy-camera",
        action="store_true",
        help=(
            "Bridge a legacy Redshift camera through a temporary native C4D "
            "camera using its evaluated transform and focal length."
        ),
    )
    parser.add_argument(
        "--apply-codex-camera-matrix-driver",
        action="store_true",
        help=(
            "After scene evaluation, apply the four numeric vectors stored "
            "in the requested camera's named Codex matrix-driver tag. The "
            "tag code is never executed; arbitrary project scripts remain "
            "disabled."
        ),
    )
    parser.add_argument(
        "--grey-override",
        action="store_true",
        help=(
            "Remove texture tags in-memory and add a native proof light so "
            "legacy scenes can yield a neutral geometry/camera proof even "
            "when old Redshift node graphs are incompatible."
        ),
    )
    parser.add_argument(
        "--proof-light-brightness",
        type=float,
        default=2.0,
        help=(
            "Brightness of the temporary proof light used by "
            "--grey-override."
        ),
    )
    parser.add_argument(
        "--enable-object",
        action="append",
        default=[],
        help=(
            "Temporarily force a named object or exact hierarchy path on for "
            "this in-memory test render. The source document is never saved."
        ),
    )
    parser.add_argument(
        "--disable-object",
        action="append",
        default=[],
        help=(
            "Temporarily force a named object or exact hierarchy path off for "
            "this in-memory test render. The source document is never saved."
        ),
    )
    parser.add_argument(
        "--enable-animation-tracks",
        action="append",
        default=[],
        metavar="OBJECT_PATH",
        help=(
            "Temporarily enable every existing CTrack on one exact object "
            "before frame evaluation. This restores authored-but-disabled "
            "animation without creating, retiming, or changing any keys; "
            "the source document is never saved."
        ),
    )
    parser.add_argument(
        "--sample-disabled-animation-tracks",
        action="append",
        default=[],
        metavar="OBJECT_PATH",
        help=(
            "Temporarily set an exact object's parameters to the values of "
            "its existing authored curves at --frame while leaving the "
            "saved disabled-track flags unchanged. This is a still-frame "
            "diagnostic for legacy scenes that crash when disabled tracks "
            "are re-enabled; no keys are created or modified and the source "
            "document is never saved."
        ),
    )
    parser.add_argument(
        "--keep-root",
        action="append",
        default=[],
        help=(
            "For an isolated diagnostic, remove every other top-level object "
            "from the in-memory document before rendering. The source "
            "document is never saved."
        ),
    )
    parser.add_argument(
        "--remove-root",
        action="append",
        default=[],
        help=(
            "Remove one named top-level object from the in-memory diagnostic "
            "before evaluation. Repeat for multiple roots. This can bypass "
            "a legacy simulation container that current Cinema 4D cannot "
            "initialize; the source document is never saved."
        ),
    )
    parser.add_argument(
        "--remove-object",
        action="append",
        default=[],
        metavar="OBJECT_PATH",
        help=(
            "Remove one exact hierarchy path from the in-memory diagnostic "
            "before evaluation. This is intended for an already-disabled "
            "legacy object whose unresolved private dependency still makes "
            "Cinema abort the entire render during asset preflight. The "
            "removed object's saved modes and type are recorded, and the "
            "source document is never saved."
        ),
    )
    parser.add_argument(
        "--offset-object",
        action="append",
        default=[],
        metavar="OBJECT_PATH|X|Y|Z",
        help=(
            "Apply a temporary world-space translation before the in-memory "
            "test render. Repeat for multiple objects; the source document is "
            "never saved."
        ),
    )
    parser.add_argument(
        "--exact-relink",
        action="append",
        default=[],
        metavar="REQUIRED_PATH|TARGET_PATH",
        help=(
            "Temporarily relink an exact Alembic dependency before the "
            "in-memory test render. Repeat for multiple authored caches; "
            "the source document is never saved."
        ),
    )
    parser.add_argument(
        "--exact-material-relink",
        action="append",
        default=[],
        metavar="REQUIRED_PATH|TARGET_PATH",
        help=(
            "Temporarily relink an exact classic-material bitmap or linked "
            "material asset path before the in-memory test render. Repeat "
            "for multiple paths; the source document is never saved."
        ),
    )
    parser.add_argument(
        "--exact-material-relink-manifest",
        type=Path,
        help=(
            "Load exact node-material relinks from a JSON manifest containing "
            "a mappings array of requiredPath/targetPath records. The source "
            "document is never saved."
        ),
    )
    parser.add_argument(
        "--set-node-bool",
        action="append",
        default=[],
        metavar="MATERIAL_INDEX|PORT_PATH|true|false",
        help=(
            "Temporarily set one existing authored Redshift boolean port by "
            "exact material index and full graph path. Repeat for multiple "
            "ports; no nodes or connections are created and the source "
            "document is never saved."
        ),
    )
    parser.add_argument(
        "--disconnect-node-input",
        action="append",
        default=[],
        metavar="MATERIAL_INDEX|PORT_PATH",
        help=(
            "Temporarily remove existing value wires from one exact authored "
            "Redshift input port. The node and its saved constant value are "
            "preserved; the source document is never saved."
        ),
    )
    parser.add_argument(
        "--freeze-redshift-proxy",
        action="append",
        default=[],
        metavar="OBJECT_PATH|TARGET_RS_FILE",
        help=(
            "Temporarily point one exact Redshift proxy object at a single "
            "verified .rs cache frame and set its animation mode to static. "
            "Repeat for multiple proxies; the source document is never saved."
        ),
    )
    parser.add_argument(
        "--donor-material-project",
        type=Path,
        help=(
            "Load selected modern materials from this separate C4D project "
            "and clone them only into the in-memory render document."
        ),
    )
    parser.add_argument(
        "--donor-material",
        action="append",
        default=[],
        help=(
            "Exact material name to clone from --donor-material-project. "
            "Repeat for multiple donor materials."
        ),
    )
    parser.add_argument(
        "--replace-material-tag",
        action="append",
        default=[],
        metavar=(
            "OBJECT_PATH|RESTRICTION|OLD_MATERIAL|DONOR_MATERIAL"
        ),
        help=(
            "Redirect one exact object material tag to a cloned donor "
            "material for this in-memory render."
        ),
    )
    parser.add_argument(
        "--remove-replaced-materials",
        action="store_true",
        help=(
            "Remove legacy materials after all of their exact target tags "
            "have been redirected. This affects only the in-memory render "
            "document."
        ),
    )
    parser.add_argument(
        "--replace-material-name-with-current-rs",
        action="append",
        default=[],
        help=(
            "Redirect every texture tag using this exact material name to a "
            "temporary current-version Redshift Standard material. Repeat "
            "for multiple names. This is an in-memory diagnostic only."
        ),
    )
    parser.add_argument(
        "--repair-missing-rs-surface-output",
        action="store_true",
        help=(
            "Reconnect known terminal Redshift shaders to empty material "
            "surface outputs in memory. Already-connected graphs are left "
            "unchanged and the source document is never saved."
        ),
    )
    parser.add_argument(
        "--repair-missing-rs-surface-material",
        action="append",
        default=[],
        help=(
            "Apply the empty-surface reconnection only to this exact material "
            "name. Repeat for multiple names. The source document is never "
            "saved."
        ),
    )
    parser.add_argument(
        "--diagnostic-material-color",
        nargs=3,
        type=float,
        default=(0.12, 0.55, 0.9),
        metavar=("R", "G", "B"),
        help=(
            "Linear 0..1 RGB color for the temporary current Redshift "
            "diagnostic material."
        ),
    )
    parser.add_argument(
        "--simulation-start-frame",
        type=int,
        help=(
            "Evaluate every frame from this frame through --frame before "
            "rendering, matching sequential batch-render state."
        ),
    )
    parser.add_argument("--simulation-frame-step", type=int, default=1)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=405)
    args = parser.parse_args()
    if args.proof_light_brightness < 0.0:
        parser.error("--proof-light-brightness cannot be negative")
    if bool(args.reconstruct_camera_position) != bool(
        args.reconstruct_camera_rotation
    ):
        parser.error(
            "--reconstruct-camera-position and "
            "--reconstruct-camera-rotation must be provided together"
        )
    if bool(args.donor_material_project) != bool(args.donor_material):
        parser.error(
            "--donor-material-project and at least one --donor-material "
            "must be provided together"
        )
    if args.replace_material_tag and not args.donor_material_project:
        parser.error(
            "--replace-material-tag requires --donor-material-project"
        )
    if any(
        component < 0.0 or component > 1.0
        for component in args.diagnostic_material_color
    ):
        parser.error("--diagnostic-material-color components must be 0..1")

    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    linear_float_output = (
        args.linear_float_output.expanduser().resolve()
        if args.linear_float_output is not None
        else None
    )
    raw_render_buffer_output = (
        args.raw_render_buffer_output.expanduser().resolve()
        if args.raw_render_buffer_output is not None
        else None
    )
    if not project.exists():
        raise FileNotFoundError(project)

    started = time.time()
    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), load_flags)
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")

    result = {"status": "failed", "project": str(project)}
    try:
        c4d.documents.SetActiveDocument(doc)
        donor_material_import = None
        if args.donor_material_project is not None:
            donor_project = (
                args.donor_material_project.expanduser().resolve()
            )
            if not donor_project.is_file():
                raise FileNotFoundError(donor_project)
            donor_material_import = import_and_assign_donor_materials(
                doc,
                donor_project,
                args.donor_material,
                args.replace_material_tag,
                args.remove_replaced_materials,
            )
        result["donorMaterialImport"] = donor_material_import
        removed_roots = []
        remove_roots = set(args.remove_root)
        if remove_roots:
            roots = []
            current_root = doc.GetFirstObject()
            while current_root:
                roots.append(current_root)
                current_root = current_root.GetNext()
            for root in roots:
                if root.GetName() in remove_roots:
                    removed_roots.append(root.GetName())
                    root.Remove()
        if args.keep_root:
            keep_roots = set(args.keep_root)
            roots = []
            current_root = doc.GetFirstObject()
            while current_root:
                roots.append(current_root)
                current_root = current_root.GetNext()
            for root in roots:
                if root.GetName() not in keep_roots:
                    removed_roots.append(root.GetName())
                    root.Remove()
        removed_objects = []
        for target in args.remove_object:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(f"Object {target!r} not found")
            removed_objects.append(
                {
                    "objectPath": object_path(scene_object),
                    "name": scene_object.GetName(),
                    "typeId": scene_object.GetType(),
                    "editorMode": scene_object.GetEditorMode(),
                    "renderMode": scene_object.GetRenderMode(),
                }
            )
            scene_object.Remove()
        inventory = enumerate_scene(doc)
        result["inventory"] = inventory

        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        elif args.take and args.take != "Main":
            raise RuntimeError(f"Take {args.take!r} not found")
        requested_relinks = {}
        for spec in args.exact_relink:
            try:
                required_path, target_path = spec.split("|", 1)
            except ValueError as error:
                raise RuntimeError(
                    "--exact-relink must be REQUIRED_PATH|TARGET_PATH; "
                    f"received {spec!r}"
                ) from error
            if not required_path or not target_path:
                raise RuntimeError(
                    "--exact-relink requires two non-empty paths; "
                    f"received {spec!r}"
                )
            unsafe_reason = unsafe_relink_target_reason(target_path)
            if unsafe_reason:
                raise RuntimeError(
                    "Unsafe dependency relink target rejected "
                    f"({unsafe_reason}): {target_path}"
                )
            requested_relinks[required_path] = target_path
        temporary_dependency_relinks = []
        if requested_relinks:
            for scene_object in walk_objects(doc.GetFirstObject()):
                if scene_object.GetType() != 1028083:
                    continue
                parameter = c4d.DescID(1000)
                current_value = str(scene_object[parameter])
                target_value = requested_relinks.get(current_value)
                if not target_value:
                    continue
                original_value = scene_object[parameter]
                filename_type = getattr(c4d, "Filename", None)
                scene_object[parameter] = (
                    filename_type(target_value)
                    if filename_type is not None
                    else target_value
                )
                scene_object.Message(c4d.MSG_UPDATE)
                temporary_dependency_relinks.append(
                    {
                        "objectPath": object_path(scene_object),
                        "requiredPath": str(original_value),
                        "targetPath": str(scene_object[parameter]),
                    }
                )
            c4d.EventAdd()
        requested_material_relinks = {}
        for spec in args.exact_material_relink:
            try:
                required_path, target_path = spec.split("|", 1)
            except ValueError as error:
                raise RuntimeError(
                    "--exact-material-relink must be "
                    "REQUIRED_PATH|TARGET_PATH; "
                    f"received {spec!r}"
                ) from error
            if not required_path or not target_path:
                raise RuntimeError(
                    "--exact-material-relink requires two non-empty paths; "
                    f"received {spec!r}"
                )
            unsafe_reason = unsafe_relink_target_reason(target_path)
            if unsafe_reason:
                raise RuntimeError(
                    "Unsafe material relink target rejected "
                    f"({unsafe_reason}): {target_path}"
                )
            requested_material_relinks[required_path] = target_path
        if args.exact_material_relink_manifest is not None:
            manifest_path = (
                args.exact_material_relink_manifest.expanduser().resolve()
            )
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            manifest_mappings, unsafe_manifest_mappings = (
                safe_manifest_mappings(manifest)
            )
            if unsafe_manifest_mappings:
                raise RuntimeError(
                    "Unsafe relink manifest target rejected: "
                    + json.dumps(
                        unsafe_manifest_mappings[:12],
                        separators=(",", ":"),
                    )
                )
            requested_material_relinks.update(manifest_mappings)
        temporary_material_relinks = relink_material_assets(
            doc, requested_material_relinks
        )
        temporary_material_relinks.extend(
            relink_node_material_assets(doc, requested_material_relinks)
        )
        temporary_scene_material_relinks = relink_scene_assets(
            doc, requested_material_relinks
        )
        temporary_node_boolean_overrides = set_node_boolean_ports(
            doc, args.set_node_bool
        )
        temporary_node_input_disconnects = disconnect_node_input_ports(
            doc, args.disconnect_node_input
        )
        frozen_redshift_proxies = freeze_redshift_proxy_frames(
            doc, args.freeze_redshift_proxy
        )
        sampled_disabled_animation_tracks = []
        enabled_animation_tracks = []
        # Legacy Redshift camera objects can be animated and take-overridden.
        # Evaluate the requested frame/take before cloning one into a native
        # camera; cloning at the document's load-time frame silently freezes
        # the wrong camera matrix for animated shots.
        fps = doc.GetFps()
        simulation_frames_stepped = 0
        if args.simulation_start_frame is not None:
            if args.simulation_start_frame > args.frame:
                raise RuntimeError(
                    "--simulation-start-frame cannot exceed --frame"
                )
            frame_step = max(1, args.simulation_frame_step)
            frames = list(
                range(args.simulation_start_frame, args.frame + 1, frame_step)
            )
            if not frames or frames[-1] != args.frame:
                frames.append(args.frame)
            for frame in frames:
                doc.SetTime(c4d.BaseTime(frame, fps))
                doc.ExecutePasses(
                    None,
                    True,
                    True,
                    True,
                    c4d.BUILDFLAGS_EXTERNALRENDERER,
                )
                simulation_frames_stepped += 1
        else:
            doc.SetTime(c4d.BaseTime(args.frame, fps))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        # Some old Alembic generator hierarchies crash when their disabled
        # animation tracks are switched on before the document has completed
        # one stable evaluation pass. Initialize the saved scene first, then
        # enable only the explicitly requested authored tracks. The later
        # camera/render evaluation pass consumes the newly enabled curves.
        for target in args.enable_animation_tracks:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(f"Object {target!r} not found")
            track_records = []
            for track in scene_object.GetCTracks():
                description = track.GetDescriptionID()
                was_off = bool(track[c4d.ID_CTRACK_ANIMOFF])
                track[c4d.ID_CTRACK_ANIMOFF] = False
                track.Message(c4d.MSG_UPDATE)
                track_records.append(
                    {
                        "description": [
                            int(description[index].id)
                            for index in range(description.GetDepth())
                        ],
                        "keyCount": (
                            track.GetCurve().GetKeyCount()
                            if track.GetCurve() is not None
                            else 0
                        ),
                        "wasAnimationOff": was_off,
                        "isAnimationOff": bool(
                            track[c4d.ID_CTRACK_ANIMOFF]
                        ),
                    }
                )
            if not track_records:
                raise RuntimeError(
                    f"Object {target!r} has no animation tracks"
                )
            scene_object.Message(c4d.MSG_UPDATE)
            enabled_animation_tracks.append(
                {
                    "objectPath": object_path(scene_object),
                    "tracks": track_records,
                }
            )
        if enabled_animation_tracks:
            c4d.EventAdd()
        # Some legacy render-time scenes contain the complete authored motion
        # curves but save them disabled. Let the document initialize in its
        # stable saved state first, then sample only the requested exact
        # objects at the target frame. Re-enabling these tracks before the
        # first pass can crash old Alembic generator hierarchies.
        sample_time = c4d.BaseTime(args.frame, fps)
        for target in args.sample_disabled_animation_tracks:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(f"Object {target!r} not found")
            track_records = []
            sampled_vectors = {
                903: c4d.Vector(scene_object.GetRelPos()),
                904: c4d.Vector(scene_object.GetRelRot()),
                905: c4d.Vector(scene_object.GetRelScale()),
            }
            sampled_vector_ids = set()
            for track in scene_object.GetCTracks():
                curve = track.GetCurve()
                if curve is None:
                    continue
                description = track.GetDescriptionID()
                value = float(curve.GetValue(sample_time))
                was_off = bool(track[c4d.ID_CTRACK_ANIMOFF])
                parameter_ids = [
                    int(description[index].id)
                    for index in range(description.GetDepth())
                ]
                if (
                    len(parameter_ids) >= 2
                    and parameter_ids[0] in sampled_vectors
                    and parameter_ids[1] in (1000, 1001, 1002)
                ):
                    component = parameter_ids[1] - 1000
                    sampled_vectors[parameter_ids[0]][component] = value
                    sampled_vector_ids.add(parameter_ids[0])
                elif not scene_object.SetParameter(
                    description,
                    value,
                    getattr(c4d, "DESCFLAGS_SET_0", 0),
                ):
                    raise RuntimeError(
                        "Could not sample authored curve for "
                        f"{target!r} at {parameter_ids}"
                    )
                track_records.append(
                    {
                        "description": parameter_ids,
                        "keyCount": curve.GetKeyCount(),
                        "sampledFrame": args.frame,
                        "sampledValue": value,
                        "animationOff": was_off,
                    }
                )
            if 903 in sampled_vector_ids:
                scene_object.SetRelPos(sampled_vectors[903])
            if 904 in sampled_vector_ids:
                scene_object.SetRelRot(sampled_vectors[904])
            if 905 in sampled_vector_ids:
                scene_object.SetRelScale(sampled_vectors[905])
            if not track_records:
                raise RuntimeError(
                    f"Object {target!r} has no animation curves"
                )
            scene_object.Message(c4d.MSG_UPDATE)
            sampled_disabled_animation_tracks.append(
                {
                    "objectPath": object_path(scene_object),
                    "tracks": track_records,
                }
            )
        if sampled_disabled_animation_tracks:
            c4d.EventAdd()
        camera = find_camera(
            doc,
            args.camera,
            args.camera_path,
            args.camera_focal_match,
        )
        fallback_to_take_camera = False
        if (
            camera is None
            and args.camera_focal_match is None
            and take_data
            and take
        ):
            effective_camera = take.GetEffectiveCamera(take_data)
            camera = (
                effective_camera[0]
                if isinstance(effective_camera, tuple)
                else effective_camera
            )
            fallback_to_take_camera = camera is not None
        render_data = find_render_data(doc, args.render_data)
        camera_reconstructed_from_arguments = False
        camera_reconstruction_template_path = None
        camera_reconstruction_template_type = None
        if args.reconstruct_camera_position:
            if args.reconstruct_camera_from_requested_template:
                if camera is None:
                    raise RuntimeError(
                        "Requested camera template is absent from the project"
                    )
                camera_reconstruction_template_path = object_path(camera)
                camera_reconstruction_template_type = camera.GetType()
                camera = camera.GetClone(
                    getattr(c4d, "COPYFLAGS_NONE", 0)
                )
                track = camera.GetFirstCTrack()
                while track:
                    next_track = track.GetNext()
                    track.Remove()
                    track = next_track
            else:
                camera = c4d.BaseObject(c4d.Ocamera)
            camera.SetName(args.camera + " CODEX ARCHIVE RECONSTRUCTION")
            camera.SetAbsPos(c4d.Vector(*args.reconstruct_camera_position))
            camera.SetAbsRot(c4d.Vector(*args.reconstruct_camera_rotation))
            camera[c4d.CAMERA_FOCUS] = args.reconstruct_camera_focal
            camera[c4d.CAMERAOBJECT_APERTURE] = (
                args.reconstruct_camera_aperture
            )
            doc.InsertObject(camera)
            camera_reconstructed_from_arguments = True
            fallback_to_take_camera = False
        if camera is None:
            raise RuntimeError(
                f"Camera {args.camera!r} not found; available: "
                + ", ".join(item["name"] for item in inventory["cameras"])
            )
        if render_data is None:
            raise RuntimeError(
                f"Render data {args.render_data!r} not found; available: "
                + ", ".join(item["name"] for item in inventory["renderData"])
            )
        source_camera_path = object_path(camera)
        camera_was_native_clone = False
        if (
            args.native_clone_legacy_camera
            and camera.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
        ):
            source_camera = camera
            camera = bridge_legacy_redshift_camera(source_camera)
            camera.SetName(source_camera.GetName() + " CODEX NATIVE BRIDGE")
            doc.InsertObject(camera)
            camera_was_native_clone = True

        enabled_objects = []
        for target in args.enable_object:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(f"Object {target!r} not found")
            scene_object.SetRenderMode(c4d.MODE_ON)
            scene_object.SetEditorMode(c4d.MODE_ON)
            enabled_objects.append(object_path(scene_object))
        disabled_objects = []
        for target in args.disable_object:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(f"Object {target!r} not found")
            scene_object.SetRenderMode(c4d.MODE_OFF)
            scene_object.SetEditorMode(c4d.MODE_OFF)
            disabled_objects.append(object_path(scene_object))
        offset_objects = []
        for spec in args.offset_object:
            try:
                target, raw_x, raw_y, raw_z = spec.rsplit("|", 3)
                offset = c4d.Vector(
                    float(raw_x), float(raw_y), float(raw_z)
                )
            except Exception as error:
                raise RuntimeError(
                    "--offset-object must be OBJECT_PATH|X|Y|Z; "
                    f"received {spec!r}"
                ) from error
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(f"Object {target!r} not found")
            matrix = scene_object.GetMg()
            matrix.off += offset
            scene_object.SetMg(matrix)
            offset_objects.append(
                {
                    "objectPath": object_path(scene_object),
                    "offset": [offset.x, offset.y, offset.z],
                }
            )
        removed_texture_tags = 0
        if args.grey_override:
            for scene_object in walk_objects(doc.GetFirstObject()):
                tag = scene_object.GetFirstTag()
                while tag:
                    next_tag = tag.GetNext()
                    if tag.CheckType(c4d.Ttexture):
                        tag.Remove()
                        removed_texture_tags += 1
                    tag = next_tag
            proof_light = c4d.BaseObject(c4d.Olight)
            proof_light.SetName("PARACOSM REDSHIFT GREY PROOF LIGHT")
            proof_light.SetAbsPos(camera.GetMg().off)
            proof_light[c4d.LIGHT_BRIGHTNESS] = (
                args.proof_light_brightness
            )
            proof_light[c4d.LIGHT_SHADOWTYPE] = 0
            doc.InsertObject(proof_light)

        fps = doc.GetFps()
        doc.SetTime(c4d.BaseTime(args.frame, fps))
        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        base_draw.SetSceneCamera(camera)
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        # Take/frame evaluation can materialize or restore Redshift node-graph
        # variants. Run a second exact relink pass after evaluation so the URLs
        # actually consumed by the renderer are covered, then audit that exact
        # in-memory state before rendering.
        post_evaluation_material_relinks = relink_material_assets(
            doc, requested_material_relinks
        )
        post_evaluation_material_relinks.extend(
            relink_node_material_assets(doc, requested_material_relinks)
        )
        post_evaluation_scene_material_relinks = relink_scene_assets(
            doc, requested_material_relinks
        )
        post_evaluation_node_boolean_overrides = set_node_boolean_ports(
            doc, args.set_node_bool
        )
        post_evaluation_node_input_disconnects = (
            disconnect_node_input_ports(
                doc, args.disconnect_node_input
            )
        )
        post_evaluation_frozen_redshift_proxies = (
            freeze_redshift_proxy_frames(
                doc, args.freeze_redshift_proxy
            )
        )
        # ExecutePasses can reapply take overrides after the requested
        # diagnostic visibility changes. Reassert those exact modes after
        # evaluation so an explicitly enabled proxy cannot silently return
        # to its saved off state before RenderDocument consumes the scene.
        post_evaluation_enabled_objects = []
        for target in args.enable_object:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(
                    f"Object {target!r} disappeared after evaluation"
                )
            scene_object.SetRenderMode(c4d.MODE_ON)
            scene_object.SetEditorMode(c4d.MODE_ON)
            post_evaluation_enabled_objects.append(
                {
                    "objectPath": object_path(scene_object),
                    "renderMode": scene_object.GetRenderMode(),
                    "editorMode": scene_object.GetEditorMode(),
                }
            )
        post_evaluation_disabled_objects = []
        for target in args.disable_object:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(
                    f"Object {target!r} disappeared after evaluation"
                )
            scene_object.SetRenderMode(c4d.MODE_OFF)
            scene_object.SetEditorMode(c4d.MODE_OFF)
            post_evaluation_disabled_objects.append(
                {
                    "objectPath": object_path(scene_object),
                    "renderMode": scene_object.GetRenderMode(),
                    "editorMode": scene_object.GetEditorMode(),
                }
            )
        post_evaluation_enabled_animation_tracks = []
        for target in args.enable_animation_tracks:
            scene_object = find_object(doc, target)
            if scene_object is None:
                raise RuntimeError(
                    f"Object {target!r} disappeared after evaluation"
                )
            track_records = []
            for track in scene_object.GetCTracks():
                description = track.GetDescriptionID()
                track[c4d.ID_CTRACK_ANIMOFF] = False
                track.Message(c4d.MSG_UPDATE)
                track_records.append(
                    {
                        "description": [
                            int(description[index].id)
                            for index in range(description.GetDepth())
                        ],
                        "keyCount": (
                            track.GetCurve().GetKeyCount()
                            if track.GetCurve() is not None
                            else 0
                        ),
                        "isAnimationOff": bool(
                            track[c4d.ID_CTRACK_ANIMOFF]
                        ),
                    }
                )
            scene_object.Message(c4d.MSG_UPDATE)
            post_evaluation_enabled_animation_tracks.append(
                {
                    "objectPath": object_path(scene_object),
                    "tracks": track_records,
                }
            )
        temporary_material_relinks.extend(
            post_evaluation_material_relinks
        )
        temporary_scene_material_relinks.extend(
            post_evaluation_scene_material_relinks
        )
        redshift_surface_output_repair = (
            repair_missing_redshift_surface_outputs(
                doc,
                args.repair_missing_rs_surface_material,
                args.repair_missing_rs_surface_output,
            )
        )
        current_rs_material_replacement = (
            replace_material_names_with_current_redshift(
                doc,
                args.replace_material_name_with_current_rs,
                tuple(args.diagnostic_material_color),
            )
        )
        camera_matrix_driver = None
        if args.apply_codex_camera_matrix_driver:
            matrix_driver_tag = next(
                (
                    tag
                    for tag in camera.GetTags()
                    if tag.GetType() == c4d.Tpython
                    and tag.GetName() == CODEX_CAMERA_MATRIX_DRIVER_TAG
                ),
                None,
            )
            if matrix_driver_tag is None:
                raise RuntimeError(
                    "Requested camera has no named Codex matrix driver"
                )
            matrix_driver_code = str(
                matrix_driver_tag[c4d.TPYTHON_CODE] or ""
            )
            number = (
                r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
                r"(?:[eE][-+]?\d+)?"
            )
            vector_pattern = re.compile(
                rf"c4d\.Vector\(\s*({number})\s*,\s*"
                rf"({number})\s*,\s*({number})\s*\)"
            )
            vector_values = [
                tuple(float(value) for value in match)
                for match in vector_pattern.findall(matrix_driver_code)
            ]
            if len(vector_values) != 4:
                raise RuntimeError(
                    "Named Codex matrix driver must contain exactly four "
                    "literal c4d.Vector triples"
                )
            matrix_before = camera.GetMg()
            camera.SetMg(
                c4d.Matrix(
                    *(c4d.Vector(*value) for value in vector_values)
                )
            )
            camera.Message(c4d.MSG_UPDATE)
            matrix_after = camera.GetMg()
            camera_matrix_driver = {
                "tag": matrix_driver_tag.GetName(),
                "codeExecuted": False,
                "literalVectorCount": len(vector_values),
                "matrixBefore": {
                    "off": [
                        matrix_before.off.x,
                        matrix_before.off.y,
                        matrix_before.off.z,
                    ],
                    "v1": [
                        matrix_before.v1.x,
                        matrix_before.v1.y,
                        matrix_before.v1.z,
                    ],
                    "v2": [
                        matrix_before.v2.x,
                        matrix_before.v2.y,
                        matrix_before.v2.z,
                    ],
                    "v3": [
                        matrix_before.v3.x,
                        matrix_before.v3.y,
                        matrix_before.v3.z,
                    ],
                },
                "matrixAfter": {
                    "off": [
                        matrix_after.off.x,
                        matrix_after.off.y,
                        matrix_after.off.z,
                    ],
                    "v1": [
                        matrix_after.v1.x,
                        matrix_after.v1.y,
                        matrix_after.v1.z,
                    ],
                    "v2": [
                        matrix_after.v2.x,
                        matrix_after.v2.y,
                        matrix_after.v2.z,
                    ],
                    "v3": [
                        matrix_after.v3.x,
                        matrix_after.v3.y,
                        matrix_after.v3.z,
                    ],
                },
            }
        if args.skip_post_relink_dependency_audit:
            post_relink_dependency_audit = {
                "skipped": True,
                "reason": (
                    "Explicitly skipped because Cinema retains a non-picture "
                    "collector asset-missing status into RenderDocument; a "
                    "separate active-frame audit is required."
                ),
            }
        else:
            post_relink_dependency_audit = collect_post_relink_assets(
                doc, project
            )

        # RenderData owns its VideoPost/PostFX chain separately from its base
        # container. Passing only a cloned GetData() container can therefore
        # select the right renderer while silently dropping the requested
        # setting's complete Redshift effect state. Clone and activate the
        # entire requested RenderData in this isolated document, then apply
        # only the explicit single-frame/output overrides to that in-memory
        # clone. The source document is never saved.
        requested_render_data_name = render_data.GetName()
        source_video_posts = render_data_video_posts(render_data)
        exact_render_data_clone = not args.render_with_source_render_data
        if args.render_with_source_render_data:
            doc.SetActiveRenderData(render_data)
            cloned_video_posts = source_video_posts
        else:
            exact_render_data = render_data.GetClone(
                getattr(c4d, "COPYFLAGS_NONE", 0)
            )
            if exact_render_data is None:
                raise RuntimeError(
                    f"Could not clone render data {requested_render_data_name!r}"
                )
            exact_render_data.SetName(
                requested_render_data_name + " CODEX EXACT IN-MEMORY COPY"
            )
            doc.InsertRenderData(exact_render_data)
            doc.SetActiveRenderData(exact_render_data)
            cloned_video_posts = render_data_video_posts(exact_render_data)
            if cloned_video_posts != source_video_posts:
                raise RuntimeError(
                    "Exact render-data clone changed the VideoPost chain: "
                    + json.dumps(
                        {
                            "source": source_video_posts,
                            "clone": cloned_video_posts,
                        },
                        separators=(",", ":"),
                    )
                )
            render_data = exact_render_data
        settings = render_data.GetDataInstance()
        source_renderer_id = settings[c4d.RDATA_RENDERENGINE]
        source_format_depth = settings[c4d.RDATA_FORMATDEPTH]
        ocio_render_setting_id = getattr(
            c4d, "RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER", None
        )
        ocio_render_setting_before = (
            bool(settings[ocio_render_setting_id])
            if ocio_render_setting_id is not None
            else None
        )
        ocio_render_setting_fallback_applied = False
        settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
        if args.render_format_depth is not None:
            settings[c4d.RDATA_FORMATDEPTH] = {
                8: c4d.RDATA_FORMATDEPTH_8,
                16: c4d.RDATA_FORMATDEPTH_16,
                32: c4d.RDATA_FORMATDEPTH_32,
            }[args.render_format_depth]
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_FRAMEFROM] = doc.GetTime()
        settings[c4d.RDATA_FRAMETO] = doc.GetTime()
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        native_save_output = (
            args.native_save_output.expanduser().resolve()
            if args.native_save_output is not None
            else None
        )
        native_save_candidates_before: set[str] = set()
        if native_save_output is not None:
            native_save_output.parent.mkdir(parents=True, exist_ok=True)
            native_save_candidates_before = {
                str(item.resolve())
                for item in native_save_output.parent.glob(
                    native_save_output.name + "*"
                )
            }
            settings[c4d.RDATA_PATH] = str(native_save_output)
            settings[c4d.RDATA_SAVEIMAGE] = True
        elif hasattr(c4d, "RDATA_SAVEIMAGE"):
            settings[c4d.RDATA_SAVEIMAGE] = False
        if hasattr(c4d, "RDATA_MULTIPASS_ENABLE"):
            settings[c4d.RDATA_MULTIPASS_ENABLE] = False

        bitmap_color_mode = (
            c4d.COLORMODE_RGBf
            if (
                linear_float_output is not None
                or raw_render_buffer_output is not None
            )
            else c4d.COLORMODE_RGB
        )
        bitmap = c4d.bitmaps.MultipassBitmap(
            args.width, args.height, bitmap_color_mode
        )
        if bitmap is None:
            raise RuntimeError("Could not initialize the render bitmap")
        bitmap.AddChannel(True, True)
        # Persist the resolved camera, take, render data, and temporary relinks
        # before RenderDocument. Asset-missing failures are diagnostically
        # useful and must not discard the exact state that reached Redshift.
        result.update(
            {
                "frame": args.frame,
                "camera": camera.GetName(),
                "cameraPath": source_camera_path,
                "cameraFallbackToTake": fallback_to_take_camera,
                "cameraWasNativeClone": camera_was_native_clone,
                "cameraReconstructedFromArguments": (
                    camera_reconstructed_from_arguments
                ),
                "cameraReconstructionTemplatePath": (
                    camera_reconstruction_template_path
                ),
                "cameraReconstructionTemplateType": (
                    camera_reconstruction_template_type
                ),
                "cameraMatrixDriver": camera_matrix_driver,
                "take": take.GetName() if take else None,
                "renderData": requested_render_data_name,
                "activeRenderData": render_data.GetName(),
                "exactRenderDataClone": exact_render_data_clone,
                "sourceVideoPosts": source_video_posts,
                "clonedVideoPosts": cloned_video_posts,
                "sourceRendererId": source_renderer_id,
                "sourceFormatDepth": source_format_depth,
                "renderFormatDepthOverride": args.render_format_depth,
                "rendererId": REDSHIFT_RENDERER_ID,
                "temporarilyEnabledObjects": enabled_objects,
                "temporarilyDisabledObjects": disabled_objects,
                "postEvaluationEnabledObjects": (
                    post_evaluation_enabled_objects
                ),
                "postEvaluationDisabledObjects": (
                    post_evaluation_disabled_objects
                ),
                "temporarilyEnabledAnimationTracks": (
                    enabled_animation_tracks
                ),
                "postEvaluationEnabledAnimationTracks": (
                    post_evaluation_enabled_animation_tracks
                ),
                "sampledDisabledAnimationTracks": (
                    sampled_disabled_animation_tracks
                ),
                "temporarilyOffsetObjects": offset_objects,
                "temporaryExactDependencyRelinks": (
                    temporary_dependency_relinks
                ),
                "temporaryExactMaterialRelinks": (
                    temporary_material_relinks
                ),
                "postEvaluationExactMaterialRelinks": (
                    post_evaluation_material_relinks
                ),
                "temporaryExactSceneMaterialRelinks": (
                    temporary_scene_material_relinks
                ),
                "postEvaluationExactSceneMaterialRelinks": (
                    post_evaluation_scene_material_relinks
                ),
                "temporaryNodeBooleanOverrides": (
                    temporary_node_boolean_overrides
                ),
                "postEvaluationNodeBooleanOverrides": (
                    post_evaluation_node_boolean_overrides
                ),
                "temporaryNodeInputDisconnects": (
                    temporary_node_input_disconnects
                ),
                "postEvaluationNodeInputDisconnects": (
                    post_evaluation_node_input_disconnects
                ),
                "frozenRedshiftProxies": frozen_redshift_proxies,
                "postEvaluationFrozenRedshiftProxies": (
                    post_evaluation_frozen_redshift_proxies
                ),
                "currentRsMaterialReplacement": (
                    current_rs_material_replacement
                ),
                "redshiftSurfaceOutputRepair": (
                    redshift_surface_output_repair
                ),
                "postRelinkDependencyAudit": (
                    post_relink_dependency_audit
                ),
                "simulationStartFrame": args.simulation_start_frame,
                "simulationFramesStepped": simulation_frames_stepped,
                "removedTopLevelObjects": removed_roots,
                "removedObjects": removed_objects,
                "greyOverride": args.grey_override,
                "proofLightBrightness": args.proof_light_brightness,
                "removedTextureTags": removed_texture_tags,
                "bitmapLayerCount": bitmap.GetLayerCount(),
                "bitmapAlphaLayerCount": bitmap.GetAlphaLayerCount(),
                "bitmapColorMode": bitmap_color_mode,
                "bitmapBitDepth": bitmap.GetBt(),
                "bitmapBytesPerPixel": bitmap.GetBpz(),
                "width": args.width,
                "height": args.height,
                "documentColorManagement": {
                    "mode": doc.GetDataInstance()[
                        c4d.DOCUMENT_COLOR_MANAGEMENT
                    ],
                    "renderColorSpace": doc.GetDataInstance()[
                        c4d.DOCUMENT_OCIO_RENDER_COLORSPACE_NAME
                    ],
                    "displayColorSpace": doc.GetDataInstance()[
                        c4d.DOCUMENT_OCIO_DISPLAY_COLORSPACE_NAME
                    ],
                },
                "redshiftColorManagement": redshift_color_management(
                    render_data
                ),
                "nativeSaveRequested": (
                    str(native_save_output)
                    if native_save_output is not None
                    else None
                ),
                "nativeSaveFormat": settings[c4d.RDATA_FORMAT],
                "nativeSaveFormatDepth": settings[c4d.RDATA_FORMATDEPTH],
                "nativeSaveColorProfile": str(
                    settings[c4d.RDATA_IMAGECOLORPROFILE]
                ),
            }
        )
        native_write_events: list[dict[str, object]] = []

        def native_write_progress(
            mode,
            written_bitmap,
            filename,
            main_image,
            write_frame,
            render_time,
            stream_number,
            stream_name,
        ):
            native_write_events.append(
                {
                    "mode": int(mode),
                    "filename": str(filename),
                    "mainImage": bool(main_image),
                    "frame": int(write_frame),
                    "renderTime": int(render_time),
                    "streamNumber": int(stream_number),
                    "streamName": str(stream_name),
                    "bitmapPresent": written_bitmap is not None,
                    "bitmapWidth": (
                        written_bitmap.GetBw()
                        if written_bitmap is not None
                        else None
                    ),
                    "bitmapHeight": (
                        written_bitmap.GetBh()
                        if written_bitmap is not None
                        else None
                    ),
                    "bitmapColorProfile": (
                        str(written_bitmap.GetColorProfile())
                        if written_bitmap is not None
                        else None
                    ),
                }
            )

        # RenderDocument does not write the cloned render-data output path in
        # c4dpy, even with BATCHRENDER. BATCHRENDER also caused a long apparent
        # hang in the isolated helper. Keep the stable external-render path and
        # treat --native-save-output strictly as a diagnostic request until a
        # real native file is observed.
        render_flags = (
            c4d.RENDERFLAGS_SHOWERRORS | c4d.RENDERFLAGS_EXTERNAL
        )
        no_document_clone_flag = getattr(
            c4d, "RENDERFLAGS_NODOCUMENTCLONE", None
        )
        if args.render_without_document_clone:
            if no_document_clone_flag is None:
                raise RuntimeError(
                    "Cinema 4D does not expose "
                    "RENDERFLAGS_NODOCUMENTCLONE"
                )
            render_flags |= no_document_clone_flag
        ocio_render_flag = getattr(
            c4d, "RENDERFLAGS_OCIO_BAKE_RENDERING", None
        )
        if args.render_with_ocio_bake_flag:
            if ocio_render_flag is not None:
                render_flags |= ocio_render_flag
            elif ocio_render_setting_id is not None:
                # Cinema 4D 2026.1 exposes the hidden render-data switch but
                # not the public RenderDocument convenience flag introduced
                # in the 2026.2 Python API. Maxon's SDK guidance identifies
                # this switch as the legacy route for baking the full OCIO
                # display/view chain into the in-memory result bitmap.
                settings[ocio_render_setting_id] = True
                ocio_render_setting_fallback_applied = True
            else:
                raise RuntimeError(
                    "Cinema 4D exposes neither "
                    "RENDERFLAGS_OCIO_BAKE_RENDERING nor "
                    "RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER"
                )
        result["renderFlags"] = int(render_flags)
        result["noDocumentCloneRequested"] = bool(
            args.render_without_document_clone
        )
        result["noDocumentCloneFlagValue"] = (
            int(no_document_clone_flag)
            if no_document_clone_flag is not None
            else None
        )
        result["ocioRenderBakeFlagRequested"] = (
            args.render_with_ocio_bake_flag
        )
        result["ocioRenderBakeFlagAvailable"] = ocio_render_flag is not None
        result["ocioRenderBakeFlagValue"] = (
            int(ocio_render_flag)
            if ocio_render_flag is not None
            else None
        )
        result["ocioRenderBakeSettingId"] = ocio_render_setting_id
        result["ocioRenderBakeSettingBefore"] = (
            ocio_render_setting_before
        )
        result["ocioRenderBakeSettingFallbackApplied"] = (
            ocio_render_setting_fallback_applied
        )
        result["ocioRenderBakeSettingDuringRender"] = (
            bool(settings[ocio_render_setting_id])
            if ocio_render_setting_id is not None
            else None
        )
        render_result = c4d.documents.RenderDocument(
            doc,
            settings,
            bitmap,
            render_flags,
            wprog=(
                native_write_progress
                if native_save_output is not None
                else None
            ),
        )
        if render_result != c4d.RENDERRESULT_OK:
            render_error_names = {
                c4d.RENDERRESULT_OUTOFMEMORY: "out_of_memory",
                c4d.RENDERRESULT_ASSETMISSING: "asset_missing",
                c4d.RENDERRESULT_FAILED: "failed",
                c4d.RENDERRESULT_UNAVAILABLE: "unavailable",
            }
            result["renderResultCode"] = int(render_result)
            result["renderResultName"] = render_error_names.get(
                render_result, "unknown"
            )
            if args.save_error_buffer:
                output.parent.mkdir(parents=True, exist_ok=True)
                error_display_bitmap = bitmap
                error_ocio_bake_applied = False
                if (
                    args.bake_ocio_view
                    and not args.render_with_ocio_bake_flag
                ):
                    error_baked_bitmap = (
                        c4d.documents.BakeOcioViewToBitmap(
                            bitmap,
                            settings,
                            getattr(c4d, "SAVEBIT_NONE", 0),
                        )
                    )
                    if error_baked_bitmap is not None:
                        error_display_bitmap = error_baked_bitmap
                        error_ocio_bake_applied = True
                error_save_result = error_display_bitmap.Save(
                    str(output),
                    c4d.FILTER_PNG,
                    c4d.BaseContainer(),
                )
                result["errorBufferOutput"] = (
                    str(output)
                    if error_save_result == c4d.IMAGERESULT_OK
                    else None
                )
                result["errorBufferSaveResult"] = int(
                    error_save_result
                )
                result["errorBufferOcioBakeApplied"] = (
                    error_ocio_bake_applied
                )
            raise RuntimeError(
                "RenderDocument returned result "
                f"{render_result} "
                f"({render_error_names.get(render_result, 'unknown')})"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        # RenderDocument writes the beauty result into the MultipassBitmap's
        # base image. GetLayerNum(0) is an auxiliary layer (and can be a
        # completely black alpha/multipass channel in Redshift), so saving that
        # layer silently produced false black "proofs" even when the render
        # itself succeeded.
        save_bitmap = bitmap
        display_bitmap = save_bitmap
        ocio_view_bake_applied = False
        ocio_view_bake_result = None
        if args.bake_ocio_view and not args.render_with_ocio_bake_flag:
            baked_bitmap = c4d.documents.BakeOcioViewToBitmap(
                save_bitmap,
                settings,
                getattr(c4d, "SAVEBIT_NONE", 0),
            )
            if baked_bitmap is not None:
                display_bitmap = baked_bitmap
                ocio_view_bake_applied = True
                ocio_view_bake_result = "baked_bitmap_returned"
            else:
                ocio_view_bake_result = "no_bake_required"
        elif args.render_with_ocio_bake_flag:
            ocio_view_bake_applied = True
            ocio_view_bake_result = "render_document_ocio_bake_flag"
        save_result = display_bitmap.Save(
            str(output), c4d.FILTER_PNG, c4d.BaseContainer()
        )
        if save_result != c4d.IMAGERESULT_OK:
            raise RuntimeError(f"Bitmap save returned result {save_result}")

        if linear_float_output is not None:
            linear_float_output.parent.mkdir(parents=True, exist_ok=True)
            linear_save_result = save_bitmap.Save(
                str(linear_float_output),
                c4d.FILTER_EXR,
                c4d.BaseContainer(),
                c4d.SAVEBIT_32BITCHANNELS | c4d.SAVEBIT_KEEP_COLOR_MODE,
            )
            if linear_save_result != c4d.IMAGERESULT_OK:
                raise RuntimeError(
                    "Linear OpenEXR save returned result "
                    f"{linear_save_result}"
                )
            result["linearFloatOutput"] = str(linear_float_output)
            result["linearFloatOutputCaveat"] = (
                "BaseBitmap.Save applies its Linear Color Space profile; "
                "this file is diagnostic, not the raw ACEScg buffer."
            )
        if raw_render_buffer_output is not None:
            raw_buffer_extraction = write_raw_float_pfm(
                save_bitmap, raw_render_buffer_output
            )
            result["rawRenderBufferOutput"] = str(
                raw_render_buffer_output
            )
            result["rawRenderBufferExtraction"] = raw_buffer_extraction
            result["rawRenderBufferColorSpace"] = (
                result["redshiftColorManagement"].get(
                    "renderingColorSpace"
                )
                or doc.GetDataInstance()[
                    c4d.DOCUMENT_OCIO_RENDER_COLORSPACE_NAME
                ]
            )

        result.update(
            {
                "status": "rendered",
                "output": str(output),
                "ocioViewBakeRequested": args.bake_ocio_view,
                "ocioViewBakeApplied": ocio_view_bake_applied,
                "ocioViewBakeResult": ocio_view_bake_result,
            }
        )
        if native_save_output is not None:
            result["nativeWriteEvents"] = native_write_events
            native_outputs = sorted(
                (
                    item.resolve()
                    for item in native_save_output.parent.glob(
                        native_save_output.name + "*"
                    )
                    if str(item.resolve())
                    not in native_save_candidates_before
                    and item.resolve() != output
                    and (
                        linear_float_output is None
                        or item.resolve() != linear_float_output
                    )
                    and (
                        raw_render_buffer_output is None
                        or item.resolve() != raw_render_buffer_output
                    )
                ),
                key=lambda item: item.stat().st_mtime_ns,
            )
            result["nativeSavedOutputs"] = [
                str(item) for item in native_outputs
            ]
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        result["seconds"] = round(time.time() - started, 3)
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(result, indent=2),
                encoding="utf-8",
            )
        print(
            "PARACOSM_REDSHIFT_TEST_JSON="
            + json.dumps(result, separators=(",", ":")),
            flush=True,
        )
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
