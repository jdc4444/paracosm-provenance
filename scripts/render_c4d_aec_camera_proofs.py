#!/usr/bin/env python3
"""Render exact in-memory cameras reconstructed from source-render AEC data."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from render_c4d_camera_proofs import render_project_c4dpy


ROOT = Path(__file__).resolve().parents[1]
AEC_INDEX = ROOT / "data" / "c4d-aec-camera-index-20260726.json"
PRIMARY_PROOFS = (
    ROOT / "data" / "c4d-camera-proof-renders-corrected-20260726.json"
)
OUTPUT_DIR = ROOT / "public" / "archive" / "camera-aec-proofs-20260726"
MANIFEST = ROOT / "data" / "c4d-aec-camera-proofs-20260726.json"
TARGETS = ROOT / "data" / "c4d-unmapped-camera-candidates-20260726.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def public_path(path: Path) -> str:
    return "/" + path.resolve().relative_to(ROOT / "public").as_posix()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aec-index", type=Path, default=AEC_INDEX)
    parser.add_argument("--primary-proofs", type=Path, default=PRIMARY_PROOFS)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--targets", type=Path, default=TARGETS)
    parser.add_argument("--cut-id", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    primary_by_cut = {
        str(cut_id): proof
        for proof in load(args.primary_proofs).get("proofs", [])
        for cut_id in proof.get("cutIds", [])
    }
    target_projects = {}
    if args.targets.exists():
        target_projects = {
            str(item["cutId"]): [
                str(Path(project).expanduser().resolve())
                for project in item.get("projects", [])
                if Path(project).expanduser().exists()
            ]
            for item in load(args.targets).get("targets", [])
        }
    selected = set(args.cut_id)
    records: list[dict[str, Any]] = []
    for item in load(args.aec_index).get("records", []):
        cut_id = str(item["cutId"])
        if selected and cut_id not in selected:
            continue
        active_keys = item.get("activeTargetKeys") or []
        if len(active_keys) != 1:
            continue
        primary = primary_by_cut.get(cut_id) or {}
        projects = [
            str(Path(project).expanduser().resolve())
            for project in item.get("projectCandidates", [])
            if Path(project).expanduser().exists()
        ]
        if not projects:
            projects = target_projects.get(cut_id) or []
        if not projects:
            project = str(
                primary.get("projectPath") or item.get("projectPath") or ""
            )
            projects = [project] if project and Path(project).exists() else []
        if not projects:
            continue
        camera = active_keys[0]
        for project_index, project in enumerate(projects, start=1):
            output = (
                args.output_dir.expanduser().resolve()
                / f"{cut_id}-p{project_index:02d}.png"
            )
            records.append(
                {
                    "sourceId": (
                        f"{cut_id}__aec_exact__project_{project_index:02d}"
                    ),
                    "cutId": cut_id,
                    "targetFrame": int(item["targetFrame"]),
                    "projectPath": project,
                    "cameraName": f"AEC exact {cut_id}",
                    "cameraObject": {
                        "objectPath": f"__AEC_EXACT__/{cut_id}",
                        "position": camera["position"],
                        "rotationDegrees": camera["rotationDegrees"],
                        "fieldOfViewDegrees": camera["fieldOfViewDegrees"],
                        "aperture": 36.0,
                    },
                    # The archived camera path is intentionally absent from
                    # the surviving source project.  Without this flag the
                    # shared proof helper falls back to the take camera before
                    # it reaches its in-memory reconstruction branch.
                    "forceReconstructedCamera": True,
                    "cameraTake": primary.get("cameraTake") or "Main",
                    "cameraRenderData": primary.get("cameraRenderData"),
                    "aecPath": item["aecPath"],
                    "aecCameraName": camera["cameraName"],
                    "aecEvidenceStatus": item["status"],
                    "aecEvidence": item.get("evidence"),
                    "outputPath": str(output),
                    "publicPath": public_path(output),
                    "status": "pending",
                }
            )

    prior_by_id: dict[str, dict[str, Any]] = {}
    if args.manifest.exists():
        prior_by_id = {
            str(item["sourceId"]): item
            for item in load(args.manifest).get("records", [])
        }
    for index, record in enumerate(records):
        prior = prior_by_id.get(str(record["sourceId"]))
        if (
            prior
            and prior.get("status") == "rendered"
            and Path(str(prior.get("outputPath") or "")).exists()
        ):
            records[index] = {**record, **prior}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("status") != "rendered":
            grouped[str(record["projectPath"])].append(record)
    for index, (project, group) in enumerate(grouped.items(), start=1):
        print(
            f"[{index}/{len(grouped)}] {Path(project).name} · "
            f"{len(group)} exact AEC camera(s)",
            flush=True,
        )
        results = render_project_c4dpy(
            Path(project),
            group,
            width=480,
            height=270,
            timeout=args.timeout,
        )
        by_id = {str(item.get("sourceId")): item for item in results}
        for record in records:
            result = by_id.get(str(record["sourceId"]))
            if result:
                record.update(result)

    statuses: dict[str, int] = defaultdict(int)
    for record in records:
        statuses[str(record.get("status") or "pending")] += 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Exact active-camera transforms reconstructed in memory from "
            "AEC files stored beside canonical source-render sequences. "
            "Original C4D projects are never saved."
        ),
        "summary": {
            "records": len(records),
            "statuses": dict(statuses),
        },
        "records": records,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
