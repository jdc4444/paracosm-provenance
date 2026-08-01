#!/usr/bin/env python3
"""Find source-level candidates for generic/offline C4D cache paths.

Exact basename/path recovery is handled by ``resolve_c4d_dependencies.py``.
This second pass is deliberately conservative: it finds semantically related
Dropbox source caches for the remaining render-critical dependencies, but it
never labels them as a valid relink until topology, frame range, and a proof
render have been checked.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
RECOVERY_PATH = APP_ROOT / "data" / "c4d-dependency-recovery.json"
OUTPUT_PATH = APP_ROOT / "data" / "c4d-semantic-recovery.json"
ABSOLUTELY = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
SOURCE_EXTENSIONS = {".abc", ".fbx", ".rs", ".c4d", ".obj", ".usd", ".usdz"}
STOPWORDS = {
    "abc",
    "absolutely",
    "alembic",
    "assets",
    "cache",
    "greece",
    "mainframe",
    "mocap",
    "surface",
    "subdivision",
}


def tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if len(token) >= 3 and token not in STOPWORDS
    }


def semantic_classes(record: dict[str, Any]) -> set[str]:
    value = " ".join(
        [
            str(record.get("requiredPath") or ""),
            str(record.get("basename") or ""),
            *[str(item) for item in record.get("owners", [])],
        ]
    ).casefold()
    classes = set()
    rules = {
        "hair": r"hair|rope",
        "character": r"abby|bodymesh|facemesh|headskm|metahuman",
        "wardrobe": r"cloth|garment|outfit|wardrobe",
        "teacup": r"teacup|cup",
        "wallpaper": r"wallpaper",
        "fracture": r"fracture|voronoi",
        "splash": r"splash|crown",
        "cupboard": r"cupboard",
    }
    for label, pattern in rules.items():
        if re.search(pattern, value):
            classes.add(label)
    return classes


def candidate_classes(path: Path) -> set[str]:
    value = str(path).casefold()
    result = set()
    rules = {
        "hair": r"hair|rope",
        "character": r"abby|body|face|metahuman|character",
        "wardrobe": r"cloth|garment|outfit|wardrobe",
        "teacup": r"teacup|cup",
        "wallpaper": r"wallpaper",
        "fracture": r"fracture|voronoi",
        "splash": r"splash|crown",
        "cupboard": r"cupboard",
    }
    for label, pattern in rules.items():
        if re.search(pattern, value):
            result.add(label)
    return result


def main() -> None:
    recovery = json.loads(RECOVERY_PATH.read_text(encoding="utf-8"))
    unresolved = [
        item
        for item in recovery.get("uniqueDependencies", [])
        if item.get("renderCritical") and item.get("status") == "unresolved"
    ]
    candidates = [
        path
        for path in ABSOLUTELY.rglob("*")
        if path.is_file() and path.suffix.casefold() in SOURCE_EXTENSIONS
    ]
    candidate_metadata = [
        (
            path,
            tokens(str(path)),
            candidate_classes(path),
            path.stat().st_size,
            datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(),
        )
        for path in candidates
    ]

    records = []
    cuts_with_candidates: set[str] = set()
    for record in unresolved:
        required_tokens = tokens(str(record.get("requiredPath") or ""))
        required_classes = semantic_classes(record)
        ranked = []
        for path, path_tokens, classes, size, modified_at in candidate_metadata:
            class_overlap = required_classes & classes
            token_overlap = required_tokens & path_tokens
            # A named semantic role is the minimum bar. Generic folder tokens
            # such as "models" are not evidence that two caches are
            # interchangeable (and previously produced false Crown Splash
            # suggestions). Unclassified records can still use token overlap,
            # but classified assets must share at least one actual role.
            if required_classes and not class_overlap:
                continue
            if not class_overlap and not token_overlap:
                continue
            score = (
                len(class_overlap) * 20
                + len(token_overlap) * 5
                + int(path.suffix.casefold() == ".abc") * 2
            )
            # Generic Subdivision_Surface caches are only useful when the
            # source candidate shares a semantic role such as hair.
            if str(record.get("basename") or "").casefold().startswith(
                "subdivision_surface"
            ) and not class_overlap:
                continue
            ranked.append(
                {
                    "path": str(path),
                    "score": score,
                    "semanticClasses": sorted(class_overlap),
                    "matchingTokens": sorted(token_overlap),
                    "size": size,
                    "modifiedAt": modified_at,
                    "status": "semantic_candidate_unverified",
                }
            )
        ranked.sort(
            key=lambda item: (
                -int(item["score"]),
                -int(item["size"]),
                str(item["path"]),
            )
        )
        top = ranked[:12]
        if top:
            cuts_with_candidates.update(str(item) for item in record.get("cuts", []))
        records.append(
            {
                "requiredPath": record.get("requiredPath"),
                "basename": record.get("basename"),
                "cuts": record.get("cuts", []),
                "projects": record.get("projects", []),
                "owners": record.get("owners", []),
                "semanticClasses": sorted(required_classes),
                "status": (
                    "semantic_candidates_found"
                    if top
                    else "no_semantic_candidate"
                ),
                "validationRequired": [
                    "matching topology",
                    "matching animation/frame range",
                    "matching transform/scale",
                    "canonical camera proof",
                ],
                "candidates": top,
            }
        )

    output = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Conservative semantic source search. Candidates are never valid "
            "relinks without topology/frame-range checks and a matching proof render."
        ),
        "summary": {
            "renderCriticalUnresolvedPaths": len(unresolved),
            "pathsWithSemanticCandidates": sum(
                item["status"] == "semantic_candidates_found"
                for item in records
            ),
            "pathsWithoutSemanticCandidates": sum(
                item["status"] == "no_semantic_candidate"
                for item in records
            ),
            "affectedCutsWithCandidates": len(cuts_with_candidates),
        },
        "records": records,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))


if __name__ == "__main__":
    main()
