#!/usr/bin/env python3
"""Build grouped grey-proof jobs from exact AS Redshift log lineage.

The generated jobs are read-only: c4dpy loads each source document once and
renders the canonical source frame through the camera/take/render-data recorded
by the completed Redshift batch log.  Visual review remains a separate gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "public" / "data" / "state.json"
DEFAULT_CHRONOLOGY = ROOT / "data" / "as-finishing-chronology-20260727.json"
DEFAULT_OUTPUT = ROOT / "data" / "as-finishing-camera-proof-jobs-20260727"
DEFAULT_PROOF_ROOT = (
    ROOT / "public" / "archive" / "as-finishing-camera-proofs-20260727"
)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "project"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def exact_log_lead(
    cut: dict[str, Any],
    chronology: dict[str, Any],
    logs_by_path: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    render_paths = {
        os.path.normpath(str(node.get("path") or ""))
        for node in cut.get("lineage", [])
        if node.get("kind") == "render_sequence" and node.get("path")
    }
    matches = []
    for lead in chronology.get("cutLineageLeads", {}).get(cut.get("id"), []):
        record = logs_by_path.get(str(lead.get("renderLogPath"))) or lead
        if os.path.normpath(str(lead.get("outputPath") or "")) not in render_paths:
            continue
        if record.get("renderEngineName") != "Redshift":
            continue
        if int(record.get("completedFrameCount") or 0) <= 0:
            continue
        if int(record.get("errorCount") or 0) != 0:
            continue
        matches.append((lead, record))
    return (
        max(
            matches,
            key=lambda pair: str(
                pair[0].get("renderLogModifiedAt")
                or pair[1].get("modifiedAt")
                or ""
            ),
        )
        if matches
        else None
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--chronology", type=Path, default=DEFAULT_CHRONOLOGY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--proof-root", type=Path, default=DEFAULT_PROOF_ROOT)
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Also render a camera already proved from the same source project.",
    )
    args = parser.parse_args()

    state = load(args.state.expanduser().resolve())
    chronology = load(args.chronology.expanduser().resolve())
    output_dir = args.output_dir.expanduser().resolve()
    proof_root = args.proof_root.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    proof_root.mkdir(parents=True, exist_ok=True)
    logs_by_path = {
        str(item.get("path")): item
        for item in chronology.get("renderLogs", [])
        if item.get("path")
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    metadata: list[dict[str, Any]] = []

    for cut in state.get("cuts", []):
        if cut.get("isGap"):
            continue
        matched = exact_log_lead(cut, chronology, logs_by_path)
        if not matched:
            continue
        lead, log_record = matched
        project_path = next(
            (
                str(path)
                for path in lead.get("projectCandidatePaths", [])
                if path and Path(str(path)).is_file()
            ),
            str(lead.get("nearestProjectStatePath") or ""),
        )
        if not project_path or not Path(project_path).is_file():
            continue
        proofs = [
            node
            for node in cut.get("lineage", [])
            if node.get("kind") == "camera_proof"
            and node.get("targetFrame") is not None
        ]
        frame_source = proofs[0] if proofs else None
        if not frame_source:
            continue
        camera_name = str(lead.get("camera") or "")
        existing = next(
            (
                node
                for node in proofs
                if str(node.get("projectPath") or node.get("path") or "")
                == project_path
                and str(node.get("label") or "").split(" · ", 1)[0]
                == camera_name
                and node.get("comparisonImage")
            ),
            None,
        )
        if existing and not args.include_existing:
            continue
        cut_id = str(cut["id"])
        target_frame = int(frame_source["targetFrame"])
        output_path = (
            proof_root
            / cut_id
            / f"{cut_id}__{slug(camera_name)}__f{target_frame:04d}.png"
        )
        job = {
            "sourceId": cut_id,
            "outputPath": str(output_path),
            "targetFrame": target_frame,
            "cameraName": camera_name,
            "cameraTake": lead.get("take") or "Main",
            "cameraRenderData": log_record.get("renderSettings"),
        }
        grouped[project_path].append(job)
        metadata.append(
            {
                "cutId": cut_id,
                "projectPath": project_path,
                "renderLogPath": lead.get("renderLogPath"),
                "renderLogModifiedAt": (
                    lead.get("renderLogModifiedAt")
                    or log_record.get("modifiedAt")
                ),
                "sourceRenderPath": lead.get("outputPath"),
                "cameraName": camera_name,
                "cameraTake": lead.get("take") or "Main",
                "cameraRenderData": log_record.get("renderSettings"),
                "targetFrame": target_frame,
                "outputPath": str(output_path),
                "publicPath": "/" + output_path.relative_to(
                    ROOT / "public"
                ).as_posix(),
                "thumbnail": cut.get("thumbnail"),
            }
        )

    groups = []
    for index, (project_path, jobs) in enumerate(sorted(grouped.items()), 1):
        job_path = output_dir / f"{index:02d}-{slug(Path(project_path).stem)}.json"
        job_path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        groups.append(
            {
                "projectPath": project_path,
                "jobPath": str(job_path),
                "jobCount": len(jobs),
                "cutIds": [job["sourceId"] for job in jobs],
            }
        )

    index_record = {
        "schemaVersion": 1,
        "authority": (
            "Exact canonical source-render directory plus completed zero-error "
            "AS Redshift batch log."
        ),
        "groups": groups,
        "jobs": metadata,
        "summary": {
            "projectCount": len(groups),
            "jobCount": len(metadata),
        },
    }
    index_path = output_dir / "index.json"
    index_path.write_text(json.dumps(index_record, indent=2), encoding="utf-8")
    print(json.dumps(index_record["summary"], indent=2))
    print(index_path)


if __name__ == "__main__":
    main()
