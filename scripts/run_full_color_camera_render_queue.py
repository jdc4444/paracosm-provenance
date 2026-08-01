#!/usr/bin/env python3
"""Render fresh full-color Redshift process frames for verified shot cameras.

The source C4D files are opened read-only and never saved. Every completed
frame is process evidence until a separate canonical-frame visual review
accepts it as a camera/material proof.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "public" / "data" / "state.json"
BASE_PROOFS = ROOT / "data" / "c4d-camera-proof-renders.json"
AS_FINISHING_PROOFS = (
    ROOT / "data" / "as-finishing-camera-proofs-20260727.json"
)
OVERRIDES = (
    ROOT / "data" / "as-finishing-camera-proof-recovery-overrides-20260727.json"
)
HELPER = ROOT / "scripts" / "c4dpy_redshift_frame_test.py"
C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026.1.2/"
    "c4dpy.app/Contents/MacOS/c4dpy"
)
OUTPUT_ROOT = (
    ROOT / "public" / "archive" / "redshift-full-color-final-20260729"
)
RESULT_ROOT = ROOT / "data" / "c4d-clean-recoveries"
MANIFEST = ROOT / "data" / "c4d-full-color-render-queue-20260729.json"
MARKER = "PARACOSM_REDSHIFT_TEST_JSON="


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "camera"


def number_arg(value: Any) -> str:
    """Keep tiny negative camera values from looking like CLI options."""

    rendered = f"{float(value):.17f}".rstrip("0").rstrip(".")
    return rendered if rendered not in {"", "-0"} else "0"


def runtime_render_data_name(value: Any) -> str:
    """Reduce audit prose that names multiple revisions to a saved selector."""

    candidate = str(value or "").strip()
    if ";" in candidate:
        candidate = candidate.split(";", 1)[0].strip()
    if " (" in candidate:
        candidate = candidate.split(" (", 1)[0].strip()
    return candidate


def write_manifest(
    records: list[dict[str, Any]],
    path: Path,
    runtime: Path = C4DPY,
) -> None:
    status_counts = Counter(str(item.get("status") or "pending") for item in records)
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Fresh material-enabled single-frame Redshift attempts from the "
            "final mapped C4D project, saved take, render data, identified "
            "camera, and exact cut frame. Source projects are never saved. "
            "Completed frames remain process evidence until visually accepted "
            "against the canonical cut."
        ),
        "runtime": str(runtime),
        "summary": {
            "targets": len(records),
            "cuts": len({str(item.get("cutId") or "") for item in records}),
            "statuses": dict(status_counts),
        },
        "records": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def existing_full_color_cuts() -> set[str]:
    existing: set[str] = set()
    for result_path in RESULT_ROOT.glob("*-result.json"):
        try:
            result = load(result_path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict) or result.get("status") != "rendered":
            continue
        output = Path(str(result.get("output") or ""))
        output_name = output.name.casefold()
        if (
            not output.exists()
            or result.get("greyOverride")
            or re.search(r"(?:grey|hardware|contact|comparison|smoke)", output_name)
            or not re.search(
                r"(?:redshift|material|full[-_ ]?color)", output_name
            )
        ):
            continue
        match = re.search(r"CUT[-_](\d{3})", result_path.name)
        if match:
            existing.add(f"CUT-{match.group(1)}")
    return existing


def proof_maps() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    base = {
        str(cut_id): proof
        for proof in load(BASE_PROOFS).get("proofs", [])
        for cut_id in proof.get("cutIds", [])
    }
    for proof in load(AS_FINISHING_PROOFS).get("proofs", []):
        cut_id = str(proof.get("cutId") or "")
        if not cut_id:
            continue
        merged = {**(base.get(cut_id) or {}), **proof}
        # The AS finishing ledger is the later camera authority. Do not retain
        # an older archive-reconstruction transform merely because the newer
        # record uses a direct saved camera and therefore omits those fields.
        merged["cameraReconstructedFromArchive"] = bool(
            proof.get("cameraReconstructedFromArchive")
        )
        if not merged["cameraReconstructedFromArchive"]:
            merged["cameraObject"] = proof.get("cameraObject") or {}
        base[cut_id] = merged
    overrides = {
        str(item.get("cutId") or ""): item
        for item in load(OVERRIDES).get("proofOverrides", [])
        if item.get("cutId")
    }
    return base, overrides


def build_records(
    selected: set[str],
    force: bool,
    include_partial: bool,
) -> list[dict[str, Any]]:
    state = load(STATE)
    base_proofs, overrides = proof_maps()
    existing = existing_full_color_cuts()
    records: list[dict[str, Any]] = []
    for cut in state.get("cuts", []):
        cut_id = str(cut.get("id") or "")
        if cut.get("isGap") or (selected and cut_id not in selected):
            continue
        link = cut.get("c4dLinkStatus") or {}
        exact = link.get("exactCutAudit") or {}
        review = (cut.get("c4dVerification") or {}).get("elements") or {}
        camera_review = str(review.get("camera") or "").casefold()
        camera_matches = (
            ("match" in camera_review and "mismatch" not in camera_review)
            or camera_review.startswith("confirmed_exact")
            or camera_review.startswith("exact_final")
        )
        camera_partial = camera_review.startswith(
            (
                "partial",
                "near_match",
                "same_shot",
                "insufficient_geometry",
            )
        )
        base = base_proofs.get(cut_id) or {}
        override = overrides.get(cut_id) or {}
        current_proof = next(
            (
                node
                for node in reversed(cut.get("lineage", []))
                if node.get("kind") == "camera_proof"
                and node.get("cameraRenderData")
                and node.get("projectPath")
                and str(node.get("proofStatus") or "").casefold()
                != "rejected"
                and "rejected"
                not in str(node.get("label") or "").casefold()
            ),
            {},
        )
        active = {**base, **current_proof} if current_proof else base
        if current_proof:
            current_proof_label = str(current_proof.get("label") or "")
            active["cameraName"] = (
                current_proof.get("cameraName")
                or current_proof_label.split(" · frame", 1)[0].strip()
                or Path(
                    str(current_proof.get("cameraObjectPath") or "")
                ).name
                or ""
            )
            active["cameraReconstructedFromArchive"] = bool(
                current_proof.get("cameraReconstructedFromArchive")
            )
            if not active["cameraReconstructedFromArchive"]:
                active["cameraObject"] = current_proof.get("cameraObject") or {}
        selected_project = Path(
            str(
                override.get("projectPath")
                or active.get("projectPath")
                or link.get("projectPath")
                or ""
            )
        )
        compressed_source_project = (
            selected_project
            if selected_project.name.casefold().endswith(".c4d.zst")
            else None
        )
        project = selected_project
        if compressed_source_project is not None:
            usable_link_project = Path(str(link.get("projectPath") or ""))
            if usable_link_project.exists():
                project = usable_link_project
        override_changes_project = bool(
            override.get("projectPath")
            and str(override.get("projectPath"))
            != str(active.get("projectPath") or "")
        )
        camera_name = str(
            override.get("cameraName")
            or active.get("cameraName")
            or active.get("cameraObjectPath")
            or ""
        )
        camera_path = str(
            override.get("cameraObjectPath")
            or active.get("cameraObjectPath")
            or camera_name
        )
        take = str(
            override.get("cameraTake")
            or active.get("cameraTake")
            or link.get("take")
            or "Main"
        )
        render_data = runtime_render_data_name(
            override.get("cameraRenderData")
            or active.get("cameraRenderData")
        )
        frame_value = (
            override.get("targetFrame")
            if override.get("targetFrame") is not None
            else active.get("targetFrame")
            if active.get("targetFrame") is not None
            else link.get("frame")
        )
        frame = int(frame_value) if frame_value is not None else None
        manifest_value = str(exact.get("manifestPath") or "")
        relink_manifest = (
            ROOT / manifest_value
            if manifest_value and not Path(manifest_value).is_absolute()
            else Path(manifest_value)
        )
        reason = ""
        if not project.exists():
            reason = "project_missing"
        elif not camera_name:
            reason = "camera_missing"
        elif not render_data:
            reason = "render_data_missing"
        elif frame is None:
            reason = "frame_missing"
        elif not camera_matches and not (include_partial and camera_partial):
            reason = f"camera_review_{camera_review or 'unavailable'}"
        elif cut_id in existing and not force:
            reason = "existing_full_color_result"
        elif not manifest_value or not relink_manifest.is_file():
            reason = "exact_relink_manifest_missing"
        elif not bool(exact.get("strictDependencyRenderSafe")):
            reason = "exact_relink_manifest_not_render_safe"

        stem = slug(
            f"{project.stem}-{camera_name}-f{frame if frame is not None else 0:06d}"
        )
        output = OUTPUT_ROOT / cut_id / f"{cut_id}-{stem}-redshift-full-color.png"
        result_path = (
            RESULT_ROOT
            / f"{cut_id}-{stem}-redshift-full-color-20260729-result.json"
        )
        reconstructed = bool(
            override.get("cameraReconstructedFromArchive")
            or (
                active.get("cameraReconstructedFromArchive")
                and not override_changes_project
            )
        )
        camera_object = (
            override.get("cameraObject")
            if override.get("cameraObject")
            else active.get("cameraObject")
            if reconstructed
            else {}
        ) or {}
        position = camera_object.get("position") or {}
        rotation = camera_object.get("rotationRadians") or {}
        reconstruction_ready = bool(
            reconstructed
            and all(key in position for key in ("x", "y", "z"))
            and all(key in rotation for key in ("x", "y", "z"))
        )
        records.append(
            {
                "cutId": cut_id,
                "status": "skipped" if reason else "pending",
                "skipReason": reason or None,
                "projectPath": str(project),
                "compressedSourceProjectPath": (
                    str(compressed_source_project)
                    if compressed_source_project is not None
                    else None
                ),
                "take": take,
                "renderData": render_data,
                "frame": frame,
                "cameraName": camera_name,
                "cameraPath": camera_path,
                "cameraReview": camera_review,
                "relinkManifest": str(relink_manifest),
                "strictDependencyRenderSafe": bool(
                    exact.get("strictDependencyRenderSafe")
                ),
                "reconstructCamera": reconstruction_ready,
                "cameraPosition": position if reconstruction_ready else None,
                "cameraRotation": rotation if reconstruction_ready else None,
                "cameraFocalLength": camera_object.get("focalLength"),
                "cameraAperture": camera_object.get("aperture"),
                "cameraSourceObjectType": camera_object.get("typeId"),
                "outputPath": str(output),
                "publicPath": "/" + output.relative_to(ROOT / "public").as_posix(),
                "resultPath": str(result_path.relative_to(ROOT)),
                "proofEligible": False,
            }
        )
    return records


def render_record(
    record: dict[str, Any],
    timeout: int,
    width: int,
    height: int,
    runtime: Path = C4DPY,
) -> None:
    output = Path(str(record["outputPath"]))
    result_path = ROOT / str(record["resultPath"])
    log_path = result_path.with_suffix(".log")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "caffeinate",
        "-dimsu",
        str(runtime),
        str(HELPER),
        "--project",
        str(record["projectPath"]),
        "--output",
        str(output),
        "--result-json",
        str(result_path),
        "--frame",
        str(record["frame"]),
        "--camera",
        str(record["cameraName"]),
        "--camera-path",
        str(record["cameraPath"]),
        "--take",
        str(record["take"]),
        "--render-data",
        str(record["renderData"]),
        "--native-clone-legacy-camera",
        "--exact-material-relink-manifest",
        str(record["relinkManifest"]),
        "--width",
        str(width),
        "--height",
        str(height),
        "--bake-ocio-view",
    ]
    if record.get("reconstructCamera"):
        position = record["cameraPosition"]
        rotation = record["cameraRotation"]
        command.extend(
            [
                "--reconstruct-camera-position",
                number_arg(position["x"]),
                number_arg(position["y"]),
                number_arg(position["z"]),
                "--reconstruct-camera-rotation",
                number_arg(rotation["x"]),
                number_arg(rotation["y"]),
                number_arg(rotation["z"]),
                "--reconstruct-camera-focal",
                number_arg(record.get("cameraFocalLength") or 35.0),
                "--reconstruct-camera-aperture",
                number_arg(record.get("cameraAperture") or 36.0),
            ]
        )
        # Archive-derived hardware proofs store the transform and lens from
        # the native Cinema camera (type 5103), even when the historical
        # camera selector was a legacy Redshift object. Cloning that legacy
        # selector changes the projection and produces a false camera view.
        # Preserve a requested template only when the archived source object
        # itself was non-native.
        if record.get("cameraSourceObjectType") not in (None, 5103):
            command.append("--reconstruct-camera-from-requested-template")
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(combined, encoding="utf-8")
        record["renderLogPath"] = str(log_path.relative_to(ROOT))
        marker = next(
            (
                line
                for line in combined.splitlines()
                if line.startswith(MARKER)
            ),
            None,
        )
        if marker is not None:
            payload = json.loads(marker[len(MARKER) :])
        elif result_path.exists():
            payload = load(result_path)
        else:
            payload = {
                "status": "failed",
                "error": (
                    f"c4dpy returned {completed.returncode} without a result: "
                    + combined[-1800:]
                ),
            }
        record["status"] = str(payload.get("status") or "failed")
        post_audit = payload.get("postRelinkDependencyAudit") or {}
        record["renderResult"] = {
            "status": payload.get("status"),
            "output": payload.get("output"),
            "seconds": payload.get("seconds"),
            "error": payload.get("error"),
            "camera": payload.get("camera"),
            "cameraPath": payload.get("cameraPath"),
            "cameraFallbackToTake": payload.get("cameraFallbackToTake"),
            "cameraReconstructedFromArguments": payload.get(
                "cameraReconstructedFromArguments"
            ),
            "unresolvedPictureReferences": post_audit.get(
                "unresolvedPictureReferences"
            ),
            "unresolvedPictureFiles": post_audit.get(
                "unresolvedPictureFiles"
            ),
            "strictDependencyRenderSafe": post_audit.get(
                "strictDependencyRenderSafe"
            ),
        }
        if record["status"] == "rendered" and not output.exists():
            record["status"] = "failed"
            record["renderResult"]["error"] = "render output is missing"
    except subprocess.TimeoutExpired as error:
        record["status"] = "failed"
        record["renderResult"] = {
            "status": "failed",
            "error": f"TimeoutExpired after {error.timeout} seconds",
        }
    except Exception as error:
        record["status"] = "failed"
        record["renderResult"] = {
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cut-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--include-partial-camera", action="store_true")
    parser.add_argument("--max-targets", type=int)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=405)
    parser.add_argument("--runtime", type=Path, default=C4DPY)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()

    records = build_records(
        set(args.cut_id),
        force=args.force,
        include_partial=args.include_partial_camera,
    )
    runnable = [record for record in records if record["status"] == "pending"]
    if args.max_targets is not None:
        allowed = {
            id(record)
            for record in runnable[: max(0, args.max_targets)]
        }
        for record in runnable:
            if id(record) not in allowed:
                record["status"] = "skipped"
                record["skipReason"] = "max_targets"
        runnable = runnable[: max(0, args.max_targets)]
    runtime = args.runtime.expanduser().resolve()
    write_manifest(records, args.manifest, runtime)
    if args.plan_only:
        print(
            f"Planned {len(runnable)} new full-color renders "
            f"from {len(records)} reviewed picture cuts"
        )
        return
    for index, record in enumerate(runnable, start=1):
        print(
            f"[{index}/{len(runnable)}] {record['cutId']} · "
            f"{Path(str(record['projectPath'])).name}",
            flush=True,
        )
        render_record(
            record,
            args.timeout,
            args.width,
            args.height,
            runtime,
        )
        write_manifest(records, args.manifest, runtime)
    print(f"Wrote full-color queue state to {args.manifest}")


if __name__ == "__main__":
    main()
