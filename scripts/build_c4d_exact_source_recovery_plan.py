#!/usr/bin/env python3
"""Find untouched sibling projects behind derived per-cut audit copies."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = (
    APP_ROOT / "data" / "c4d-cut-dependency-audits-20260728"
)
DEFAULT_QUEUE = (
    APP_ROOT / "data" / "c4d-full-color-render-queue-480-plan-20260729.json"
)
DEFAULT_OUTPUT = (
    APP_ROOT
    / "data"
    / "c4d-mainframe-recovery-20260730"
    / "ALL-CUTS-exact-source-project-recovery-plan-20260801.json"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_records(value: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if isinstance(value, dict):
        cut_id = value.get("cutId")
        if isinstance(cut_id, str):
            result.setdefault(cut_id, value)
        for child in value.values():
            result.update(queue_records(child))
    elif isinstance(value, list):
        for child in value:
            result.update(queue_records(child))
    return result


def exact_sibling_candidate(project: Path) -> Path | None:
    name = re.sub(
        r"_codex(?:_[0-9]+)?(?=\.c4d$)",
        "",
        project.name,
        flags=re.IGNORECASE,
    )
    parent = project.parent
    if parent.name.casefold().startswith("_codex_"):
        parent = parent.parent
    candidate = parent / name
    if candidate != project and candidate.is_file():
        return candidate.resolve()
    return None


def stat_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "modifiedNs": stat.st_mtime_ns,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    queue_by_cut = queue_records(queue)
    candidates = []
    derived_without_sibling = []
    source_audits = []
    for audit_path in sorted(args.audit_dir.glob("CUT-???.json")):
        cut_id = audit_path.stem
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        project = Path(str(audit["project"])).expanduser().resolve()
        queue_item = queue_by_cut.get(cut_id, {})
        render_contract = {
            key: queue_item.get(key)
            for key in (
                "take",
                "frame",
                "cameraName",
                "cameraPath",
                "renderData",
                "reconstructCamera",
                "cameraPosition",
                "cameraRotation",
                "cameraFocalLength",
                "cameraAperture",
            )
        }
        candidate = exact_sibling_candidate(project)
        record = {
            "cutId": cut_id,
            "auditPath": str(audit_path.resolve()),
            "auditProject": stat_record(project),
            "take": audit.get("take"),
            "frame": audit.get("frame"),
            "renderContract": render_contract,
        }
        if candidate is not None:
            record["exactSourceCandidate"] = stat_record(candidate)
            record["bytesDelta"] = (
                candidate.stat().st_size - project.stat().st_size
            )
            record["status"] = "untouched_sibling_requires_audit"
            candidates.append(record)
        elif "codex" in str(project).casefold():
            record["status"] = "derived_project_no_direct_sibling"
            derived_without_sibling.append(record)
        else:
            record["status"] = "audit_already_uses_source_path"
            source_audits.append(record)

    payload = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "authority": (
            "Read-only filesystem identity inventory; candidates require "
            "Cinema take/camera/dependency verification before promotion"
        ),
        "policy": {
            "sourceReadOnly": True,
            "candidateIsNotProof": True,
            "derivedCopyCannotSupersedeUntouchedSibling": True,
        },
        "summary": {
            "pictureCuts": (
                len(candidates)
                + len(derived_without_sibling)
                + len(source_audits)
            ),
            "untouchedSiblingCandidates": len(candidates),
            "derivedWithoutDirectSibling": len(derived_without_sibling),
            "auditsAlreadyUsingSourcePath": len(source_audits),
        },
        "untouchedSiblingCandidates": candidates,
        "derivedWithoutDirectSibling": derived_without_sibling,
        "auditsAlreadyUsingSourcePath": source_audits,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
