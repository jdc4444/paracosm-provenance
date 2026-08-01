"""Shared safety checks for read-only Cinema 4D dependency relinks.

Relink manifests are evidence, not a license to use every same-basename file
found in the project tree.  Quarantined and explicitly rejected candidates
must never be injected into a scene, even for a diagnostic render.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def normalized_path_parts(value: str) -> list[str]:
    return [
        part.casefold().replace("-", "_")
        for part in PurePosixPath(str(value).replace("\\", "/")).parts
        if part not in {"", "/"}
    ]


def unsafe_relink_target_reason(value: str) -> str | None:
    """Return the explicit quarantine/rejection marker in ``value``."""

    for part in normalized_path_parts(value):
        if part == "quarantine" or part.startswith("quarantine_"):
            return "quarantined_target"
        if part.endswith("_quarantine"):
            return "quarantined_target"
        if "rejected" in part and "unproven" in part:
            return "rejected_unproven_target"
    return None


def _contains_contiguous_parts(
    haystack: list[str], needle: list[str]
) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[index : index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


def basename_only_semantics_match(
    required_path: str, target_path: str
) -> bool:
    """Require path-level identity for a basename-only recovery.

    A unique basename is not shot provenance.  In particular, animation
    caches such as ``Subdivision_Surface.abc`` occur in many Paracosm shots.
    A basename-only mapping is usable only when the recovered target retains
    the authored Mainframe-relative path, or at least three trailing path
    components (parent, asset family, and basename) agree exactly.
    """

    required = normalized_path_parts(required_path)
    target = normalized_path_parts(target_path)
    if not required or not target:
        return False

    if "mainframe" in required:
        authored_tail = required[required.index("mainframe") + 1 :]
        if len(authored_tail) >= 3:
            return _contains_contiguous_parts(target, authored_tail)

    if len(required) < 3:
        return False
    return target[-3:] == required[-3:]


def unsafe_manifest_mapping_reason(item: dict[str, Any]) -> str | None:
    target_path = str(item.get("targetPath") or "")
    target_reason = unsafe_relink_target_reason(target_path)
    if target_reason:
        return target_reason
    required_path = str(item.get("requiredPath") or "")
    selection_basis = str(item.get("selectionBasis") or "")
    shot_cache = PurePosixPath(
        required_path.replace("\\", "/")
    ).suffix.casefold() in {".abc", ".rs"}
    if selection_basis == "exact_basename_only" or (
        selection_basis == "preferred_collected_texture_folder"
        and shot_cache
    ):
        if not basename_only_semantics_match(required_path, target_path):
            return "basename_only_path_semantics_mismatch"
    return None


def safe_manifest_mappings(
    manifest: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Return usable mappings and every rejected manifest record."""

    mappings: dict[str, str] = {}
    violations: list[dict[str, str]] = []
    for item in manifest.get("mappings", []):
        required_path = str(item.get("requiredPath") or "")
        target_path = str(item.get("targetPath") or "")
        if not required_path or not target_path:
            continue
        reason = unsafe_manifest_mapping_reason(item)
        if reason:
            violations.append(
                {
                    "requiredPath": required_path,
                    "targetPath": target_path,
                    "reason": reason,
                }
            )
            continue
        mappings[required_path] = target_path
    return mappings, violations
