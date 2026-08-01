"""Retired external-hair experiment retained only for forensic provenance.

The shared hanging-dread mesh is not the shot-authored animated hair. This
script is deliberately non-runnable; the target shot's own hair hierarchy and
driver caches must be repaired in place.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d
import maxon


RETIRED_REASON = (
    "Rejected external hair recovery: repair the target shot's authored Hair "
    "hierarchy and exact caches in place; never import a shared hair mesh."
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
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def find_path(doc, path: str):
    return next(
        (
            op
            for op in walk_objects(doc.GetFirstObject())
            if object_path(op) == path
        ),
        None,
    )


def matrix_values(value):
    return [
        value.off.x,
        value.off.y,
        value.off.z,
        value.v1.x,
        value.v1.y,
        value.v1.z,
        value.v2.x,
        value.v2.y,
        value.v2.z,
        value.v3.x,
        value.v3.y,
        value.v3.z,
    ]


def polygon_world_bounds(op):
    if not isinstance(op, c4d.PolygonObject):
        raise RuntimeError(f"{object_path(op)} is not polygonal")
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    matrix = op.GetMg()
    for point in op.GetAllPoints():
        world = matrix * point
        for index, value in enumerate((world.x, world.y, world.z)):
            low[index] = min(low[index], value)
            high[index] = max(high[index], value)
    return c4d.Vector(*low), c4d.Vector(*high)


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


def set_classic_asset(owner, parameter_id: int, value: str):
    if owner is None or parameter_id < 0:
        return False, "asset has no classic owner/parameter"
    attempts = [value]
    filename_type = getattr(c4d, "Filename", None)
    if filename_type is not None:
        attempts.append(filename_type(value))
    errors = []
    for candidate in attempts:
        try:
            owner[c4d.DescID(parameter_id)] = candidate
            owner.Message(c4d.MSG_UPDATE)
            return True, ""
        except Exception as error:
            errors.append(f"{type(error).__name__}: {error}")
    return False, " | ".join(errors)


def main() -> None:
    raise RuntimeError(RETIRED_REASON)
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--hair-reference-project", type=Path, required=True
    )
    parser.add_argument("--hair-mesh", type=Path, required=True)
    parser.add_argument("--dependency-recovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=244)
    parser.add_argument(
        "--target-hair-root",
        default="th until end of scene v3/Hair",
    )
    parser.add_argument(
        "--target-face",
        default=(
            "th until end of scene v3/Hair/"
            "SKM_NewMetaHumanCharacter_FaceMesh.1"
        ),
    )
    parser.add_argument(
        "--hair-reference-face",
        default="Abby_Hanging_Posed.obj/Face.001",
    )
    parser.add_argument("--hair-object", default="hair_hanging")
    parser.add_argument(
        "--disable-target-path",
        action="append",
        default=[
            "th until end of scene v3/Hair/Subdivision Surface",
            "th until end of scene v3/Hair/Subdivision Surface_2",
            "th until end of scene v3/Hair/Null",
        ],
    )
    args = parser.parse_args()

    target_path = args.target.expanduser().resolve()
    hair_reference_path = (
        args.hair_reference_project.expanduser().resolve()
    )
    hair_path = args.hair_mesh.expanduser().resolve()
    output = args.output.expanduser().resolve()
    dependency_recovery_path = (
        args.dependency_recovery.expanduser().resolve()
    )
    if output in (
        target_path,
        hair_reference_path,
        hair_path,
    ):
        raise RuntimeError("Output must not overwrite a source")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite recovery copy: {output}")
    if (
        "_codex_072526" not in output.name
        or output.parent.name != "_codex_072526"
    ):
        raise RuntimeError("Output must use the _codex_072526 convention")

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    target = c4d.documents.LoadDocument(str(target_path), flags)
    hair_reference = c4d.documents.LoadDocument(
        str(hair_reference_path), flags
    )
    hair_doc = c4d.documents.LoadDocument(str(hair_path), flags)
    if (
        target is None
        or hair_reference is None
        or hair_doc is None
    ):
        raise RuntimeError("Could not load target/reference/hair documents")

    report = {
        "sourceTarget": str(target_path),
        "hairReferenceProject": str(hair_reference_path),
        "hairMesh": str(hair_path),
        "outputProject": str(output),
        "frame": args.frame,
        "saved": False,
        "status": "static_hair_geometry_candidate",
    }
    try:
        recovery_data = json.loads(
            dependency_recovery_path.read_text(encoding="utf-8")
        )
        exact_mapping = {
            str(item["requiredPath"]): str(item["candidates"][0]["path"])
            for item in recovery_data.get("projectDependencies", [])
            if Path(
                str(item.get("projectPath") or "")
            ).expanduser().resolve()
            == target_path
            and item.get("status") == "recovered_exact_path"
            and item.get("renderCritical")
            and item.get("candidates")
            and Path(str(item["candidates"][0]["path"])).is_file()
        }
        collector_before, assets_before = collect_assets(target)
        relink_changes = []
        relink_failures = []
        for asset in assets_before:
            required = str(asset.get("filename") or "")
            replacement = exact_mapping.get(required)
            if asset.get("exists") or not replacement:
                continue
            if asset.get("nodePath"):
                relink_failures.append(
                    {
                        "requiredPath": required,
                        "targetPath": replacement,
                        "reason": "node asset relinking is not enabled",
                    }
                )
                continue
            owner = asset.get("owner")
            parameter_id = int(asset.get("paramId", -1) or -1)
            changed, error = set_classic_asset(
                owner, parameter_id, replacement
            )
            item = {
                "requiredPath": required,
                "targetPath": replacement,
                "owner": owner.GetName() if owner else None,
                "parameterId": parameter_id,
            }
            if changed:
                relink_changes.append(item)
            else:
                relink_failures.append({**item, "reason": error})

        target.SetTime(c4d.BaseTime(args.frame, target.GetFps()))
        hair_reference.SetTime(
            c4d.BaseTime(0, hair_reference.GetFps())
        )
        hair_doc.SetTime(c4d.BaseTime(0, hair_doc.GetFps()))
        for doc in (target, hair_reference, hair_doc):
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        target_root = find_path(target, args.target_hair_root)
        target_face = find_path(target, args.target_face)
        hair_reference_face = find_path(
            hair_reference, args.hair_reference_face
        )
        source_hair = find_path(hair_doc, args.hair_object)
        if any(
            item is None
            for item in (
                target_root,
                target_face,
                hair_reference_face,
                source_hair,
            )
        ):
            raise RuntimeError("A required source or target object is missing")
        if not isinstance(source_hair, c4d.PolygonObject):
            raise RuntimeError("The hanging hair source is not polygonal")
        if source_hair.GetPolygonCount() < 30000:
            raise RuntimeError("Hanging hair source polygon count is too low")

        alias = c4d.AliasTrans()
        if not alias.Init(hair_doc):
            raise RuntimeError("Could not initialize C4D alias translation")
        material_clones = []
        material = hair_doc.GetFirstMaterial()
        while material:
            clone = material.GetClone(c4d.COPYFLAGS_NONE, alias)
            clone.SetName(f"{material.GetName()} [TH HANGING HAIR]")
            material_clones.append(clone)
            material = material.GetNext()
        recovered = source_hair.GetClone(c4d.COPYFLAGS_NONE, alias)
        alias.Translate(True)
        for clone in material_clones:
            target.InsertMaterial(clone)

        target_low, target_high = polygon_world_bounds(target_face)
        hair_reference_low, hair_reference_high = polygon_world_bounds(
            hair_reference_face
        )
        target_center = (target_low + target_high) * 0.5
        hair_reference_center = (
            hair_reference_low + hair_reference_high
        ) * 0.5
        target_extent = target_high - target_low
        hair_reference_extent = hair_reference_high - hair_reference_low
        source_scale = (
            target_extent.x / hair_reference_extent.x
            + target_extent.z / hair_reference_extent.z
        ) * 0.5
        source_to_target = c4d.Matrix(
            target_center - hair_reference_center * source_scale,
            c4d.Vector(source_scale, 0, 0),
            c4d.Vector(0, source_scale, 0),
            c4d.Vector(0, 0, source_scale),
        )
        mapped_global = source_to_target * source_hair.GetMg()
        recovered.SetName("hair_hanging_codex_recovery_072526")
        recovered.InsertUnder(target_root)
        recovered.SetMg(mapped_global)
        expected_local = ~target_root.GetMg() * mapped_global

        disabled = []
        for path in args.disable_target_path:
            op = find_path(target, path)
            if op is None:
                disabled.append({"path": path, "found": False})
                continue
            op.SetRenderMode(c4d.MODE_OFF)
            op.SetEditorMode(c4d.MODE_OFF)
            op.SetName(op.GetName() + "__offline_original")
            disabled.append({"path": path, "found": True})

        target.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        collector_after, assets_after = collect_assets(target)
        unresolved_exact = sorted(
            {
                str(asset.get("filename") or "")
                for asset in assets_after
                if not asset.get("exists")
                and (
                    str(asset.get("filename") or "") in exact_mapping
                    or str(asset.get("assetname") or "") in exact_mapping
                )
            }
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
                "targetFps": target.GetFps(),
                "hairReferenceFps": hair_reference.GetFps(),
                "hairSourceScale": source_scale,
                "targetFaceCenter": [
                    target_center.x,
                    target_center.y,
                    target_center.z,
                ],
                "hairReferenceFaceCenter": [
                    hair_reference_center.x,
                    hair_reference_center.y,
                    hair_reference_center.z,
                ],
                "hairPolygonCount": source_hair.GetPolygonCount(),
                "hairPointCount": source_hair.GetPointCount(),
                "recoveredPolygonCount": recovered.GetPolygonCount(),
                "recoveredPointCount": recovered.GetPointCount(),
                "localTransformDelta": local_delta,
                "clonedSourceMaterials": len(material_clones),
                "disabledOfflineBranches": disabled,
                "collectorBefore": collector_before,
                "collectorAfter": collector_after,
                "exactRelinkChanges": relink_changes,
                "exactRelinkFailures": relink_failures,
                "unresolvedExactRelinks": unresolved_exact,
                "limitations": [
                    "Static hanging-hair source; per-shot motion is unverified.",
                    "Grey geometry only; final Redshift material is unverified.",
                ],
            }
        )
        if local_delta > 1e-5:
            raise RuntimeError(
                f"Recovered hair transform drifted ({local_delta})"
            )
        if recovered.GetPolygonCount() != source_hair.GetPolygonCount():
            raise RuntimeError("Recovered hair polygon count changed")
        if relink_failures or unresolved_exact:
            raise RuntimeError("Exact dependency relinks did not verify")

        output.parent.mkdir(parents=True, exist_ok=True)
        target.GetDataInstance()[c4d.DOCUMENT_SECONDARYPATH] = maxon.Url(
            str(target_path.parent)
        )
        saved = c4d.documents.SaveDocument(
            target,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report["saved"] = bool(saved)
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        print(
            "PARACOSM_TH_HANGING_HAIR_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        c4d.documents.KillDocument(target)
        c4d.documents.KillDocument(hair_reference)
        c4d.documents.KillDocument(hair_doc)
        os._exit(0)


if __name__ == "__main__":
    main()
