"""Prepare an isolated, exactly relinked C4D package for native rendering.

The source document is loaded read-only.  Exact dependency mappings are
applied only to the in-memory document, the requested take/camera/render data
are selected, and Cinema 4D's Save Project with Assets operation creates a
portable project at an explicit non-existing path.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take
from c4dpy_redshift_frame_test import (
    collect_post_relink_assets,
    find_camera,
    find_render_data,
    object_path,
    redshift_color_management,
    relink_material_assets,
    relink_node_material_assets,
    relink_scene_assets,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-project", type=Path, required=True)
    parser.add_argument("--render-output-base", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--exact-material-relink-manifest", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--camera-path")
    parser.add_argument("--take", default="Main")
    parser.add_argument("--render-data", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_project = args.output_project.expanduser().resolve()
    render_output_base = args.render_output_base.expanduser().resolve()
    result_json = args.result_json.expanduser().resolve()
    manifest_path = (
        args.exact_material_relink_manifest.expanduser().resolve()
    )
    report: dict[str, object] = {
        "status": "failed",
        "sourceProject": str(project),
        "outputProject": str(output_project),
        "sourcePreserved": True,
    }
    doc = None
    try:
        if not project.is_file():
            raise FileNotFoundError(project)
        if not manifest_path.is_file():
            raise FileNotFoundError(manifest_path)
        if output_project.exists():
            raise FileExistsError(
                f"Refusing to overwrite prepared project: {output_project}"
            )
        if output_project == project:
            raise RuntimeError("Prepared project must differ from source")
        if output_project.parent.exists() and any(
            output_project.parent.iterdir()
        ):
            raise FileExistsError(
                "Refusing to mix a prepared project with an existing package: "
                f"{output_project.parent}"
            )
        output_project.parent.mkdir(parents=True, exist_ok=True)
        render_output_base.parent.mkdir(parents=True, exist_ok=True)

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

        render_data = find_render_data(doc, args.render_data)
        if render_data is None:
            raise RuntimeError(f"Render data not found: {args.render_data}")
        camera = find_camera(doc, args.camera, args.camera_path)
        if camera is None:
            raise RuntimeError(
                f"Camera not found: {args.camera_path or args.camera}"
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mappings = {
            str(item.get("requiredPath") or ""): str(
                item.get("targetPath") or ""
            )
            for item in manifest.get("mappings", [])
            if item.get("requiredPath") and item.get("targetPath")
        }
        first_material_relinks = relink_material_assets(doc, mappings)
        first_material_relinks.extend(
            relink_node_material_assets(doc, mappings)
        )
        first_scene_relinks = relink_scene_assets(doc, mappings)

        fps = doc.GetFps()
        doc.SetTime(c4d.BaseTime(args.frame, fps))
        doc.GetRenderBaseDraw().SetSceneCamera(camera)
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        second_material_relinks = relink_material_assets(doc, mappings)
        second_material_relinks.extend(
            relink_node_material_assets(doc, mappings)
        )
        second_scene_relinks = relink_scene_assets(doc, mappings)
        dependency_audit = collect_post_relink_assets(doc, project)
        # Retain the exact failing audit as evidence even when the strict gate
        # correctly refuses to create a portable package.  Without this, a
        # failed historical revision only reports a boolean failure and hides
        # the active owners/paths needed to decide whether the revision is
        # locally recoverable.
        report["postRelinkDependencyAudit"] = dependency_audit
        if not dependency_audit.get("strictDependencyRenderSafe"):
            raise RuntimeError(
                "Strict post-relink dependency audit failed; refusing to "
                "save a native-render candidate"
            )

        settings = render_data.GetData()
        settings[c4d.RDATA_RENDERENGINE] = 1036219
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_FRAMEFROM] = doc.GetTime()
        settings[c4d.RDATA_FRAMETO] = doc.GetTime()
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        settings[c4d.RDATA_PATH] = str(render_output_base)
        settings[c4d.RDATA_SAVEIMAGE] = True
        settings[c4d.RDATA_MULTIPASS_ENABLE] = False
        render_data.SetData(settings)
        doc.SetActiveRenderData(render_data)

        # A plain SaveDocument call makes source-relative texture URLs relative
        # to the new output directory without copying their targets.  Cinema's
        # supported movable-scene operation instead copies/localizes all
        # dependencies (including node material assets) into the package.
        original_document_name = doc.GetDocumentName()
        doc.SetDocumentName(output_project.name)
        packaged_assets: list[dict[str, object]] = []
        missing_packaged_assets: list[dict[str, object]] = []
        save_project_flags = (
            c4d.SAVEPROJECT_ASSETS
            | c4d.SAVEPROJECT_SCENEFILE
            | c4d.SAVEPROJECT_USEDOCUMENTNAMEASFILENAME
            | c4d.SAVEPROJECT_WITHCACHES
            | c4d.SAVEPROJECT_ASSETLINKS_COPY_FILEASSETS
        )
        saved = c4d.documents.SaveProject(
            doc,
            save_project_flags,
            str(output_project.parent),
            packaged_assets,
            missing_packaged_assets,
        )
        if not saved:
            raise RuntimeError(
                "Cinema 4D SaveProject returned false; "
                f"missing packaged assets: {len(missing_packaged_assets)}"
            )
        if not output_project.is_file():
            raise RuntimeError(
                "Cinema 4D reported a successful package save but the expected "
                f"project does not exist: {output_project}"
            )

        report.update(
            {
                "status": "prepared",
                "frame": args.frame,
                "fps": fps,
                "take": take.GetName(),
                "camera": camera.GetName(),
                "cameraPath": object_path(camera),
                "cameraTypeId": camera.GetType(),
                "renderData": render_data.GetName(),
                "resolution": [args.width, args.height],
                "renderOutputBase": str(render_output_base),
                "renderFormat": settings[c4d.RDATA_FORMAT],
                "renderFormatDepth": settings[c4d.RDATA_FORMATDEPTH],
                "renderColorProfile": str(
                    settings[c4d.RDATA_IMAGECOLORPROFILE]
                ),
                "redshiftColorManagement": redshift_color_management(
                    render_data
                ),
                "exactMappingCount": len(mappings),
                "firstMaterialRelinks": first_material_relinks,
                "firstSceneRelinks": first_scene_relinks,
                "postEvaluationMaterialRelinks": second_material_relinks,
                "postEvaluationSceneRelinks": second_scene_relinks,
                "postRelinkDependencyAudit": dependency_audit,
                "saveMethod": "c4d.documents.SaveProject",
                "saveProjectFlags": save_project_flags,
                "sourceDocumentName": original_document_name,
                "packagedAssetCount": len(packaged_assets),
                "missingPackagedAssetCount": len(
                    missing_packaged_assets
                ),
                "missingPackagedAssets": [
                    str(item.get("filename") or "")
                    for item in missing_packaged_assets
                ],
            }
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        result_json.parent.mkdir(parents=True, exist_ok=True)
        result_json.write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(
            "PARACOSM_EXACT_NATIVE_PROJECT_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        if doc is not None:
            c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
