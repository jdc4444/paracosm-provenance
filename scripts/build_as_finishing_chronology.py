#!/usr/bin/env python3
"""Inventory AS Finishing projects, C4D backups, and batch-render logs."""

from __future__ import annotations

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AS_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
    "Absolutely/AS/0 Finishing"
)
LOCAL_DROPBOX_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder"
)
BACKUP_PATTERN = re.compile(
    r"^(?P<source>.+\.c4d)@(?P<timestamp>\d{8}_\d{6})$",
    re.IGNORECASE,
)
CHAPTERS = ("01 ND", "02 NTH", "03 TH", "04 NA", "05 GG", "06 IJDKYY")
CHAPTER_ALIASES = {
    "01 ND": "01 ND",
    "02 NTH": "02 NTH",
    "03 TH": "03 TH",
    "04 NA": "04 NA",
    "05 GG": "05 GG",
    "06 IJDKYY": "06 IJDKYY",
}
PREFIX_CHAPTERS = {
    "1": "01 ND",
    "2": "02 NTH",
    "3": "03 TH",
    "4": "04 NA",
    "5": "05 GG",
    "6": "06 IJDKYY",
}
EXCLUDED_DIRECTORIES = {".git", ".cache", "node_modules", "__pycache__"}
RELEVANT_WINDOWS = (
    ("ND final CU revision era", "01 ND", "2026-02-24", "2026-03-01"),
    ("NTH February source era", "02 NTH", "2026-02-12", "2026-02-19"),
    ("NTH walk/run render era", "02 NTH", "2026-03-19", "2026-03-22"),
    ("NTH late finishing era", "02 NTH", "2026-04-28", "2026-05-08"),
    ("TH final horses/freezer era", "03 TH", "2026-04-16", "2026-05-10"),
    ("NA March render era", "04 NA", "2026-03-01", "2026-03-17"),
    ("NA April/May LayDown era", "04 NA", "2026-04-16", "2026-05-02"),
    (
        "IJDKYY carousel revision era",
        "06 IJDKYY",
        "2026-03-11",
        "2026-03-15",
    ),
    (
        "IJDKYY final finishing era",
        "06 IJDKYY",
        "2026-04-06",
        "2026-04-22",
    ),
)


def local_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).astimezone().isoformat()


def utc_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def chapter_for(
    relative: Path, project_filename: str | None = None
) -> str | None:
    direct = next((part for part in relative.parts if part in CHAPTERS), None)
    if direct:
        return CHAPTER_ALIASES[direct]
    for raw_candidate in (project_filename, relative.name):
        if not raw_candidate:
            continue
        candidate = raw_candidate.lstrip().casefold()
        if candidate.startswith("log_"):
            candidate = candidate[4:].lstrip()
        match = re.match(r"0?([1-6])(?:[a-z_ ]|$)", candidate)
        if match:
            return PREFIX_CHAPTERS.get(match.group(1))
    return None


def windows_for(chapter: str | None, modified_date: str) -> list[str]:
    return [
        label
        for label, window_chapter, start, end in RELEVANT_WINDOWS
        if chapter == window_chapter and start <= modified_date < end
    ]


def iter_files(root: Path):
    for directory, child_directories, filenames in os.walk(root):
        child_directories[:] = [
            item
            for item in child_directories
            if item not in EXCLUDED_DIRECTORIES
        ]
        for filename in filenames:
            yield Path(directory) / filename


def normalize_windows_path(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"/+", "/", value.replace("\\", "/"))
    prefixes = (
        "F:/Guassian Dropbox/Steven Guas",
        "D:/Guassian Dropbox/Steven Guas",
        "C:/Users/sguas/Guassian Dropbox/Steven Guas",
    )
    for prefix in prefixes:
        if normalized.casefold().startswith(prefix.casefold()):
            suffix = normalized[len(prefix) :].lstrip("/")
            return str(LOCAL_DROPBOX_ROOT / suffix)
    finishing_markers = (
        "/Absolutely/AS/0 Finishing/",
        "/Projects/Absolutely/AS/0 Finishing/",
    )
    for marker in finishing_markers:
        marker_index = normalized.casefold().find(marker.casefold())
        if marker_index >= 0:
            suffix = normalized[
                marker_index + len(marker) - len("AS/0 Finishing/")
            :]
            return str(LOCAL_DROPBOX_ROOT / "Absolutely" / suffix)
    return value


def text(node: ET.Element, selector: str) -> str | None:
    found = node.find(selector)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def integer(node: ET.Element, selector: str) -> int | None:
    value = text(node, selector)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def rendered_image_basename(node: ET.Element) -> str | None:
    """Extract the emitted filename from a Batch Render imageinfo node."""
    value = (node.text or "").strip()
    if not value:
        return None
    match = re.match(r"^\d{2}:\d{2}:\d{2}\s+(.+)$", value)
    rendered_path = match.group(1) if match else value
    basename = re.split(r"[\\/]", rendered_path)[-1].strip()
    return basename or None


def rendered_image_prefix(basename: str) -> str:
    """Return the stable filename prefix before a terminal frame number."""
    return re.sub(r"-?\d+$", "", Path(basename).stem)


def parse_render_log(path: Path, relative: Path) -> dict[str, Any]:
    stat = path.stat()
    modified_at = local_timestamp(stat.st_mtime)
    record: dict[str, Any] = {
        "path": str(path.resolve()),
        "relativePath": str(relative),
        "name": path.name,
        "chapter": chapter_for(relative),
        "sizeBytes": stat.st_size,
        "modifiedAt": modified_at,
        "modifiedAtUtc": utc_timestamp(stat.st_mtime),
        "modifiedDate": modified_at[:10],
        "relevantWindowLabels": windows_for(
            chapter_for(relative), modified_at[:10]
        ),
        "parseStatus": "unparsed",
    }
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError, UnicodeError) as error:
        record["parseStatus"] = "error"
        record["parseError"] = str(error)
        return record
    if root.tag.casefold() != "batchrender":
        record["parseStatus"] = "not_batchrender"
        return record

    file_info = root.find("./fileinfo")
    render_data = root.find("./fileinfo/renderdatainfo")
    engine = root.find("./fileinfo/renderdatainfo/renderengine/engine")
    image_nodes = root.findall("./renderinfo/imageinfo")
    error_nodes = root.findall("./renderinfo/errorinfo")
    image_basenames = [
        basename
        for item in image_nodes
        if (basename := rendered_image_basename(item)) is not None
    ]
    image_prefixes = sorted(
        {
            rendered_image_prefix(basename)
            for basename in image_basenames
        }
    )
    image_samples = []
    if image_basenames:
        for index in (0, len(image_basenames) // 2, len(image_basenames) - 1):
            basename = image_basenames[index]
            if basename not in image_samples:
                image_samples.append(basename)
    frames = [
        int(item.attrib["frame"])
        for item in image_nodes
        if item.attrib.get("frame", "").lstrip("-").isdigit()
    ]
    project_filename = (
        text(file_info, "./filename") if file_info is not None else None
    )
    inferred_chapter = chapter_for(relative, project_filename)
    record["chapter"] = inferred_chapter
    record["relevantWindowLabels"] = windows_for(
        inferred_chapter, modified_at[:10]
    )
    project_directory = (
        text(file_info, "./filepath") if file_info is not None else None
    )
    output_path = (
        text(render_data, "./saveinfo/imagepath")
        if render_data is not None
        else None
    )
    record.update(
        {
            "parseStatus": "parsed",
            "projectFilename": project_filename,
            "projectDirectoryOriginal": project_directory,
            "projectDirectoryNormalized": normalize_windows_path(
                project_directory
            ),
            "renderSettings": (
                text(render_data, "./rendersettings")
                if render_data is not None
                else None
            ),
            "take": (
                text(render_data, "./take")
                if render_data is not None
                else None
            ),
            "camera": (
                text(render_data, "./camera")
                if render_data is not None
                else None
            ),
            "fps": (
                integer(render_data, "./fps")
                if render_data is not None
                else None
            ),
            "frameFrom": (
                integer(render_data, "./from")
                if render_data is not None
                else None
            ),
            "frameTo": (
                integer(render_data, "./to")
                if render_data is not None
                else None
            ),
            "frameStep": (
                integer(render_data, "./steps")
                if render_data is not None
                else None
            ),
            "width": (
                integer(render_data, "./width")
                if render_data is not None
                else None
            ),
            "height": (
                integer(render_data, "./height")
                if render_data is not None
                else None
            ),
            "outputPathOriginal": output_path,
            "outputPathNormalized": normalize_windows_path(output_path),
            "renderEngineId": engine.attrib.get("id") if engine is not None else None,
            "renderEngineName": (
                engine.attrib.get("name") if engine is not None else None
            ),
            "completedFrameCount": len(frames),
            "completedFrameMin": min(frames) if frames else None,
            "completedFrameMax": max(frames) if frames else None,
            "completedImageBasenamePrefixes": image_prefixes,
            "completedImageBasenameSamples": image_samples,
            "errorCount": len(error_nodes),
            "errors": [
                (item.text or "").strip()
                for item in error_nodes
                if (item.text or "").strip()
            ],
            "c4dVersion": text(root, "./environmentinfo/c4dinfo/c4dversion"),
            "machineName": text(
                root, "./environmentinfo/machineinfo/machinename"
            ),
        }
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "c4d-clean-manifest-20260726.json",
    )
    args = parser.parse_args()

    root = AS_ROOT.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cuts_by_project: dict[str, list[str]] = defaultdict(list)
    cuts_by_render: list[tuple[str, str]] = []
    for item in manifest.get("records", []):
        project = item.get("sourceProjectPath")
        render = item.get("sourceRenderPath")
        cut_id = item.get("cutId")
        if project and cut_id:
            cuts_by_project[str(Path(project).resolve())].append(cut_id)
        if render and cut_id:
            cuts_by_render.append((cut_id, str(render)))
    render_basenames: dict[str, set[str]] = {}
    for _, render_path in cuts_by_render:
        if render_path in render_basenames:
            continue
        directory = Path(render_path)
        try:
            render_basenames[render_path] = {
                candidate.name
                for candidate in directory.iterdir()
                if candidate.is_file()
            }
        except OSError:
            render_basenames[render_path] = set()

    projects = []
    logs = []
    text_support = []
    for path in iter_files(root):
        relative = path.relative_to(root)
        lower_name = path.name.casefold()
        backup_match = BACKUP_PATTERN.match(path.name)
        if lower_name.endswith(".c4d") or backup_match:
            stat = path.stat()
            modified_at = local_timestamp(stat.st_mtime)
            file_kind = "backup_snapshot" if backup_match else "primary_project"
            logical_name = (
                backup_match.group("source") if backup_match else path.name
            )
            projects.append(
                {
                    "fileKind": file_kind,
                    "path": str(path.resolve()),
                    "relativePath": str(relative),
                    "name": path.name,
                    "logicalProjectName": logical_name,
                    "backupSnapshotLabel": (
                        backup_match.group("timestamp")
                        if backup_match
                        else None
                    ),
                    "chapter": chapter_for(relative),
                    "sizeBytes": stat.st_size,
                    "allocatedBytes": stat.st_blocks * 512,
                    "modifiedAt": modified_at,
                    "modifiedAtUtc": utc_timestamp(stat.st_mtime),
                    "modifiedDate": modified_at[:10],
                    "modifiedMonth": modified_at[:7],
                    "codexGenerated": "_codex_" in str(relative).casefold(),
                    "readable": os.access(path, os.R_OK),
                    "empty": stat.st_size == 0,
                    "selectedCutIds": cuts_by_project.get(
                        str(path.resolve()), []
                    ),
                    "relevantWindowLabels": windows_for(
                        chapter_for(relative), modified_at[:10]
                    ),
                }
            )
        elif lower_name.endswith(".xml"):
            logs.append(parse_render_log(path, relative))
        elif lower_name.endswith(".txt"):
            stat = path.stat()
            modified_at = local_timestamp(stat.st_mtime)
            text_support.append(
                {
                    "path": str(path.resolve()),
                    "relativePath": str(relative),
                    "name": path.name,
                    "chapter": chapter_for(relative),
                    "sizeBytes": stat.st_size,
                    "modifiedAt": modified_at,
                    "modifiedAtUtc": utc_timestamp(stat.st_mtime),
                    "modifiedDate": modified_at[:10],
                    "relevantWindowLabels": windows_for(
                        chapter_for(relative), modified_at[:10]
                    ),
                }
            )

    projects.sort(key=lambda item: item["path"].casefold())
    logs.sort(key=lambda item: item["path"].casefold())
    text_support.sort(key=lambda item: item["path"].casefold())

    projects_by_name: dict[tuple[str | None, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for item in projects:
        projects_by_name[
            (item["chapter"], item["logicalProjectName"].casefold())
        ].append(item)

    for item in logs:
        key = (
            item.get("chapter"),
            (item.get("projectFilename") or "").casefold(),
        )
        candidates = projects_by_name.get(key, [])
        item["projectCandidatePaths"] = [entry["path"] for entry in candidates]
        preceding = [
            entry
            for entry in candidates
            if entry["modifiedAtUtc"] <= item["modifiedAtUtc"]
        ]
        following = [
            entry
            for entry in candidates
            if entry["modifiedAtUtc"] > item["modifiedAtUtc"]
        ]
        item["nearestPrecedingProjectPath"] = (
            max(preceding, key=lambda entry: entry["modifiedAtUtc"])["path"]
            if preceding
            else None
        )
        item["nearestFollowingProjectPath"] = (
            min(following, key=lambda entry: entry["modifiedAtUtc"])["path"]
            if following
            else None
        )
        nearest = (
            min(
                candidates,
                key=lambda entry: abs(
                    datetime.fromisoformat(entry["modifiedAtUtc"]).timestamp()
                    - datetime.fromisoformat(item["modifiedAtUtc"]).timestamp()
                ),
            )
            if candidates
            else None
        )
        item["nearestProjectStatePath"] = (
            nearest["path"] if nearest else None
        )
        item["nearestProjectStateDeltaSeconds"] = (
            round(
                datetime.fromisoformat(nearest["modifiedAtUtc"]).timestamp()
                - datetime.fromisoformat(item["modifiedAtUtc"]).timestamp()
            )
            if nearest
            else None
        )
        output = item.get("outputPathNormalized")
        emitted_prefixes = [
            str(prefix)
            for prefix in item.get("completedImageBasenamePrefixes", [])
            if prefix
        ]
        prefix_patterns = [
            re.compile(
                rf"^{re.escape(prefix)}\d+\.[^.]+$",
                re.IGNORECASE,
            )
            for prefix in emitted_prefixes
        ]
        prefix_matches = {
            cut_id
            for cut_id, render_path in cuts_by_render
            if prefix_patterns
            and any(
                pattern.match(basename)
                for basename in render_basenames.get(render_path, set())
                for pattern in prefix_patterns
            )
        }
        output_path_matches = {
            cut_id
            for cut_id, render_path in cuts_by_render
            if output
            and (
                output.casefold().startswith(render_path.casefold())
                or render_path.casefold().startswith(output.casefold())
            )
        }
        item["matchingCutIds"] = sorted(
            prefix_matches or output_path_matches
        )
        item["cutMatchingRule"] = (
            "exact_emitted_filename_prefix_across_canonical_render_directories"
            if prefix_matches
            else "render_output_path"
            if output_path_matches
            else "unmatched"
        )
        item["renderOutputRelocated"] = bool(
            prefix_matches and not prefix_matches.issubset(output_path_matches)
        )

    project_kind_counts = Counter(item["fileKind"] for item in projects)
    chapter_counts = Counter(
        item["chapter"] for item in projects if item["chapter"]
    )
    parsed_logs = [item for item in logs if item["parseStatus"] == "parsed"]
    relevant_windows = []
    for label, chapter, start, end in RELEVANT_WINDOWS:
        matching_projects = [
            item
            for item in projects
            if item["chapter"] == chapter
            and start <= item["modifiedDate"] < end
            and not item["codexGenerated"]
        ]
        matching_logs = [
            item
            for item in logs
            if item["chapter"] == chapter
            and start <= item["modifiedDate"] < end
        ]
        relevant_windows.append(
            {
                "label": label,
                "chapter": chapter,
                "startInclusive": start,
                "endExclusive": end,
                "primaryProjectCount": sum(
                    item["fileKind"] == "primary_project"
                    for item in matching_projects
                ),
                "backupSnapshotCount": sum(
                    item["fileKind"] == "backup_snapshot"
                    for item in matching_projects
                ),
                "renderLogCount": len(matching_logs),
                "projectPaths": [item["path"] for item in matching_projects],
                "renderLogPaths": [item["path"] for item in matching_logs],
            }
        )

    cut_lineage_leads: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in logs:
        for cut_id in item.get("matchingCutIds", []):
            delta = item.get("nearestProjectStateDeltaSeconds")
            cut_lineage_leads[cut_id].append(
                {
                    "renderLogPath": item["path"],
                    "renderLogModifiedAt": item["modifiedAt"],
                    "projectFilename": item.get("projectFilename"),
                    "take": item.get("take"),
                    "camera": item.get("camera"),
                    "frameFrom": item.get("frameFrom"),
                    "frameTo": item.get("frameTo"),
                    "fps": item.get("fps"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "outputPath": item.get("outputPathNormalized"),
                    "renderEngineName": item.get("renderEngineName"),
                    "completedFrameCount": item.get("completedFrameCount"),
                    "errorCount": item.get("errorCount"),
                    "projectCandidatePaths": item.get(
                        "projectCandidatePaths", []
                    ),
                    "nearestPrecedingProjectPath": item.get(
                        "nearestPrecedingProjectPath"
                    ),
                    "nearestFollowingProjectPath": item.get(
                        "nearestFollowingProjectPath"
                    ),
                    "nearestProjectStatePath": item.get(
                        "nearestProjectStatePath"
                    ),
                    "nearestProjectStateDeltaSeconds": delta,
                    "nearestProjectStateTemporalRelation": (
                        "project_state_at_or_before_log"
                        if delta is not None and delta <= 0
                        else (
                            "project_state_after_log"
                            if delta is not None
                            else "project_state_not_present"
                        )
                    ),
                }
            )
    for leads in cut_lineage_leads.values():
        leads.sort(key=lambda item: item["renderLogModifiedAt"])

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Read-only live filesystem walk of the complete AS/0 Finishing "
            "root. Includes primary .c4d projects, native .c4d@timestamp "
            "backup snapshots, batch-render XML logs, and supporting text logs."
        ),
        "root": str(root),
        "manifest": str(args.manifest.resolve()),
        "summary": {
            "projectStates": len(projects),
            "primaryProjects": project_kind_counts["primary_project"],
            "backupSnapshots": project_kind_counts["backup_snapshot"],
            "codexGeneratedProjectStates": sum(
                item["codexGenerated"] for item in projects
            ),
            "authoredProjectStates": sum(
                not item["codexGenerated"] for item in projects
            ),
            "emptyProjectStates": sum(item["empty"] for item in projects),
            "unreadableProjectStates": sum(
                not item["readable"] for item in projects
            ),
            "batchRenderXmlFiles": len(logs),
            "parsedBatchRenderLogs": len(parsed_logs),
            "redshiftBatchRenderLogs": sum(
                (item.get("renderEngineName") or "").casefold() == "redshift"
                for item in parsed_logs
            ),
            "supportingTextFiles": len(text_support),
            "byChapter": dict(sorted(chapter_counts.items())),
            "selectedPrimaryProjectStates": sum(
                bool(item["selectedCutIds"]) for item in projects
            ),
            "selectedCutsWithAsProject": len(
                {
                    cut_id
                    for item in projects
                    for cut_id in item["selectedCutIds"]
                }
            ),
            "renderLogsMatchingSelectedCuts": sum(
                bool(item.get("matchingCutIds")) for item in logs
            ),
            "selectedCutsWithRenderLogEvidence": len(cut_lineage_leads),
        },
        "relevantDateWindows": relevant_windows,
        "cutLineageLeads": dict(sorted(cut_lineage_leads.items())),
        "projects": projects,
        "renderLogs": logs,
        "supportingTextFiles": text_support,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
