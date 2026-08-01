#!/usr/bin/env python3
"""Merge exact-source audits and selected render proofs into one override."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = (
    APP_ROOT / "data" / "c4d-mainframe-recovery-20260730"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(value: Any) -> Path:
    path = Path(str(value or "")).expanduser()
    return path.resolve() if path.is_absolute() else (APP_ROOT / path).resolve()


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(APP_ROOT))
    except ValueError:
        return str(path.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, action="append", default=[])
    parser.add_argument(
        "--selection-dir", type=Path, default=DEFAULT_EVIDENCE_DIR
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records: dict[str, dict[str, Any]] = {}
    sources: list[str] = []
    for summary_arg in args.summary:
        summary_path = summary_arg.expanduser().resolve()
        summary = load(summary_path)
        sources.append(str(summary_path))
        for item in summary.get("cuts", []):
            cut_id = str(item.get("cutId") or "")
            if cut_id:
                records[cut_id] = dict(item)

    selection_dir = args.selection_dir.expanduser().resolve()
    selection_paths = sorted(
        set(selection_dir.glob("CUT-???-exact-source-*-selection-*.json"))
        | set(selection_dir.glob("CUT-???-exact-source-frame-selection-*.json"))
    )
    selection_overrides = 0
    for selection_path in selection_paths:
        selection = load(selection_path)
        cut_id = str(selection.get("cutId") or "")
        proof = selection.get("selectedEvidence") or selection
        audit_value = proof.get("dependencyAudit") or selection.get(
            "dependencyAudit"
        )
        manifest_value = proof.get("strictManifest") or selection.get(
            "strictManifest"
        )
        verification_value = proof.get(
            "strictVerification"
        ) or selection.get("strictVerification")
        if not cut_id or not audit_value or not manifest_value or not verification_value:
            continue
        audit_path = resolve(audit_value)
        manifest_path = resolve(manifest_value)
        verification_path = resolve(verification_value)
        if not all(
            path.is_file()
            for path in (audit_path, manifest_path, verification_path)
        ):
            continue
        audit = load(audit_path)
        manifest = load(manifest_path)
        verification = load(verification_path)
        if verification.get("status") != "verified":
            continue
        post = verification.get("postRelinkDependencyAudit") or {}
        unresolved = list(
            post.get("renderCriticalUnresolvedPaths")
            or manifest.get("unresolved")
            or []
        )
        records[cut_id] = {
            "cutId": cut_id,
            "project": selection.get("project") or audit.get("project"),
            "projectBytes": (
                Path(str(selection.get("project") or audit.get("project"))).stat().st_size
                if Path(str(selection.get("project") or audit.get("project"))).is_file()
                else None
            ),
            "take": selection.get("take") or audit.get("take") or "Main",
            "frame": selection.get(
                "selectedProjectFrame", selection.get("frame", audit.get("frame"))
            ),
            "auditPath": relative(audit_path),
            "manifestPath": relative(manifest_path),
            "verificationPath": relative(verification_path),
            "status": "verified",
            "rawRenderCriticalMissingFiles": audit.get(
                "renderCriticalMissingFiles"
            ),
            "mappedPaths": (manifest.get("summary") or {}).get(
                "mappedPaths"
            ),
            "manifestUnresolvedPaths": list(manifest.get("unresolved") or []),
            "postRelinkUnresolvedPaths": unresolved,
            "strictDependencyRenderSafe": bool(
                verification.get("strictDependencyRenderSafe")
            ),
            "selectionEvidence": relative(selection_path),
        }
        selection_overrides += 1

    ordered = [records[key] for key in sorted(records)]
    payload = {
        "schemaVersion": 1,
        "updatedAt": now_iso(),
        "authority": (
            "Merged untouched-source audits with manually selected, strict "
            "exact-source render evidence"
        ),
        "sources": sources,
        "summary": {
            "processedCuts": len(ordered),
            "verifiedCuts": sum(
                item.get("status") == "verified" for item in ordered
            ),
            "strictDependencyRenderSafeCuts": sum(
                bool(item.get("strictDependencyRenderSafe")) for item in ordered
            ),
            "failedCuts": sum(item.get("status") == "failed" for item in ordered),
            "selectionOverrides": selection_overrides,
        },
        "cuts": ordered,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
