"""Save an exact in-memory relink as a C4D Project-with-Assets package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import c4d

from c4d_relink_safety import safe_manifest_mappings
from c4dpy_camera_proof import find_take
from c4dpy_redshift_frame_test import (
    collect_post_relink_assets,
    relink_material_assets,
    relink_node_material_assets,
    relink_scene_assets,
)


def asset_record(asset: object) -> dict[str, object]:
    if not isinstance(asset, dict):
        return {"value": str(asset)}
    owner = asset.get("owner")
    try:
        owner_name = owner.GetName() if owner is not None else None
    except Exception:
        owner_name = None
    return {
        "filename": str(asset.get("filename") or ""),
        "assetname": str(asset.get("assetname") or ""),
        "exists": bool(asset.get("exists")),
        "ownerName": owner_name,
        "nodePath": str(asset.get("nodePath") or ""),
        "nodeSpace": str(asset.get("nodeSpace") or ""),
        "parameterId": int(asset.get("paramId", -1) or -1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--output-name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--take", default="Main")
    parser.add_argument("--frame", type=int, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_directory = args.output_directory.expanduser().resolve()
    output_project = output_directory / args.output_name
    manifest_path = args.manifest.expanduser().resolve()
    result_json = args.result_json.expanduser().resolve()
    report: dict[str, object] = {
        "status": "failed",
        "sourceProject": str(project),
        "outputDirectory": str(output_directory),
        "outputProject": str(output_project),
        "manifest": str(manifest_path),
        "take": args.take,
        "frame": args.frame,
        "sourcePreserved": True,
        "saved": False,
    }
    doc = None
    try:
        if not project.is_file():
            raise FileNotFoundError(project)
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        if output_directory.exists():
            raise FileExistsError(
                f"Refusing to reuse output directory: {output_directory}"
            )
        if Path(args.output_name).name != args.output_name:
            raise RuntimeError("--output-name must be a filename only")
        if not args.output_name.casefold().endswith(".c4d"):
            raise RuntimeError("--output-name must end with .c4d")
        if "_codex_" not in output_directory.name.casefold():
            raise RuntimeError(
                "Output directory must contain _codex_"
            )
        if "_codex_" not in args.output_name.casefold():
            raise RuntimeError("Output filename must contain _codex_")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mappings, unsafe_mappings = safe_manifest_mappings(manifest)
        if unsafe_mappings:
            raise RuntimeError(
                "Unsafe relink targets rejected: "
                + json.dumps(unsafe_mappings[:12], separators=(",", ":"))
            )
        if not mappings:
            raise RuntimeError("Manifest contains no usable exact mappings")

        doc = c4d.documents.LoadDocument(
            str(project),
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
        )
        if doc is None:
            raise RuntimeError("Cinema 4D could not load the source project")
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        take_data.SetCurrentTake(take)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))

        first_material = relink_material_assets(doc, mappings)
        first_material.extend(relink_node_material_assets(doc, mappings))
        first_scene = relink_scene_assets(doc, mappings)
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        second_material = relink_material_assets(doc, mappings)
        second_material.extend(relink_node_material_assets(doc, mappings))
        second_scene = relink_scene_assets(doc, mappings)
        dependency_audit = collect_post_relink_assets(doc, project)
        report.update(
            {
                "mappingCount": len(mappings),
                "firstMaterialRelinks": first_material,
                "firstSceneRelinks": first_scene,
                "postEvaluationMaterialRelinks": second_material,
                "postEvaluationSceneRelinks": second_scene,
                "postRelinkDependencyAudit": dependency_audit,
            }
        )
        if not dependency_audit.get("strictDependencyRenderSafe"):
            raise RuntimeError(
                "Strict post-relink dependency audit failed; refusing to save"
            )

        output_directory.mkdir(parents=True, exist_ok=False)
        doc.SetDocumentName(args.output_name)
        assets: list[object] = []
        missing_assets: list[object] = []
        flags = (
            c4d.SAVEPROJECT_ASSETS
            | c4d.SAVEPROJECT_SCENEFILE
            | c4d.SAVEPROJECT_WITHCACHES
            | c4d.SAVEPROJECT_ASSETLINKS_COPY_FILEASSETS
            | c4d.SAVEPROJECT_ASSETLINKS_COPY_NODEASSETS
        )
        saved = c4d.documents.SaveProject(
            doc,
            flags,
            str(output_directory),
            assets,
            missing_assets,
        )
        # Cinema 4D can ignore SetDocumentName here and name the packaged
        # scene after the destination folder. Resolve that deterministic
        # single-file result instead of misreporting a successful package as
        # failed merely because the requested basename was not honored.
        if saved and not output_project.is_file():
            packaged_projects = sorted(output_directory.glob("*.c4d"))
            if len(packaged_projects) == 1:
                output_project = packaged_projects[0]
                report["outputProject"] = str(output_project)
                report["requestedOutputProject"] = str(
                    output_directory / args.output_name
                )
        report.update(
            {
                "saveProjectFlags": int(flags),
                "saveProjectResult": bool(saved),
                "saved": bool(saved and output_project.is_file()),
                "packagedAssetCount": len(assets),
                "missingAssetCount": len(missing_assets),
                "missingAssets": [
                    asset_record(item) for item in missing_assets
                ],
                "outputProjectBytes": (
                    output_project.stat().st_size
                    if output_project.is_file()
                    else None
                ),
            }
        )
        if not saved:
            raise RuntimeError("Cinema 4D SaveProject returned false")
        if not output_project.is_file():
            raise RuntimeError(
                f"SaveProject did not create {output_project}"
            )
        if missing_assets:
            raise RuntimeError(
                f"SaveProject reported {len(missing_assets)} missing assets"
            )
        report["status"] = "saved_project_with_assets"
    except Exception as error:
        report["error"] = repr(error)
    finally:
        if doc is not None:
            c4d.documents.KillDocument(doc)
        result_json.parent.mkdir(parents=True, exist_ok=True)
        result_json.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(
            "PARACOSM_SAVE_PROJECT_JSON="
            + json.dumps(report, separators=(",", ":"))
        )


if __name__ == "__main__":
    main()
