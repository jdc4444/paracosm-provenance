"""Save a non-destructive camera-exposure test copy of a packaged C4D scene."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take
from c4dpy_verify_relink_manifest import collect_active_render_dependencies
from c4dpy_redshift_frame_test import (
    collect_post_relink_assets,
    find_camera,
)


EXPOSURE_TYPE_PARAMETER = 7016
EXPOSURE_EV_PARAMETER = 1220
EXPOSURE_TYPE_EV_ONLY = 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--take", default="Main")
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--camera-path")
    parser.add_argument("--exposure-ev", type=float, required=True)
    parser.add_argument(
        "--allow-active-frame-safe-with-dormant-project-residue",
        action="store_true",
        help=(
            "Permit a dated exposure-test copy when the evaluated take/frame "
            "is render-safe but disabled objects retain project-wide missing "
            "references. Both audit scopes are recorded."
        ),
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    result_path = args.result_json.expanduser().resolve()
    report: dict[str, object] = {
        "status": "failed",
        "sourceProject": str(project),
        "outputProject": str(output),
        "take": args.take,
        "frame": args.frame,
        "camera": args.camera,
        "cameraPath": args.camera_path,
        "requestedExposureEv": args.exposure_ev,
        "sourcePreserved": True,
        "saved": False,
    }
    doc = None
    try:
        if not project.is_file():
            raise FileNotFoundError(project)
        if output.exists():
            raise FileExistsError(f"Refusing to overwrite {output}")
        if output.parent != project.parent:
            raise RuntimeError(
                "Exposure copy must stay beside the packaged project so all "
                "relative asset links remain valid"
            )
        if "_codex_" not in output.name.casefold():
            raise RuntimeError("Output filename must contain _codex_")

        doc = c4d.documents.LoadDocument(
            str(project),
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
        )
        if doc is None:
            raise RuntimeError("Cinema 4D could not load the package")
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        take_data.SetCurrentTake(take)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        camera = find_camera(doc, args.camera, args.camera_path)
        if camera is None:
            raise RuntimeError(f"Camera not found: {args.camera}")

        exposure_type_before = int(camera[EXPOSURE_TYPE_PARAMETER])
        exposure_ev_before = float(camera[EXPOSURE_EV_PARAMETER])
        if exposure_type_before != EXPOSURE_TYPE_EV_ONLY:
            raise RuntimeError(
                "Camera is not authored in EV Only mode: "
                f"{exposure_type_before}"
            )
        camera[EXPOSURE_EV_PARAMETER] = float(args.exposure_ev)
        camera.Message(c4d.MSG_UPDATE)
        c4d.EventAdd()
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        exposure_ev_after = float(camera[EXPOSURE_EV_PARAMETER])
        if abs(exposure_ev_after - args.exposure_ev) > 1e-9:
            raise RuntimeError(
                f"Camera exposure did not verify: {exposure_ev_after}"
            )
        active_frame_dependency_audit = collect_active_render_dependencies(
            doc, project
        )
        dependency_audit = collect_post_relink_assets(doc, project)
        active_frame_safe = not active_frame_dependency_audit.get(
            "renderCriticalUnresolvedFiles"
        )
        project_wide_safe = bool(
            dependency_audit.get("strictDependencyRenderSafe")
        )
        if not project_wide_safe and not (
            args.allow_active_frame_safe_with_dormant_project_residue
            and active_frame_safe
        ):
            raise RuntimeError(
                "Project-wide dependency audit failed and the explicit "
                "active-frame-safe dormant-residue gate did not pass"
            )
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        if not saved or not output.is_file():
            raise RuntimeError("Cinema 4D failed to save the exposure copy")
        report.update(
            {
                "status": "saved_exposure_test_copy",
                "saved": True,
                "cameraResolvedName": camera.GetName(),
                "cameraExposureType": exposure_type_before,
                "cameraExposureEvBefore": exposure_ev_before,
                "cameraExposureEvAfter": exposure_ev_after,
                "activeFrameDependencyAuditBeforeSave": (
                    active_frame_dependency_audit
                ),
                "dependencyAuditBeforeSave": dependency_audit,
                "saveGate": {
                    "activeFrameSafe": bool(active_frame_safe),
                    "projectWideSafe": project_wide_safe,
                    "dormantProjectResidueAccepted": bool(
                        not project_wide_safe
                        and active_frame_safe
                        and args.allow_active_frame_safe_with_dormant_project_residue
                    ),
                },
                "outputProjectBytes": output.stat().st_size,
            }
        )
    except Exception as error:
        report["error"] = repr(error)
    finally:
        if doc is not None:
            c4d.documents.KillDocument(doc)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, separators=(",", ":")), flush=True)
        os._exit(0)


if __name__ == "__main__":
    main()
