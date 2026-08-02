#!/usr/bin/env python3
"""Replace one relink mapping only when exact source evidence proves it.

This helper is deliberately narrower than the normal candidate resolver.  It
is for a recovered authored payload whose original scene semantics establish
the mapping even though the broken downstream project stored a directory or
otherwise unusable path.  The input manifest is never modified in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--required-path", required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--target-sha256", required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    target = args.target.expanduser().resolve()
    output = args.output.expanduser().resolve()
    evidence = [item.expanduser().resolve() for item in args.evidence]
    if output == manifest_path:
        raise RuntimeError("Output must differ from the input manifest")
    if output.exists():
        raise FileExistsError(output)
    if not target.is_file():
        raise FileNotFoundError(target)
    missing_evidence = [str(item) for item in evidence if not item.is_file()]
    if missing_evidence:
        raise FileNotFoundError(
            "Missing exact-mapping evidence: " + ", ".join(missing_evidence)
        )
    expected_sha = args.target_sha256.casefold()
    actual_sha = sha256_file(target)
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"Target SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mappings = list(payload.get("mappings") or [])
    indexes = [
        index
        for index, item in enumerate(mappings)
        if str(item.get("requiredPath") or "") == args.required_path
    ]
    if len(indexes) != 1:
        raise RuntimeError(
            "Expected exactly one existing mapping for required path; "
            f"found {len(indexes)}"
        )
    original = mappings[indexes[0]]
    mappings[indexes[0]] = {
        "requiredPath": args.required_path,
        "targetPath": str(target),
        "basename": target.name,
        "selectionBasis": "exact_authored_native_source_image_recovery",
        "targetSha256": actual_sha,
        "targetBytes": target.stat().st_size,
        "exactMappingReason": args.reason,
        "exactMappingEvidence": [str(item) for item in evidence],
        "supersededMapping": original,
    }
    unresolved = [
        str(item)
        for item in (payload.get("unresolved") or [])
        if str(item) != args.required_path
    ]
    summary = dict(payload.get("summary") or {})
    summary.update(
        {
            "totalMappedPaths": len(mappings),
            "totalUnresolvedPaths": len(unresolved),
            "exactEvidenceOverrideCount": int(
                summary.get("exactEvidenceOverrideCount") or 0
            )
            + 1,
        }
    )
    payload.update(
        {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "authority": (
                str(payload.get("authority") or "")
                + "; exact authored native-source image recovery override"
            ).lstrip("; "),
            "sourceBaseManifest": str(manifest_path),
            "summary": summary,
            "mappings": mappings,
            "unresolved": unresolved,
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "requiredPath": args.required_path,
                "targetPath": str(target),
                "targetSha256": actual_sha,
                "mappingCount": len(mappings),
                "unresolvedCount": len(unresolved),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
