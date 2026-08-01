#!/usr/bin/env python3
"""Resolve dependencies that become visible only after first-stage relinks."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "data" / "c4d-cut-dependency-audits-20260728"
BUILDER = ROOT / "scripts" / "build_c4d_material_relink_manifest.py"
VERIFIER = ROOT / "scripts" / "c4dpy_verify_relink_manifest.py"
INDEX_CACHE = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "absolutely-file-index-20260728.json"
)
HASH_CACHE = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "absolutely-sha256-cache-20260728.json"
)
ABSOLUTELY = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026.1.2/"
    "c4dpy.app/Contents/MacOS/c4dpy"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str], log_path: Path, timeout: int) -> None:
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"exit {completed.returncode}; see {log_path}"
        )


def merged_manifest(
    base: dict[str, Any],
    phase: dict[str, Any],
    *,
    raw_audit_path: Path,
    round_index: int,
    phase_audit_path: Path,
    phase_manifest_path: Path,
) -> dict[str, Any]:
    mappings = {
        str(item.get("requiredPath") or ""): item
        for item in base.get("mappings", [])
        if item.get("requiredPath")
    }
    phase_required = {
        str(item)
        for item in (
            phase.get("unresolved", [])
            + [
                item.get("requiredPath")
                for item in phase.get("mappings", [])
            ]
        )
        if item
    }
    for item in phase.get("mappings", []):
        required = str(item.get("requiredPath") or "")
        if required:
            mappings[required] = item
    unresolved = {
        str(item)
        for item in base.get("unresolved", [])
        if str(item) and str(item) not in mappings
    }
    unresolved.difference_update(phase_required - set(phase.get("unresolved", [])))
    unresolved.update(str(item) for item in phase.get("unresolved", []))
    unresolved.difference_update(mappings)

    records = list(mappings.values())
    stages = list(base.get("relinkStages") or [])
    stages.append(
        {
            "round": round_index,
            "generatedAt": phase.get("generatedAt"),
            "auditPath": str(phase_audit_path),
            "manifestPath": str(phase_manifest_path),
            "summary": phase.get("summary"),
        }
    )
    return {
        **base,
        "generatedAt": now_iso(),
        "auditPath": str(raw_audit_path),
        "renderCriticalOnly": True,
        "summary": {
            "missingPaths": len(records) + len(unresolved),
            "mappedPaths": len(records),
            "unresolvedPaths": len(unresolved),
            "exactLocalTranslations": sum(
                item.get("selectionBasis")
                == "exact_local_path_translation"
                for item in records
            ),
            "preferredFolderSelections": sum(
                item.get("selectionBasis")
                == "preferred_collected_texture_folder"
                for item in records
            ),
            "basenameOnlySelections": sum(
                item.get("selectionBasis") == "exact_basename_only"
                for item in records
            ),
            "ambiguousContentMappings": sum(
                int(item.get("distinctCandidateHashes") or 0) > 1
                for item in records
            ),
            "relinkStages": len(stages),
        },
        "mappings": records,
        "unresolved": sorted(unresolved),
        "unresolvedCandidates": phase.get("unresolvedCandidates", []),
        "relinkStages": stages,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cuts",
        required=True,
        help="Comma-separated CUT-### identifiers.",
    )
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    cut_ids = [
        value.strip()
        for value in args.cuts.split(",")
        if value.strip()
    ]
    results = []
    for cut_id in cut_ids:
        raw_audit_path = AUDIT_DIR / f"{cut_id}.json"
        manifest_path = AUDIT_DIR / f"{cut_id}-relink-manifest.json"
        verification_path = (
            AUDIT_DIR / f"{cut_id}-relink-verification.json"
        )
        if not (
            raw_audit_path.is_file()
            and manifest_path.is_file()
            and verification_path.is_file()
        ):
            raise FileNotFoundError(f"Incomplete audit set for {cut_id}")

        raw_audit = load_json(raw_audit_path)
        project = Path(str(raw_audit["project"])).expanduser().resolve()
        backup_path = (
            AUDIT_DIR / f"{cut_id}-relink-manifest-stage0.json"
        )
        if not backup_path.exists():
            shutil.copy2(manifest_path, backup_path)

        rounds = []
        for round_index in range(1, args.max_rounds + 1):
            verification = load_json(verification_path)
            if verification.get("strictDependencyRenderSafe"):
                break
            post = verification.get("postRelinkDependencyAudit") or {}
            unresolved_paths = sorted(
                {
                    str(item)
                    for item in (
                        post.get("renderCriticalUnresolvedPaths") or []
                    )
                    if str(item)
                }
            )
            current_manifest = load_json(manifest_path)
            mapped_requirements = {
                str(item.get("requiredPath") or "")
                for item in current_manifest.get("mappings", [])
            }
            new_requirements = [
                item
                for item in unresolved_paths
                if item not in mapped_requirements
            ]
            if not new_requirements:
                break

            phase_audit_path = (
                AUDIT_DIR
                / f"{cut_id}-relink-stage{round_index}-audit.json"
            )
            phase_manifest_path = (
                AUDIT_DIR
                / f"{cut_id}-relink-stage{round_index}-manifest.json"
            )
            phase_audit = {
                "schemaVersion": 1,
                "generatedAt": now_iso(),
                "project": str(project),
                "take": raw_audit.get("take"),
                "frame": raw_audit.get("frame"),
                "renderCriticalMissingPaths": new_requirements,
                "authority": (
                    "Dependencies exposed by the prior in-memory relink and "
                    "frame-specific post-relink Cinema audit"
                ),
            }
            phase_audit_path.write_text(
                json.dumps(phase_audit, indent=2),
                encoding="utf-8",
            )
            build_command = [
                "python3",
                str(BUILDER),
                "--audit",
                str(phase_audit_path),
                "--root",
                str(ABSOLUTELY),
                "--index-cache",
                str(INDEX_CACHE),
                "--hash-cache",
                str(HASH_CACHE),
                "--strict-ambiguous",
                "--render-critical-only",
                "--output",
                str(phase_manifest_path),
            ]
            for directory in (project.parent / "tex", project.parent):
                if directory.is_dir():
                    build_command.extend(["--prefer-dir", str(directory)])
            run(
                build_command,
                AUDIT_DIR / f"{cut_id}-relink-stage{round_index}-build.log",
                args.timeout_seconds,
            )
            phase_manifest = load_json(phase_manifest_path)
            current_manifest = merged_manifest(
                current_manifest,
                phase_manifest,
                raw_audit_path=raw_audit_path,
                round_index=round_index,
                phase_audit_path=phase_audit_path,
                phase_manifest_path=phase_manifest_path,
            )
            manifest_path.write_text(
                json.dumps(current_manifest, indent=2),
                encoding="utf-8",
            )
            run(
                [
                    str(C4DPY),
                    str(VERIFIER),
                    "--project",
                    str(project),
                    "--manifest",
                    str(manifest_path),
                    "--result-json",
                    str(verification_path),
                    "--take",
                    str(raw_audit.get("take") or "Main"),
                    "--frame",
                    str(raw_audit["frame"]),
                ],
                AUDIT_DIR
                / f"{cut_id}-relink-stage{round_index}-verify.log",
                args.timeout_seconds,
            )
            verification = load_json(verification_path)
            rounds.append(
                {
                    "round": round_index,
                    "newRequirements": len(new_requirements),
                    "newMappings": int(
                        phase_manifest.get("summary", {}).get(
                            "mappedPaths", 0
                        )
                    ),
                    "newUnresolved": int(
                        phase_manifest.get("summary", {}).get(
                            "unresolvedPaths", 0
                        )
                    ),
                    "strictDependencyRenderSafe": bool(
                        verification.get("strictDependencyRenderSafe")
                    ),
                    "postRelinkUnresolvedFiles": int(
                        (
                            verification.get(
                                "postRelinkDependencyAudit"
                            )
                            or {}
                        ).get("renderCriticalUnresolvedFiles")
                        or 0
                    ),
                }
            )
            if not phase_manifest.get("mappings"):
                break

        final_verification = load_json(verification_path)
        result = {
            "cutId": cut_id,
            "rounds": rounds,
            "strictDependencyRenderSafe": bool(
                final_verification.get("strictDependencyRenderSafe")
            ),
            "postRelinkUnresolvedFiles": int(
                (
                    final_verification.get("postRelinkDependencyAudit")
                    or {}
                ).get("renderCriticalUnresolvedFiles")
                or 0
            ),
        }
        results.append(result)
        print(json.dumps(result, indent=2))

    output = AUDIT_DIR / "iterative-relink-results-20260728.json"
    output.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "generatedAt": now_iso(),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
