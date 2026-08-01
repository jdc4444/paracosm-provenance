"""Retired external-hair experiment retained only for forensic provenance."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_build_th_hanging_hair_recovery import (
    find_path,
    matrix_values,
    polygon_world_bounds,
)


TARGET_ROOT = "walks in snow while shivering in wind v2"
TARGET_FACE = (
    TARGET_ROOT
    + "/Hair__offline_original/SKM_NewMetaHumanCharacter_FaceMesh.1"
)
TARGET_ORIENTATION_FACE = (
    TARGET_ROOT + "/SKM_NewMetaHumanCharacter_FaceMesh"
)
RETIRED_REASON = (
    "Rejected external hair recovery: CUT-033 must use its own authored Hair "
    "hierarchy and exact caches; never import a shared hanging-hair mesh."
)
OLD_RECOVERY = (
    TARGET_ROOT + "/HAIR_codex_recovery_072526"
)
EXISTING_CANDIDATE = (
    TARGET_ROOT + "/hair_hanging_CUT033_codex_072526"
)
REFERENCE_FACE = "Abby_Hanging_Posed.obj/Face.001"


def find_material(doc, name: str):
    material = doc.GetFirstMaterial()
    while material:
        if material.GetName() == name:
            return material
        material = material.GetNext()
    return None


def main() -> None:
    raise RuntimeError(RETIRED_REASON)
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--reference-project",
        type=Path,
        default=Path(
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
            "/ZK/3_Houdini_Hair/Abby_Walking/geo/Abby_Hanging_Posed.obj"
        ),
    )
    parser.add_argument(
        "--hair-mesh",
        type=Path,
        default=Path(
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
            "/ZK/3_Houdini_Hair/Abby_Walking/geo/hair_hanging.obj"
        ),
    )
    parser.add_argument("--frame", type=int, default=490)
    parser.add_argument("--hair-length-scale", type=float, default=2.2)
    parser.add_argument("--hair-x-scale", type=float, default=1.0)
    parser.add_argument(
        "--anchor-horizontal-to-hair-bounds",
        action="store_true",
        help=(
            "Center the source hair bounds on the target face in X/Z. Use "
            "this for standalone hair exports that are not authored in the "
            "reference-face coordinate space."
        ),
    )
    parser.add_argument("--source-object", default="hair_hanging")
    parser.add_argument(
        "--candidate-name",
        default="hair_hanging_CUT033_codex_072526",
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    reference_path = args.reference_project.expanduser().resolve()
    hair_path = args.hair_mesh.expanduser().resolve()
    if "_codex_" not in project.name.casefold() or not any(
        "_codex_" in parent.name.casefold() for parent in project.parents
    ):
        raise RuntimeError("Refusing to edit a non-Codex-dated project")
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    target = c4d.documents.LoadDocument(str(project), flags)
    reference = c4d.documents.LoadDocument(str(reference_path), flags)
    hair_doc = c4d.documents.LoadDocument(str(hair_path), flags)
    if target is None or reference is None or hair_doc is None:
        raise RuntimeError("Could not load target/reference/hair documents")
    report = {
        "project": str(project),
        "referenceProject": str(reference_path),
        "hairMesh": str(hair_path),
        "frame": args.frame,
        "saved": False,
    }
    try:
        target.SetTime(c4d.BaseTime(args.frame, target.GetFps()))
        for doc in (target, reference, hair_doc):
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        target_root = find_path(target, TARGET_ROOT)
        target_face = find_path(target, TARGET_FACE)
        target_orientation_face = find_path(
            target, TARGET_ORIENTATION_FACE
        )
        reference_face = find_path(reference, REFERENCE_FACE)
        source_hair = find_path(hair_doc, args.source_object)
        if any(
            item is None
            for item in (
                target_root,
                target_face,
                target_orientation_face,
                reference_face,
                source_hair,
            )
        ):
            raise RuntimeError("A required target/reference object is missing")
        prior_candidate = find_path(
            target, TARGET_ROOT + "/" + args.candidate_name
        )
        if prior_candidate is None:
            prior_candidate = find_path(target, EXISTING_CANDIDATE)
        if prior_candidate is not None:
            prior_candidate.Remove()
        recovered = source_hair.GetClone(c4d.COPYFLAGS_NONE)
        recovered.SetName(args.candidate_name)

        target_low, target_high = polygon_world_bounds(target_face)
        reference_low, reference_high = polygon_world_bounds(reference_face)
        hair_low, hair_high = polygon_world_bounds(source_hair)
        target_center = (target_low + target_high) * 0.5
        reference_center = (reference_low + reference_high) * 0.5
        target_extent = target_high - target_low
        reference_extent = reference_high - reference_low
        source_scale = (
            target_extent.x / reference_extent.x
            + target_extent.z / reference_extent.z
        ) * 0.5
        target_matrix = target_orientation_face.GetMg()
        target_up = target_matrix.v2.GetNormalized()
        source_top_anchor = c4d.Vector(
            (
                (hair_low.x + hair_high.x) * 0.5
                if args.anchor_horizontal_to_hair_bounds
                else reference_center.x
            ),
            hair_high.y,
            (
                (hair_low.z + hair_high.z) * 0.5
                if args.anchor_horizontal_to_hair_bounds
                else reference_center.z
            ),
        )
        target_top_anchor = (
            target_center
            + target_up
            * (hair_high.y - reference_center.y)
            * source_scale
        )
        source_to_target = c4d.Matrix(
            target_top_anchor,
            target_matrix.v1.GetNormalized()
            * source_scale
            * args.hair_x_scale,
            target_up * source_scale * args.hair_length_scale,
            target_matrix.v3.GetNormalized() * source_scale,
        )
        reference_center_offset = c4d.Matrix(-source_top_anchor)
        mapped_global = (
            source_to_target
            * reference_center_offset
            * source_hair.GetMg()
        )
        recovered.InsertUnder(target_root)
        recovered.SetMg(mapped_global)
        expected_local = ~target_root.GetMg() * mapped_global

        tag = recovered.GetFirstTag()
        while tag:
            next_tag = tag.GetNext()
            if tag.CheckType(c4d.Ttexture):
                tag.Remove()
            tag = next_tag
        hair_material = find_material(
            target, "PARACOSM CODEX COPPER HAIR 072526"
        )
        if hair_material is None:
            raise RuntimeError("Compatibility hair material is missing")
        material_tag = c4d.BaseTag(c4d.Ttexture)
        material_tag.SetMaterial(hair_material)
        recovered.InsertTag(material_tag)

        old_recovery = find_path(target, OLD_RECOVERY)
        if old_recovery is not None:
            old_recovery.SetRenderMode(c4d.MODE_OFF)
            old_recovery.SetEditorMode(c4d.MODE_OFF)
            old_recovery.SetName(
                old_recovery.GetName() + "__wrong_silhouette"
            )
        target.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        local_delta = max(
            abs(left - right)
            for left, right in zip(
                matrix_values(expected_local),
                matrix_values(recovered.GetMl()),
            )
        )
        report.update(
            {
                "targetFaceCenter": [
                    target_center.x,
                    target_center.y,
                    target_center.z,
                ],
                "referenceFaceCenter": [
                    reference_center.x,
                    reference_center.y,
                    reference_center.z,
                ],
                "sourceScale": source_scale,
                "hairLengthScale": args.hair_length_scale,
                "hairXScale": args.hair_x_scale,
                "anchorHorizontalToHairBounds": (
                    args.anchor_horizontal_to_hair_bounds
                ),
                "sourceObject": args.source_object,
                "candidateName": args.candidate_name,
                "sourceHairBounds": {
                    "low": [hair_low.x, hair_low.y, hair_low.z],
                    "high": [hair_high.x, hair_high.y, hair_high.z],
                },
                "polygonCount": recovered.GetPolygonCount(),
                "pointCount": recovered.GetPointCount(),
                "localTransformDelta": local_delta,
                "disabledPreviousHairRecovery": old_recovery is not None,
                "replacedPriorHangingCandidate": prior_candidate is not None,
                "material": hair_material.GetName(),
                "status": "static_hanging_hair_visual_candidate",
                "limitations": [
                    "Static shared dread mesh; per-frame strand motion is not recovered.",
                    "Visual comparison is required before this can count as hair match.",
                ],
            }
        )
        if local_delta > 1e-5:
            raise RuntimeError(f"Hair transform drifted ({local_delta})")
        saved = c4d.documents.SaveDocument(
            target,
            str(project),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report["saved"] = bool(saved)
        if not saved:
            report["error"] = "Cinema 4D SaveDocument returned false"
        print(
            "PARACOSM_CUT033_HANGING_HAIR_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_CUT033_HANGING_HAIR_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(target)
        c4d.documents.KillDocument(reference)
        c4d.documents.KillDocument(hair_doc)
        os._exit(0)


if __name__ == "__main__":
    main()
