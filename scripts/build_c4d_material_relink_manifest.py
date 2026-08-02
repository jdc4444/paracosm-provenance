#!/usr/bin/env python3
"""Build an evidence-rich material relink manifest from a C4D audit.

The audit must come from Cinema 4D's own asset collector under the target
runtime. This helper indexes the shared Absolutely tree once, prefers an exact
local translation of historical paths, then prefers explicit shot/package
texture folders. It never edits a Cinema 4D document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    from scripts.c4d_relink_safety import (
        basename_only_semantics_match,
        unsafe_relink_target_reason,
    )
except ModuleNotFoundError:
    from c4d_relink_safety import (
        basename_only_semantics_match,
        unsafe_relink_target_reason,
    )


MAXON_ASSET_BASENAME = re.compile(
    r"^file_([0-9a-f]{16})~?(\.[^.]+)$",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_parts(value: str) -> list[str]:
    text = value.replace("\\", "/")
    parts = [
        part
        for part in PurePosixPath(text).parts
        if part not in {"", "/"}
    ]
    lowered = [part.casefold() for part in parts]
    if "absolutely" in lowered:
        return parts[lowered.index("absolutely") + 1 :]
    return parts


def sha256(
    path: Path, cache: dict[str, dict[str, int | str]]
) -> str:
    key = str(path.resolve())
    stat = path.stat()
    cached = cache.get(key)
    if (
        cached
        and cached.get("size") == stat.st_size
        and cached.get("mtimeNs") == stat.st_mtime_ns
        and cached.get("sha256")
    ):
        return str(cached["sha256"])
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    cache[key] = {
        "size": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
        "sha256": value,
    }
    return value


def exact_local_translation(required: str, root: Path) -> Path | None:
    parts = normalized_parts(required)
    if not parts:
        return None
    candidate = root.joinpath(*parts)
    return candidate if candidate.exists() else None


def directory_tree_sha256(
    path: Path, cache: dict[str, dict[str, int | str]]
) -> tuple[str, int]:
    """Fingerprint an exact translated directory and every file below it."""

    digest = hashlib.sha256()
    files = sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    )
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(item, cache).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def maxon_asset_id(required: str) -> tuple[str, str] | None:
    basename = Path(required.replace("\\", "/")).name
    match = MAXON_ASSET_BASENAME.fullmatch(basename)
    if match is None:
        return None
    return match.group(1).casefold(), match.group(2).casefold()


def maxon_asset_cache_candidates(
    required: str,
    cache_roots: list[Path],
) -> list[Path]:
    parsed = maxon_asset_id(required)
    if parsed is None:
        return []
    asset_id, required_suffix = parsed
    results: list[Path] = []
    for root in cache_roots:
        if not root.is_dir():
            continue
        for asset_dir in root.rglob(f"file_{asset_id}"):
            payload_dir = asset_dir / "1"
            if not payload_dir.is_dir():
                continue
            results.extend(
                path
                for path in payload_dir.iterdir()
                if path.is_file()
                and path.suffix.casefold() == required_suffix
                and not unsafe_relink_target_reason(str(path))
            )
    return sorted(set(results), key=str)


def score_candidate(
    candidate: Path,
    exact_translation: Path | None,
    preferred_dirs: list[Path],
) -> tuple[int, int, int, int, int, str]:
    resolved = candidate.resolve()
    non_symlink = int(not candidate.is_symlink())
    no_literal_drive_segment = int(
        not any(
            len(part) == 2 and part[1] == ":"
            for part in candidate.parts
        )
    )
    codex_penalty = -str(candidate).casefold().count("_codex_")
    if (
        exact_translation is not None
        and resolved == exact_translation.resolve()
    ):
        return (
            10_000,
            non_symlink,
            no_literal_drive_segment,
            codex_penalty,
            candidate.stat().st_size,
            str(candidate),
        )
    for index, directory in enumerate(preferred_dirs):
        try:
            resolved.relative_to(directory.resolve())
        except ValueError:
            continue
        return (
            9_000 - index * 100,
            non_symlink,
            no_literal_drive_segment,
            codex_penalty,
            candidate.stat().st_size,
            str(candidate),
        )
    return (
        1_000,
        non_symlink,
        no_literal_drive_segment,
        codex_penalty,
        candidate.stat().st_size,
        str(candidate),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--prefer-dir", type=Path, action="append", default=[]
    )
    parser.add_argument(
        "--index-cache",
        type=Path,
        help=(
            "Optional reusable JSON file index for the shared root. The "
            "first invocation builds it; later manifests avoid rescanning "
            "the complete Dropbox tree."
        ),
    )
    parser.add_argument(
        "--refresh-index",
        action="store_true",
        help=(
            "Rebuild the reusable file index before resolving paths. Use "
            "after Dropbox has hydrated additional local files."
        ),
    )
    parser.add_argument(
        "--hash-cache",
        type=Path,
        help=(
            "Optional persistent size/mtime-qualified SHA-256 cache. This "
            "avoids rehashing large identical Alembics across cut audits."
        ),
    )
    parser.add_argument(
        "--strict-ambiguous",
        action="store_true",
        help=(
            "Do not select a basename-only candidate when candidates have "
            "different content hashes. Retain the requirement as unresolved."
        ),
    )
    parser.add_argument(
        "--render-critical-only",
        action="store_true",
        help=(
            "Build mappings only for the audit's frame-specific active "
            "render-critical missing paths."
        ),
    )
    parser.add_argument(
        "--maxon-asset-cache-root",
        type=Path,
        action="append",
        default=[],
        help=(
            "Optional Maxon asset-cache root. Required paths named "
            "file_<asset-id>~.<ext> are resolved only through the exact "
            "asset-id directory and matching payload extension."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    audit_path = args.audit.expanduser().resolve()
    root = args.root.expanduser().resolve()
    preferred_dirs = [
        item.expanduser().resolve() for item in args.prefer_dir
    ]
    configured_maxon_cache_roots = [
        item.expanduser().resolve()
        for item in args.maxon_asset_cache_root
    ]
    default_maxon_cache_root = (
        Path.home()
        / "Library"
        / "Preferences"
        / "Maxon"
        / "_assetcache"
    )
    maxon_cache_roots = (
        configured_maxon_cache_roots
        if configured_maxon_cache_roots
        else [default_maxon_cache_root]
    )
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    index_cache_path = (
        args.index_cache.expanduser().resolve()
        if args.index_cache is not None
        else None
    )
    indexed_paths: list[Path]
    if (
        index_cache_path is not None
        and index_cache_path.is_file()
        and not args.refresh_index
    ):
        cached_index = json.loads(
            index_cache_path.read_text(encoding="utf-8")
        )
        if cached_index.get("root") != str(root):
            raise RuntimeError(
                "Index cache root does not match requested root"
            )
        indexed_paths = [
            Path(item)
            for item in cached_index.get("files", [])
            if Path(item).is_file()
        ]
    else:
        indexed_paths = [
            path for path in root.rglob("*") if path.is_file()
        ]
        if index_cache_path is not None:
            index_cache_path.parent.mkdir(parents=True, exist_ok=True)
            index_cache_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "generatedAt": utc_now(),
                        "root": str(root),
                        "files": [str(item) for item in indexed_paths],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    by_basename: dict[str, list[Path]] = defaultdict(list)
    unsafe_by_basename: dict[str, list[Path]] = defaultdict(list)
    for path in indexed_paths:
        if unsafe_relink_target_reason(str(path)):
            unsafe_by_basename[path.name.casefold()].append(path)
        else:
            by_basename[path.name.casefold()].append(path)

    missing_source = (
        audit.get("renderCriticalMissingPaths", [])
        if args.render_critical_only
        else audit.get("missingFiles", [])
    )
    missing_paths = sorted(
        {
            str(item)
            for item in missing_source
            if str(item)
        }
    )
    mappings = []
    unresolved = []
    unresolved_candidates = []
    hash_cache_path = (
        args.hash_cache.expanduser().resolve()
        if args.hash_cache is not None
        else None
    )
    hash_cache: dict[str, dict[str, int | str]] = {}
    if hash_cache_path is not None and hash_cache_path.is_file():
        hash_cache = json.loads(
            hash_cache_path.read_text(encoding="utf-8")
        ).get("files", {})
    for required in missing_paths:
        basename = Path(required.replace("\\", "/")).name
        exact_translation = exact_local_translation(required, root)
        if (
            exact_translation is not None
            and exact_translation.is_dir()
            and not unsafe_relink_target_reason(str(exact_translation))
        ):
            tree_digest, entry_count = directory_tree_sha256(
                exact_translation, hash_cache
            )
            mappings.append(
                {
                    "requiredPath": required,
                    "targetPath": str(exact_translation),
                    "basename": basename,
                    "selectionBasis": "exact_local_directory_translation",
                    "targetTreeSha256": tree_digest,
                    "targetEntryCount": entry_count,
                    "candidateCount": 1,
                    "distinctCandidateHashes": 1,
                    "candidateHashGroups": [],
                }
            )
            continue
        candidates = by_basename.get(basename.casefold(), [])
        maxon_candidates = maxon_asset_cache_candidates(
            required, maxon_cache_roots
        )
        if maxon_candidates:
            candidate_hashes: dict[str, list[str]] = defaultdict(list)
            for candidate in maxon_candidates:
                candidate_hashes[sha256(candidate, hash_cache)].append(
                    str(candidate)
                )
            if len(candidate_hashes) == 1:
                selected = maxon_candidates[0]
                selected_hash = next(iter(candidate_hashes))
                mappings.append(
                    {
                        "requiredPath": required,
                        "targetPath": str(selected),
                        "basename": basename,
                        "selectionBasis": "exact_maxon_asset_id",
                        "targetSha256": selected_hash,
                        "candidateCount": len(maxon_candidates),
                        "distinctCandidateHashes": 1,
                        "candidateHashGroups": [
                            {
                                "sha256": selected_hash,
                                "paths": [
                                    str(item)
                                    for item in maxon_candidates[:12]
                                ],
                            }
                        ],
                    }
                )
                continue
            unresolved.append(required)
            unresolved_candidates.append(
                {
                    "requiredPath": required,
                    "reason": "ambiguous_maxon_asset_id_payload",
                    "candidateHashGroups": [
                        {"sha256": digest, "paths": paths[:24]}
                        for digest, paths in sorted(
                            candidate_hashes.items()
                        )
                    ],
                }
            )
            continue
        if not candidates:
            unresolved.append(required)
            unsafe_candidates = unsafe_by_basename.get(
                basename.casefold(), []
            )
            unresolved_candidates.append(
                {
                    "requiredPath": required,
                    "reason": (
                        "rejected_unsafe_candidate_path"
                        if unsafe_candidates
                        else "no_exact_basename_candidate"
                    ),
                    "candidateHashGroups": [],
                    "rejectedUnsafeCandidates": [
                        str(item) for item in unsafe_candidates[:24]
                    ],
                }
            )
            continue
        ranked = sorted(
            candidates,
            key=lambda item: (
                int(
                    basename_only_semantics_match(
                        required, str(item)
                    )
                ),
                score_candidate(
                    item, exact_translation, preferred_dirs
                ),
            ),
            reverse=True,
        )
        selected = ranked[0]
        selected_hash = sha256(selected, hash_cache)
        hashes: dict[str, list[str]] = defaultdict(list)
        for candidate in ranked:
            hashes[sha256(candidate, hash_cache)].append(str(candidate))
        preferred_selection = False
        for directory in preferred_dirs:
            try:
                selected.resolve().relative_to(directory.resolve())
                preferred_selection = True
                break
            except ValueError:
                continue
        selection_basis = (
            "exact_local_path_translation"
            if exact_translation is not None
            and selected.resolve() == exact_translation.resolve()
            else "preferred_collected_texture_folder"
            if preferred_selection
            and Path(required.replace("\\", "/")).suffix.casefold()
            not in {".abc", ".rs"}
            else "exact_basename_only"
        )
        if (
            selection_basis == "exact_basename_only"
            and basename_only_semantics_match(required, str(selected))
        ):
            selection_basis = "authored_path_tail_recovery"
        if (
            args.strict_ambiguous
            and selection_basis == "exact_basename_only"
        ):
            unresolved.append(required)
            unresolved_candidates.append(
                {
                    "requiredPath": required,
                    "reason": (
                        "ambiguous_content"
                        if len(hashes) > 1
                        else "basename_only_without_path_provenance"
                    ),
                    "candidateHashGroups": [
                        {
                            "sha256": digest,
                            "paths": paths[:24],
                        }
                        for digest, paths in sorted(hashes.items())
                    ],
                }
            )
            continue
        mappings.append(
            {
                "requiredPath": required,
                "targetPath": str(selected),
                "basename": basename,
                "selectionBasis": selection_basis,
                "targetSha256": selected_hash,
                "candidateCount": len(ranked),
                "distinctCandidateHashes": len(hashes),
                "candidateHashGroups": [
                    {"sha256": digest, "paths": paths[:12]}
                    for digest, paths in sorted(hashes.items())
                ],
            }
        )

    payload = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "auditPath": str(audit_path),
        "root": str(root),
        "renderCriticalOnly": args.render_critical_only,
        "preferredDirectories": [str(item) for item in preferred_dirs],
        "maxonAssetCacheRoots": [
            str(item) for item in maxon_cache_roots
        ],
        "summary": {
            "missingPaths": len(missing_paths),
            "mappedPaths": len(mappings),
            "unresolvedPaths": len(unresolved),
            "exactLocalTranslations": sum(
                item["selectionBasis"] == "exact_local_path_translation"
                for item in mappings
            ),
            "exactLocalDirectoryTranslations": sum(
                item["selectionBasis"]
                == "exact_local_directory_translation"
                for item in mappings
            ),
            "preferredFolderSelections": sum(
                item["selectionBasis"]
                == "preferred_collected_texture_folder"
                for item in mappings
            ),
            "authoredPathTailRecoveries": sum(
                item["selectionBasis"]
                == "authored_path_tail_recovery"
                for item in mappings
            ),
            "basenameOnlySelections": sum(
                item["selectionBasis"] == "exact_basename_only"
                for item in mappings
            ),
            "exactMaxonAssetIds": sum(
                item["selectionBasis"] == "exact_maxon_asset_id"
                for item in mappings
            ),
            "ambiguousContentMappings": sum(
                item["distinctCandidateHashes"] > 1 for item in mappings
            ),
            "unsafeIndexedCandidatesExcluded": sum(
                len(items) for items in unsafe_by_basename.values()
            ),
        },
        "mappings": mappings,
        "unresolved": unresolved,
        "unresolvedCandidates": unresolved_candidates,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if hash_cache_path is not None:
        hash_cache_path.parent.mkdir(parents=True, exist_ok=True)
        hash_cache_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "updatedAt": utc_now(),
                    "files": hash_cache,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    print(json.dumps(payload["summary"], indent=2))
    print(output)


if __name__ == "__main__":
    main()
