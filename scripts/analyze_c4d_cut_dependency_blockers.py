#!/usr/bin/env python3
"""Summarize exact cut dependency blockers into recoverable payload families."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "data" / "c4d-cut-relink-summary-20260728.json"
DEFAULT_INDEX = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "absolutely-file-index-20260728.json"
)
DEFAULT_HASH_CACHE = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "absolutely-sha256-cache-20260728.json"
)
DEFAULT_OUTPUT = (
    ROOT / "data" / "c4d-cut-dependency-blockers-20260728.json"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sequence_key(value: str) -> str:
    normalized = value.replace("\\", "/")
    return re.sub(
        r"(?<=\D)\d{3,6}(?=\.[A-Za-z0-9.]+$)",
        "####",
        normalized,
    )


def classify(
    representative: str,
    candidate_count: int,
    distinct_hashes: int,
) -> str:
    lower = representative.casefold()
    extension = Path(lower).suffix
    ambiguous = candidate_count > 0 and distinct_hashes > 1
    if extension == ".rs":
        return (
            "ambiguous_local_proxy_candidates"
            if ambiguous
            else "local_proxy_candidate"
            if candidate_count
            else "external_redshift_proxy_payload"
        )
    if extension in {".abc", ".vdb", ".bgeo", ".sc"}:
        return (
            "ambiguous_local_cache_candidates"
            if ambiguous
            else "local_cache_candidate"
            if candidate_count
            else "external_authored_cache_payload"
        )
    if extension in {
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".exr",
        ".hdr",
        ".tx",
    }:
        return (
            "ambiguous_local_texture_candidates"
            if ambiguous
            else "local_texture_candidate"
            if candidate_count
            else "missing_texture_payload"
        )
    return (
        "ambiguous_local_file_candidates"
        if ambiguous
        else "local_file_candidate"
        if candidate_count
        else "external_or_missing_file"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--hash-cache", type=Path, default=DEFAULT_HASH_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    summary_path = args.summary.expanduser().resolve()
    summary = load_json(summary_path)
    cut_records: list[dict[str, Any]] = []
    missing_basenames: set[str] = set()

    for record in summary.get("cuts", []):
        if record.get("status") != "verified":
            continue
        verification_path = ROOT / str(record.get("verificationPath") or "")
        verification = (
            load_json(verification_path)
            if verification_path.is_file()
            else {}
        )
        post = verification.get("postRelinkDependencyAudit") or {}
        unresolved = sorted(
            {
                str(value)
                for value in [
                    *(record.get("unresolvedPaths") or []),
                    *(post.get("renderCriticalUnresolvedPaths") or []),
                ]
                if str(value)
            }
        )
        for value in unresolved:
            missing_basenames.add(
                Path(value.replace("\\", "/")).name.casefold()
            )
        cut_records.append(
            {
                **record,
                "postRelinkUnresolvedFiles": int(
                    post.get("renderCriticalUnresolvedFiles")
                    if post.get("renderCriticalUnresolvedFiles") is not None
                    else len(unresolved)
                ),
                "postRelinkUnresolvedReferences": int(
                    post.get("renderCriticalUnresolvedReferences")
                    if post.get("renderCriticalUnresolvedReferences")
                    is not None
                    else len(unresolved)
                ),
                "unresolved": unresolved,
            }
        )

    indexed = load_json(args.index_cache.expanduser().resolve())
    candidates_by_basename: dict[str, list[str]] = defaultdict(list)
    for value in indexed.get("files", []):
        path = Path(str(value))
        folded = path.name.casefold()
        if folded in missing_basenames and path.is_file():
            candidates_by_basename[folded].append(str(path))

    hash_cache_path = args.hash_cache.expanduser().resolve()
    hash_cache = (
        load_json(hash_cache_path).get("files", {})
        if hash_cache_path.is_file()
        else {}
    )

    families: dict[str, dict[str, Any]] = {}
    for record in cut_records:
        cut_id = str(record.get("cutId") or "")
        for required in record["unresolved"]:
            key = sequence_key(required)
            family = families.setdefault(
                key,
                {
                    "key": key,
                    "representativePath": required,
                    "cutIds": set(),
                    "requiredPaths": set(),
                    "localCandidates": set(),
                    "candidateHashes": set(),
                },
            )
            family["cutIds"].add(cut_id)
            family["requiredPaths"].add(required)
            basename = Path(required.replace("\\", "/")).name.casefold()
            for candidate in candidates_by_basename.get(basename, []):
                family["localCandidates"].add(candidate)
                cached = hash_cache.get(str(Path(candidate).resolve())) or {}
                digest = cached.get("sha256")
                if digest:
                    family["candidateHashes"].add(str(digest))

    serialized_families: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    for family in families.values():
        local_candidates = sorted(family.pop("localCandidates"))
        candidate_hashes = sorted(family.pop("candidateHashes"))
        required_paths = sorted(family.pop("requiredPaths"))
        cut_ids = sorted(family.pop("cutIds"))
        family_type = classify(
            str(family["representativePath"]),
            len(local_candidates),
            len(candidate_hashes),
        )
        family_counts[family_type] += 1
        serialized_families.append(
            {
                **family,
                "classification": family_type,
                "cutIds": cut_ids,
                "cutCount": len(cut_ids),
                "requiredFileCount": len(required_paths),
                "requiredPaths": required_paths[:24],
                "localCandidateCount": len(local_candidates),
                "distinctLocalCandidateHashes": len(candidate_hashes),
                "localCandidates": local_candidates[:24],
            }
        )
    serialized_families.sort(
        key=lambda item: (
            -int(item["cutCount"]),
            -int(item["requiredFileCount"]),
            str(item["classification"]),
            str(item["key"]),
        )
    )

    cut_blockers = []
    for record in cut_records:
        if record.get("strictDependencyRenderSafe"):
            classification = "strict_dependency_safe"
        elif int(record["postRelinkUnresolvedFiles"]) <= 14:
            classification = "small_gap_local_recovery_priority"
        else:
            classification = "large_payload_recovery"
        cut_blockers.append(
            {
                "cutId": record.get("cutId"),
                "project": record.get("project"),
                "take": record.get("take"),
                "frame": record.get("frame"),
                "classification": classification,
                "rawRenderCriticalMissingFiles": record.get(
                    "rawRenderCriticalMissingFiles"
                ),
                "mappedPaths": record.get("mappedPaths"),
                "postRelinkUnresolvedFiles": record[
                    "postRelinkUnresolvedFiles"
                ],
                "postRelinkUnresolvedReferences": record[
                    "postRelinkUnresolvedReferences"
                ],
                "strictDependencyRenderSafe": bool(
                    record.get("strictDependencyRenderSafe")
                ),
            }
        )

    payload = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "authority": (
            "Completed exact cut/take/frame dependency verification plus the "
            "complete local Absolutely file index and cached content hashes"
        ),
        "sourceSummary": str(summary_path.relative_to(ROOT)),
        "summary": {
            "verifiedCuts": len(cut_records),
            "strictDependencySafeCuts": sum(
                bool(item.get("strictDependencyRenderSafe"))
                for item in cut_records
            ),
            "blockedCuts": sum(
                not bool(item.get("strictDependencyRenderSafe"))
                for item in cut_records
            ),
            "smallGapCuts": sum(
                item["classification"]
                == "small_gap_local_recovery_priority"
                for item in cut_blockers
            ),
            "blockerFamilies": len(serialized_families),
            "familiesByClassification": dict(family_counts),
        },
        "cuts": cut_blockers,
        "families": serialized_families,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(output)


if __name__ == "__main__":
    main()
