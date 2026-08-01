#!/usr/bin/env python3
"""Render resumable exact-settings Redshift recovery proofs by film section.

Every source project is opened in an isolated Cinema 4D process and is never
saved. The helper clones the complete requested RenderData, including its
VideoPost chain, then applies only the requested single-frame output overrides
in memory. Completed frames remain yellow/process evidence until separately
compared with the canonical production render.

TH remains the reference implementation. Other sections use only their own
cut-specific relink manifests; no TH picture manifest or cross-shot cache is
inherited outside TH.
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

from run_full_color_camera_render_queue import build_records


ROOT = Path(__file__).resolve().parents[1]
C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026.1.4/"
    "c4dpy.app/Contents/MacOS/c4dpy"
)
HELPER = ROOT / "scripts" / "c4dpy_redshift_frame_test.py"
PICTURE_MANIFEST = (
    ROOT
    / "data"
    / "c4d-material-recovery-20260729"
    / "CUT-040-full-picture-relink-manifest.json"
)
RESULT_ROOT = ROOT / "data" / "c4d-material-recovery-20260729"
ARCHIVE_ROOT = (
    ROOT / "public" / "archive" / "redshift-material-recovery-20260729"
)
TH_CUTS = tuple(f"CUT-{number:03d}" for number in range(32, 48))
SECTION_CUTS = {
    "NTH": tuple(f"CUT-{number:03d}" for number in range(17, 32)),
    "TH": TH_CUTS,
    "NA": tuple(f"CUT-{number:03d}" for number in range(48, 60)),
    "GG": tuple(f"CUT-{number:03d}" for number in range(61, 73)),
    "IJDKYY": tuple(f"CUT-{number:03d}" for number in range(74, 88)),
}
CUT_AUDIT_ROOT = ROOT / "data" / "c4d-cut-dependency-audits-20260728"
VERIFIED_CUT_040_RESULT = (
    RESULT_ROOT / "CUT-040-exact-render-settings-full-color-result.json"
)
TH_SHARED_SUPPLEMENT = (
    RESULT_ROOT
    / "TH-exact-settings-shared-picture-relink-supplement.json"
)
CUT_056_058_MAINFRAME_SUPPLEMENT = (
    RESULT_ROOT
    / "CUT-056-058-mainframe-recovered-assets-manifest.json"
)
CUT_056_058_CURRENT_PROJECT_SUPPLEMENT = (
    RESULT_ROOT
    / "NA-current-project-supplemental-exact-picture-relink-manifest.json"
)
CUT_SUPPLEMENTAL_MANIFESTS = {
    cut_id: (
        CUT_056_058_MAINFRAME_SUPPLEMENT,
        CUT_056_058_CURRENT_PROJECT_SUPPLEMENT,
    )
    for cut_id in ("CUT-056", "CUT-057", "CUT-058")
}
CUT_FRAME_OVERRIDES = {
    # These are the strongest canonical-thumbnail matches in the exhaustive
    # production-sequence frame audit, superseding the older grey-proof
    # sampling frames 1182, 1342, and 1367.
    "CUT-056": 1190,
    "CUT-057": 1350,
    "CUT-058": 1376,
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "camera"


def picture_manifest_for_cut(cut_id: str, section: str) -> Path:
    cut_manifest = (
        RESULT_ROOT / f"{cut_id}-full-picture-relink-manifest.json"
    )
    cut_audit_manifest = CUT_AUDIT_ROOT / f"{cut_id}-relink-manifest.json"
    source_paths: list[Path] = []
    if section == "TH":
        source_paths.append(PICTURE_MANIFEST)
    elif cut_audit_manifest.is_file():
        source_paths.append(cut_audit_manifest)
    if cut_manifest.is_file() and cut_manifest not in source_paths:
        source_paths.append(cut_manifest)
    if section == "TH" and TH_SHARED_SUPPLEMENT.is_file():
        source_paths.append(TH_SHARED_SUPPLEMENT)
    for supplemental_manifest in CUT_SUPPLEMENTAL_MANIFESTS.get(
        cut_id, ()
    ):
        if (
            supplemental_manifest.is_file()
            and supplemental_manifest not in source_paths
        ):
            source_paths.append(supplemental_manifest)
    if not source_paths:
        raise RuntimeError(
            f"No cut-specific relink manifest is available for {cut_id}"
        )
    if len(source_paths) == 1:
        return source_paths[0]

    payloads = [(path, load(path)) for path in source_paths]
    mappings: dict[str, dict[str, Any]] = {}
    unresolved: set[str] = set()
    unresolved_candidates: list[dict[str, Any]] = []
    for _, payload in payloads:
        for item in payload.get("mappings") or []:
            required = str(item.get("requiredPath") or "")
            if required:
                mappings[required] = item
        unresolved.update(
            str(item)
            for item in payload.get("unresolved") or []
            if str(item)
        )
        unresolved_candidates.extend(
            item
            for item in payload.get("unresolvedCandidates") or []
            if isinstance(item, dict)
        )
        unresolved_candidates.extend(
            item
            for item in payload.get(
                "renderObservedUnresolvedCandidates"
            )
            or []
            if isinstance(item, dict)
        )
    unresolved.difference_update(mappings)
    output = (
        RESULT_ROOT
        / (
            f"{cut_id}-{section.casefold()}-exact-settings-"
            "picture-relink-manifest.json"
        )
    )
    merged = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            (
                "Union of the proven Cut 40 exact-picture manifest, the "
                "cut's own picture manifest when present, and the shared TH "
                "supplement."
                if section == "TH"
                else (
                    f"Union of {cut_id}'s own dependency and render-observed "
                    f"picture manifests for section {section}."
                )
            )
            + " Later sources override only the same exact required path. "
            "No source C4D file is saved and no cross-section base manifest "
            "is inherited."
        ),
        "sourceManifests": [str(path) for path in source_paths],
        "renderCriticalOnly": False,
        "summary": {
            "sourceManifestCount": len(source_paths),
            "sourceMappedPathCounts": {
                path.name: len(payload.get("mappings") or [])
                for path, payload in payloads
            },
            "totalMappedPaths": len(mappings),
            "totalUnresolvedPaths": len(unresolved),
        },
        "mappings": list(mappings.values()),
        "unresolved": sorted(unresolved),
        "unresolvedCandidates": unresolved_candidates,
    }
    output.write_text(
        json.dumps(merged, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def write_manifest(
    path: Path,
    records: list[dict[str, Any]],
    section: str,
) -> None:
    counts = Counter(str(item.get("status") or "pending") for item in records)
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            f"Fresh read-only {section} recovery renders using the exact saved project, "
            "take, camera, frame, and complete cloned RenderData/VideoPost chain. "
            "Cut-specific exact relinks and empty Redshift surface-output repair "
            "are applied only in memory. A completed render remains process "
            "evidence until visual comparison accepts it. TH's shared picture "
            "manifest is used only for TH."
        ),
        "runtime": str(C4DPY),
        "helper": str(HELPER),
        "basePictureManifest": str(PICTURE_MANIFEST),
        "summary": {
            "targets": len(records),
            "statuses": dict(counts),
        },
        "records": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def target_records(
    selected: set[str],
    section: str,
    profile: str,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    queue_records = build_records(
        selected,
        force=True,
        include_partial=True,
    )
    records: list[dict[str, Any]] = []
    for source in queue_records:
        cut_id = str(source["cutId"])
        if cut_id not in SECTION_CUTS[section]:
            continue
        source_frame = int(source["frame"])
        frame = CUT_FRAME_OVERRIDES.get(cut_id, source_frame)
        camera_slug = slug(str(source["cameraName"]))
        stem = (
            f"{cut_id}-{camera_slug}-f{frame:06d}"
            f"-exact-settings-{profile}"
        )
        output = (
            ARCHIVE_ROOT
            / f"{section}-exact-settings-{profile}"
            / cut_id
            / f"{stem}.png"
        )
        result_path = RESULT_ROOT / f"{stem}-result.json"
        log_path = RESULT_ROOT / f"{stem}-render.log"
        picture_manifest = picture_manifest_for_cut(cut_id, section)
        record = {
            "cutId": cut_id,
            "status": "pending",
            "projectPath": str(source["projectPath"]),
            "take": source["take"],
            "cameraName": source["cameraName"],
            "cameraPath": source["cameraPath"],
            "renderData": source["renderData"],
            "frame": frame,
            "frameAuthority": (
                {
                    "kind": "canonical_thumbnail_best_match",
                    "sourceAudit": (
                        "data/as-finishing-frame-match-audit-20260727.json"
                    ),
                    "supersedesFrame": source_frame,
                }
                if frame != source_frame
                else {
                    "kind": "camera_recovery_queue",
                    "sourceAudit": (
                        "scripts/run_full_color_camera_render_queue.py"
                    ),
                }
            ),
            "width": width,
            "height": height,
            "pictureManifest": str(picture_manifest),
            "outputPath": str(output),
            "publicPath": "/" + output.relative_to(ROOT / "public").as_posix(),
            "resultPath": str(result_path.relative_to(ROOT)),
            "renderLogPath": str(log_path.relative_to(ROOT)),
            "proofEligible": False,
        }
        if cut_id == "CUT-040" and profile == "full":
            prior = load(VERIFIED_CUT_040_RESULT)
            record.update(
                {
                    "status": "verified_existing",
                    "outputPath": prior["output"],
                    "publicPath": "/"
                    + Path(prior["output"])
                    .relative_to(ROOT / "public")
                    .as_posix(),
                    "resultPath": str(
                        VERIFIED_CUT_040_RESULT.relative_to(ROOT)
                    ),
                    "renderResult": {
                        "status": prior["status"],
                        "seconds": prior["seconds"],
                        "exactRenderDataClone": prior[
                            "exactRenderDataClone"
                        ],
                        "sourceVideoPosts": prior["sourceVideoPosts"],
                        "clonedVideoPosts": prior["clonedVideoPosts"],
                        "strictDependencyRenderSafe": prior[
                            "postRelinkDependencyAudit"
                        ]["strictDependencyRenderSafe"],
                    },
                }
            )
        records.append(record)
    return records


def render_record(record: dict[str, Any], timeout: int) -> None:
    output = Path(str(record["outputPath"]))
    result_path = ROOT / str(record["resultPath"])
    log_path = ROOT / str(record["renderLogPath"])
    output.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "caffeinate",
        "-dimsu",
        str(C4DPY),
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
        "--exact-material-relink-manifest",
        str(record["pictureManifest"]),
        "--repair-missing-rs-surface-output",
        "--width",
        str(record["width"]),
        "--height",
        str(record["height"]),
        "--bake-ocio-view",
    ]
    try:
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )
        if not result_path.exists():
            raise RuntimeError(
                f"Cinema 4D exited {completed.returncode} without a result"
            )
        result = load(result_path)
        record["status"] = str(result.get("status") or "failed")
        dependency = result.get("postRelinkDependencyAudit") or {}
        repair = result.get("redshiftSurfaceOutputRepair") or {}
        record["renderResult"] = {
            "status": result.get("status"),
            "error": result.get("error"),
            "seconds": result.get("seconds"),
            "camera": result.get("camera"),
            "cameraPath": result.get("cameraPath"),
            "cameraWasNativeClone": result.get("cameraWasNativeClone"),
            "activeRenderData": result.get("activeRenderData"),
            "exactRenderDataClone": result.get("exactRenderDataClone"),
            "sourceVideoPosts": result.get("sourceVideoPosts"),
            "clonedVideoPosts": result.get("clonedVideoPosts"),
            "surfaceRepairs": len(repair.get("repairs") or []),
            "alreadyConnectedSurfaces": len(
                repair.get("alreadyConnected") or []
            ),
            "unresolvedPictureReferences": dependency.get(
                "unresolvedPictureReferences"
            ),
            "unresolvedPictureFiles": dependency.get(
                "unresolvedPictureFiles"
            ),
            "strictDependencyRenderSafe": dependency.get(
                "strictDependencyRenderSafe"
            ),
        }
        if record["status"] == "rendered" and not output.exists():
            raise RuntimeError("Cinema reported success but output is absent")
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
    parser.add_argument(
        "--profile",
        choices=("test", "full"),
        default="test",
    )
    parser.add_argument(
        "--section",
        choices=tuple(SECTION_CUTS),
        default="TH",
    )
    parser.add_argument("--cut-id", action="append", default=[])
    parser.add_argument("--max-targets", type=int)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--rerender", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    section = str(args.section)
    section_cuts = set(SECTION_CUTS[section])
    selected = set(args.cut_id) or section_cuts
    invalid = selected.difference(section_cuts)
    if invalid:
        parser.error(
            f"Non-{section} cuts requested: " + ", ".join(sorted(invalid))
        )
    if not C4DPY.is_file():
        parser.error(f"Cinema 4D runtime is missing: {C4DPY}")
    if section == "TH" and not PICTURE_MANIFEST.is_file():
        parser.error(f"Picture manifest is missing: {PICTURE_MANIFEST}")

    width, height = ((240, 135) if args.profile == "test" else (1280, 720))
    manifest_path = (
        args.manifest.expanduser().resolve()
        if args.manifest is not None
        else RESULT_ROOT
        / f"{section}-exact-settings-{args.profile}-manifest.json"
    )
    records = target_records(
        selected,
        section,
        args.profile,
        width,
        height,
    )
    prior = {}
    if manifest_path.exists():
        prior = {
            str(item["cutId"]): item
            for item in load(manifest_path).get("records", [])
        }
    for index, record in enumerate(records):
        previous = prior.get(str(record["cutId"]))
        if (
            not args.rerender
            and previous
            and previous.get("status") in {"rendered", "verified_existing"}
            and Path(str(previous.get("outputPath") or "")).is_file()
        ):
            records[index] = previous

    runnable = [
        record for record in records if record["status"] == "pending"
    ]
    if args.max_targets is not None:
        runnable = runnable[: max(0, args.max_targets)]
    write_manifest(manifest_path, records, section)
    if args.plan_only:
        print(
            f"Planned {len(runnable)} {args.profile} {section} renders"
        )
        return

    for index, record in enumerate(runnable, start=1):
        print(
            f"[{index}/{len(runnable)}] {record['cutId']} · "
            f"{record['cameraName']} · frame {record['frame']}",
            flush=True,
        )
        render_record(record, args.timeout)
        write_manifest(manifest_path, records, section)
    print(
        f"Wrote {section} exact-settings recovery state to {manifest_path}"
    )


if __name__ == "__main__":
    main()
