#!/usr/bin/env python3
"""Identify current C4D files whose saved state postdates exact render logs."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AS_FINISHING_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
    "AS/0 Finishing"
)
DEFAULT_CHRONOLOGY = ROOT / "data/as-finishing-chronology-20260727.json"
DEFAULT_HISTORY = ROOT / "data/as-finishing-dropbox-history-20260727.json"
DEFAULT_STATE = ROOT / "public/data/state.json"
DEFAULT_OUTPUT = ROOT / "data/as-finishing-revision-targets-20260727.json"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def observed_history(
    history: dict[str, Any], project_path: str
) -> list[dict[str, Any]]:
    project = observed_history_project(history, project_path)
    return list((project or {}).get("historyEntries") or [])


def observed_history_project(
    history: dict[str, Any], project_path: str
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in history.get("projects", [])
            if item.get("projectPath") == project_path
        ),
        None,
    )


def explicit_revision_for_cut(
    history: dict[str, Any], project_path: str, cut_id: str
) -> dict[str, Any] | None:
    """Return a manually adjudicated revision when the history records one.

    This is needed when a save and the first emitted render frame share the
    same minute, or when one large C4D project generated multiple canonical
    shot batches from different saved states.
    """
    project = observed_history_project(history, project_path)
    if not project:
        return None
    selections = list(project.get("relevantRevisionSelections") or [])
    singular = project.get("relevantRevisionSelection")
    if singular:
        selections.append(singular)
    selection = next(
        (
            item
            for item in selections
            if item.get("cutId") == cut_id
            or cut_id in (item.get("cutIds") or [])
        ),
        None,
    )
    if not selection:
        return None
    selected_at = (
        selection.get("selectedRevisionSavedAt")
        or selection.get("nearestPrecedingRevisionSavedAt")
    )
    if not selected_at:
        return None
    revision = next(
        (
            item
            for item in project.get("historyEntries", [])
            if item.get("savedAt") == selected_at
        ),
        None,
    )
    if not revision:
        return None
    return {
        **revision,
        "selectionOverride": "explicit_relevant_revision_selection",
        "selectionRule": selection.get("selectionRule"),
    }


def is_codex_generated(path_value: str | None) -> bool:
    value = str(path_value or "").lower()
    return "_codex_" in value


def local_timestamped_backups(
    finishing_root: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Index C4D's local timestamped backups without treating them as source.

    Cinema 4D backup snapshots in this project use
    ``project.c4d@YYYYMMDD_HHMMSS``.  The filename timestamp is retained as a
    label, while the filesystem mtime is the ordering authority because these
    Dropbox-local files preserve the actual saved-state chronology.
    """
    indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not finishing_root.is_dir():
        return indexed
    for candidate in finishing_root.rglob("*.c4d@*"):
        if not candidate.is_file() or is_codex_generated(str(candidate)):
            continue
        match = re.match(
            r"^(?P<base>.+\.c4d)@(?P<label>\d{8}_\d{6})$",
            candidate.name,
            re.IGNORECASE,
        )
        if not match:
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        indexed[match.group("base").lower()].append(
            {
                "path": str(candidate),
                "savedAt": datetime.fromtimestamp(
                    stat.st_mtime
                ).astimezone().isoformat(),
                "snapshotLabel": match.group("label"),
                "sizeBytes": stat.st_size,
                "source": "local_timestamped_c4d_backup",
            }
        )
    for entries in indexed.values():
        entries.sort(key=lambda item: item["savedAt"])
    return indexed


def backups_for_project(
    indexed: dict[str, list[dict[str, Any]]], project_path: str
) -> list[dict[str, Any]]:
    """Return exact-name backups nearest to the authored project directory."""
    project = Path(project_path)
    entries = list(indexed.get(project.name.lower(), []))
    if not entries:
        return []
    local = [
        item
        for item in entries
        if project.parent in Path(item["path"]).parents
    ]
    return local or entries


def bracket_versions(
    entries: list[dict[str, Any]], render_time: datetime
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    parsed = [
        (parse_time(item.get("savedAt")), item)
        for item in entries
        if parse_time(item.get("savedAt"))
    ]
    before = [item for saved, item in parsed if saved <= render_time]
    after = [item for saved, item in parsed if saved >= render_time]
    preceding = (
        max(before, key=lambda item: parse_time(item["savedAt"]))
        if before
        else None
    )
    following = (
        min(after, key=lambda item: parse_time(item["savedAt"]))
        if after
        else None
    )
    return preceding, following


def preferred_revision(
    local_preceding: dict[str, Any] | None,
    dropbox_preceding: dict[str, Any] | None,
) -> dict[str, Any] | None:
    options = [
        item
        for item in [local_preceding, dropbox_preceding]
        if item and parse_time(item.get("savedAt"))
    ]
    return (
        max(options, key=lambda item: parse_time(item["savedAt"]))
        if options
        else None
    )


def recovery_status(
    local_preceding: dict[str, Any] | None,
    dropbox_preceding: dict[str, Any] | None,
) -> str:
    if local_preceding:
        return "local_pre_render_backup_available"
    if dropbox_preceding:
        return "dropbox_pre_render_revision_observed"
    return "historical_revision_still_required"


def emitted_frame_window(
    render_log: dict[str, Any] | None,
    alternate_output_paths: list[str] | None = None,
) -> tuple[datetime | None, datetime | None, int]:
    """Return the exact batch's first/last emitted-frame mtimes.

    A log's modification time is normally its close time. Long batches can
    straddle later C4D saves, so revision selection must use the first emitted
    frame instead. Match the parsed filename prefix exactly through the
    trailing frame number; this deliberately excludes later suffix batches
    written into the same output directory.
    """
    if not render_log:
        return None, None, 0
    output_value = (
        render_log.get("outputPathNormalized")
        or render_log.get("outputPath")
    )
    prefixes = list(render_log.get("completedImageBasenamePrefixes") or [])
    output_values = [
        str(path)
        for path in [output_value, *(alternate_output_paths or [])]
        if path
    ]
    if not output_values or not prefixes:
        return None, None, 0
    patterns = [
        re.compile(rf"^{re.escape(str(prefix))}\d+\.[^.]+$", re.IGNORECASE)
        for prefix in prefixes
        if prefix
    ]
    if not patterns:
        return None, None, 0
    frame_times: list[datetime] = []
    seen_directories: set[str] = set()
    for output_value in output_values:
        output_path = Path(output_value)
        output_key = str(output_path)
        if output_key in seen_directories or not output_path.is_dir():
            continue
        seen_directories.add(output_key)
        for candidate in output_path.iterdir():
            if not candidate.is_file():
                continue
            if not any(pattern.match(candidate.name) for pattern in patterns):
                continue
            try:
                frame_times.append(
                    datetime.fromtimestamp(
                        candidate.stat().st_mtime
                    ).astimezone()
                )
            except OSError:
                continue
    if not frame_times:
        return None, None, 0
    return min(frame_times), max(frame_times), len(frame_times)


def priority(delta_seconds: int) -> str:
    if delta_seconds >= 7 * 24 * 60 * 60:
        return "historical_revision_required"
    if delta_seconds >= 6 * 60 * 60:
        return "history_review_required"
    return "near_render_state_review"


def file_modified_at(path_value: str | None) -> datetime | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chronology", type=Path, default=DEFAULT_CHRONOLOGY)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    chronology = json.loads(args.chronology.read_text())
    history = (
        json.loads(args.history.read_text())
        if args.history.is_file()
        else {"projects": []}
    )
    state = (
        json.loads(args.state.read_text())
        if args.state.is_file()
        else {"cuts": []}
    )
    projects_by_path = {
        str(item.get("path")): item
        for item in chronology.get("projects", [])
        if item.get("path")
    }
    render_logs_by_path = {
        str(item.get("path")): item
        for item in chronology.get("renderLogs", [])
        if item.get("path")
    }
    local_backups_by_name = local_timestamped_backups(AS_FINISHING_ROOT)
    grouped: dict[str, dict[str, Any]] = {}
    log_cuts: dict[tuple[str, str], set[str]] = defaultdict(set)
    canonical_windows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    canonical_render_by_cut = {
        str(cut.get("id")): str(segment.get("renderDirectory") or "")
        for cut in state.get("cuts", [])
        for segment in cut.get("sourceSegments", [])
        if cut.get("id") and segment.get("canonical")
    }

    for cut_id, leads in chronology.get("cutLineageLeads", {}).items():
        for lead in leads:
            if (
                lead.get("nearestProjectStateTemporalRelation")
                != "project_state_after_log"
            ):
                continue
            project_path = str(lead.get("nearestProjectStatePath") or "")
            render_log = str(lead.get("renderLogPath") or "")
            if not project_path or not render_log:
                continue
            log_cuts[(project_path, render_log)].add(str(cut_id))
            group = grouped.setdefault(
                project_path,
                {
                    "projectPath": project_path,
                    "projectName": Path(project_path).name,
                    "chapter": (
                        projects_by_path.get(project_path, {}).get("chapter")
                    ),
                    "currentModifiedAt": (
                        projects_by_path.get(project_path, {}).get(
                            "modifiedAt"
                        )
                    ),
                    "renderLogs": {},
                },
            )
            group["renderLogs"].setdefault(
                render_log,
                {
                    "renderLogPath": render_log,
                    "renderLogModifiedAt": lead.get("renderLogModifiedAt"),
                    "camera": lead.get("camera"),
                    "take": lead.get("take"),
                    "outputPath": lead.get("outputPath"),
                    "deltaSecondsToCurrentState": int(
                        lead.get("nearestProjectStateDeltaSeconds") or 0
                    ),
                },
            )

    for cut in state.get("cuts", []):
        if cut.get("isGap"):
            continue
        canonical_segment = next(
            (
                segment
                for segment in cut.get("sourceSegments", [])
                if segment.get("canonical")
            ),
            None,
        )
        if not canonical_segment:
            continue
        lineage_paths = [
            (
                str(node.get("projectPath") or node.get("path") or ""),
                str(node.get("kind") or ""),
                bool(node.get("primaryRecoveryProof")),
            )
            for node in cut.get("lineage", [])
            if str(node.get("projectPath") or node.get("path") or "").startswith(
                str(AS_FINISHING_ROOT) + "/"
            )
        ]
        project_path = next(
            (
                path
                for path, kind, _primary in lineage_paths
                if kind == "cinema4d" and not is_codex_generated(path)
            ),
            "",
        )
        if not project_path:
            project_path = next(
                (
                    path
                    for path, kind, _primary in lineage_paths
                    if kind == "camera_proof"
                    and not is_codex_generated(path)
                ),
                "",
            )
        if not project_path:
            project_path = next(
                (
                    path
                    for path, _kind, primary in lineage_paths
                    if primary
                ),
                "",
            )
        if not project_path:
            continue
        sequence_start_path = str(
            canonical_segment.get("sourcePath")
            or canonical_segment.get("sourceFirstFramePath")
            or ""
        )
        selected_first_path = str(
            canonical_segment.get("sourceFirstFramePath") or ""
        )
        selected_last_path = str(
            canonical_segment.get("sourceLastFramePath") or ""
        )
        sequence_started_at = file_modified_at(sequence_start_path)
        selected_first_at = file_modified_at(selected_first_path)
        selected_last_at = file_modified_at(selected_last_path)
        if not sequence_started_at:
            sequence_started_at = selected_first_at
            sequence_start_path = selected_first_path
        if not sequence_started_at:
            continue
        current_modified_at = parse_time(
            projects_by_path.get(project_path, {}).get("modifiedAt")
        )
        delta_seconds = (
            max(
                0,
                int((current_modified_at - sequence_started_at).total_seconds()),
            )
            if current_modified_at
            else 0
        )
        entries = observed_history(history, project_path)
        local_entries = backups_for_project(
            local_backups_by_name, project_path
        )
        preceding = following = None
        local_preceding = local_following = None
        if entries:
            preceding, following = bracket_versions(
                entries, sequence_started_at
            )
        if local_entries:
            local_preceding, local_following = bracket_versions(
                local_entries, sequence_started_at
            )
        explicit_revision = explicit_revision_for_cut(
            history, project_path, str(cut.get("id"))
        )
        if explicit_revision:
            preceding = explicit_revision
        recommended = explicit_revision or preferred_revision(
            local_preceding, preceding
        )
        canonical_windows[project_path].append(
            {
                "cutId": cut.get("id"),
                "renderDirectory": canonical_segment.get("renderDirectory"),
                "sequenceStartFramePath": sequence_start_path,
                "selectedFirstFramePath": selected_first_path,
                "selectedLastFramePath": selected_last_path,
                "sequenceStartedAt": sequence_started_at.isoformat(),
                "selectedFirstFrameModifiedAt": (
                    selected_first_at.isoformat()
                    if selected_first_at
                    else None
                ),
                "selectedLastFrameModifiedAt": (
                    selected_last_at.isoformat()
                    if selected_last_at
                    else None
                ),
                "sourceStartFrame": canonical_segment.get("sourceStartFrame"),
                "sourceEndFrame": canonical_segment.get("sourceEndFrame"),
                "deltaSecondsToCurrentState": delta_seconds,
                "priority": priority(delta_seconds),
                "nearestPrecedingDropboxVersion": preceding,
                "nearestFollowingDropboxVersion": following,
                "nearestPrecedingLocalBackup": local_preceding,
                "nearestFollowingLocalBackup": local_following,
                "recommendedRevision": recommended,
                "recoveryStatus": recovery_status(
                    local_preceding, preceding
                ),
                "revisionSelectionBasis": (
                    "explicit_relevant_revision_selection"
                    if explicit_revision
                    else "canonical_sequence_first_frame_timestamp"
                ),
                "recommendation": (
                    (
                        "Copy the exact local timestamped backup into a dated "
                        "_codex_072526 folder"
                        if local_preceding
                        else "Download the nearest preceding Dropbox version "
                        "into a dated _codex_072526 folder"
                    )
                    + ", never restore over the source; "
                    "audit dependencies and render the canonical source "
                    "frame through the shot-authored camera."
                ),
            }
        )
        grouped.setdefault(
            project_path,
            {
                "projectPath": project_path,
                "projectName": Path(project_path).name,
                "chapter": (
                    projects_by_path.get(project_path, {}).get("chapter")
                ),
                "currentModifiedAt": (
                    projects_by_path.get(project_path, {}).get("modifiedAt")
                ),
                "renderLogs": {},
            },
        )

    project_rows: list[dict[str, Any]] = []
    for project_path, group in grouped.items():
        entries = observed_history(history, project_path)
        local_entries = backups_for_project(
            local_backups_by_name, project_path
        )
        log_rows = []
        for render_log, row in group.pop("renderLogs").items():
            render_log_record = render_logs_by_path.get(render_log)
            sequence_started, sequence_completed, emitted_frame_count = (
                emitted_frame_window(
                    render_log_record,
                    [
                        canonical_render_by_cut.get(cut_id, "")
                        for cut_id in log_cuts[(project_path, render_log)]
                    ],
                )
            )
            log_closed_at = parse_time(row.get("renderLogModifiedAt"))
            revision_selection_time = sequence_started or log_closed_at
            preceding = following = None
            local_preceding = local_following = None
            if revision_selection_time and entries:
                preceding, following = bracket_versions(
                    entries, revision_selection_time
                )
            if revision_selection_time and local_entries:
                local_preceding, local_following = bracket_versions(
                    local_entries, revision_selection_time
                )
            recommended = preferred_revision(local_preceding, preceding)
            log_rows.append(
                {
                    **row,
                    "renderSequenceStartedAt": (
                        sequence_started.isoformat()
                        if sequence_started
                        else None
                    ),
                    "renderSequenceCompletedAt": (
                        sequence_completed.isoformat()
                        if sequence_completed
                        else None
                    ),
                    "emittedFrameTimestampCount": emitted_frame_count,
                    "revisionSelectionTimestamp": (
                        revision_selection_time.isoformat()
                        if revision_selection_time
                        else None
                    ),
                    "revisionSelectionBasis": (
                        "first_exact_emitted_frame"
                        if sequence_started
                        else "render_log_close_fallback"
                    ),
                    "cutIds": sorted(log_cuts[(project_path, render_log)]),
                    "priority": priority(
                        int(row["deltaSecondsToCurrentState"])
                    ),
                    "nearestPrecedingDropboxVersion": preceding,
                    "nearestFollowingDropboxVersion": following,
                    "nearestPrecedingLocalBackup": local_preceding,
                    "nearestFollowingLocalBackup": local_following,
                    "recommendedRevision": recommended,
                    "recoveryStatus": recovery_status(
                        local_preceding, preceding
                    ),
                    "recommendation": (
                        (
                            "Copy the exact local timestamped backup into a "
                            "dated _codex_072526 folder"
                            if local_preceding
                            else "Download the nearest preceding Dropbox "
                            "version into a dated _codex_072526 folder"
                        )
                        + ", never restore over the source; "
                        "render the exact logged take/camera/frame and compare "
                        "against the canonical source frame."
                    ),
                }
            )
        log_rows.sort(
            key=lambda item: item.get("renderLogModifiedAt") or ""
        )
        source_windows = sorted(
            canonical_windows.get(project_path, []),
            key=lambda item: item.get("sequenceStartedAt") or "",
        )
        max_delta = max(
            (
                int(item["deltaSecondsToCurrentState"])
                for item in [*log_rows, *source_windows]
            ),
            default=0,
        )
        project_rows.append(
            {
                **group,
                "status": priority(max_delta),
                "observedDropboxHistory": bool(entries),
                "observedDropboxVersionCount": len(entries),
                "localTimestampedBackupCount": len(local_entries),
                "hasLocalPreRenderBackup": any(
                    item.get("nearestPrecedingLocalBackup")
                    for item in [*log_rows, *source_windows]
                ),
                "cutIds": sorted(
                    {
                        cut_id
                        for item in log_rows
                        for cut_id in item["cutIds"]
                    }
                    | {
                        str(item["cutId"])
                        for item in source_windows
                        if item.get("cutId")
                    }
                ),
                "renderLogs": log_rows,
                "canonicalSourceWindows": source_windows,
            }
        )

    project_rows.sort(
        key=lambda item: max(
            (
                int(log["deltaSecondsToCurrentState"])
                for log in [
                    *item["renderLogs"],
                    *item["canonicalSourceWindows"],
                ]
            ),
            default=0,
        ),
        reverse=True,
    )
    cut_ids = {
        cut_id for item in project_rows for cut_id in item["cutIds"]
    }
    result = {
        "schemaVersion": 1,
        "generatedAt": datetime.now().astimezone().isoformat(),
        "authority": {
            "canonicalRenderEvidence": str(args.chronology),
            "dropboxHistoryEvidence": (
                str(args.history) if args.history.is_file() else None
            ),
            "rule": (
                "A current C4D file saved after its exact completed Redshift "
                "render log is not accepted as camera proof until the logged "
                "state is reproduced. Dropbox history is bracketed against "
                "the first exact emitted frame for that log filename prefix, "
                "falling back to the log close time only when emitted frames "
                "are unavailable. Authored local C4D "
                "backup/*.c4d@timestamp states are checked before remote "
                "history and are ordered by preserved filesystem mtime. "
                "_codex copies are never source revisions. Historical copies "
                "are never restored over source."
            ),
        },
        "summary": {
            "projectCount": len(project_rows),
            "cutCount": len(cut_ids),
            "renderLogCount": sum(
                len(item["renderLogs"]) for item in project_rows
            ),
            "canonicalSourceWindowCount": sum(
                len(item["canonicalSourceWindows"])
                for item in project_rows
            ),
            "projectsWithObservedDropboxHistory": sum(
                1
                for item in project_rows
                if item["observedDropboxHistory"]
            ),
            "projectsWithoutObservedDropboxHistory": sum(
                1
                for item in project_rows
                if not item["observedDropboxHistory"]
            ),
            "localTimestampedBackupCount": sum(
                len(entries) for entries in local_backups_by_name.values()
            ),
            "projectsWithLocalPreRenderBackup": sum(
                1
                for item in project_rows
                if item["hasLocalPreRenderBackup"]
            ),
            "historicalRevisionRequiredProjects": sum(
                1
                for item in project_rows
                if item["status"] == "historical_revision_required"
            ),
        },
        "projects": project_rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
