#!/usr/bin/env python3
"""Augment an exact relink manifest from a failed render's live asset audit.

The cut dependency audits intentionally classify only frame-active dependencies
as render critical. Cinema's Redshift bridge can nevertheless abort a render
when an inactive material or light still points at an offline asset. This
helper takes the exact unresolved picture paths reported by the failed render,
resolves them through the normal evidence-rich manifest builder, and merges
those mappings into a separate derived manifest. It never edits a C4D project.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_c4d_material_relink_manifest.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prefer-dir", type=Path, action="append", default=[])
    parser.add_argument("--index-cache", type=Path)
    parser.add_argument("--hash-cache", type=Path)
    parser.add_argument(
        "--include-base-unresolved",
        action="store_true",
        help=(
            "Resolve the union of the render-observed missing paths and "
            "the base manifest's unresolved paths. This preserves an "
            "already runtime-relinked dependency when it no longer appears "
            "in the latest render result."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result_path = args.result.expanduser().resolve()
    base_path = args.base_manifest.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    result = load_json(result_path)
    base = load_json(base_path)
    post = result.get("postRelinkDependencyAudit") or {}
    render_unresolved = {
        str(item)
        for item in post.get("unresolvedPicturePaths", [])
        if str(item)
    }
    base_unresolved = {
        str(item) for item in base.get("unresolved", []) if str(item)
    }
    unresolved = sorted(
        render_unresolved
        | (base_unresolved if args.include_base_unresolved else set())
    )
    if not unresolved:
        raise RuntimeError(
            "Render result does not contain unresolved picture paths"
        )

    with tempfile.TemporaryDirectory(
        prefix="paracosm-full-picture-relink-"
    ) as temp_dir:
        temp_root = Path(temp_dir)
        audit_path = temp_root / "audit.json"
        phase_manifest_path = temp_root / "manifest.json"
        audit_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "generatedAt": utc_now(),
                    "sourceRenderResult": str(result_path),
                    "missingFiles": unresolved,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        command = [
            "python3",
            str(BUILDER),
            "--audit",
            str(audit_path),
            "--root",
            str(args.root.expanduser().resolve()),
            "--strict-ambiguous",
            "--output",
            str(phase_manifest_path),
        ]
        for directory in args.prefer_dir:
            command.extend(
                ["--prefer-dir", str(directory.expanduser().resolve())]
            )
        if args.index_cache is not None:
            command.extend(
                [
                    "--index-cache",
                    str(args.index_cache.expanduser().resolve()),
                ]
            )
        if args.hash_cache is not None:
            command.extend(
                [
                    "--hash-cache",
                    str(args.hash_cache.expanduser().resolve()),
                ]
            )
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Manifest builder failed:\n" + completed.stdout
            )
        phase = load_json(phase_manifest_path)

    mappings = {
        str(item.get("requiredPath") or ""): item
        for item in base.get("mappings", [])
        if item.get("requiredPath")
    }
    for item in phase.get("mappings", []):
        required = str(item.get("requiredPath") or "")
        if required:
            mappings[required] = item
    unresolved_after = sorted(
        {
            str(item)
            for item in (
                list(base.get("unresolved") or [])
                + list(phase.get("unresolved") or [])
            )
            if str(item) and str(item) not in mappings
        }
    )
    records = list(mappings.values())
    phase_mappings = list(phase.get("mappings") or [])
    phase_unresolved = list(phase.get("unresolved") or [])
    payload = {
        **base,
        "schemaVersion": max(int(base.get("schemaVersion") or 1), 1),
        "generatedAt": utc_now(),
        "authority": (
            "Base relink manifest plus exact unresolved picture paths "
            "observed by a failed material-enabled Redshift render"
            + (
                " and every unresolved requirement retained by the base "
                "manifest"
                if args.include_base_unresolved
                else ""
            )
        ),
        "sourceBaseManifest": str(base_path),
        "sourceRenderResult": str(result_path),
        "renderCriticalOnly": False,
        "summary": {
            "baseMappedPaths": len(base.get("mappings") or []),
            "renderObservedMissingPaths": len(render_unresolved),
            "baseUnresolvedPathsIncluded": (
                len(base_unresolved)
                if args.include_base_unresolved
                else 0
            ),
            "phaseRequiredPaths": len(unresolved),
            "renderObservedMappedPaths": sum(
                str(item.get("requiredPath") or "") in render_unresolved
                for item in phase_mappings
            ),
            "renderObservedUnresolvedPaths": sum(
                str(item) in render_unresolved
                for item in phase_unresolved
            ),
            "phaseMappedPaths": len(phase_mappings),
            "phaseUnresolvedPaths": len(phase_unresolved),
            "totalMappedPaths": len(records),
            "totalUnresolvedPaths": len(unresolved_after),
        },
        "mappings": records,
        "unresolved": unresolved_after,
        "renderObservedUnresolvedCandidates": phase.get(
            "unresolvedCandidates", []
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload["summary"], indent=2))
    print(output_path)


if __name__ == "__main__":
    main()
