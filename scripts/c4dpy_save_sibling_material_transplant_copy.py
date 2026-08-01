"""Save a strict recovery copy with source-authored sibling materials.

The target contributes geometry, animation, take, camera, and render settings.
The donor contributes only its material list. Materials must pair exactly by
index, name, and type. Every target texture tag is rebound to the corresponding
donor clone, exact dependency relinks are applied, and both active-frame and
project-wide dependency gates must pass before the new copy is saved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import c4d
import maxon

from c4d_relink_safety import safe_manifest_mappings
from c4dpy_camera_proof import find_take, object_path, walk_objects
from c4dpy_redshift_frame_test import (
    collect_post_relink_assets,
    find_render_data,
    relink_material_assets,
    relink_node_material_assets,
    relink_scene_assets,
)
from c4dpy_verify_relink_manifest import (
    collect_active_render_dependencies,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materials(doc) -> list[c4d.BaseMaterial]:
    result = []
    material = doc.GetFirstMaterial()
    while material is not None:
        result.append(material)
        material = material.GetNext()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-project", type=Path, required=True)
    parser.add_argument("--donor-project", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--take", required=True)
    parser.add_argument("--render-data", required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument(
        "--allow-dormant-project-residue",
        action="store_true",
        help=(
            "Permit a save when the selected take/frame is strictly safe but "
            "the project collector still reports off-frame dormant residue. "
            "The result remains explicitly non-project-wide."
        ),
    )
    args = parser.parse_args()

    target_project = args.target_project.expanduser().resolve()
    donor_project = args.donor_project.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    output = args.output.expanduser().resolve()
    result_json = args.result_json.expanduser().resolve()
    report: dict[str, object] = {
        "status": "failed",
        "targetProject": str(target_project),
        "donorProject": str(donor_project),
        "manifest": str(manifest_path),
        "outputProject": str(output),
        "take": args.take,
        "renderData": args.render_data,
        "frame": args.frame,
        "targetSourcePreserved": True,
        "donorSourcePreserved": True,
        "saved": False,
    }
    target_doc = None
    donor_doc = None
    try:
        for path in (target_project, donor_project, manifest_path):
            if not path.is_file():
                raise FileNotFoundError(path)
        if output in {target_project, donor_project}:
            raise RuntimeError("Output must differ from both source projects")
        if output.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing output: {output}"
            )
        if "_codex_" not in output.name.casefold() and not any(
            "_codex_" in parent.name.casefold() for parent in output.parents
        ):
            raise RuntimeError(
                "Output filename or an ancestor folder must contain _codex_"
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mappings, unsafe_mappings = safe_manifest_mappings(manifest)
        if unsafe_mappings:
            raise RuntimeError(
                "Unsafe relink targets rejected: "
                + json.dumps(unsafe_mappings[:12], separators=(",", ":"))
            )
        if manifest.get("unresolved"):
            raise RuntimeError("Manifest still contains unresolved entries")
        if not mappings:
            raise RuntimeError("Manifest contains no usable exact mappings")

        flags = (
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
        )
        target_doc = c4d.documents.LoadDocument(
            str(target_project), flags
        )
        donor_doc = c4d.documents.LoadDocument(str(donor_project), flags)
        if target_doc is None or donor_doc is None:
            raise RuntimeError("Could not load target and donor documents")
        c4d.documents.SetActiveDocument(target_doc)

        target_materials = materials(target_doc)
        donor_materials = materials(donor_doc)
        if len(target_materials) != len(donor_materials):
            raise RuntimeError(
                "Material count differs: "
                f"{len(target_materials)} != {len(donor_materials)}"
            )
        pairs = []
        clones = []
        for index, (target, donor) in enumerate(
            zip(target_materials, donor_materials)
        ):
            pair = {
                "index": index,
                "targetName": target.GetName(),
                "donorName": donor.GetName(),
                "targetTypeId": int(target.GetType()),
                "donorTypeId": int(donor.GetType()),
            }
            if (
                pair["targetName"] != pair["donorName"]
                or pair["targetTypeId"] != pair["donorTypeId"]
            ):
                raise RuntimeError(
                    f"Material identity differs at index {index}: {pair}"
                )
            clone = donor.GetClone(c4d.COPYFLAGS_0)
            if clone is None:
                raise RuntimeError(
                    f"Could not clone donor material at index {index}"
                )
            clones.append(clone)
            pairs.append(pair)

        previous = None
        for clone in clones:
            target_doc.InsertMaterial(clone, previous, False)
            previous = clone

        assignments = []
        unlinked_tags = []
        for scene_object in walk_objects(target_doc.GetFirstObject()):
            tag = scene_object.GetFirstTag()
            tag_index = 0
            while tag is not None:
                if tag.CheckType(c4d.Ttexture):
                    linked = tag.GetMaterial()
                    if linked is None:
                        unlinked_tags.append(
                            {
                                "objectPath": object_path(scene_object),
                                "tagIndex": tag_index,
                            }
                        )
                    else:
                        material_index = next(
                            (
                                index
                                for index, material in enumerate(
                                    target_materials
                                )
                                if linked == material
                            ),
                            None,
                        )
                        if material_index is None:
                            raise RuntimeError(
                                "Texture tag references a material outside "
                                "the target material list: "
                                f"{object_path(scene_object)} tag {tag_index}"
                            )
                        tag.SetMaterial(clones[material_index])
                        tag.Message(c4d.MSG_UPDATE)
                        if tag.GetMaterial() != clones[material_index]:
                            raise RuntimeError(
                                "Texture tag material rebind did not verify: "
                                f"{object_path(scene_object)} tag {tag_index}"
                            )
                        assignments.append(
                            {
                                "objectPath": object_path(scene_object),
                                "tagIndex": tag_index,
                                "materialIndex": material_index,
                                "materialName": clones[
                                    material_index
                                ].GetName(),
                            }
                        )
                tag = tag.GetNext()
                tag_index += 1

        for material in target_materials:
            material.Remove()
        surviving = materials(target_doc)
        if len(surviving) != len(clones) or any(
            material != clone
            for material, clone in zip(surviving, clones)
        ):
            raise RuntimeError(
                "Transplanted material list did not preserve donor order"
            )

        take_data = target_doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        take_data.SetCurrentTake(take)
        render_data = find_render_data(target_doc, args.render_data)
        if render_data is None:
            raise RuntimeError(
                f"Render data not found: {args.render_data}"
            )
        target_doc.SetActiveRenderData(render_data)
        target_doc.SetTime(
            c4d.BaseTime(args.frame, target_doc.GetFps())
        )

        first_material_relinks = relink_material_assets(
            target_doc, mappings
        )
        first_material_relinks.extend(
            relink_node_material_assets(target_doc, mappings)
        )
        first_scene_relinks = relink_scene_assets(target_doc, mappings)
        target_doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        second_material_relinks = relink_material_assets(
            target_doc, mappings
        )
        second_material_relinks.extend(
            relink_node_material_assets(target_doc, mappings)
        )
        second_scene_relinks = relink_scene_assets(target_doc, mappings)

        active_audit = collect_active_render_dependencies(
            target_doc,
            target_project,
        )
        project_audit = collect_post_relink_assets(
            target_doc, target_project
        )
        project_safe = bool(
            project_audit.get("strictDependencyRenderSafe")
        )
        active_safe = (
            not active_audit.get("renderCriticalUnresolvedFiles")
        )
        report.update(
            {
                "targetSha256": sha256(target_project),
                "donorSha256": sha256(donor_project),
                "manifestMappingCount": len(mappings),
                "materialPairs": pairs,
                "materialTransplantCount": len(clones),
                "textureTagRebindCount": len(assignments),
                "textureTagRebinds": assignments,
                "unlinkedTextureTags": unlinked_tags,
                "firstMaterialRelinks": first_material_relinks,
                "firstSceneRelinks": first_scene_relinks,
                "postEvaluationMaterialRelinks": second_material_relinks,
                "postEvaluationSceneRelinks": second_scene_relinks,
                "activeFrameDependencyAudit": active_audit,
                "postRelinkDependencyAudit": project_audit,
                "saveGate": {
                    "mode": (
                        "active_frame_strict_with_dormant_project_residue"
                        if args.allow_dormant_project_residue
                        else "project_wide_strict"
                    ),
                    "activeFrameSafe": active_safe,
                    "projectWideSafe": project_safe,
                    "dormantProjectResidueAccepted": bool(
                        args.allow_dormant_project_residue
                        and active_safe
                        and not project_safe
                    ),
                },
            }
        )
        if not active_safe or (
            not project_safe
            and not args.allow_dormant_project_residue
        ):
            raise RuntimeError(
                "Strict dependency gate failed after material transplant"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        target_doc.GetDataInstance()[
            c4d.DOCUMENT_SECONDARYPATH
        ] = maxon.Url(str(output.parent))
        saved = c4d.documents.SaveDocument(
            target_doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        if not saved or not output.is_file():
            raise RuntimeError("Cinema 4D did not save the recovery copy")
        report["saved"] = True
        report["status"] = (
            "saved"
            if project_safe
            else "saved_active_frame_strict"
        )
        report["outputBytes"] = output.stat().st_size
        report["outputSha256"] = sha256(output)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        result_json.parent.mkdir(parents=True, exist_ok=True)
        result_json.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            "PARACOSM_SIBLING_MATERIAL_TRANSPLANT_COPY="
            + json.dumps(
                {
                    "status": report.get("status"),
                    "saved": report.get("saved"),
                    "output": str(output),
                    "result": str(result_json),
                    "error": report.get("error"),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        if target_doc is not None:
            c4d.documents.KillDocument(target_doc)
        if donor_doc is not None:
            c4d.documents.KillDocument(donor_doc)
        os._exit(0)


if __name__ == "__main__":
    main()
