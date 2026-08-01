#!/usr/bin/env python3
"""Resolve missing C4D dependencies against the shared Absolutely file tree.

This is a read-only resolver. It produces evidence and candidate rankings but
does not relink or save any Cinema 4D document.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPENDENCIES = APP_ROOT / "data" / "c4d-dependency-export.json"
DEFAULT_STATE = APP_ROOT / "public" / "data" / "state.json"
DEFAULT_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
DEFAULT_OUTPUT = APP_ROOT / "data" / "c4d-dependency-recovery.json"
VERSION_TOKEN = re.compile(r"(?i)(?:^|[_ .-])v\d+(?=$|[_ .-])")
NON_ALNUM = re.compile(r"[^a-z0-9]+")
UDIM_TOKEN = re.compile(r"(?i)<udim>")
UDIM_TILE = re.compile(r"1\d{3}(?=\.[^.]+$)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_parts(value: str) -> list[str]:
    text = value.replace("\\", "/").strip()
    text = re.sub(r"^\./", "", text)
    text = re.sub(r"^[a-zA-Z]:/", "", text)
    parts = [part.casefold() for part in PurePosixPath(text).parts if part]
    if "absolutely" in parts:
        parts = parts[parts.index("absolutely") + 1 :]
    return parts


def normalized_stem(value: str) -> str:
    stem = Path(value).stem.casefold()
    stem = VERSION_TOKEN.sub(" ", stem)
    stem = re.sub(r"(?i)(?:[._ -])copy(?:[._ -]?\d+)?$", "", stem)
    stem = re.sub(r"(?i)(?:[._ -])\d+$", "", stem)
    return NON_ALNUM.sub("", stem)


def common_suffix_count(left: list[str], right: list[str]) -> int:
    count = 0
    for a, b in zip(reversed(left), reversed(right)):
        if a != b:
            break
        count += 1
    return count


def index_files(
    root: Path,
) -> tuple[
    list[Path],
    dict[str, list[Path]],
    dict[str, list[Path]],
    dict[str, list[Path]],
]:
    result = subprocess.run(
        ["rg", "--files", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    files = [Path(line) for line in result.stdout.splitlines() if line]
    by_basename: dict[str, list[Path]] = defaultdict(list)
    by_stem: dict[str, list[Path]] = defaultdict(list)
    by_udim_template: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        basename = path.name.casefold()
        by_basename[basename].append(path)
        udim_template = UDIM_TILE.sub("<udim>", basename)
        if udim_template != basename:
            by_udim_template[udim_template].append(path)
        key = normalized_stem(path.name)
        if key:
            by_stem[key].append(path)
    return files, by_basename, by_stem, by_udim_template


def cuts_by_project(state: dict) -> dict[str, list[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for cut in state.get("cuts", []):
        for node in cut.get("lineage", []):
            if node.get("kind") != "cinema4d":
                continue
            project = node.get("projectPath") or node.get("path")
            if project:
                result[str(project)].add(cut["id"])
    return {key: sorted(value) for key, value in result.items()}


def candidate_payload(path: Path, required: str) -> dict[str, object]:
    required_parts = normalized_parts(required)
    candidate_parts = normalized_parts(str(path))
    suffix = common_suffix_count(required_parts, candidate_parts)
    try:
        stat = path.stat()
        size = stat.st_size
        modified = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        size = None
        modified = None
    return {
        "path": str(path),
        "commonSuffixSegments": suffix,
        "exactRelativeSuffix": suffix == len(required_parts),
        "size": size,
        "modifiedAt": modified,
    }


def ranked_candidates(
    required: str,
    by_basename: dict[str, list[Path]],
    by_stem: dict[str, list[Path]],
    by_udim_template: dict[str, list[Path]],
) -> tuple[str, list[dict[str, object]]]:
    basename = Path(required.replace("\\", "/")).name.casefold()
    exact = by_basename.get(basename, [])
    kind = "exact_basename"
    candidates = exact
    udim_sequence = False
    if not candidates and UDIM_TOKEN.search(basename):
        kind = "udim_sequence"
        candidates = by_udim_template.get(basename, [])
        udim_sequence = bool(candidates)
    if not candidates:
        kind = "normalized_name"
        candidates = by_stem.get(normalized_stem(basename), [])
    payloads = [candidate_payload(path, required) for path in candidates]
    if udim_sequence:
        required_parts = normalized_parts(required)
        for payload in payloads:
            candidate = Path(str(payload["path"]))
            candidate_parts = normalized_parts(str(candidate))
            directory_suffix = common_suffix_count(
                required_parts[:-1], candidate_parts[:-1]
            )
            payload["udimSequence"] = True
            payload["udimTemplatePath"] = str(
                candidate.parent
                / Path(required.replace("\\", "/")).name
            )
            payload["exactRelativeSuffix"] = (
                directory_suffix == len(required_parts[:-1])
            )
            payload["commonSuffixSegments"] = directory_suffix
    payloads.sort(
        key=lambda item: (
            bool(item["exactRelativeSuffix"]),
            int(item["commonSuffixSegments"]),
            int(item["size"] or 0),
        ),
        reverse=True,
    )
    if not payloads:
        return "unresolved", []
    if payloads[0]["exactRelativeSuffix"]:
        return "recovered_exact_path", payloads[:12]
    if kind in ("exact_basename", "udim_sequence"):
        return "candidate_exact_basename", payloads[:12]
    return "candidate_normalized_name", payloads[:12]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dependencies", type=Path, default=DEFAULT_DEPENDENCIES)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    dependencies = json.loads(args.dependencies.read_text(encoding="utf-8"))
    state = json.loads(args.state.read_text(encoding="utf-8"))
    _, by_basename, by_stem, by_udim_template = index_files(args.root)
    project_cuts = cuts_by_project(state)

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for project in dependencies.get("projects", []):
        project_path = str(project.get("projectPath") or "")
        for dependency in project.get("fullScene", {}).get("dependencies", []):
            if dependency.get("exists"):
                continue
            filename = str(dependency.get("filename") or "")
            if not filename:
                continue
            key = (project_path, filename)
            record = grouped.setdefault(
                key,
                {
                    "projectPath": project_path,
                    "cuts": project_cuts.get(project_path, []),
                    "requiredPath": filename,
                    "basename": Path(filename.replace("\\", "/")).name,
                    "categories": set(),
                    "owners": set(),
                    "ownerPaths": set(),
                    "characterRelated": False,
                    "renderCritical": False,
                    "referenceCount": 0,
                },
            )
            record["categories"].add(dependency.get("category") or "other")
            record["owners"].add(dependency.get("ownerName") or "Unknown")
            record["ownerPaths"].add(dependency.get("ownerPath") or "")
            record["characterRelated"] = bool(
                record["characterRelated"] or dependency.get("characterRelated")
            )
            record["renderCritical"] = bool(
                record["renderCritical"]
                or dependency.get("renderEnabled") is not False
            )
            record["referenceCount"] += 1

    records = []
    for record in grouped.values():
        status, candidates = ranked_candidates(
            record["requiredPath"],
            by_basename,
            by_stem,
            by_udim_template,
        )
        records.append(
            {
                **record,
                "categories": sorted(record["categories"]),
                "owners": sorted(record["owners"]),
                "ownerPaths": sorted(item for item in record["ownerPaths"] if item),
                "status": status,
                "candidates": candidates,
            }
        )
    records.sort(
        key=lambda item: (
            not item["renderCritical"],
            not item["characterRelated"],
            item["status"],
            item["projectPath"],
            item["requiredPath"],
        )
    )

    unique_required = {}
    for record in records:
        key = record["requiredPath"].casefold()
        summary = unique_required.setdefault(
            key,
            {
                "requiredPath": record["requiredPath"],
                "basename": record["basename"],
                "projects": set(),
                "cuts": set(),
                "categories": set(),
                "owners": set(),
                "characterRelated": False,
                "renderCritical": False,
                "referenceCount": 0,
                "status": record["status"],
                "candidates": record["candidates"],
            },
        )
        summary["projects"].add(record["projectPath"])
        summary["cuts"].update(record["cuts"])
        summary["categories"].update(record["categories"])
        summary["owners"].update(record["owners"])
        summary["characterRelated"] = bool(
            summary["characterRelated"] or record["characterRelated"]
        )
        summary["renderCritical"] = bool(
            summary["renderCritical"] or record["renderCritical"]
        )
        summary["referenceCount"] += record["referenceCount"]
        if (
            record["status"] == "recovered_exact_path"
            or summary["status"] == "unresolved"
        ):
            summary["status"] = record["status"]
            summary["candidates"] = record["candidates"]

    unique_records = []
    for record in unique_required.values():
        unique_records.append(
            {
                **record,
                "projects": sorted(record["projects"]),
                "cuts": sorted(record["cuts"]),
                "categories": sorted(record["categories"]),
                "owners": sorted(record["owners"]),
            }
        )
    unique_records.sort(
        key=lambda item: (
            not item["renderCritical"],
            not item["characterRelated"],
            item["status"],
            item["requiredPath"],
        )
    )

    status_counts = defaultdict(int)
    critical_status_counts = defaultdict(int)
    for record in unique_records:
        status_counts[record["status"]] += 1
        if record["renderCritical"]:
            critical_status_counts[record["status"]] += 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "method": (
            "Read-only exact relative-path, exact-basename, then normalized-name "
            "matching against the shared Absolutely file inventory"
        ),
        "root": str(args.root),
        "summary": {
            "projectDependencyRecords": len(records),
            "uniqueMissingPaths": len(unique_records),
            "renderCriticalUniquePaths": sum(
                1 for item in unique_records if item["renderCritical"]
            ),
            "characterRelatedUniquePaths": sum(
                1 for item in unique_records if item["characterRelated"]
            ),
            "byStatus": dict(sorted(status_counts.items())),
            "renderCriticalByStatus": dict(
                sorted(critical_status_counts.items())
            ),
        },
        "uniqueDependencies": unique_records,
        "projectDependencies": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
