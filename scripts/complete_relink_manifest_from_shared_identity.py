#!/usr/bin/env python3
"""Complete a relink manifest from exact sibling and content evidence.

This helper is intentionally narrow.  It only resolves an existing unresolved
requirement when one of these authorities is supplied:

* an explicit source-to-local account-root translation; or
* an exact sibling manifest mapping for the same asset basename; or
* an explicitly allowed basename whose indexed candidates have one SHA-256.

The source manifest is never modified in place, and every selected byte stream
is re-hashed before the derived manifest is written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def basename(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).name


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verified_target(path: Path, expected_sha: str | None = None) -> tuple[str, int]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise FileNotFoundError(f"Missing or empty exact target: {resolved}")
    actual_sha = sha256_file(resolved)
    if expected_sha and actual_sha != expected_sha.casefold():
        raise RuntimeError(
            f"SHA-256 mismatch for {resolved}: expected {expected_sha}, got {actual_sha}"
        )
    return actual_sha, resolved.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sibling-manifest", type=Path, required=True)
    parser.add_argument(
        "--exact-target",
        nargs=2,
        action="append",
        metavar=("REQUIRED_PATH", "TARGET_PATH"),
        default=[],
    )
    parser.add_argument(
        "--unique-content-basename",
        action="append",
        default=[],
        help=(
            "Permit a named unresolved asset only when its candidate index "
            "contains exactly one content hash."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    sibling_path = args.sibling_manifest.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if output_path in {manifest_path, sibling_path}:
        raise RuntimeError("Output must differ from both input manifests")
    if output_path.exists():
        raise FileExistsError(output_path)

    payload = load_json(manifest_path)
    sibling = load_json(sibling_path)
    unresolved = [str(item) for item in payload.get("unresolved") or []]
    unresolved_candidates = {
        str(item.get("requiredPath") or ""): item
        for item in payload.get("unresolvedCandidates") or []
        if item.get("requiredPath")
    }
    explicit = {
        str(required): Path(target).expanduser().resolve()
        for required, target in args.exact_target
    }
    sibling_by_basename: dict[str, list[dict[str, Any]]] = {}
    for item in sibling.get("mappings") or []:
        name = str(item.get("basename") or basename(str(item.get("requiredPath") or "")))
        if name:
            sibling_by_basename.setdefault(name, []).append(item)

    allowed_unique = {str(item) for item in args.unique_content_basename}
    added: list[dict[str, Any]] = []
    retained: list[str] = []

    for required in unresolved:
        name = basename(required)
        if required in explicit:
            target = explicit[required]
            actual_sha, target_bytes = verified_target(target)
            added.append(
                {
                    "requiredPath": required,
                    "targetPath": str(target),
                    "basename": name,
                    "selectionBasis": "exact_source_account_root_translation",
                    "targetSha256": actual_sha,
                    "targetBytes": target_bytes,
                    "evidence": {
                        "sourceRequiredPath": required,
                        "translation": (
                            "authored Guassian Dropbox Projects/2026/Absolutely "
                            "root to the locally connected Jos Diaz Contreras/Absolutely root"
                        ),
                    },
                }
            )
            continue

        sibling_matches = sibling_by_basename.get(name, [])
        if len(sibling_matches) == 1:
            sibling_item = sibling_matches[0]
            target = Path(str(sibling_item.get("targetPath") or "")).expanduser().resolve()
            expected_sha = str(sibling_item.get("targetSha256") or "") or None
            actual_sha, target_bytes = verified_target(target, expected_sha)
            candidate = unresolved_candidates.get(required) or {}
            groups = candidate.get("candidateHashGroups") or []
            indexed_hashes = {str(group.get("sha256") or "") for group in groups}
            if indexed_hashes and indexed_hashes != {actual_sha}:
                raise RuntimeError(
                    f"Sibling content conflicts with indexed candidates for {required}"
                )
            added.append(
                {
                    "requiredPath": required,
                    "targetPath": str(target),
                    "basename": name,
                    "selectionBasis": "shared_asset_identity_from_exact_sibling_path_translation",
                    "targetSha256": actual_sha,
                    "targetBytes": target_bytes,
                    "evidence": {
                        "siblingManifest": str(sibling_path),
                        "siblingRequiredPath": sibling_item.get("requiredPath"),
                        "siblingSelectionBasis": sibling_item.get("selectionBasis"),
                        "indexedDistinctHashes": sorted(indexed_hashes),
                    },
                }
            )
            continue

        if name in allowed_unique:
            candidate = unresolved_candidates.get(required) or {}
            groups = candidate.get("candidateHashGroups") or []
            if len(groups) != 1 or not groups[0].get("sha256"):
                raise RuntimeError(
                    f"Expected one indexed content hash for explicitly allowed {required}"
                )
            expected_sha = str(groups[0]["sha256"])
            paths = [Path(str(item)).expanduser().resolve() for item in groups[0].get("paths") or []]
            existing = [item for item in paths if item.is_file() and item.stat().st_size > 0]
            if not existing:
                raise FileNotFoundError(f"No non-empty indexed candidate for {required}")
            target = existing[0]
            actual_sha, target_bytes = verified_target(target, expected_sha)
            added.append(
                {
                    "requiredPath": required,
                    "targetPath": str(target),
                    "basename": name,
                    "selectionBasis": "exact_single_content_identity_across_collected_assets",
                    "targetSha256": actual_sha,
                    "targetBytes": target_bytes,
                    "evidence": {
                        "indexedCandidatePaths": [str(item) for item in paths],
                        "distinctIndexedHashes": 1,
                    },
                }
            )
            continue

        retained.append(required)

    if not added:
        raise RuntimeError("No unresolved paths were completed")

    added_required = {str(item["requiredPath"]) for item in added}
    mappings = list(payload.get("mappings") or []) + added
    payload.update(
        {
            "schemaVersion": max(int(payload.get("schemaVersion") or 1), 1),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "authority": (
                "Exact base manifest completed from an authored account-root "
                "translation, exact sibling path translations, and explicitly "
                "allowed single-content collected-asset identity"
            ),
            "sourceBaseManifest": str(manifest_path),
            "sourceSiblingManifest": str(sibling_path),
            "renderCriticalOnly": bool(
                payload.get("renderCriticalOnly", False)
            ),
            "mappings": mappings,
            "unresolved": retained,
            "unresolvedCandidates": [
                item
                for item in payload.get("unresolvedCandidates") or []
                if str(item.get("requiredPath") or "") not in added_required
            ],
        }
    )
    summary = dict(payload.get("summary") or {})
    summary.update(
        {
            "mappedPaths": len(mappings),
            "unresolvedPaths": len(retained),
            "completedFromExactAccountRootTranslation": sum(
                item["selectionBasis"] == "exact_source_account_root_translation"
                for item in added
            ),
            "completedFromExactSiblingIdentity": sum(
                item["selectionBasis"]
                == "shared_asset_identity_from_exact_sibling_path_translation"
                for item in added
            ),
            "completedFromSingleContentIdentity": sum(
                item["selectionBasis"]
                == "exact_single_content_identity_across_collected_assets"
                for item in added
            ),
        }
    )
    payload["summary"] = summary
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "added": len(added),
                "mapped": len(mappings),
                "unresolved": len(retained),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
