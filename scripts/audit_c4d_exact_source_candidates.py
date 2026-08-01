#!/usr/bin/env python3
"""Audit and verify untouched sibling C4D projects without saving them."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = (
    APP_ROOT
    / "data"
    / "c4d-mainframe-recovery-20260730"
    / "ALL-CUTS-exact-source-project-recovery-plan-20260801.json"
)
DEFAULT_OUTPUT_DIR = (
    APP_ROOT / "data" / "c4d-exact-source-recovery-20260801"
)
DEFAULT_SUMMARY = DEFAULT_OUTPUT_DIR / "summary.json"
DEFAULT_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
DEFAULT_C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026.1.2/"
    "c4dpy.app/Contents/MacOS/c4dpy"
)
AUDIT_HELPER = APP_ROOT / "scripts" / "c4dpy_audit_dependencies.py"
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
    payload = {
        "schemaVersion": 1,
        "updatedAt": now_iso(),
        "authority": (
            "Untouched sibling project, frame-specific dependency audit, "
            "strict manifest, and second in-memory Cinema verification"
        ),
        "renderEnabledPolicy": (
            "Render-mode inheritance is evaluated through ancestors. The "
            "Cinema generator-enable switch applies only to its owning "
            "object, because disabling a generator does not render-disable "
            "authored child objects beneath it."
        ),
        "summary": {
            "processedCuts": len(records),
            "verifiedCuts": sum(
                item.get("status") == "verified" for item in records
            ),
            "strictDependencyRenderSafeCuts": sum(
                bool(item.get("strictDependencyRenderSafe"))
                for item in records
            ),
            "failedCuts": sum(
                item.get("status") == "failed" for item in records
            ),
        },
        "cuts": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned[:96] or "project"


def run_logged(
    command: list[str], log_path: Path, timeout_seconds: int
) -> None:
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_seconds,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"command exit {completed.returncode}: {command[0]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--c4dpy", type=Path, default=DEFAULT_C4DPY)
    parser.add_argument("--cuts")
    parser.add_argument(
        "--frame-override",
        action="append",
        default=[],
        metavar="CUT-ID=FRAME",
        help=(
            "Use a directly verified project-frame correction for one cut "
            "without changing the shared source plan."
        ),
    )
    parser.add_argument("--max-project-bytes", type=int)
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument(
        "--rerun-manifest",
        action="store_true",
        help=(
            "Reuse an existing frame audit, rebuild its strict manifest, "
            "and rerun the in-memory verification."
        ),
    )
    parser.add_argument(
        "--rerun-verification",
        action="store_true",
        help="Reuse the audit and manifest but rerun Cinema verification.",
    )
    parser.add_argument(
        "--prefer-dir",
        type=Path,
        action="append",
        default=[],
        help=(
            "Additional exact collected-source directory preferred while "
            "rebuilding manifests; repeat as needed."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    frame_overrides: dict[str, int] = {}
    for value in args.frame_override:
        cut_id, separator, frame_value = value.partition("=")
        if not separator or not cut_id.strip():
            parser.error(f"invalid --frame-override: {value}")
        try:
            frame_overrides[cut_id.strip()] = int(frame_value)
        except ValueError:
            parser.error(f"invalid --frame-override frame: {value}")

    plan = load_json(args.plan.expanduser().resolve())
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    requested = {
        item.strip() for item in (args.cuts or "").split(",") if item.strip()
    }
    candidates = [
        item
        for item in plan.get("untouchedSiblingCandidates", [])
        if not requested or item["cutId"] in requested
    ]
    if args.max_project_bytes is not None:
        candidates = [
            item
            for item in candidates
            if int(item["exactSourceCandidate"]["bytes"])
            <= args.max_project_bytes
        ]

    records: list[dict[str, Any]] = []
    for item in candidates:
        cut_id = str(item["cutId"])
        project = Path(
            str(item["exactSourceCandidate"]["path"])
        ).expanduser().resolve()
        take = str(item.get("take") or "Main")
        frame = frame_overrides.get(cut_id, int(item["frame"]))
        prefix = f"{cut_id}-{safe_stem(project.stem)}"
        audit_path = output_dir / f"{prefix}-dependency-audit.json"
        manifest_path = output_dir / f"{prefix}-strict-relink-manifest.json"
        verification_path = output_dir / f"{prefix}-strict-relink-verification.json"
        record: dict[str, Any] = {
            "cutId": cut_id,
            "project": str(project),
            "projectBytes": project.stat().st_size,
            "take": take,
            "frame": frame,
            "plannedFrame": int(item["frame"]),
            "frameOverridden": cut_id in frame_overrides,
            "auditPath": str(audit_path.relative_to(APP_ROOT)),
            "manifestPath": str(manifest_path.relative_to(APP_ROOT)),
            "verificationPath": str(
                verification_path.relative_to(APP_ROOT)
            ),
            "status": "failed",
        }
        try:
            if args.rerun or not audit_path.is_file():
                run_logged(
                    [
                        str(args.c4dpy.expanduser().resolve()),
                        str(AUDIT_HELPER),
                        "--project",
                        str(project),
                        "--take",
                        take,
                        "--frame",
                        str(frame),
                        "--result-json",
                        str(audit_path),
                    ],
                    output_dir / f"{prefix}-dependency-audit.log",
                    args.timeout_seconds,
                )
            audit = load_json(audit_path)

            if (
                args.rerun
                or args.rerun_manifest
                or not manifest_path.is_file()
            ):
                build_command = [
                    "python3",
                    str(MANIFEST_BUILDER),
                    "--audit",
                    str(audit_path),
                    "--root",
                    str(args.root.expanduser().resolve()),
                    "--index-cache",
                    str(INDEX_CACHE),
                    "--hash-cache",
                    str(HASH_CACHE),
                    "--strict-ambiguous",
                    "--render-critical-only",
                    "--output",
                    str(manifest_path),
                ]
                for directory in (project.parent / "tex", project.parent):
                    if directory.is_dir():
                        build_command.extend(["--prefer-dir", str(directory)])
                for directory in args.prefer_dir:
                    resolved = directory.expanduser().resolve()
                    if resolved.is_dir():
                        build_command.extend(["--prefer-dir", str(resolved)])
                run_logged(
                    build_command,
                    output_dir / f"{prefix}-manifest.log",
                    args.timeout_seconds,
                )
            manifest = load_json(manifest_path)

            if (
                args.rerun
                or args.rerun_manifest
                or args.rerun_verification
                or not verification_path.is_file()
            ):
                run_logged(
                    [
                        str(args.c4dpy.expanduser().resolve()),
                        str(VERIFY_HELPER),
                        "--project",
                        str(project),
                        "--manifest",
                        str(manifest_path),
                        "--result-json",
                        str(verification_path),
                        "--take",
                        take,
                        "--frame",
                        str(frame),
                    ],
                    output_dir / f"{prefix}-verification.log",
                    args.timeout_seconds,
                )
            verification = load_json(verification_path)
            if verification.get("status") != "verified":
                raise RuntimeError(
                    str(verification.get("error") or "verification failed")
                )
            post = verification.get("postRelinkDependencyAudit") or {}
            record.update(
                {
                    "status": "verified",
                    "rawRenderCriticalMissingFiles": audit.get(
                        "renderCriticalMissingFiles"
                    ),
                    "mappedPaths": manifest.get("summary", {}).get(
                        "mappedPaths"
                    ),
                    "manifestUnresolvedPaths": manifest.get(
                        "unresolved", []
                    ),
                    "postRelinkUnresolvedPaths": post.get(
                        "renderCriticalUnresolvedPaths", []
                    ),
                    "strictDependencyRenderSafe": verification.get(
                        "strictDependencyRenderSafe"
                    ),
                }
            )
            print(
                f"{cut_id}: source={project.name}, "
                f"mapped={record['mappedPaths']}, "
                f"manifest-unresolved={len(record['manifestUnresolvedPaths'])}, "
                f"strict={record['strictDependencyRenderSafe']}"
            )
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
            print(f"{cut_id}: failed: {error}")
        records.append(record)
        write_summary(args.summary.expanduser().resolve(), records)

    write_summary(args.summary.expanduser().resolve(), records)
    print(args.summary.expanduser().resolve())


if __name__ == "__main__":
    main()
