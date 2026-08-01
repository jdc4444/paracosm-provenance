#!/usr/bin/env python3
"""Inventory reusable linked character and wardrobe assets across scenes.

This does not relink anything. It identifies where hair, skin, eye, shoe, and
the three wardrobe-variant texture families are already present and linked so
missing scenes can be repaired from evidence instead of filename guesswork.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "public" / "data" / "state.json"
DEPENDENCIES = ROOT / "data" / "c4d-dependency-export.json"
OUTPUT = ROOT / "data" / "c4d-shared-asset-library-20260726.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cut_number(cut_id: str) -> int:
    match = re.search(r"(\d+)$", cut_id)
    return int(match.group(1)) if match else -1


def wardrobe_variant(cut_id: str) -> str:
    number = cut_number(cut_id)
    if 1 <= number <= 3 or 37 <= number <= 56:
        return "grey"
    if 75 <= number <= 87:
        return "grey_colored"
    return "patchwork"


def semantic_class(owner: str, filename: str) -> str | None:
    text = f"{owner} {filename}".casefold()
    if re.search(r"(?:^|[^a-z])hair(?:[^a-z]|$)", text):
        return "hair"
    if "skin" in text or "metahuman_figure" in text:
        return "skin"
    if "eye" in text or "iris" in text:
        return "eyes"
    if "teeth" in text or "mouth" in text:
        return "teeth"
    if "shoe" in text or "boot" in text:
        return "shoes"
    if re.search(
        r"outfit|garment|wardrobe|dress|cloth|fabric|sweater|trouser|shirt",
        text,
    ):
        return "wardrobe"
    return None


def main() -> None:
    state = load(STATE)
    dependency_archive = load(DEPENDENCIES)
    project_deps = {
        str(item.get("projectPath") or ""): (
            (item.get("fullScene") or {}).get("dependencies") or []
        )
        for item in dependency_archive.get("projects", [])
        if item.get("projectPath")
    }
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for cut in state.get("cuts", []):
        if cut.get("isGap"):
            continue
        cut_id = str(cut.get("id") or "")
        project = str((cut.get("c4dLinkStatus") or {}).get("projectPath") or "")
        if not project:
            continue
        variant = wardrobe_variant(cut_id)
        for dependency in project_deps.get(project, []):
            if not dependency.get("exists"):
                continue
            filename = str(dependency.get("filename") or "")
            owner = str(
                dependency.get("ownerName")
                or dependency.get("ownerPath")
                or ""
            )
            owner_semantic = bool(
                re.search(
                    r"abby|character|metahuman|hair|skin|eye|iris|teeth|"
                    r"shoe|boot|outfit|garment|wardrobe|dress|sweater|"
                    r"trouser|shirt",
                    owner,
                    re.IGNORECASE,
                )
            )
            if not dependency.get("characterRelated") and not owner_semantic:
                continue
            asset_class = semantic_class(owner, filename)
            if asset_class is None:
                continue
            path = filename
            key = (variant, asset_class, path)
            record = records.setdefault(
                key,
                {
                    "wardrobeVariant": variant,
                    "assetClass": asset_class,
                    "path": path,
                    "assetName": dependency.get("assetName") or Path(path).name,
                    "owners": set(),
                    "projects": set(),
                    "cuts": set(),
                    "renderEnabledReferences": 0,
                },
            )
            if owner:
                record["owners"].add(owner)
            record["projects"].add(project)
            record["cuts"].add(cut_id)
            if dependency.get("renderEnabled") is not False:
                record["renderEnabledReferences"] += 1

    output_records = []
    for record in records.values():
        output_records.append(
            {
                **record,
                "owners": sorted(record["owners"]),
                "projects": sorted(record["projects"]),
                "cuts": sorted(record["cuts"]),
            }
        )
    output_records.sort(
        key=lambda item: (
            item["wardrobeVariant"],
            item["assetClass"],
            item["path"].casefold(),
        )
    )
    summary: dict[str, Any] = {}
    for variant in ("patchwork", "grey", "grey_colored"):
        variant_records = [
            item for item in output_records if item["wardrobeVariant"] == variant
        ]
        by_class = defaultdict(int)
        for item in variant_records:
            by_class[item["assetClass"]] += 1
        summary[variant] = {
            "linkedAssetPaths": len(variant_records),
            "byClass": dict(sorted(by_class.items())),
            "sourceProjects": len(
                {
                    project
                    for item in variant_records
                    for project in item["projects"]
                }
            ),
            "sourceCuts": len(
                {cut for item in variant_records for cut in item["cuts"]}
            ),
        }
    OUTPUT.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "authority": (
                    "Read-only cross-scene inventory of dependencies already "
                    "reported linked by Cinema 4D. Semantic grouping is a "
                    "repair index, not proof that two materials are interchangeable."
                ),
                "wardrobeRanges": {
                    "grey": ["CUT-001..CUT-003", "CUT-037..CUT-056"],
                    "grey_colored": ["CUT-075..CUT-087"],
                    "patchwork": ["all other character cuts"],
                },
                "summary": summary,
                "records": output_records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
