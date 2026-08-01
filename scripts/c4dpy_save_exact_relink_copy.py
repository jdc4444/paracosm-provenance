"""Save a non-destructive C4D copy after exact manifest relinks verify.

The source document is opened read-only. Exact classic, node, and Redshift
scene-asset mappings are applied, the requested take/frame is evaluated, and
the same strict dependency collectors used by render proofs must pass before a
new Codex-dated copy can be saved. Project-wide strictness remains the default;
an explicit opt-in can accept documented dormant residue only when the selected
take/frame has no render-critical unresolved dependency.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4d_relink_safety import safe_manifest_mappings
from c4dpy_camera_proof import find_take
from c4dpy_verify_relink_manifest import collect_active_render_dependencies
from c4dpy_redshift_frame_test import (
    collect_post_relink_assets,
    find_camera,
    find_render_data,
    relink_material_assets,
    relink_node_material_assets,
    relink_scene_assets,
    repair_missing_redshift_surface_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--take", default="Main")
    parser.add_argument(
        "--render-data",
        help=(
            "Make this exact authored render setting active in the recovery "
            "copy so normal Cinema batch rendering uses the intended chain."
        ),
    )
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument(
        "--repair-missing-rs-surface-output",
        action="store_true",
        help=(
            "Reconnect authored terminal shaders to empty Redshift surface "
            "outputs before saving the dated recovery copy."
        ),
    )
    parser.add_argument(
        "--allow-active-frame-safe-with-dormant-project-residue",
        action="store_true",
        help=(
            "Allow a recovery copy only when the evaluated take/frame has no "
            "render-critical unresolved dependency, even if disabled dormant "
            "objects retain project-wide missing paths. The full residue is "
            "still recorded in the result JSON."
        ),
    )
    parser.add_argument("--camera")
    parser.add_argument("--camera-path")
    parser.add_argument("--exposure-camera")
    parser.add_argument("--exposure-camera-path")
    parser.add_argument("--camera-exposure-ev", type=float)
    parser.add_argument("--rs-post-effects-exposure-ev", type=float)
    parser.add_argument("--recovery-camera-name")
    parser.add_argument(
        "--reconstruct-camera-position",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
    )
    parser.add_argument(
        "--reconstruct-camera-rotation",
        nargs=3,
        type=float,
        metavar=("H", "P", "B"),
    )
    parser.add_argument("--reconstruct-camera-focal", type=float)
    parser.add_argument("--reconstruct-camera-aperture", type=float)
    args = parser.parse_args()
    camera_recovery_values = (
        args.camera,
        args.reconstruct_camera_position,
        args.reconstruct_camera_rotation,
        args.reconstruct_camera_focal,
        args.reconstruct_camera_aperture,
    )
    if any(value is not None for value in camera_recovery_values) and not all(
        value is not None for value in camera_recovery_values
    ):
        parser.error(
            "--camera, --reconstruct-camera-position, "
            "--reconstruct-camera-rotation, --reconstruct-camera-focal, and "
            "--reconstruct-camera-aperture must be provided together"
        )
    exposure_values = (
        args.exposure_camera,
        args.camera_exposure_ev,
    )
    if any(value is not None for value in exposure_values) and not all(
        value is not None for value in exposure_values
    ):
        parser.error(
            "--exposure-camera and --camera-exposure-ev must be provided "
            "together"
        )

    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    result_json = args.result_json.expanduser().resolve()
    report: dict[str, object] = {
        "status": "failed",
        "sourceProject": str(project),
        "outputProject": str(output),
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
        if output == project:
            raise RuntimeError("Output must differ from the source project")
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
        active_render_data = doc.GetActiveRenderData()
        if args.render_data is not None:
            active_render_data = find_render_data(doc, args.render_data)
            if active_render_data is None:
                raise RuntimeError(
                    f"Render data not found: {args.render_data}"
                )
            doc.SetActiveRenderData(active_render_data)
        post_effects_exposure_adjustment = None
        if args.rs_post_effects_exposure_ev is not None:
            if active_render_data is None:
                raise RuntimeError(
                    "--rs-post-effects-exposure-ev requires active render data"
                )
            post_effects = active_render_data.GetFirstVideoPost()
            while (
                post_effects is not None
                and post_effects.GetType() != 1040189
            ):
                post_effects = post_effects.GetNext()
            if post_effects is None:
                raise RuntimeError(
                    "RS Post-Effects video post not found in active render data"
                )
            override_before = bool(post_effects[12504])
            enabled_before = bool(post_effects[12500])
            exposure_before = float(post_effects[12501])
            post_effects[12504] = True
            post_effects[12500] = True
            post_effects[12501] = float(
                args.rs_post_effects_exposure_ev
            )
            post_effects.Message(c4d.MSG_UPDATE)
            override_after = bool(post_effects[12504])
            enabled_after = bool(post_effects[12500])
            exposure_after = float(post_effects[12501])
            if (
                not override_after
                or not enabled_after
                or abs(
                    exposure_after - args.rs_post_effects_exposure_ev
                )
                > 1e-9
            ):
                raise RuntimeError(
                    "RS Post-Effects exposure adjustment did not verify"
                )
            post_effects_exposure_adjustment = {
                "videoPost": post_effects.GetName(),
                "typeId": post_effects.GetType(),
                "colorControlsOverrideBefore": override_before,
                "colorControlsOverrideAfter": override_after,
                "colorControlsEnabledBefore": enabled_before,
                "colorControlsEnabledAfter": enabled_after,
                "exposureEvBefore": exposure_before,
                "exposureEvAfter": exposure_after,
                "currentRuntimeCalibration": True,
            }

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
        redshift_surface_output_repair = (
            repair_missing_redshift_surface_outputs(
                doc,
                [],
                args.repair_missing_rs_surface_output,
            )
        )
        exposure_adjustment = None
        if args.exposure_camera is not None:
            exposure_camera = find_camera(
                doc,
                args.exposure_camera,
                args.exposure_camera_path,
            )
            if exposure_camera is None:
                raise RuntimeError(
                    f"Exposure camera not found: {args.exposure_camera}"
                )
            exposure_type = int(exposure_camera[7016])
            if exposure_type != 0:
                raise RuntimeError(
                    "Exposure camera is not authored in EV Only mode: "
                    f"{exposure_type}"
                )
            exposure_before = float(exposure_camera[1220])
            exposure_camera[1220] = float(args.camera_exposure_ev)
            exposure_camera.Message(c4d.MSG_UPDATE)
            c4d.EventAdd()
            exposure_after = float(exposure_camera[1220])
            if abs(exposure_after - args.camera_exposure_ev) > 1e-9:
                raise RuntimeError(
                    f"Camera exposure did not verify: {exposure_after}"
                )
            exposure_adjustment = {
                "camera": exposure_camera.GetName(),
                "cameraPath": args.exposure_camera_path,
                "exposureType": exposure_type,
                "exposureEvBefore": exposure_before,
                "exposureEvAfter": exposure_after,
                "currentRuntimeCalibration": True,
            }
        recovered_camera = None
        if args.camera is not None:
            source_camera = find_camera(doc, args.camera, args.camera_path)
            if source_camera is None:
                raise RuntimeError(f"Camera not found: {args.camera}")
            recovered_camera = source_camera.GetClone(
                getattr(c4d, "COPYFLAGS_NONE", 0)
            )
            track = recovered_camera.GetFirstCTrack()
            while track:
                next_track = track.GetNext()
                track.Remove()
                track = next_track
            recovered_camera.SetName(
                args.recovery_camera_name
                or f"{args.camera} CODEX FRAME {args.frame} RECOVERY"
            )
            recovered_camera.SetAbsPos(
                c4d.Vector(*args.reconstruct_camera_position)
            )
            recovered_camera.SetAbsRot(
                c4d.Vector(*args.reconstruct_camera_rotation)
            )
            recovered_camera[c4d.CAMERA_FOCUS] = (
                args.reconstruct_camera_focal
            )
            recovered_camera[c4d.CAMERAOBJECT_APERTURE] = (
                args.reconstruct_camera_aperture
            )
            doc.InsertObject(recovered_camera)
            recovered_camera.Message(c4d.MSG_UPDATE)
        active_frame_dependency_audit = collect_active_render_dependencies(
            doc, project
        )
        dependency_audit = collect_post_relink_assets(doc, project)
        manifest_unresolved = manifest.get("unresolved", [])
        active_frame_safe = (
            not manifest_unresolved
            and not active_frame_dependency_audit.get(
                "renderCriticalUnresolvedFiles"
            )
        )
        project_wide_safe = bool(
            dependency_audit.get("strictDependencyRenderSafe")
        )
        save_gate_mode = (
            "project_wide_strict"
            if project_wide_safe
            else "active_frame_safe_with_dormant_project_residue"
        )
        report.update(
            {
                "mappingCount": len(mappings),
                "manifestUnresolved": manifest_unresolved,
                "activeRenderData": (
                    active_render_data.GetName()
                    if active_render_data is not None
                    else None
                ),
                "redshiftPostEffectsExposureAdjustment": (
                    post_effects_exposure_adjustment
                ),
                "firstMaterialRelinks": first_material,
                "firstSceneRelinks": first_scene,
                "postEvaluationMaterialRelinks": second_material,
                "postEvaluationSceneRelinks": second_scene,
                "redshiftSurfaceOutputRepair": (
                    redshift_surface_output_repair
                ),
                "cameraExposureAdjustment": exposure_adjustment,
                "activeFrameDependencyAudit": (
                    active_frame_dependency_audit
                ),
                "postRelinkDependencyAudit": dependency_audit,
                "saveGate": {
                    "mode": save_gate_mode,
                    "activeFrameSafe": bool(active_frame_safe),
                    "projectWideSafe": project_wide_safe,
                    "dormantProjectResidueAccepted": bool(
                        not project_wide_safe
                        and active_frame_safe
                        and args.allow_active_frame_safe_with_dormant_project_residue
                    ),
                },
                "recoveredCamera": (
                    {
                        "sourceName": args.camera,
                        "sourcePath": args.camera_path,
                        "name": recovered_camera.GetName(),
                        "position": args.reconstruct_camera_position,
                        "rotationRadians": args.reconstruct_camera_rotation,
                        "focalLength": args.reconstruct_camera_focal,
                        "aperture": args.reconstruct_camera_aperture,
                        "animationTracksRemoved": True,
                    }
                    if recovered_camera is not None
                    else None
                ),
            }
        )
        if not project_wide_safe and not (
            args.allow_active_frame_safe_with_dormant_project_residue
            and active_frame_safe
        ):
            raise RuntimeError(
                "Project-wide strict dependency audit failed and the explicit "
                "active-frame-safe dormant-residue gate did not pass; "
                "refusing to save"
            )
        if not project_wide_safe and output.parent != project.parent:
            raise RuntimeError(
                "Active-frame-safe recovery copies with dormant project "
                "residue must be saved beside the source project so relative "
                "dependencies keep the same resolution base"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        if not saved or not output.is_file():
            raise RuntimeError("Cinema 4D SaveDocument did not create output")
        report.update({"status": "saved", "saved": True})
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        result_json.parent.mkdir(parents=True, exist_ok=True)
        result_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            "PARACOSM_EXACT_RELINK_COPY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        if doc is not None:
            c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
