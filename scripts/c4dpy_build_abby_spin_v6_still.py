"""Retarget one exact Blender Spin pose into the accepted Abby Redshift v6 scene.

The Blender animation and rest FBXs are read-only calibration sources. The
accepted v6 C4D scene is also read-only. A new versioned C4D document and PNG
are created. Only the body/head pose is transferred in this lighting gate;
the accepted v6 facial pose remains a clearly labelled temporary proxy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from pathlib import Path

import c4d
import maxon


REDSHIFT_RENDERER_ID = 1036219
REDSHIFT_OBJECT_TAG_ID = 1036222
NODE_SPACE = "com.redshift3d.redshift4c4d.class.nodespace"
HAIR_MATERIAL_NAME = "Clay_Hair"
HAIR_OBJECT_PATH = (
    "root.002/pelvis/spine_01/spine_02/spine_03/spine_04/spine_05/"
    "neck_01/neck_02/head/FACIAL_C_FacialRoot/Hair"
)
SHOE_NORMAL_OLD = (
    "/C:/Users/zkyrg/Dropbox/Absolutely/ZK/0_Abby_Avatar/"
    "Asset/Shoes/Shoes.fbm/abby_shoe_full_lp_full_Normal.png"
)

# Parent-to-child order. Intermediate MetaHuman spine/neck/metacarpal bones
# inherit the calibrated pose from their mapped parent.
BONE_MAP = (
    ("Hips", "pelvis"),
    ("Spine", "spine_01"),
    ("Spine1", "spine_03"),
    ("Spine2", "spine_05"),
    ("Neck", "neck_01"),
    ("Head", "head"),
    ("LeftShoulder", "clavicle_l"),
    ("LeftArm", "upperarm_l"),
    ("LeftForeArm", "lowerarm_l"),
    ("LeftHand", "hand_l"),
    ("RightShoulder", "clavicle_r"),
    ("RightArm", "upperarm_r"),
    ("RightForeArm", "lowerarm_r"),
    ("RightHand", "hand_r"),
    ("LeftUpLeg", "thigh_l"),
    ("LeftLeg", "calf_l"),
    ("LeftFoot", "foot_l"),
    ("LeftToeBase", "ball_l"),
    ("RightUpLeg", "thigh_r"),
    ("RightLeg", "calf_r"),
    ("RightFoot", "foot_r"),
    ("RightToeBase", "ball_r"),
    ("LeftHandThumb1", "thumb_01_l"),
    ("LeftHandThumb2", "thumb_02_l"),
    ("LeftHandThumb3", "thumb_03_l"),
    ("LeftHandIndex1", "index_01_l"),
    ("LeftHandIndex2", "index_02_l"),
    ("LeftHandIndex3", "index_03_l"),
    ("LeftHandMiddle1", "middle_01_l"),
    ("LeftHandMiddle2", "middle_02_l"),
    ("LeftHandMiddle3", "middle_03_l"),
    ("LeftHandRing1", "ring_01_l"),
    ("LeftHandRing2", "ring_02_l"),
    ("LeftHandRing3", "ring_03_l"),
    ("LeftHandPinky1", "pinky_01_l"),
    ("LeftHandPinky2", "pinky_02_l"),
    ("LeftHandPinky3", "pinky_03_l"),
    ("RightHandThumb1", "thumb_01_r"),
    ("RightHandThumb2", "thumb_02_r"),
    ("RightHandThumb3", "thumb_03_r"),
    ("RightHandIndex1", "index_01_r"),
    ("RightHandIndex2", "index_02_r"),
    ("RightHandIndex3", "index_03_r"),
    ("RightHandMiddle1", "middle_01_r"),
    ("RightHandMiddle2", "middle_02_r"),
    ("RightHandMiddle3", "middle_03_r"),
    ("RightHandRing1", "ring_01_r"),
    ("RightHandRing2", "ring_02_r"),
    ("RightHandRing3", "ring_03_r"),
    ("RightHandPinky1", "pinky_01_r"),
    ("RightHandPinky2", "pinky_02_r"),
    ("RightHandPinky3", "pinky_03_r"),
)

FINGER_TARGETS = {
    target_name
    for source_name, target_name in BONE_MAP
    if "Hand" in source_name and source_name not in {"LeftHand", "RightHand"}
}


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def descendants(root):
    result = [root]

    def visit(parent):
        child = parent.GetDown()
        while child:
            result.append(child)
            visit(child)
            child = child.GetNext()

    visit(root)
    return result


def by_unique_name(root):
    grouped = {}
    for item in descendants(root):
        grouped.setdefault(item.GetName(), []).append(item)
    return {
        name: values[0]
        for name, values in grouped.items()
        if len(values) == 1
    }


def find_top(doc, name):
    matches = [
        item
        for item in walk_objects(doc.GetFirstObject())
        if item.GetUp() is None and item.GetName() == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one top-level {name!r}, got {len(matches)}")
    return matches[0]


def find_unique(doc, name):
    matches = [
        item
        for item in walk_objects(doc.GetFirstObject())
        if item.GetName() == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one object {name!r}, got {len(matches)}")
    return matches[0]


def object_path(op):
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def find_object_path(doc, path):
    return next(
        (
            item
            for item in walk_objects(doc.GetFirstObject())
            if object_path(item) == path
        ),
        None,
    )


def find_material(doc, name):
    material = doc.GetFirstMaterial()
    while material:
        if material.GetName() == name:
            return material
        material = material.GetNext()
    return None


def restore_lookmatch_hair(doc, hair_source):
    source_doc = c4d.documents.LoadDocument(
        str(hair_source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if source_doc is None:
        raise RuntimeError(f"Could not load exact hair source {hair_source}")
    try:
        source_hair = find_object_path(source_doc, HAIR_OBJECT_PATH)
        target_hair = find_object_path(doc, HAIR_OBJECT_PATH)
        if source_hair is None or target_hair is None:
            raise RuntimeError("The exact 1:1 Hair object is missing")
        if not (
            isinstance(source_hair, c4d.PolygonObject)
            and isinstance(target_hair, c4d.PolygonObject)
        ):
            raise RuntimeError("The exact 1:1 Hair object is not polygonal")
        if (
            source_hair.GetPointCount() != target_hair.GetPointCount()
            or source_hair.GetPolygonCount() != target_hair.GetPolygonCount()
        ):
            raise RuntimeError("The v6 and 1:1 Hair topologies differ")
        source_material = find_material(source_doc, HAIR_MATERIAL_NAME)
        if source_material is None:
            raise RuntimeError("The 1:1 hair material is missing")
        restored_hair = source_hair.GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        restored_material = source_material.GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        restored_material.SetName(f"{HAIR_MATERIAL_NAME}_1to1_Spin")
        doc.InsertMaterial(restored_material)
        reassigned = 0
        for tag in restored_hair.GetTags():
            if not tag.CheckType(c4d.Ttexture):
                continue
            material = tag[c4d.TEXTURETAG_MATERIAL]
            if material is None or material.GetName() != HAIR_MATERIAL_NAME:
                continue
            tag[c4d.TEXTURETAG_MATERIAL] = restored_material
            tag.Message(c4d.MSG_UPDATE)
            reassigned += 1
        if reassigned != 1:
            raise RuntimeError(
                f"Expected one 1:1 hair material tag, got {reassigned}"
            )
        parent = target_hair.GetUp()
        matrix = target_hair.GetMg()
        target_hair.Remove()
        restored_hair.InsertUnder(parent)
        restored_hair.SetMg(matrix)
        restored_hair.SetEditorMode(c4d.MODE_ON)
        restored_hair.SetRenderMode(c4d.MODE_ON)
        restored_hair.Message(c4d.MSG_UPDATE)
        return {
            "source": str(hair_source),
            "objectPath": HAIR_OBJECT_PATH,
            "pointCount": restored_hair.GetPointCount(),
            "polygonCount": restored_hair.GetPolygonCount(),
            "material": restored_material.GetName(),
            "textureTagsReassigned": reassigned,
            "editorMode": int(restored_hair.GetEditorMode()),
            "renderMode": int(restored_hair.GetRenderMode()),
        }
    finally:
        c4d.documents.KillDocument(source_doc)


def preserve_existing_lookmatch_hair(doc, source_path):
    hair = find_object_path(doc, HAIR_OBJECT_PATH)
    material = find_material(doc, HAIR_MATERIAL_NAME)
    if not isinstance(hair, c4d.PolygonObject) or material is None:
        raise RuntimeError("The master scene has no exact 1:1 Hair/material")
    hair.SetEditorMode(c4d.MODE_ON)
    hair.SetRenderMode(c4d.MODE_ON)
    hair.Message(c4d.MSG_UPDATE)
    return {
        "source": str(source_path),
        "objectPath": HAIR_OBJECT_PATH,
        "pointCount": hair.GetPointCount(),
        "polygonCount": hair.GetPolygonCount(),
        "material": material.GetName(),
        "preservedInPlace": True,
        "editorMode": int(hair.GetEditorMode()),
        "renderMode": int(hair.GetRenderMode()),
    }


def import_exact_spin_hair(
    look_doc,
    hair_motion_doc,
    root_scale,
    source_hips,
    target_pose_origin,
    material_authority,
    reverse_normals,
):
    source_hair = next(
        (
            item
            for item in walk_objects(hair_motion_doc.GetFirstObject())
            if item.GetName().casefold() == "hair"
            and item.CheckType(c4d.Opolygon)
        ),
        None,
    )
    target_hair = find_object_path(look_doc, HAIR_OBJECT_PATH)
    target_material = find_material(look_doc, HAIR_MATERIAL_NAME)
    if source_hair is None or target_hair is None or target_material is None:
        raise RuntimeError("Could not resolve exact Spin/C4D Hair authorities")
    if material_authority == "source":
        source_texture_tag = next(
            (
                tag
                for tag in source_hair.GetTags()
                if tag.CheckType(c4d.Ttexture)
                and tag[c4d.TEXTURETAG_MATERIAL] is not None
            ),
            None,
        )
        if source_texture_tag is None:
            raise RuntimeError("The exact Spin Hair has no imported material")
        source_material = source_texture_tag[c4d.TEXTURETAG_MATERIAL]
        target_material = source_material.GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        target_material.SetName("hair_copper_ExactSpin")
        look_doc.InsertMaterial(target_material)
    elif material_authority in {"proxy", "debug"}:
        target_material = c4d.BaseMaterial(c4d.Mmaterial)
        if material_authority == "proxy":
            target_material.SetName("Clay_Hair_CopperProxy_ExactSpin")
            # The accepted Clay_Hair substance is authored for the static
            # 1:1 hair UVs and resolves black on the evaluated Blender Spin
            # topology. Keep its accepted burnt-copper appearance through a
            # topology-independent conventional surface for this exact cache.
            target_material[c4d.MATERIAL_COLOR_COLOR] = c4d.Vector(
                0.18, 0.045, 0.018
            )
        else:
            target_material.SetName("DEBUG_HAIR_MAGENTA")
            target_material[c4d.MATERIAL_COLOR_COLOR] = c4d.Vector(
                1.0, 0.0, 1.0
            )
            target_material[c4d.MATERIAL_USE_LUMINANCE] = True
            target_material[c4d.MATERIAL_LUMINANCE_COLOR] = c4d.Vector(
                1.0, 0.0, 1.0
            )
            target_material[c4d.MATERIAL_LUMINANCE_BRIGHTNESS] = 2.0
        target_material[c4d.MATERIAL_COLOR_BRIGHTNESS] = 1.0
        look_doc.InsertMaterial(target_material)
    carrier = source_hair.GetClone(getattr(c4d, "COPYFLAGS_NONE", 0))
    if not isinstance(carrier, c4d.PolygonObject):
        raise RuntimeError("Could not clone the evaluated Spin Hair object")
    carrier.SetName("Hair_SpinExact_f0170")
    for track in list(carrier.GetCTracks()):
        track.Remove()
    target_texture_tag = next(
        (
            tag
            for tag in target_hair.GetTags()
            if tag.CheckType(c4d.Ttexture)
        ),
        None,
    )
    redshift_object_tag = next(
        (
            tag
            for tag in target_hair.GetTags()
            if tag.GetType() == REDSHIFT_OBJECT_TAG_ID
        ),
        None,
    )
    if target_texture_tag is None or redshift_object_tag is None:
        raise RuntimeError(
            "The accepted C4D Hair lacks its material/Redshift Object tag"
        )
    for tag in list(carrier.GetTags()):
        if tag.CheckType(c4d.Ttexture) or (
            hasattr(c4d, "Tnormal") and tag.CheckType(c4d.Tnormal)
        ):
            tag.Remove()
    cloned_redshift_tag = redshift_object_tag.GetClone(
        getattr(c4d, "COPYFLAGS_NONE", 0)
    )
    cloned_texture_tag = target_texture_tag.GetClone(
        getattr(c4d, "COPYFLAGS_NONE", 0)
    )
    if cloned_redshift_tag is None or cloned_texture_tag is None:
        raise RuntimeError("Could not clone accepted Hair render tags")
    copied_redshift_tag = material_authority in {"c4d", "source"}
    if copied_redshift_tag:
        carrier.InsertTag(cloned_redshift_tag)
    cloned_texture_tag[c4d.TEXTURETAG_MATERIAL] = target_material
    carrier.InsertTag(cloned_texture_tag)
    for index, polygon in enumerate(source_hair.GetAllPolygons()):
        if reverse_normals:
            if polygon.c == polygon.d:
                target_polygon = c4d.CPolygon(
                    polygon.a, polygon.c, polygon.b, polygon.c
                )
            else:
                target_polygon = c4d.CPolygon(
                    polygon.a, polygon.d, polygon.c, polygon.b
                )
        else:
            target_polygon = polygon
        carrier.SetPolygon(index, target_polygon)
    mapping = c4d.Matrix(
        target_pose_origin - source_hips * root_scale,
        c4d.Vector(root_scale, 0.0, 0.0),
        c4d.Vector(0.0, root_scale, 0.0),
        c4d.Vector(0.0, 0.0, root_scale),
    )
    source_matrix = source_hair.GetMg()
    if material_authority == "debug":
        # Diagnose the source take's object-identity visibility chain by
        # keeping the accepted Hair as the visible parent and adding the
        # evaluated cache beneath it.
        carrier.InsertUnder(target_hair)
    else:
        look_doc.InsertObject(carrier)
    carrier.SetMg(mapping * source_matrix)
    carrier.SetEditorMode(c4d.MODE_ON)
    carrier.SetRenderMode(c4d.MODE_ON)
    carrier.Message(c4d.MSG_UPDATE)
    if material_authority != "debug":
        target_hair.Remove()
    debug_probe = None
    if material_authority == "debug":
        debug_probe = c4d.BaseObject(c4d.Ocube)
        debug_probe.SetName("DEBUG_HAIR_RENDER_PROBE")
        debug_probe[c4d.PRIM_CUBE_LEN] = c4d.Vector(8.0, 8.0, 8.0)
        debug_probe.SetAbsPos(
            target_pose_origin + c4d.Vector(-35.0, 45.0, 0.0)
        )
        debug_tag = c4d.TextureTag()
        debug_tag[c4d.TEXTURETAG_MATERIAL] = target_material
        debug_probe.InsertTag(debug_tag)
        look_doc.InsertObject(debug_probe)
        debug_probe.Message(c4d.MSG_UPDATE)
    return {
        "sourceObject": source_hair.GetName(),
        "sourceBoundsAuthority": "exact evaluated Blender frame 170 FBX",
        "lookMaterialAuthority": target_material.GetName(),
        "materialAuthorityMode": material_authority,
        "carrier": carrier.GetName(),
        "objectPath": object_path(carrier),
        "carrierConstruction": (
            "evaluated FBX polygon clone replaces the accepted Hair object"
        ),
        "pointCount": carrier.GetPointCount(),
        "polygonCount": carrier.GetPolygonCount(),
        "rootScale": root_scale,
        "normalsReversedAfterFbxAxisConversion": reverse_normals,
        "acceptedRedshiftObjectTagCopied": copied_redshift_tag,
        "sourceMasterHairReplacedOnlyInDerivedScene": True,
        "bakePolicy": (
            "export the exact Blender Hair evaluation as a 0-365 cache and "
            "apply this same source-to-target world transform"
        ),
        "debugProbe": debug_probe.GetName() if debug_probe else None,
    }


def normalized_matrix(matrix, position=None):
    def unit(vector):
        length = vector.GetLength()
        if length <= 1.0e-9:
            raise RuntimeError("Degenerate matrix axis")
        return vector / length

    return c4d.Matrix(
        matrix.off if position is None else position,
        unit(matrix.v1),
        unit(matrix.v2),
        unit(matrix.v3),
    )


def remove_transform_tracks(item):
    removed = 0
    transform_ids = {
        c4d.ID_BASEOBJECT_REL_POSITION,
        c4d.ID_BASEOBJECT_REL_ROTATION,
        c4d.ID_BASEOBJECT_REL_SCALE,
        c4d.ID_BASEOBJECT_POSITION,
        c4d.ID_BASEOBJECT_ROTATION,
        c4d.ID_BASEOBJECT_SCALE,
    }
    for track in list(item.GetCTracks()):
        desc = track.GetDescriptionID()
        if desc.GetDepth() and int(desc[0].id) in transform_ids:
            track.Remove()
            removed += 1
    return removed


def collect_assets(doc):
    assets = []
    flags = (
        c4d.ASSETDATA_FLAG_WITHCACHES
        | c4d.ASSETDATA_FLAG_WITHFONTS
        | c4d.ASSETDATA_FLAG_COLLECT_NODES_ASSETS
        | c4d.ASSETDATA_FLAG_MULTIPLEUSE
    )
    c4d.documents.GetAllAssetsNew(doc, False, "", flags, assets)
    return assets


def relink_shoe_normal(doc, exact_path):
    exact_path = exact_path.resolve()
    if not exact_path.is_file():
        raise RuntimeError(f"Exact shoe normal is missing: {exact_path}")
    changes = []
    for asset in collect_assets(doc):
        required = str(asset.get("filename") or "")
        if required != SHOE_NORMAL_OLD or asset.get("exists"):
            continue
        owner = asset.get("owner")
        node_space = str(asset.get("nodeSpace") or "")
        node_path = str(asset.get("nodePath") or "")
        if not isinstance(owner, c4d.BaseMaterial) or not node_path:
            raise RuntimeError("Missing shoe normal has no writable node owner")
        graph = owner.GetNodeMaterialReference().GetGraph(maxon.Id(node_space))
        graph_node = graph.GetNode(maxon.NodePath(node_path))
        port = graph_node
        try:
            current = str(port.GetPortValue())
        except Exception:
            current = ""
        if required not in current:
            port = next(
                (
                    item
                    for item in graph.GetRoot().GetInnerNodes(
                        maxon.NODE_KIND.ALL_MASK, True
                    )
                    if str(item.GetPath()).startswith(node_path)
                    and required in str(item.GetPortValue()).replace("file://", "")
                ),
                None,
            )
        if not port:
            raise RuntimeError("Could not find shoe-normal asset port")
        with graph.BeginTransaction() as transaction:
            port.SetPortValue(maxon.Url(str(exact_path)))
            transaction.Commit()
        changes.append(
            {
                "owner": owner.GetName(),
                "old": required,
                "new": str(exact_path),
                "nodePath": node_path,
            }
        )
    if len(changes) != 1:
        raise RuntimeError(f"Expected one shoe-normal relink, got {len(changes)}")
    c4d.EventAdd()
    return changes


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_reload_assets(doc, look_source, output_project):
    """Mirror the master's resolved tex payload beside the derived C4D file.

    C4D resolves bare node-asset filenames through the source document's
    sibling ``tex`` directory. Saving the derived scene elsewhere preserves
    those bare filenames but changes that search root, so a reload otherwise
    loses the accepted Abby skin/eyes/teeth/outfit/HDRI assets.
    """

    source_tex = look_source.parent / "tex"
    target_tex = output_project.parent / "tex"
    if not source_tex.is_dir():
        raise RuntimeError(f"The accepted look source has no tex folder: {source_tex}")
    target_tex.mkdir(parents=True, exist_ok=True)

    required_names = sorted(
        {
            Path(str(asset.get("filename") or "")).name
            for asset in collect_assets(doc)
            if str(asset.get("filename") or "")
        }
    )
    staged = []
    unresolved = []
    for name in required_names:
        source = source_tex / name
        if not source.is_file():
            # Absolute external assets, such as the repaired shoe normal, do
            # not need to be duplicated into the derived package.
            asset_path = Path(name)
            if asset_path.is_absolute() and asset_path.is_file():
                continue
            unresolved.append(name)
            continue
        target = target_tex / name
        source_hash = file_sha256(source)
        if target.exists():
            target_hash = file_sha256(target)
            if target_hash != source_hash:
                raise RuntimeError(
                    f"Refusing to replace mismatched staged asset: {target}"
                )
        else:
            shutil.copy2(source, target)
            target_hash = file_sha256(target)
        if target_hash != source_hash:
            raise RuntimeError(f"Staged asset hash mismatch: {target}")
        staged.append(
            {
                "name": name,
                "source": str(source),
                "target": str(target),
                "sha256": source_hash,
                "bytes": source.stat().st_size,
            }
        )
    return {
        "sourceTex": str(source_tex),
        "targetTex": str(target_tex),
        "staged": staged,
        "unresolved": unresolved,
    }


def render_video_posts(render_data):
    result = []
    current = render_data.GetFirstVideoPost()
    while current:
        result.append({"name": current.GetName(), "type": int(current.GetType())})
        current = current.GetNext()
    return result


def point_camera(camera, target):
    position = camera.GetMg().off
    forward = (target - position).GetNormalized()
    world_up = c4d.Vector(0.0, 1.0, 0.0)
    right = world_up.Cross(forward).GetNormalized()
    up = forward.Cross(right).GetNormalized()
    camera.SetMg(c4d.Matrix(position, right, up, forward))


def point_redshift_area_light(light, target, aim_axis):
    """Aim a Redshift area light at *target* using the requested local axis."""
    position = light.GetMg().off
    if aim_axis == "positive-z":
        positive_z = (target - position).GetNormalized()
    elif aim_axis == "negative-z":
        positive_z = (position - target).GetNormalized()
    else:
        raise ValueError(f"Unsupported Redshift light aim axis: {aim_axis}")
    world_up = c4d.Vector(0.0, 1.0, 0.0)
    right = world_up.Cross(positive_z).GetNormalized()
    up = positive_z.Cross(right).GetNormalized()
    light.SetMg(c4d.Matrix(position, right, up, positive_z))


def frame_camera(camera, points, width, height, margin):
    minimum = c4d.Vector(
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    )
    maximum = c4d.Vector(
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    )
    center = (minimum + maximum) * 0.5
    size = maximum - minimum
    focal = float(camera[500] or camera[7003] or 50.0)
    sensor_width = 36.0
    aspect = float(width) / float(height)
    sensor_height = sensor_width / max(aspect, 1.0e-6)
    horizontal_fov = 2.0 * math.atan(sensor_width / (2.0 * focal))
    vertical_fov = 2.0 * math.atan(sensor_height / (2.0 * focal))
    distance = max(
        size.x / max(2.0 * math.tan(horizontal_fov * 0.5), 1.0e-6),
        size.y / max(2.0 * math.tan(vertical_fov * 0.5), 1.0e-6),
    )
    distance *= margin
    forward = camera.GetMg().v3.GetNormalized()
    camera.SetAbsPos(center - forward * distance)
    point_camera(camera, center)
    return {
        "center": [center.x, center.y, center.z],
        "size": [size.x, size.y, size.z],
        "distance": distance,
        "focal": focal,
        "aspect": aspect,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-fbx", type=Path, required=True)
    parser.add_argument("--motion-hair-fbx", type=Path, required=True)
    parser.add_argument("--rest-fbx", type=Path, required=True)
    parser.add_argument("--look-source", type=Path, required=True)
    parser.add_argument("--hair-source", type=Path, required=True)
    parser.add_argument(
        "--hair-material-authority",
        choices=("c4d", "source", "proxy", "debug"),
        default="c4d",
    )
    parser.add_argument(
        "--hair-mode",
        choices=("exact", "static"),
        default="exact",
    )
    parser.add_argument("--shoe-normal", type=Path, required=True)
    parser.add_argument("--output-project", type=Path, required=True)
    parser.add_argument("--output-still", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=170)
    parser.add_argument("--width", type=int, default=540)
    parser.add_argument("--height", type=int, default=960)
    parser.add_argument("--framing-margin", type=float, default=1.22)
    parser.add_argument("--dome-intensity", type=float, default=1.25)
    parser.add_argument("--area-intensity", type=float, default=3.28)
    parser.add_argument("--camera-fill-intensity", type=float, default=0.0)
    parser.add_argument(
        "--camera-fill-aim-axis",
        choices=("positive-z", "negative-z"),
        default="positive-z",
    )
    parser.add_argument("--camera-fill-distance-scale", type=float, default=0.55)
    parser.add_argument(
        "--camera-side",
        choices=("negative-z", "positive-z"),
        default="negative-z",
    )
    parser.add_argument("--allow-render-clone", action="store_true")
    parser.add_argument("--reload-before-render", action="store_true")
    parser.add_argument("--reverse-hair-normals", action="store_true")
    parser.add_argument(
        "--finger-mode",
        choices=("preserve", "rotation-only", "transfer"),
        default="rotation-only",
        help=(
            "Preserve the accepted C4D hand articulation, transfer Blender "
            "finger rotations while preserving C4D joint positions, or "
            "transfer Blender finger joints directly."
        ),
    )
    parser.add_argument(
        "--root-placement",
        choices=("studio", "source"),
        default="studio",
        help=(
            "Keep the exact pose at the accepted C4D studio root, or include "
            "the Blender file's scene-level world staging."
        ),
    )
    args = parser.parse_args()
    bone_map = tuple(
        (source_name, target_name)
        for source_name, target_name in BONE_MAP
        if args.finger_mode != "preserve" or target_name not in FINGER_TARGETS
    )

    paths = {
        key: value.expanduser().resolve()
        for key, value in {
            "motion": args.motion_fbx,
            "motionHair": args.motion_hair_fbx,
            "rest": args.rest_fbx,
            "look": args.look_source,
            "hair": args.hair_source,
            "shoe": args.shoe_normal,
            "project": args.output_project,
            "still": args.output_still,
            "report": args.report_json,
        }.items()
    }
    for key in ("motion", "motionHair", "rest", "look", "hair", "shoe"):
        if not paths[key].is_file():
            raise RuntimeError(f"Missing {key} source: {paths[key]}")
    for key in ("project", "still", "report"):
        if paths[key].exists():
            raise RuntimeError(f"Refusing to overwrite {paths[key]}")
        paths[key].parent.mkdir(parents=True, exist_ok=True)

    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    motion_doc = c4d.documents.LoadDocument(str(paths["motion"]), load_flags)
    hair_motion_doc = c4d.documents.LoadDocument(
        str(paths["motionHair"]), load_flags
    )
    rest_doc = c4d.documents.LoadDocument(str(paths["rest"]), load_flags)
    look_doc = c4d.documents.LoadDocument(str(paths["look"]), load_flags)
    if None in (motion_doc, hair_motion_doc, rest_doc, look_doc):
        raise RuntimeError("Could not load all retarget sources")

    report = {
        "motionSource": str(paths["motion"]),
        "motionHairSource": str(paths["motionHair"]),
        "restSource": str(paths["rest"]),
        "lookSource": str(paths["look"]),
        "hairSource": str(paths["hair"]),
        "sourcesUntouched": True,
        "outputProject": str(paths["project"]),
        "outputStill": str(paths["still"]),
        "frame": args.frame,
        "fps": 30,
        "fingerMode": args.finger_mode,
        "facialStatus": (
            "accepted v6 facial pose retained as a temporary lighting proxy; "
            "source facial animation not yet retargeted"
        ),
    }
    render_doc = None
    try:
        look_take_data = look_doc.GetTakeData()
        look_take_name = (
            look_take_data.GetCurrentTake().GetName()
            if look_take_data and look_take_data.GetCurrentTake()
            else None
        )
        evaluations = (
            (
                motion_doc,
                c4d.BaseTime(args.frame, motion_doc.GetFps()),
                True,
            ),
            (
                hair_motion_doc,
                c4d.BaseTime(0, hair_motion_doc.GetFps()),
                True,
            ),
            (
                rest_doc,
                c4d.BaseTime(0, max(rest_doc.GetFps(), 1)),
                True,
            ),
            (look_doc, c4d.BaseTime(0, look_doc.GetFps()), False),
        )
        for doc, time, force_main_take in evaluations:
            c4d.documents.SetActiveDocument(doc)
            take_data = doc.GetTakeData()
            if take_data and force_main_take:
                take_data.SetCurrentTake(take_data.GetMainTake())
            doc.SetTime(time)
            doc.ExecutePasses(
                None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
            )
        c4d.documents.SetActiveDocument(look_doc)

        motion_root = find_top(
            motion_doc, "1_cut0_AbbyCharacter-BODY_character"
        )
        rest_root = find_top(rest_doc, "1_cut0_AbbyCharacter-BODY_character")
        motion_nodes = by_unique_name(motion_root)
        rest_nodes = by_unique_name(rest_root)
        body_root = find_top(look_doc, "root.003")
        face_root = find_top(look_doc, "root.002")
        body_nodes = by_unique_name(body_root)
        face_nodes = by_unique_name(face_root)
        face_carrier_map = tuple(
            (source_name, target_name)
            for source_name, target_name in bone_map
            if target_name in face_nodes
        )

        missing = []
        for source_name, target_name in bone_map:
            for label, nodes, name in (
                ("motion", motion_nodes, source_name),
                ("rest", rest_nodes, source_name),
                ("body", body_nodes, target_name),
            ):
                if name not in nodes:
                    missing.append(f"{label}:{name}")
        if missing:
            raise RuntimeError("Missing mapped bones: " + ", ".join(missing))
        if not face_carrier_map:
            raise RuntimeError("The accepted facial rig has no mapped carrier bones")

        # Remove only body/core transforms from the facial carrier. Facial
        # descendant tracks remain untouched.
        removed_tracks = 0
        face_carrier_names = {
            target_name for _source_name, target_name in face_carrier_map
        }
        face_track_items = [face_root]
        face_track_items.extend(
            face_nodes[name]
            for name in face_carrier_names
            if face_nodes[name] is not face_root
        )
        for item in face_track_items:
            removed_tracks += remove_transform_tracks(item)

        # Align the facial carrier's body chain to the static body chain before
        # applying the exact motion delta.
        face_root.SetMg(body_root.GetMg())
        for _source_name, target_name in face_carrier_map:
            face_nodes[target_name].SetMg(body_nodes[target_name].GetMg())

        target_rest = {
            name: normalized_matrix(node.GetMg())
            for name, node in body_nodes.items()
            if name in {target for _source, target in bone_map}
        }
        source_rest = {
            name: normalized_matrix(rest_nodes[name].GetMg())
            for name, _target in bone_map
        }
        source_pose = {
            name: normalized_matrix(motion_nodes[name].GetMg())
            for name, _target in bone_map
        }
        source_height = max(
            (
                source_rest["Head"].off - source_rest["Hips"].off
            ).GetLength(),
            1.0e-8,
        )
        target_height = max(
            (
                target_rest["head"].off - target_rest["pelvis"].off
            ).GetLength(),
            1.0e-8,
        )
        root_scale = target_height / source_height
        source_root_delta = (
            source_pose["Hips"].off - source_rest["Hips"].off
        ) * root_scale
        if args.root_placement == "source":
            applied_root_delta = source_root_delta
        else:
            applied_root_delta = c4d.Vector(0.0)
        target_pose_origin = target_rest["pelvis"].off + applied_root_delta
        target_pose_positions = {
            target_name: (
                target_pose_origin
                + (
                    source_pose[source_name].off
                    - source_pose["Hips"].off
                )
                * root_scale
            )
            for source_name, target_name in bone_map
        }

        applied = []
        for source_name, target_name in bone_map:
            delta = source_pose[source_name] * ~source_rest[source_name]
            desired_rotation = delta * target_rest[target_name]
            target_carriers = [("body", body_nodes)]
            if target_name in face_carrier_names:
                target_carriers.append(("face", face_nodes))
            for label, nodes in target_carriers:
                node = nodes[target_name]
                target_position = target_pose_positions[target_name]
                if (
                    args.finger_mode == "rotation-only"
                    and target_name in FINGER_TARGETS
                ):
                    target_position = node.GetMg().off
                desired = normalized_matrix(
                    desired_rotation,
                    position=target_position,
                )
                node.SetMg(desired)
                applied.append(
                    {
                        "source": source_name,
                        "target": target_name,
                        "carrier": label,
                    }
                )
            look_doc.ExecutePasses(
                None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
            )

        if paths["hair"] == paths["look"]:
            hair_restore = preserve_existing_lookmatch_hair(
                look_doc, paths["look"]
            )
        else:
            hair_restore = restore_lookmatch_hair(look_doc, paths["hair"])
        relinks = relink_shoe_normal(look_doc, paths["shoe"])
        dome_light = find_unique(look_doc, "RS Dome Light")
        area_light = find_unique(look_doc, "RS Area Light.1")
        lighting = {
            "dome": {
                "name": dome_light.GetName(),
                "previousIntensity": float(dome_light[12024]),
                "intensity": args.dome_intensity,
                "previousReflection": float(dome_light[10034]),
                "reflection": 0.0,
            },
            "area": {
                "name": area_light.GetName(),
                "previousIntensity": float(area_light[11004]),
                "intensity": args.area_intensity,
                "previousReflection": float(area_light[10034]),
                "reflection": 1.0,
            },
        }
        dome_light[12024] = lighting["dome"]["intensity"]
        dome_light[10034] = lighting["dome"]["reflection"]
        area_light[11004] = lighting["area"]["intensity"]
        area_light[10034] = lighting["area"]["reflection"]
        dome_light.Message(c4d.MSG_UPDATE)
        area_light.Message(c4d.MSG_UPDATE)
        look_doc.SetFps(30)
        look_doc.SetMinTime(c4d.BaseTime(0, 30))
        look_doc.SetMaxTime(c4d.BaseTime(0, 30))
        look_doc.SetLoopMinTime(c4d.BaseTime(0, 30))
        look_doc.SetLoopMaxTime(c4d.BaseTime(0, 30))
        look_doc.SetTime(c4d.BaseTime(0, 30))
        look_doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )

        if args.hair_mode == "static":
            exact_hair = find_object_path(look_doc, HAIR_OBJECT_PATH)
            if not isinstance(exact_hair, c4d.PolygonObject):
                raise RuntimeError("Could not resolve the accepted static Hair")
            static_material = find_material(look_doc, HAIR_MATERIAL_NAME)
            if args.hair_material_authority == "debug":
                static_material = find_material(look_doc, "Abby_Face")
                for tag in list(exact_hair.GetTags()):
                    if tag.GetType() == REDSHIFT_OBJECT_TAG_ID:
                        tag.Remove()
            static_texture_tag = next(
                (
                    tag
                    for tag in exact_hair.GetTags()
                    if tag.CheckType(c4d.Ttexture)
                ),
                None,
            )
            if static_material is None or static_texture_tag is None:
                raise RuntimeError("Could not resolve static Hair material")
            static_texture_tag[c4d.TEXTURETAG_MATERIAL] = static_material
            static_texture_tag.Message(c4d.MSG_UPDATE)
            hair_carrier = {
                "mode": "accepted static 1:1 hair diagnostic",
                "sourceObject": exact_hair.GetName(),
                "carrier": exact_hair.GetName(),
                "objectPath": HAIR_OBJECT_PATH,
                "pointCount": exact_hair.GetPointCount(),
                "polygonCount": exact_hair.GetPolygonCount(),
                "materialAuthorityMode": (
                    "Abby_Face diagnostic"
                    if args.hair_material_authority == "debug"
                    else "c4d"
                ),
            }
        else:
            hair_carrier = import_exact_spin_hair(
                look_doc,
                hair_motion_doc,
                root_scale,
                source_pose["Hips"].off,
                target_pose_origin,
                args.hair_material_authority,
                args.reverse_hair_normals,
            )
            exact_hair = find_object_path(
                look_doc, hair_carrier["objectPath"]
            )
            if not isinstance(exact_hair, c4d.PolygonObject):
                raise RuntimeError("Could not resolve exact derived Hair")
        look_doc.SetChanged()
        look_doc.Message(c4d.MSG_UPDATE)
        c4d.EventAdd()
        look_doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )

        source_camera = next(
            (
                item
                for item in walk_objects(look_doc.GetFirstObject())
                if item.GetName()
                in (
                    "RS Camera - Delighted Side Glance V6 Lookmatch",
                    "RS Camera",
                )
                and item.GetType() == 1057516
            ),
            None,
        )
        if source_camera is None:
            raise RuntimeError("Could not find the accepted Redshift camera")
        camera = source_camera.GetClone(getattr(c4d, "COPYFLAGS_NONE", 0))
        if camera is None:
            raise RuntimeError("Could not clone accepted v6 camera")
        camera.SetName("RS Camera - Abby Spin Full Body f0170 v001")
        camera[500] = 74.62
        camera[7003] = 74.62
        camera[1220] = 0.0
        look_doc.InsertObject(camera)
        points = [
            body_nodes[target_name].GetMg().off
            for _source_name, target_name in bone_map
        ]
        points.extend(
            exact_hair.GetMg() * point for point in exact_hair.GetAllPoints()
        )
        framing = frame_camera(
            camera,
            points,
            args.width,
            args.height,
            args.framing_margin,
        )
        if args.camera_side == "positive-z":
            framing_center = c4d.Vector(*framing["center"])
            camera.SetAbsPos(
                framing_center
                + c4d.Vector(
                    framing["distance"] * 0.12,
                    framing["distance"] * 0.04,
                    framing["distance"],
                )
            )
            point_camera(camera, framing_center)
            framing["cameraSide"] = args.camera_side
        else:
            framing["cameraSide"] = args.camera_side
        look_doc.GetActiveBaseDraw().SetSceneCamera(camera)
        if args.camera_fill_intensity > 0.0:
            fill_light = area_light.GetClone(getattr(c4d, "COPYFLAGS_NONE", 0))
            if fill_light is None:
                raise RuntimeError("Could not clone the accepted Redshift key")
            fill_light.SetName("RS Area Fill - Abby Spin v001")
            camera_matrix = camera.GetMg()
            fill_target = c4d.Vector(*framing["center"])
            fill_distance = (
                framing["distance"] * args.camera_fill_distance_scale
            )
            fill_light.SetMg(
                c4d.Matrix(
                    fill_target
                    + camera_matrix.v1.GetNormalized() * 24.0
                    + camera_matrix.v2.GetNormalized() * 18.0
                    - camera_matrix.v3.GetNormalized() * fill_distance,
                    camera_matrix.v1,
                    camera_matrix.v2,
                    camera_matrix.v3,
                )
            )
            point_redshift_area_light(
                fill_light, fill_target, args.camera_fill_aim_axis
            )
            fill_light[11004] = args.camera_fill_intensity
            fill_light[10034] = 0.0
            fill_light.Message(c4d.MSG_UPDATE)
            look_doc.InsertObject(fill_light)
            lighting["cameraFill"] = {
                "name": fill_light.GetName(),
                "intensity": args.camera_fill_intensity,
                "reflection": 0.0,
                "aimAxis": args.camera_fill_aim_axis,
                "distanceScale": args.camera_fill_distance_scale,
                "position": [
                    fill_light.GetMg().off.x,
                    fill_light.GetMg().off.y,
                    fill_light.GetMg().off.z,
                ],
            }
        else:
            lighting["cameraFill"] = {
                "enabled": False,
                "reason": "v17 uses the dome as diffuse-only fill",
            }
        source_render_data = look_doc.GetActiveRenderData()
        source_posts = render_video_posts(source_render_data)
        render_data = source_render_data.GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        if render_data is None:
            raise RuntimeError("Could not clone accepted render settings")
        render_data.SetName(
            source_render_data.GetName() + " ABBY SPIN F0170 V001"
        )
        look_doc.InsertRenderData(render_data)
        look_doc.SetActiveRenderData(render_data)
        if render_video_posts(render_data) != source_posts:
            raise RuntimeError("Render-data clone changed the post chain")
        settings = render_data.GetDataInstance()
        settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        settings[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        settings[c4d.RDATA_SAVEIMAGE] = False
        if hasattr(c4d, "RDATA_MULTIPASS_ENABLE"):
            settings[c4d.RDATA_MULTIPASS_ENABLE] = False

        saved = False
        render_target = look_doc
        reload_assets = None
        if args.reload_before_render:
            reload_assets = stage_reload_assets(
                look_doc, paths["look"], paths["project"]
            )
            saved = c4d.documents.SaveDocument(
                look_doc,
                str(paths["project"]),
                c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
                c4d.FORMAT_C4DEXPORT,
            )
            if not saved:
                raise RuntimeError("Could not save reloadable derived scene")
            render_doc = c4d.documents.LoadDocument(
                str(paths["project"]), load_flags
            )
            if render_doc is None:
                raise RuntimeError("Could not reload derived C4D scene")
            c4d.documents.SetActiveDocument(render_doc)
            render_doc.SetTime(c4d.BaseTime(0, 30))
            render_doc.ExecutePasses(
                None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
            )
            reloaded_camera = find_unique(render_doc, camera.GetName())
            render_doc.GetActiveBaseDraw().SetSceneCamera(reloaded_camera)
            render_target = render_doc
            render_data = render_doc.GetActiveRenderData()
            settings = render_data.GetDataInstance()
            settings[c4d.RDATA_XRES] = float(args.width)
            settings[c4d.RDATA_YRES] = float(args.height)
            settings[c4d.RDATA_FRAMESEQUENCE] = (
                c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
            )
            settings[c4d.RDATA_SAVEIMAGE] = False

        bitmap = c4d.bitmaps.MultipassBitmap(
            args.width, args.height, c4d.COLORMODE_RGB
        )
        bitmap.AddChannel(True, True)
        render_flags = c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS
        if not args.allow_render_clone:
            render_flags |= getattr(c4d, "RENDERFLAGS_NODOCUMENTCLONE", 0)
        result = c4d.documents.RenderDocument(
            render_target, settings, bitmap, render_flags
        )
        if result != c4d.RENDERRESULT_OK:
            raise RuntimeError(f"RenderDocument returned {result}")
        layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
        if (
            layer.Save(
                str(paths["still"]),
                c4d.FILTER_PNG,
                c4d.BaseContainer(),
            )
            != c4d.IMAGERESULT_OK
        ):
            raise RuntimeError("Could not save PNG")

        if not saved:
            saved = c4d.documents.SaveDocument(
                look_doc,
                str(paths["project"]),
                c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
                c4d.FORMAT_C4DEXPORT,
            )
            if not saved:
                raise RuntimeError("Could not save derived C4D project")

        remaining_missing = [
            str(asset.get("filename") or "")
            for asset in collect_assets(render_target)
            if not asset.get("exists")
        ]
        report.update(
            {
                "mappedBones": len(bone_map),
                "faceCarrierMappedBones": len(face_carrier_map),
                "faceCarrierMappedTargets": [
                    target_name
                    for _source_name, target_name in face_carrier_map
                ],
                "faceCarrierUnsupportedTargets": [
                    target_name
                    for _source_name, target_name in bone_map
                    if target_name not in face_carrier_names
                ],
                "targetAssignments": len(applied),
                "removedFaceCarrierCoreTracks": removed_tracks,
                "rootTranslationScale": root_scale,
                "rootTranslationDelta": [
                    source_root_delta.x,
                    source_root_delta.y,
                    source_root_delta.z,
                ],
                "rootTranslationPolicy": args.root_placement,
                "appliedRootTranslationDelta": [
                    applied_root_delta.x,
                    applied_root_delta.y,
                    applied_root_delta.z,
                ],
                "shoeNormalRelinks": relinks,
                "lookmatchHair": hair_restore,
                "evaluatedHairCarrier": hair_carrier,
                "lighting": lighting,
                "renderOrder": "in-memory render before derived scene save",
                "reloadedBeforeRender": args.reload_before_render,
                "reloadAssets": reload_assets,
                "remainingMissingDependencies": remaining_missing,
                "framing": framing,
                "camera": camera.GetName(),
                "renderData": render_data.GetName(),
                "lookTakePreserved": look_take_name,
                "videoPosts": source_posts,
                "saved": True,
                "rendered": True,
            }
        )
        paths["report"].write_text(json.dumps(report, indent=2))
        print(
            "ABBY_SPIN_V6_STILL="
            + json.dumps(
                {
                    "project": str(paths["project"]),
                    "still": str(paths["still"]),
                    "report": str(paths["report"]),
                    "frame": args.frame,
                    "mappedBones": len(bone_map),
                    "remainingMissing": len(remaining_missing),
                }
            ),
            flush=True,
        )
    finally:
        for doc in (
            motion_doc,
            hair_motion_doc,
            rest_doc,
            look_doc,
            render_doc,
        ):
            if doc is not None:
                c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
