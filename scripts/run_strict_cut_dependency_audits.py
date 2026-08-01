#!/usr/bin/env python3
"""Run resumable, frame-specific strict C4D audits for canonical picture cuts.

The generated task list comes from the same published state that drives the
UI.  Every cut is evaluated in an isolated Cinema 4D process at its recorded
take and source frame.  Source projects are loaded read-only and never saved.
Results are retained per cut so a long all-film audit can safely resume.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = APP_ROOT / "public" / "data" / "state.json"
DEFAULT_OUTPUT_DIR = (
    APP_ROOT / "data" / "c4d-cut-dependency-audits-20260728"
)
DEFAULT_SUMMARY = (
    APP_ROOT / "data" / "c4d-cut-dependency-audit-summary-20260728.json"
)
DEFAULT_C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026.1.2/"
    "c4dpy.app/Contents/MacOS/c4dpy"
)
AUDIT_HELPER = APP_ROOT / "scripts" / "c4dpy_audit_dependencies.py"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def latest_node(
    lineage: list[dict[str, Any]], kind: str
) -> dict[str, Any]:
    matches = [item for item in lineage if item.get("kind") == kind]
    return matches[-1] if matches else {}


def task_from_cut(cut: dict[str, Any]) -> dict[str, Any]:
    lineage = cut.get("lineage") or []
    project_node = latest_node(lineage, "cinema4d")
    proof_node = latest_node(lineage, "camera_proof")
    camera_node = latest_node(lineage, "camera")
    project_path = (
        project_node.get("projectPath")
        or project_node.get("path")
        or proof_node.get("projectPath")
        or proof_node.get("path")
        or camera_node.get("projectPath")
        or camera_node.get("path")
    )
    target_frame = proof_node.get("targetFrame")
    if target_frame is None:
        target_frame = camera_node.get("targetFrame")
    take = (
        proof_node.get("cameraTake")
        or camera_node.get("cameraTake")
        or "Main"
    )
    return {
        "cutId": cut["id"],
        "cutIndex": cut.get("index"),
        "sectionCode": cut.get("sectionCode"),
        "projectPath": str(project_path or ""),
        "take": str(take),
        "frame": target_frame,
        "cameraObjectPath": (
            proof_node.get("cameraObjectPath")
            or camera_node.get("cameraObjectPath")
            or ""
        ),
        "renderData": (
            proof_node.get("cameraRenderData")
            or camera_node.get("cameraRenderData")
            or ""
        ),
        "sourceRender": next(
            (
                item.get("path")
                for item in lineage
                if item.get("kind") == "render_sequence"
                and item.get("path")
            ),
            "",
        ),
    }


def result_matches_task(
    result_path: Path, task: dict[str, Any]
) -> bool:
    if not result_path.is_file():
        return False
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        result.get("project") == task["projectPath"]
        and result.get("take") == task["take"]
        and result.get("frame") == task["frame"]
        and "renderCriticalMissingFiles" in result
    )


def compact_result(
    task: dict[str, Any], result_path: Path
) -> dict[str, Any]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        **task,
        "status": "audited",
        "resultPath": str(result_path.relative_to(APP_ROOT)),
        "dependencyReferences": result.get("dependencyReferences"),
        "linkedReferences": result.get("linkedReferences"),
        "relinkRequiredReferences": result.get(
            "relinkRequiredReferences"
        ),
        "missingReferences": result.get("missingReferences"),
        "uniqueMissingFiles": result.get("uniqueMissingFiles"),
        "renderCriticalMissingReferences": result.get(
            "renderCriticalMissingReferences"
        ),
        "renderCriticalMissingFiles": result.get(
            "renderCriticalMissingFiles"
        ),
        "renderCriticalRelinkRequiredReferences": result.get(
            "renderCriticalRelinkRequiredReferences"
        ),
        "renderCriticalRelinkRequiredFiles": result.get(
            "renderCriticalRelinkRequiredFiles"
        ),
        "redshiftProxyReferences": result.get(
            "redshiftProxyReferences"
        ),
    }


def write_summary(
    path: Path,
    tasks: list[dict[str, Any]],
    records: list[dict[str, Any]],
    c4dpy: Path,
) -> None:
    audited = [item for item in records if item["status"] == "audited"]
    payload = {
        "schemaVersion": 1,
        "updatedAt": now_iso(),
        "authority": (
            "Canonical published cut lineage evaluated by the corrected "
            "frame-specific active-material and Redshift-proxy audit"
        ),
        "runtime": str(c4dpy),
        "summary": {
            "pictureCuts": len(tasks),
            "auditedCuts": len(audited),
            "failedCuts": sum(
                item["status"] == "failed" for item in records
            ),
            "pendingCuts": len(tasks) - len(records),
            "rawZeroRenderCriticalMissingCuts": sum(
                item.get("renderCriticalMissingFiles") == 0
                for item in audited
            ),
            "rawRenderCriticalMissingCuts": sum(
                (item.get("renderCriticalMissingFiles") or 0) > 0
                for item in audited
            ),
        },
        "cuts": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR
    )
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--c4dpy", type=Path, default=DEFAULT_C4DPY)
    parser.add_argument(
        "--cuts",
        help="Comma-separated CUT-### identifiers; default is every picture cut.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Re-run matching completed cut results.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    state_path = args.state.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    summary_path = args.summary.expanduser().resolve()
    c4dpy = args.c4dpy.expanduser().resolve()
    if not c4dpy.is_file():
        raise FileNotFoundError(c4dpy)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = [
        task_from_cut(cut)
        for cut in state.get("cuts", [])
        if not cut.get("isGap")
    ]
    requested = {
        item.strip()
        for item in (args.cuts or "").split(",")
        if item.strip()
    }
    selected = [
        item
        for item in tasks
        if not requested or item["cutId"] in requested
    ]
    if args.limit is not None:
        selected = selected[: args.limit]
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for task in selected:
        cut_id = task["cutId"]
        result_path = output_dir / f"{cut_id}.json"
        log_path = output_dir / f"{cut_id}.log"
        project = Path(task["projectPath"]).expanduser()
        if not project.is_file() or task["frame"] is None:
            records.append(
                {
                    **task,
                    "status": "failed",
                    "error": (
                        "project_missing"
                        if not project.is_file()
                        else "target_frame_missing"
                    ),
                }
            )
            write_summary(summary_path, tasks, records, c4dpy)
            continue
        if not args.rerun and result_matches_task(result_path, task):
            record = compact_result(task, result_path)
            record["resumed"] = True
            records.append(record)
            write_summary(summary_path, tasks, records, c4dpy)
            print(
                f"{cut_id}: resumed "
                f"({record['renderCriticalMissingFiles']} critical files)"
            )
            continue

        command = [
            str(c4dpy),
            str(AUDIT_HELPER),
            "--project",
            str(project.resolve()),
            "--take",
            task["take"],
            "--frame",
            str(task["frame"]),
            "--result-json",
            str(result_path),
            "--summary-only",
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=args.timeout_seconds,
            )
            log_path.write_text(completed.stdout, encoding="utf-8")
            if completed.returncode != 0 or not result_matches_task(
                result_path, task
            ):
                raise RuntimeError(
                    f"c4dpy exit {completed.returncode}; "
                    f"see {log_path.relative_to(APP_ROOT)}"
                )
            record = compact_result(task, result_path)
            records.append(record)
            print(
                f"{cut_id}: {record['linkedReferences']} linked, "
                f"{record['renderCriticalMissingFiles']} "
                "render-critical files missing"
            )
        except Exception as error:
            records.append(
                {
                    **task,
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                    "logPath": str(log_path.relative_to(APP_ROOT)),
                }
            )
            print(f"{cut_id}: failed: {error}")
        write_summary(summary_path, tasks, records, c4dpy)

    write_summary(summary_path, tasks, records, c4dpy)
    print(summary_path)


if __name__ == "__main__":
    main()
