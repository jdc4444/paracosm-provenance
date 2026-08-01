#!/usr/bin/env python3
"""Build a deterministic Mainframe/Windows recovery plan from current cut state."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "public" / "data" / "state.json"
OUTPUT = ROOT / "data" / "mainframe-recovery-plan-20260729.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_for_cut(cut: dict[str, Any]) -> dict[str, Any]:
    verification = cut.get("c4dVerification") or {}
    link_status = cut.get("c4dLinkStatus") or {}
    return (
        verification.get("linkageAudit")
        or link_status.get("linkageAudit")
        or {}
    )


def normalized_source_path(value: str) -> tuple[str, str]:
    path = value.strip().replace("\\", "/")
    path = re.sub(r"^\./", "", path)
    mainframe_marker = "Mainframe/"
    if mainframe_marker.casefold() in path.casefold():
        index = path.casefold().index(mainframe_marker.casefold())
        return "mainframe", path[index + len(mainframe_marker) :]
    guassian_marker = "Guassian Dropbox/Steven Guas/Absolutely/"
    if guassian_marker.casefold() in path.casefold():
        index = path.casefold().index(guassian_marker.casefold())
        return "guassian_dropbox", path[index + len(guassian_marker) :]
    if path.startswith("/ASSETS/"):
        return "mainframe", path[1:]
    if path.startswith("ASSETS/"):
        return "mainframe", path
    if path.startswith("F:/"):
        return "windows_absolute", path
    if path.startswith("C:/") or path.startswith("/C:/"):
        return "windows_absolute", path.lstrip("/")
    if path.startswith("tex/") or path.startswith("../") or "/" not in path:
        return "project_relative", path
    return "unresolved_other", path


def is_literal_file_path(value: str) -> bool:
    """Reject human-readable sequence descriptions that are not real paths."""
    return " through " not in value.casefold()


def package_root(source: str, path: str) -> str:
    parts = [part for part in path.split("/") if part]
    folded = [part.casefold() for part in parts]
    greece_prefix = [
        "assets",
        "mocap",
        "absolutely",
        "greece",
    ]
    if folded[:4] == greece_prefix and len(parts) >= 5:
        root_length = 5
        if (
            folded[4] in {"teacup", "teacup-2_lookingfordirection_run-onbuttons"}
            and len(parts) >= 6
        ):
            root_length = 6
        return "/".join(parts[:root_length])
    if folded[:3] == ["assets", "gsg", "greyscalegorilla"]:
        return "/".join(parts[:5]) if len(parts) >= 5 else path
    if folded[:3] == ["assets", "textures", "lighting"]:
        return "/".join(parts[:6]) if len(parts) >= 6 else path
    if source == "guassian_dropbox":
        return "/".join(parts[:5]) if len(parts) >= 5 else path
    return "/".join(parts[:-1]) if len(parts) > 1 else path


def phase_for_cuts(cut_ids: set[str]) -> int:
    numbers = {
        int(cut_id.split("-")[-1])
        for cut_id in cut_ids
        if re.fullmatch(r"CUT-\d{3}", cut_id)
    }
    if numbers.intersection(range(47, 59)):
        return 1
    if numbers.intersection(range(74, 88)):
        return 2
    if numbers.intersection(range(19, 32)):
        return 3
    if numbers.intersection(range(4, 16)):
        return 4
    return 5


def main() -> None:
    state = load(STATE)
    packages: dict[
        tuple[str, str],
        dict[str, Any],
    ] = defaultdict(
        lambda: {
            "cutIds": set(),
            "requiredPaths": set(),
            "reportedRenderCriticalMissingFiles": 0,
        }
    )
    cuts_with_missing: set[str] = set()
    for cut in state.get("cuts") or []:
        cut_id = str(cut.get("id") or "")
        if not cut_id or cut.get("isGap"):
            continue
        audit = audit_for_cut(cut)
        reported_missing = int(
            audit.get("renderCriticalMissingFiles")
            or audit.get("renderCriticalUnresolvedFiles")
            or 0
        )
        missing_paths = {
            str(item)
            for item in audit.get("missingExactFiles") or []
            if str(item).strip()
        }
        if not reported_missing and not missing_paths:
            continue
        cuts_with_missing.add(cut_id)
        for required in missing_paths:
            if not is_literal_file_path(required):
                continue
            source, normalized = normalized_source_path(required)
            package = package_root(source, normalized)
            record = packages[(source, package)]
            record["cutIds"].add(cut_id)
            record["requiredPaths"].add(normalized)
            record["reportedRenderCriticalMissingFiles"] = max(
                int(record["reportedRenderCriticalMissingFiles"]),
                reported_missing,
            )

    records: list[dict[str, Any]] = []
    for (source, package), record in packages.items():
        cut_ids = set(record["cutIds"])
        required_paths = set(record["requiredPaths"])
        records.append(
            {
                "phase": phase_for_cuts(cut_ids),
                "source": source,
                "packageRoot": package,
                "cutIds": sorted(cut_ids),
                "cutCount": len(cut_ids),
                "requiredPathCount": len(required_paths),
                "reportedRenderCriticalMissingFiles": record[
                    "reportedRenderCriticalMissingFiles"
                ],
                "requiredPaths": sorted(required_paths),
                "transferRule": (
                    "Copy the exact package preserving relative paths, then "
                    "record SHA-256 for every transferred file. Do not replace "
                    "a required path with a same-basename file from another shot."
                ),
            }
        )
    records.sort(
        key=lambda item: (
            int(item["phase"]),
            -int(item["cutCount"]),
            -int(item["requiredPathCount"]),
            str(item["source"]),
            str(item["packageRoot"]).casefold(),
        )
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Current public/data/state.json missingExactFiles grouped into "
            "exact Windows/Mainframe transfer packages. This is a search and "
            "copy plan, not proof that any package exists or is correct."
        ),
        "statePath": str(STATE),
        "summary": {
            "cutsWithReportedMissingAssets": len(cuts_with_missing),
            "packageCount": len(records),
            "mainframePackageCount": sum(
                item["source"] == "mainframe" for item in records
            ),
            "guassianDropboxPackageCount": sum(
                item["source"] == "guassian_dropbox" for item in records
            ),
        },
        "packages": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(records)} exact recovery packages for "
        f"{len(cuts_with_missing)} cuts to {OUTPUT}"
    )


if __name__ == "__main__":
    main()
