#!/usr/bin/env python3
"""Build one exact-path Mainframe recovery request for every picture cut."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from c4d_relink_safety import safe_manifest_mappings


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = (
    APP_ROOT / "data" / "c4d-cut-dependency-audits-20260728"
)
DEFAULT_OUTPUT = (
    APP_ROOT
    / "data"
    / "c4d-mainframe-recovery-20260730"
    / "ALL-CUTS-exact-missing-path-request-20260801.json"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_path(value: str) -> str:
    return str(value).replace("\\", "/")


def basename(value: str) -> str:
    return PurePosixPath(normalized_path(value)).name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--override-summary",
        type=Path,
        action="append",
        default=[],
        help=(
            "Recovery summary whose verified per-cut audit/manifest paths "
            "replace the older standard pair for the same cut."
        ),
    )
    parser.add_argument(
        "--mirror-output",
        type=Path,
        help="Optional second copy inside the shared recovery mirror.",
    )
    parser.add_argument(
        "--supplemental-manifest",
        type=Path,
        action="append",
        default=[],
        help=(
            "Additional exact-source candidate manifest whose unresolved "
            "paths should be requested without replacing the selected audit "
            "for that cut. The CUT-### id is inferred from the filename."
        ),
    )
    args = parser.parse_args()

    audit_dir = args.audit_dir.expanduser().resolve()
    audit_sources: dict[str, tuple[Path, Path, str]] = {}
    for audit_path in sorted(audit_dir.glob("CUT-???.json")):
        cut_id = audit_path.stem
        manifest_path = audit_dir / f"{cut_id}-relink-manifest.json"
        if manifest_path.is_file():
            audit_sources[cut_id] = (
                audit_path,
                manifest_path,
                "standard_cut_audit",
            )
    applied_overrides: list[dict[str, str]] = []
    for summary_path_arg in args.override_summary:
        summary_path = summary_path_arg.expanduser().resolve()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for item in summary.get("cuts", []):
            if item.get("status") != "verified":
                continue
            cut_id = str(item.get("cutId") or "")
            audit_value = str(item.get("auditPath") or "")
            manifest_value = str(item.get("manifestPath") or "")
            if not cut_id or not audit_value or not manifest_value:
                continue
            audit_path = Path(audit_value).expanduser()
            manifest_path = Path(manifest_value).expanduser()
            if not audit_path.is_absolute():
                audit_path = APP_ROOT / audit_path
            if not manifest_path.is_absolute():
                manifest_path = APP_ROOT / manifest_path
            if not audit_path.is_file() or not manifest_path.is_file():
                continue
            audit_sources[cut_id] = (
                audit_path.resolve(),
                manifest_path.resolve(),
                f"override:{summary_path.name}",
            )
            applied_overrides.append(
                {
                    "cutId": cut_id,
                    "summary": str(summary_path),
                    "audit": str(audit_path.resolve()),
                    "manifest": str(manifest_path.resolve()),
                }
            )

    records: dict[str, dict[str, Any]] = {}
    cut_summaries: list[dict[str, Any]] = []
    for cut_id, (audit_path, manifest_path, audit_source) in sorted(
        audit_sources.items()
    ):
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        safe_mappings, rejected = safe_manifest_mappings(manifest)
        requests: dict[str, set[str]] = {}
        for required_path in manifest.get("unresolved", []):
            requests.setdefault(str(required_path), set()).add(
                "manifest_unresolved"
            )
        for item in rejected:
            requests.setdefault(str(item["requiredPath"]), set()).add(
                str(item["reason"])
            )
        for required_path, target_path in safe_mappings.items():
            if not Path(target_path).is_file():
                requests.setdefault(required_path, set()).add(
                    "safe_mapping_target_not_locally_readable"
                )

        for required_path, reasons in requests.items():
            record = records.setdefault(
                required_path,
                {
                    "requiredPath": required_path,
                    "basename": basename(required_path),
                    "extension": PurePosixPath(
                        normalized_path(required_path)
                    ).suffix.casefold(),
                    "cuts": [],
                    "projects": [],
                    "reasons": [],
                },
            )
            record["cuts"].append(cut_id)
            project = str(audit.get("project") or "")
            if project and project not in record["projects"]:
                record["projects"].append(project)
            for reason in sorted(reasons):
                if reason not in record["reasons"]:
                    record["reasons"].append(reason)
        cut_summaries.append(
            {
                "cutId": cut_id,
                "requestedPaths": len(requests),
                "manifestUnresolvedPaths": len(
                    manifest.get("unresolved", [])
                ),
                "unsafeManifestMappings": len(rejected),
                "safeMappings": len(safe_mappings),
                "auditSource": audit_source,
            }
        )

    supplemental_manifests: list[dict[str, Any]] = []
    cut_summaries_by_id = {
        str(item["cutId"]): item for item in cut_summaries
    }
    for manifest_arg in args.supplemental_manifest:
        manifest_path = manifest_arg.expanduser().resolve()
        match = re.search(r"CUT-\d{3}", manifest_path.name)
        if match is None:
            raise ValueError(
                "Supplemental manifest filename must contain CUT-###: "
                f"{manifest_path}"
            )
        cut_id = match.group(0)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audit_value = str(manifest.get("auditPath") or "")
        audit_path = Path(audit_value).expanduser() if audit_value else None
        audit: dict[str, Any] = {}
        if audit_path is not None and not audit_path.is_absolute():
            audit_path = APP_ROOT / audit_path
        if audit_path is not None and audit_path.is_file():
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        unresolved = [str(value) for value in manifest.get("unresolved", [])]
        for required_path in unresolved:
            record = records.setdefault(
                required_path,
                {
                    "requiredPath": required_path,
                    "basename": basename(required_path),
                    "extension": PurePosixPath(
                        normalized_path(required_path)
                    ).suffix.casefold(),
                    "cuts": [],
                    "projects": [],
                    "reasons": [],
                },
            )
            if cut_id not in record["cuts"]:
                record["cuts"].append(cut_id)
            project = str(audit.get("project") or "")
            if project and project not in record["projects"]:
                record["projects"].append(project)
            reason = "supplemental_candidate_manifest_unresolved"
            if reason not in record["reasons"]:
                record["reasons"].append(reason)
        cut_summary = cut_summaries_by_id.get(cut_id)
        if cut_summary is not None:
            cut_summary["supplementalRequestedPaths"] = int(
                cut_summary.get("supplementalRequestedPaths") or 0
            ) + len(unresolved)
        supplemental_manifests.append(
            {
                "cutId": cut_id,
                "manifest": str(manifest_path),
                "audit": str(audit_path) if audit_path is not None else None,
                "requestedPaths": len(unresolved),
            }
        )

    requested = sorted(
        records.values(),
        key=lambda item: (item["requiredPath"].casefold(), item["cuts"]),
    )
    extension_counts = Counter(item["extension"] for item in requested)
    reason_counts = Counter(
        reason for item in requested for reason in item["reasons"]
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "authority": (
            "Exact authored dependency paths from all frame-specific cut "
            "audits after rejecting unsafe basename-only relinks"
        ),
        "policy": {
            "sourceReadOnly": True,
            "pathIdentityRequired": True,
            "basenameOnlySubstitutionsForbidden": True,
            "crossShotCacheSubstitutionsForbidden": True,
            "destinationConflictPolicy": (
                "preserve both and report; never overwrite nonidentical"
            ),
            "verification": "source and destination SHA-256",
        },
        "summary": {
            "cuts": len(cut_summaries),
            "uniqueRequestedPaths": len(requested),
            "affectedCuts": sum(
                bool(item["requestedPaths"]) for item in cut_summaries
            ),
            "totalCutPathReferences": sum(
                int(item["requestedPaths"])
                + int(item.get("supplementalRequestedPaths") or 0)
                for item in cut_summaries
            ),
            "extensionCounts": dict(sorted(extension_counts.items())),
            "reasonCounts": dict(sorted(reason_counts.items())),
            "appliedOverrideCuts": len(applied_overrides),
            "supplementalCandidateManifests": len(
                supplemental_manifests
            ),
        },
        "cuts": cut_summaries,
        "requestedPaths": requested,
        "appliedOverrides": applied_overrides,
        "supplementalManifests": supplemental_manifests,
    }
    rendered = json.dumps(payload, indent=2) + "\n"
    outputs = [args.output.expanduser().resolve()]
    if args.mirror_output is not None:
        outputs.append(args.mirror_output.expanduser().resolve())
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(output)
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
