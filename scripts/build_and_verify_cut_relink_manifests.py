#!/usr/bin/env python3
"""Build and verify strict cut manifests from completed raw cut audits."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = (
    APP_ROOT / "data" / "c4d-cut-dependency-audits-20260728"
)
DEFAULT_SUMMARY = (
    APP_ROOT / "data" / "c4d-cut-relink-summary-20260728.json"
)
DEFAULT_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
DEFAULT_C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026.1.2/"
    "c4dpy.app/Contents/MacOS/c4dpy"
)
MANIFEST_BUILDER = APP_ROOT / "scripts" / "build_c4d_material_relink_manifest.py"
VERIFY_HELPER = APP_ROOT / "scripts" / "c4dpy_verify_relink_manifest.py"
INDEX_CACHE = (
    APP_ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "absolutely-file-index-20260728.json"
)
HASH_CACHE = (
    APP_ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "absolutely-sha256-cache-20260728.json"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_summary(path: Path, records: list[dict[str, Any]]) -> None:
    verified = [item for item in records if item["status"] == "verified"]
    payload = {
        "schemaVersion": 1,
        "updatedAt": now_iso(),
        "authority": (
            "Frame-specific active dependencies, exact local path/content "
            "resolution, and a second in-memory post-relink Cinema audit"
        ),
        "summary": {
            "processedCuts": len(records),
            "verifiedCuts": len(verified),
            "strictDependencyRenderSafeCuts": sum(
                bool(item.get("strictDependencyRenderSafe"))
                for item in verified
            ),
            "externalOrAmbiguousCuts": sum(
                not bool(item.get("strictDependencyRenderSafe"))
                for item in verified
            ),
            "failedCuts": sum(
                item["status"] == "failed" for item in records
            ),
        },
        "cuts": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--c4dpy", type=Path, default=DEFAULT_C4DPY)
    parser.add_argument(
        "--cuts", help="Comma-separated CUT-### identifiers."
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument(
        "--reverify",
        action="store_true",
        help="Rerun the in-memory Cinema verification without rebuilding a current manifest.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--refresh-index",
        action="store_true",
        help=(
            "Rebuild the shared Dropbox file index before manifest "
            "resolution. Useful after on-demand files have hydrated."
        ),
    )
    args = parser.parse_args()

    audit_dir = args.audit_dir.expanduser().resolve()
    summary_path = args.summary.expanduser().resolve()
    root = args.root.expanduser().resolve()
    c4dpy = args.c4dpy.expanduser().resolve()
    requested = {
        item.strip()
        for item in (args.cuts or "").split(",")
        if item.strip()
    }
    audit_paths = sorted(
        path
        for path in audit_dir.glob("CUT-???.json")
        if not requested or path.stem in requested
    )
    if args.limit is not None:
        audit_paths = audit_paths[: args.limit]

    records: list[dict[str, Any]] = []
    for audit_path in audit_paths:
        cut_id = audit_path.stem
        audit = load_json(audit_path)
        project = Path(str(audit["project"])).expanduser().resolve()
        manifest_path = audit_dir / f"{cut_id}-relink-manifest.json"
        verification_path = (
            audit_dir / f"{cut_id}-relink-verification.json"
        )
        build_log = audit_dir / f"{cut_id}-manifest.log"
        verify_log = audit_dir / f"{cut_id}-relink-verification.log"
        preferred = [project.parent / "tex", project.parent]
        record: dict[str, Any] = {
            "cutId": cut_id,
            "project": str(project),
            "take": audit.get("take"),
            "frame": audit.get("frame"),
            "rawAuditPath": str(audit_path.relative_to(APP_ROOT)),
            "manifestPath": str(manifest_path.relative_to(APP_ROOT)),
            "verificationPath": str(
                verification_path.relative_to(APP_ROOT)
            ),
            "status": "failed",
        }
        try:
            manifest_payload: dict[str, Any] = {}
            if manifest_path.is_file():
                manifest_payload = load_json(manifest_path)
            manifest_is_current = (
                manifest_path.is_file()
                and manifest_payload.get("auditPath") == str(audit_path)
                and manifest_payload.get("renderCriticalOnly") is True
            )
            manifest_rebuilt = False
            if args.rerun or not manifest_is_current:
                command = [
                    "python3",
                    str(MANIFEST_BUILDER),
                    "--audit",
                    str(audit_path),
                    "--root",
                    str(root),
                    "--index-cache",
                    str(INDEX_CACHE),
                    "--hash-cache",
                    str(HASH_CACHE),
                    "--strict-ambiguous",
                    "--render-critical-only",
                    "--output",
                    str(manifest_path),
                ]
                if args.refresh_index:
                    command.append("--refresh-index")
                for directory in preferred:
                    if directory.is_dir():
                        command.extend(["--prefer-dir", str(directory)])
                completed = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=args.timeout_seconds,
                )
                build_log.write_text(
                    completed.stdout, encoding="utf-8"
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"manifest builder exit {completed.returncode}"
                    )
                manifest_rebuilt = True

            manifest = load_json(manifest_path)
            verification_is_current = False
            if verification_path.is_file() and not manifest_rebuilt:
                verification = load_json(verification_path)
                verification_is_current = (
                    verification.get("project") == str(project)
                    and verification.get("manifest")
                    == str(manifest_path)
                    and verification.get("take") == audit.get("take")
                    and verification.get("frame") == audit.get("frame")
                    and verification.get("status") == "verified"
                )
            if args.rerun or args.reverify or not verification_is_current:
                command = [
                    str(c4dpy),
                    str(VERIFY_HELPER),
                    "--project",
                    str(project),
                    "--manifest",
                    str(manifest_path),
                    "--result-json",
                    str(verification_path),
                    "--take",
                    str(audit.get("take") or "Main"),
                    "--frame",
                    str(audit["frame"]),
                ]
                completed = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=args.timeout_seconds,
                )
                verify_log.write_text(
                    completed.stdout, encoding="utf-8"
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"relink verifier exit {completed.returncode}"
                    )
            verification = load_json(verification_path)
            if verification.get("status") != "verified":
                raise RuntimeError(
                    str(verification.get("error") or "verification failed")
                )
            post = verification.get("postRelinkDependencyAudit") or {}
            post_unresolved_paths = list(
                post.get("renderCriticalUnresolvedPaths") or []
            )
            record.update(
                {
                    "status": "verified",
                    "rawRenderCriticalMissingFiles": audit.get(
                        "renderCriticalMissingFiles"
                    ),
                    "mappedPaths": manifest["summary"]["mappedPaths"],
                    "unresolvedPaths": manifest.get("unresolved", []),
                    "manifestSummary": manifest.get("summary"),
                    "postRelinkDependencyReferences": post.get(
                        "dependencyReferences"
                    ),
                    "postRelinkUnresolvedReferences": post.get(
                        "renderCriticalUnresolvedReferences"
                    ),
                    "postRelinkUnresolvedFiles": post.get(
                        "renderCriticalUnresolvedFiles"
                    ),
                    "postRelinkUnresolvedPaths": post_unresolved_paths,
                    "strictDependencyRenderSafe": verification.get(
                        "strictDependencyRenderSafe"
                    ),
                }
            )
            print(
                f"{cut_id}: {record['mappedPaths']} mapped, "
                f"{len(record['unresolvedPaths'])} unresolved, "
                f"strict={record['strictDependencyRenderSafe']}"
            )
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
            print(f"{cut_id}: failed: {error}")
        records.append(record)
        write_summary(summary_path, records)

    write_summary(summary_path, records)
    print(summary_path)


if __name__ == "__main__":
    main()
