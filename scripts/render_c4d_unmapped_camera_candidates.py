#!/usr/bin/env python3
"""Render every retained camera for the previously unmapped canonical cuts."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from render_c4d_camera_candidate_sweep import (
    contact_sheet,
    image_metrics,
    public_path,
)
from render_c4d_camera_proofs import render_project_c4dpy
from render_c4d_camera_proofs import analyze_proof


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "public" / "data" / "state.json"
PROBES_PATH = ROOT / "data" / "c4d-unmapped-camera-state-probes-20260726.json"
OUTPUT_DIR = ROOT / "public" / "archive" / "camera-unmapped-candidates-20260726"
MANIFEST_PATH = ROOT / "data" / "c4d-unmapped-camera-proofs-20260726.json"
SOURCE_FRAMES_PATH = (
    ROOT / "data" / "c4d-source-frame-archive-20260726.json"
)
SOURCE_EXPORT_FRAMES_PATH = (
    ROOT / "data" / "c4d-source-export-frames-20260726.json"
)
PROOF_VERSION = "evaluated-transform-v2"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "camera"


def write_manifest(
    path: Path,
    records: list[dict[str, Any]],
    rankings: dict[str, Any],
) -> None:
    statuses: dict[str, int] = defaultdict(int)
    for item in records:
        statuses[str(item.get("status") or "pending")] += 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Read-only exhaustive retained-camera proofs for previously "
            "unmapped cuts. Ranking is triage only; manual visual review is "
            "required before a project or camera is promoted."
        ),
        "summary": {
            "candidateProofs": len(records),
            "statuses": dict(statuses),
            "cuts": len({str(item.get("cutId")) for item in records}),
            "projects": len({str(item.get("projectPath")) for item in records}),
        },
        "records": records,
        "rankings": rankings,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probes", type=Path, default=PROBES_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--cut-id", action="append", default=[])
    parser.add_argument(
        "--max-cameras-per-batch",
        type=int,
        default=12,
        help="Bound each C4D load/render batch so partial work is checkpointed.",
    )
    parser.add_argument("--rank-only", action="store_true")
    parser.add_argument("--source-frames", type=Path, default=SOURCE_FRAMES_PATH)
    parser.add_argument(
        "--source-export-frames",
        type=Path,
        default=SOURCE_EXPORT_FRAMES_PATH,
    )
    args = parser.parse_args()

    state = load(STATE_PATH)
    cuts = {
        str(item["id"]): item
        for item in state.get("cuts", [])
        if not item.get("isGap")
    }
    source_frames = {}
    if args.source_frames.exists():
        source_frames = {
            str(item["cutId"]): item
            for item in load(args.source_frames).get("records", [])
            if item.get("status") == "archived"
            and Path(str(item.get("outputPath") or "")).exists()
        }
    if args.source_export_frames.exists():
        for item in load(args.source_export_frames).get("records", []):
            if (
                item.get("archiveStatus") == "archived"
                and Path(str(item.get("outputPath") or "")).exists()
            ):
                source_frames[str(item["cutId"])] = {
                    **item,
                    "sourceFramePath": item.get("exportPath"),
                    "referenceKind": "source_export_frame",
                }
    selected_cuts = set(args.cut_id)
    probe_records = [
        item
        for item in load(args.probes.expanduser().resolve()).get("records", [])
        if item.get("status") == "probed"
        and (
            not selected_cuts
            or str(item.get("cutId") or "") in selected_cuts
        )
    ]
    records: list[dict[str, Any]] = []
    for project_index, probe in enumerate(probe_records, start=1):
        cut_id = str(probe["cutId"])
        cut = cuts.get(cut_id)
        if cut is None:
            continue
        canonical_thumbnail = str(
            ROOT / "public" / str(cut["thumbnail"]).lstrip("/")
        )
        source_frame = source_frames.get(cut_id) or {}
        reference_image = str(
            source_frame.get("outputPath") or canonical_thumbnail
        )
        project = str(probe["project"])
        for camera_index, camera in enumerate(probe.get("cameras", []), start=1):
            camera_path = str(camera.get("objectPath") or camera.get("name") or "")
            source_id = (
                f"{cut_id}__project_{project_index:02d}"
                f"__camera_{camera_index:03d}__{PROOF_VERSION}"
            )
            output = (
                args.output_dir.expanduser().resolve()
                / cut_id
                / f"p{project_index:02d}-{camera_index:03d}-"
                f"{slug(camera_path)}-f{int(probe['targetFrame']):06d}"
                "-eval2.png"
            )
            records.append(
                {
                    "sourceId": source_id,
                    "cutId": cut_id,
                    "targetFrame": int(probe["targetFrame"]),
                    "projectPath": project,
                    "cameraName": camera.get("name"),
                    "cameraTake": probe.get("cameraTake"),
                    "displayLabel": (
                        f"{Path(project).stem[:24]} / "
                        f"{camera.get('name') or camera_path}"
                    ),
                    "cameraObject": {
                        **camera,
                        "objectPath": camera_path,
                    },
                    "forceReconstructedCamera": True,
                    "proofVersion": PROOF_VERSION,
                    "outputPath": str(output),
                    "publicPath": public_path(output),
                    "canonicalThumbnail": canonical_thumbnail,
                    "sourceFrameReference": source_frame.get("sourceFramePath"),
                    "sourceReferenceKind": source_frame.get(
                        "referenceKind", "raw_render_frame"
                    ),
                    "referenceImage": reference_image,
                    "status": "pending",
                }
            )

    prior_by_id: dict[str, dict[str, Any]] = {}
    if args.manifest.exists():
        prior_by_id = {
            str(item["sourceId"]): item
            for item in load(args.manifest).get("records", [])
        }
    for index, item in enumerate(records):
        prior = prior_by_id.get(str(item["sourceId"]))
        if args.rank_only and prior:
            records[index] = {
                **prior,
                "displayLabel": item.get("displayLabel"),
                "canonicalThumbnail": item.get("canonicalThumbnail"),
                "sourceFrameReference": item.get("sourceFrameReference"),
                "referenceImage": item.get("referenceImage"),
            }
            continue
        if (
            prior
            and prior.get("status") == "rendered"
            and Path(str(prior.get("outputPath") or "")).exists()
        ):
            records[index] = prior
            continue
        output_path = Path(str(item.get("outputPath") or ""))
        if output_path.exists() and output_path.stat().st_size > 0:
            records[index] = {
                **item,
                "status": "rendered",
                "backend": "c4dpy_hardware_preview_salvaged",
                "fileSize": output_path.stat().st_size,
                **analyze_proof(output_path),
            }

    write_manifest(args.manifest, records, {})
    grouped_by_project: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        if args.rank_only:
            continue
        if item.get("status") != "rendered":
            grouped_by_project[str(item["projectPath"])].append(item)
    groups = [
        (project, records[index : index + args.max_cameras_per_batch])
        for project, records in grouped_by_project.items()
        for index in range(0, len(records), args.max_cameras_per_batch)
    ]
    for index, (project, group) in enumerate(groups, start=1):
        print(
            f"[{index}/{len(groups)}] {Path(project).name} · "
            f"{len(group)} camera(s)",
            flush=True,
        )
        try:
            results = render_project_c4dpy(
                Path(project),
                group,
                width=480,
                height=270,
                timeout=args.timeout,
            )
        except Exception as error:
            print(
                f"Batch incomplete: {type(error).__name__}: {error}",
                flush=True,
            )
            results = []
            for item in group:
                output_path = Path(str(item.get("outputPath") or ""))
                if output_path.exists() and output_path.stat().st_size > 0:
                    results.append(
                        {
                            **item,
                            "status": "rendered",
                            "backend": "c4dpy_hardware_preview_salvaged",
                            "fileSize": output_path.stat().st_size,
                            **analyze_proof(output_path),
                        }
                    )
                else:
                    results.append(
                        {
                            **item,
                            "status": "pending",
                            "lastBatchError": (
                                f"{type(error).__name__}: {error}"
                            ),
                        }
                    )
        by_id = {str(item.get("sourceId")): item for item in results}
        for record_index, record in enumerate(records):
            result = by_id.get(str(record["sourceId"]))
            if result:
                records[record_index] = {**record, **result}
        write_manifest(args.manifest, records, {})

    rankings: dict[str, Any] = {}
    for cut_id in sorted({str(item["cutId"]) for item in records}):
        candidates = [
            item
            for item in records
            if item["cutId"] == cut_id
            and item.get("status") == "rendered"
            and Path(str(item.get("outputPath") or "")).exists()
        ]
        ranked = []
        for item in candidates:
            copy = dict(item)
            try:
                copy["metrics"] = image_metrics(
                    Path(
                        str(
                            item.get("referenceImage")
                            or item["canonicalThumbnail"]
                        )
                    ),
                    Path(str(item["outputPath"])),
                )
            except Exception as error:
                copy["metricError"] = f"{type(error).__name__}: {error}"
                copy["metrics"] = {"rankScore": -1.0}
            copy["path"] = copy["outputPath"]
            ranked.append(copy)
        ranked.sort(
            key=lambda item: float((item.get("metrics") or {}).get("rankScore", -1)),
            reverse=True,
        )
        sheet = args.output_dir.expanduser().resolve() / cut_id / "top-cameras.jpg"
        if ranked:
            contact_sheet(
                cut_id,
                Path(
                    str(
                        ranked[0].get("referenceImage")
                        or ranked[0]["canonicalThumbnail"]
                    )
                ),
                ranked,
                sheet,
            )
        rankings[cut_id] = {
            "status": "manual_review_required" if ranked else "no_rendered_candidates",
            "candidateCount": len(ranked),
            "referenceImage": (
                ranked[0].get("referenceImage") if ranked else None
            ),
            "contactSheet": public_path(sheet) if ranked else None,
            "ranked": ranked,
        }
    write_manifest(args.manifest, records, rankings)
    print(f"Wrote {len(records)} candidate proofs to {args.manifest}")


if __name__ == "__main__":
    main()
