#!/usr/bin/env python3
"""Apply the active Premiere conform export as the atlas authority.

The clean conform uses V1/V2 source-render clip instances and Audio 1 chapter
edits. Legacy exports retain the earlier V5/V6/V7 comparison semantics.
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROLE_LABELS = {
    "older_than_cut": "Older than cut · V5 · Rose",
    "exact_match": "Canonical source · V6 · Iris",
    "newer_than_cut": "Canonical source · V7 · Green",
}

PREMIERE_LABEL_NAMES = {
    0: "Violet",
    1: "Iris",
    2: "Caribbean",
    3: "Lavender",
    4: "Cerulean",
    5: "Forest",
    6: "Rose",
    7: "Mango",
    8: "Purple",
    9: "Blue",
    10: "Teal",
    11: "Magenta",
    12: "Tan",
    13: "Green",
    14: "Brown",
    15: "Yellow",
}

STATUS_EVIDENCE = {
    "exact_match": "confirmed",
    "partially_exact": "visually_confirmed",
    "bracketed_missing_exact": "candidate",
    "older_than_cut": "candidate",
    "newer_than_cut": "confirmed",
    "partially_tracked": "strong_inference",
    "untracked": "missing",
}


def _timecode(seconds: float, fps: float) -> str:
    frames = max(0, round(seconds * fps))
    display_fps = round(fps)
    frame = frames % display_fps
    whole = frames // display_fps
    sec = whole % 60
    minute = (whole // 60) % 60
    hour = whole // 3600
    return f"{hour:02d}:{minute:02d}:{sec:02d}:{frame:02d}"


def _normalized(path: str | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(Path(path).expanduser())


def _frame_path(source: dict[str, Any], selected_frame: int | None) -> str:
    original = str(source.get("path") or "")
    if selected_frame is None:
        return original
    path = Path(original)
    match = re.search(r"(\d+)(?=\.[^.]+$)", path.name)
    if not match:
        return original
    padding = int(source.get("mediaFramePadding") or len(match.group(1)))
    replacement = f"{int(selected_frame):0{padding}d}"
    return str(path.with_name(path.name[: match.start()] + replacement + path.name[match.end() :]))


def _best_overlap(
    candidates: list[dict[str, Any]],
    start: float,
    end: float,
) -> dict[str, Any] | None:
    ranked = []
    for candidate in candidates:
        overlap = max(
            0.0,
            min(float(candidate["end"]), end)
            - max(float(candidate["start"]), start),
        )
        if overlap > 0:
            ranked.append((overlap, -abs(float(candidate["start"]) - start), candidate))
    return max(ranked, key=lambda item: (item[0], item[1]))[2] if ranked else None


def _source_segment(source: dict[str, Any]) -> dict[str, Any]:
    selected_first = source.get("selectedFirstFrame")
    selected_last = source.get("selectedLastFrame")
    role = str(source["role"])
    is_canonical = role in {"exact_match", "newer_than_cut"}
    evidence = "confirmed" if is_canonical else "candidate"
    clean_layer = source.get("canonicalLayer")
    source_edit = (
        f"Canonical render · Premiere {clean_layer}"
        if source.get("origin") == "clean_v1_v2" and clean_layer
        else ROLE_LABELS[role]
    )
    actual_label = source.get("premiereLabel")
    actual_label_index = (
        actual_label.get("index")
        if isinstance(actual_label, dict)
        else None
    )
    return {
        "id": source["id"],
        "sectionCode": source["sectionCode"],
        "finalStart": source["start"],
        "finalEnd": source["end"],
        "finalStartFrame": source["startFrame"],
        "finalEndFrame": source["endFrame"],
        "sourceSystem": f"Premiere V{source['track']}",
        "sourceEdit": source_edit,
        "sourcePath": source["path"],
        "renderDirectory": source.get("renderDirectory"),
        "sourceFirstFramePath": (
            source.get("selectedFirstFramePath")
            or _frame_path(source, selected_first)
        ),
        "sourceLastFramePath": (
            source.get("selectedLastFramePath")
            or _frame_path(source, selected_last)
        ),
        "sourceStartFrame": selected_first,
        "sourceEndFrame": selected_last,
        "sourceFrameRate": source.get("sourceFrameRate"),
        "sourceTrack": source["track"],
        "playBackwards": source.get("playBackwards", False),
        "evidence": evidence,
        "role": role,
        "canonical": is_canonical,
        "timelineStartTicks": source["startTicks"],
        "timelineEndTicks": source["endTicks"],
        "sourceInTicks": source["sourceInTicks"],
        "sourceOutTicks": source["sourceOutTicks"],
        "sourceIn": source["sourceIn"],
        "sourceOut": source["sourceOut"],
        "sourceInFrameOffset": source["sourceInFrameOffset"],
        "sourceOutFrameOffset": source["sourceOutFrameOffset"],
        "selectedFirstFrame": selected_first,
        "selectedLastFrame": selected_last,
        "premiereLabel": PREMIERE_LABEL_NAMES.get(
            actual_label_index,
            source.get("premiereLabelExpected"),
        ),
        "premiereLabelIndex": actual_label_index,
        "premiereRoleLabel": source.get("premiereLabelExpected"),
        "isNewRecovery": (
            actual_label_index == 15
            or str(source.get("name") or "").startswith("YELLOW-")
        ),
        "sourceMediaHealth": copy.deepcopy(
            source.get("sourceMediaHealth") or {}
        ),
        "visualAlignment": copy.deepcopy(source.get("visualAlignment")),
        "frameAlignedConform": copy.deepcopy(
            source.get("frameAlignedConform")
        ),
        "manualTrimAuthority": True,
    }


def _render_indexes(
    renders: list[dict[str, Any]],
    render_matches: dict[str, list[dict[str, Any]]],
    assets: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    assets_by_id = {str(item["id"]): item for item in assets}
    renders_by_path = {
        _normalized(str(item.get("path") or "")): item for item in renders
    }
    best_match_by_path: dict[str, dict[str, Any]] = {}
    for render in renders:
        path = _normalized(str(render.get("path") or ""))
        choices = render_matches.get(str(render.get("id")), [])
        if not choices:
            continue
        best = max(
            choices,
            key=lambda item: (
                item.get("evidence") == "confirmed",
                item.get("evidence") == "strong_inference",
                float(item.get("score") or 0),
            ),
        )
        asset = assets_by_id.get(str(best.get("assetId") or ""))
        if asset:
            best_match_by_path[path] = {**best, "asset": asset}
    return renders_by_path, best_match_by_path


def _ui_alternate_evidence(alternate: dict[str, Any]) -> str:
    value = str(alternate.get("evidence") or "")
    if (
        alternate.get("role") == "missing_exact_source"
        and float(alternate.get("temporalScore") or 0) < 0.70
    ):
        return "missing"
    if value == "strong_candidate":
        return "strong_inference"
    if value == "visually_confirmed_candidate":
        return value
    return "candidate"


def _alternate_nodes(
    alternate: dict[str, Any],
    renders_by_path: dict[str, dict[str, Any]],
    best_match_by_path: dict[str, dict[str, Any]],
    prefix: str = "Alternate search",
) -> list[dict[str, Any]]:
    render_path = _normalized(alternate.get("candidateRenderDirectory"))
    alternate_evidence = _ui_alternate_evidence(alternate)
    proposed_first = alternate.get("proposedFirstFrame")
    proposed_last = alternate.get("proposedLastFrame")
    proposed_range = (
        f"proposed frames {proposed_first}→{proposed_last}"
        if isinstance(proposed_first, int)
        and isinstance(proposed_last, int)
        and proposed_first >= 0
        and proposed_last >= 0
        else "source range unresolved"
    )
    confidence_phrase = (
        "weak top hit; no plausible source confirmed"
        if alternate_evidence == "missing"
        else str(alternate["evidence"]).replace("_", " ")
    )
    nodes = [
        {
            "kind": "visual_match",
            "label": Path(render_path).name,
            "detail": (
                f"{prefix} · temporal {alternate['temporalScore']:.3f} · "
                f"{confidence_phrase} · {proposed_range}"
            ),
            "path": render_path,
            "comparisonImage": alternate.get("comparisonImage"),
            "confirmationMethod": (
                "three-point direct comparison against final reference"
            ),
            "evidence": alternate_evidence,
        }
    ]
    if alternate_evidence == "missing":
        return nodes
    project_match = best_match_by_path.get(render_path)
    render = renders_by_path.get(render_path)
    if project_match:
        asset = project_match["asset"]
        nodes.append(
            {
                "kind": "cinema4d",
                "label": asset["name"],
                "detail": (
                    f"Candidate alternate render-to-project link · "
                    f"{float(project_match.get('score') or 0):.3f} · "
                    f"{project_match.get('matchKind') or 'name/output evidence'}"
                ),
                "path": asset["path"],
                "projectPath": asset["path"],
                "evidence": "candidate",
            }
        )
        if camera_name := project_match.get("cameraName"):
            nodes.append(
                {
                    "kind": "camera",
                    "label": camera_name,
                    "detail": (
                        f"Candidate alternate active camera · take "
                        f"{project_match.get('cameraTake') or 'Main'} · pending "
                        "confirmation that the searched render is the cut source"
                    ),
                    "path": asset["path"],
                    "projectPath": asset["path"],
                    "evidence": "candidate",
                    "confirmationMethod": "candidate render-project archive",
                    "cameraObject": project_match.get("cameraObject") or {},
                }
            )
    if render and render.get("aecCamera") and not any(
        node["kind"] == "camera" for node in nodes
    ):
        aec = render["aecCamera"]
        nodes.append(
            {
                "kind": "camera",
                "label": aec.get("activeCamera") or "AEC active camera",
                "detail": (
                    "Candidate alternate camera embedded in AEC metadata · "
                    "pending confirmation that this render is the cut source"
                ),
                "path": aec.get("path"),
                "evidence": "candidate",
                "confirmationMethod": "candidate Cinema 4D AEC metadata",
                "cameraObject": aec.get("activeCameraObject"),
            }
        )
    return nodes


def _source_nodes(
    source: dict[str, Any],
    renders_by_path: dict[str, dict[str, Any]],
    best_match_by_path: dict[str, dict[str, Any]],
    alternate: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    role = str(source["role"])
    render_path = _normalized(source.get("renderDirectory"))
    is_canonical = role in {"exact_match", "newer_than_cut"}
    evidence = "confirmed" if is_canonical else "candidate"
    clean_layer = source.get("canonicalLayer")
    role_label = (
        f"Canonical render · Premiere {clean_layer}"
        if source.get("origin") == "clean_v1_v2" and clean_layer
        else ROLE_LABELS[role]
    )
    source_media_health = source.get("sourceMediaHealth") or {}
    canonical_layer_label = clean_layer or f"V{source['track']}"
    media_health_detail = ""
    if source_media_health.get("status") == "incomplete":
        media_health_detail = (
            f" · selected media incomplete: "
            f"{source_media_health.get('missingFrames') or 0}/"
            f"{source_media_health.get('expectedFrames') or 0} frames missing "
            f"({source_media_health.get('missingFirstFrame')}–"
            f"{source_media_health.get('missingLastFrame')})"
        )
    source_tag = (
        [
            {
                "type": "source_render",
                "label": "Source Render",
                "detail": (
                    f"{source['id']} is the manually aligned canonical "
                    f"{canonical_layer_label} render for this "
                    "final-cut interval"
                ),
                "evidence": "confirmed",
            }
        ]
        if is_canonical
        else []
    )
    nodes: list[dict[str, Any]] = [
        {
            "kind": "render_sequence",
            "label": Path(render_path or str(source.get("path") or "")).name,
            "detail": (
                f"{role_label} · exact saved timeline and source "
                f"In/Out from {source['id']}{media_health_detail}"
            ),
            "path": render_path or str(Path(str(source.get("path") or "")).parent),
            "evidence": evidence,
            "tags": source_tag,
        }
    ]
    render = renders_by_path.get(render_path)
    project_match = best_match_by_path.get(render_path)
    if project_match:
        asset = project_match["asset"]
        project_evidence = (
            str(project_match.get("evidence") or "candidate")
            if is_canonical
            else "candidate"
        )
        nodes.append(
            {
                "kind": "cinema4d",
                "label": asset["name"],
                "detail": (
                    f"Render-to-project match {float(project_match.get('score') or 0):.3f}"
                    f" · {project_match.get('matchKind') or 'name/output evidence'}"
                ),
                "path": asset["path"],
                "projectPath": asset["path"],
                "evidence": project_evidence,
            }
        )
        camera_name = project_match.get("cameraName")
        camera_object = project_match.get("cameraObject") or {}
        if camera_name:
            nodes.append(
                {
                    "kind": "camera",
                    "label": camera_name,
                    "detail": (
                        f"Active render camera · take "
                        f"{project_match.get('cameraTake') or 'Main'} · "
                        f"{project_match.get('cameraRenderData') or 'render settings'}"
                    ),
                    "path": asset["path"],
                    "projectPath": asset["path"],
                    "evidence": project_evidence,
                    "confirmationMethod": (
                        project_match.get("outputAlignment")
                        or project_match.get("matchKind")
                        or "render-project archive"
                    ),
                    "cameraObject": camera_object,
                }
            )
    if render and render.get("aecCamera") and not any(
        node["kind"] == "camera" for node in nodes
    ):
        aec = render["aecCamera"]
        nodes.append(
            {
                "kind": "camera",
                "label": aec.get("activeCamera") or "AEC active camera",
                "detail": (
                    f"Active camera embedded in the render AEC metadata · "
                    f"{aec.get('cameraCount') or 0} cameras archived"
                ),
                "path": aec.get("path"),
                "evidence": (
                    "confirmed" if is_canonical else "candidate"
                ),
                "confirmationMethod": "Cinema 4D AEC render metadata",
                "cameraObject": aec.get("activeCameraObject"),
            }
        )
    if alternate:
        nodes.extend(
            _alternate_nodes(
                alternate,
                renders_by_path,
                best_match_by_path,
            )
        )
    return nodes


def _chapter_blocks(
    inventory: list[dict[str, Any]],
    chapter_cuts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if chapter_cuts:
        return [
            {
                "id": f"manual-block-{index}",
                "name": str(chapter["sectionName"]),
                "path": str(chapter.get("audioMediaPath") or ""),
                "track": int(chapter.get("audioTrack") or 1),
                "start": float(chapter["start"]),
                "end": float(chapter["end"]),
                "duration": float(chapter["end"]) - float(chapter["start"]),
                "sectionCode": str(chapter["sectionCode"]),
                "sectionName": str(chapter["sectionName"]),
                "evidence": "confirmed",
                "boundaryAuthority": "saved_audio_track_edit_points",
                "manualTrimAuthority": True,
            }
            for index, chapter in enumerate(chapter_cuts, start=1)
        ]
    by_section: dict[str, list[dict[str, Any]]] = {}
    for item in inventory:
        if item.get("role") == "intentional_blank":
            continue
        by_section.setdefault(str(item["sectionCode"]), []).append(item)
    order = ["ND", "NTH", "TH", "NA", "GG", "IJDKYY"]
    blocks = []
    for index, code in enumerate(order, start=1):
        items = by_section.get(code, [])
        if not items:
            continue
        start = min(float(item["start"]) for item in items)
        end = max(float(item["end"]) for item in items)
        blocks.append(
            {
                "id": f"manual-block-{index}",
                "name": items[0]["sectionName"],
                "path": "",
                "track": 1,
                "start": start,
                "end": end,
                "duration": end - start,
                "sectionCode": code,
                "sectionName": items[0]["sectionName"],
                "evidence": "confirmed",
                "manualTrimAuthority": True,
            }
        )
    return blocks


def reconcile_revised_conform(
    old_cuts: list[dict[str, Any]],
    revised: dict[str, Any],
    renders: list[dict[str, Any]],
    render_matches: dict[str, list[dict[str, Any]]],
    assets: list[dict[str, Any]],
    alternate_search: dict[str, Any],
    fps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Return cuts and conform data keyed to the user's saved clip instances."""

    is_clean_conform = revised.get("authorityKind") == "clean_v1_v2"
    if is_clean_conform:
        alternate_search = {}
    sources = list(revised.get("sources", []))
    sources_by_id = {str(item["id"]): item for item in sources}
    alternates_by_source = {
        str(item["sourceId"]): item
        for item in alternate_search.get("results", [])
    }
    alternates_by_cut: dict[str, list[dict[str, Any]]] = {}
    for alternate in alternate_search.get("results", []):
        if target_cut_id := alternate.get("targetCutId"):
            alternates_by_cut.setdefault(str(target_cut_id), []).append(
                alternate
            )
    renders_by_path, best_match_by_path = _render_indexes(
        renders, render_matches, assets
    )
    revised_cuts: list[dict[str, Any]] = []
    for item in revised.get("inventory", []):
        start = float(item["start"])
        end = float(item["end"])
        is_gap = item.get("role") == "intentional_blank"
        base = _best_overlap(old_cuts, start, end)
        cut = copy.deepcopy(base) if base else {}
        cut.update(
            {
                "id": item["canonicalId"],
                "index": int(item["canonicalIndex"]),
                "start": start,
                "end": end,
                "duration": end - start,
                "timecode": _timecode(start, fps),
                "endTimecode": _timecode(end, fps),
                "thumbnail": f"/archive/cuts/{item['canonicalId']}.jpg",
                "boundaryEvidence": (
                    "reference_frame_matched_source"
                    if item.get("visualAlignment")
                    else "user_aligned_premiere_clip_instance"
                ),
                "boundaryDetail": (
                    str((item.get("visualAlignment") or {}).get("detail"))
                    if item.get("visualAlignment")
                    else
                    "Exact saved Premiere V1/V2 timeline In/Out; no boundary "
                    "detection or trim recalculation applied."
                    if is_clean_conform
                    else
                    "Exact saved V1 timeline In/Out; no boundary detection or "
                    "trim recalculation applied."
                ),
                "verification": (
                    "Exact reference-frame aligned source trim"
                    if item.get("visualAlignment")
                    else "Authoritative Clean conform Premiere trim"
                    if is_clean_conform and not is_gap
                    else "Authoritative intentional Premiere black"
                    if is_clean_conform
                    else "Authoritative manual Premiere trim"
                    if not is_gap
                    else "Authoritative intentional V1 blank"
                ),
                "sectionCode": item["sectionCode"],
                "sectionName": item["sectionName"],
                "isGap": is_gap,
            }
        )
        if is_gap:
            cut.update(
                {
                    "confidence": "confirmed",
                    "plannedShotId": None,
                    "sourceSegments": [],
                    "exportScreenshots": [],
                    "lineage": [
                        {
                            "kind": "reference",
                            "label": item["canonicalId"],
                            "detail": "Final-reference intentional blank interval",
                            "path": "",
                            "evidence": "confirmed",
                        },
                        {
                            "kind": "premiere_gap",
                            "label": (
                                "V1/V2 intentional black"
                                if is_clean_conform
                                else "V1 intentional blank"
                            ),
                            "detail": (
                                f"Saved {'V1/V2' if is_clean_conform else 'V1'} "
                                f"gap · frames {item['startFrame']}–"
                                f"{item['endFrame']} · manual authority"
                            ),
                            "path": revised.get("projectPath"),
                            "evidence": "confirmed",
                        },
                    ],
                    "manualConform": {
                        "authority": "saved_premiere_clip_instance",
                        "timelineStartTicks": item.get("startTicks"),
                        "timelineEndTicks": item.get("endTicks"),
                        "startFrame": item["startFrame"],
                        "endFrame": item["endFrame"],
                        "status": "intentional_blank",
                        "sources": [],
                    },
                }
            )
            cut.pop("c4dLinkStatus", None)
            cut.pop("comparison", None)
            revised_cuts.append(cut)
            continue

        coverage = copy.deepcopy(item.get("sourceCoverage") or {})
        source_ids = list(coverage.get("sourceIds") or [])
        overlapping_sources = [
            sources_by_id[source_id]
            for source_id in source_ids
            if source_id in sources_by_id
        ]
        segments = [_source_segment(source) for source in overlapping_sources]
        status = str(coverage.get("status") or "untracked")
        cut["confidence"] = STATUS_EVIDENCE.get(status, "candidate")
        cut["sourceSegments"] = segments
        cut["manualConform"] = {
            "authority": "saved_premiere_clip_instance",
            "project": revised.get("projectPath"),
            "sequence": revised.get("sequence"),
            "timelineTrack": item.get("track"),
            "timelineStartTicks": item["startTicks"],
            "timelineEndTicks": item["endTicks"],
            "startFrame": item["startFrame"],
            "endFrame": item["endFrame"],
            "sourceInTicks": item.get("sourceInTicks"),
            "sourceOutTicks": item.get("sourceOutTicks"),
            "sourceIn": item.get("sourceIn"),
            "sourceOut": item.get("sourceOut"),
            "sourceInFrameOffset": item.get("sourceInFrameOffset"),
            "sourceOutFrameOffset": item.get("sourceOutFrameOffset"),
            "status": status,
            "visualAlignment": copy.deepcopy(item.get("visualAlignment")),
            "frameAlignedConform": copy.deepcopy(
                item.get("frameAlignedConform")
            ),
            "canonicalSources": [
                source["id"]
                for source in overlapping_sources
                if str(source.get("role"))
                in {"exact_match", "newer_than_cut"}
            ],
            "coverage": coverage.get("coverage", 0),
            "exactCoverage": coverage.get("exactCoverage", 0),
            "sources": source_ids,
        }

        retained = [
            copy.deepcopy(node)
            for node in cut.get("lineage", [])
            if node.get("kind")
            in {
                "premiere",
                "premiere_sequence",
                "premiere_export",
                "resolve",
                "resolve_media",
                "after_effects",
                "after_effects_comp",
                "after_effects_layer",
            }
        ]
        lineage = [
            {
                "kind": "reference",
                "label": item["canonicalId"],
                "detail": (
                    f"Canonical V{item.get('track') or 1} picture · frames "
                    f"{item['startFrame']}–"
                    f"{item['endFrame']}"
                    if is_clean_conform
                    else f"Final V1 picture · frames {item['startFrame']}–"
                    f"{item['endFrame']}"
                ),
                "path": "",
                "evidence": "confirmed",
            },
            {
                "kind": "premiere",
                "label": revised.get("sequence") or "Paracosm Source Conform",
                "detail": (
                    f"V{item.get('track') or 1} source clip · "
                    + (
                        "reference-frame aligned · "
                        if item.get("visualAlignment")
                        else "saved placement · "
                    )
                    + f"timeline {start:.6f}–{end:.6f}s · source "
                    f"{float(item.get('sourceIn') or 0):.6f}–"
                    f"{float(item.get('sourceOut') or 0):.6f}s"
                ),
                "path": revised.get("projectPath"),
                "projectPath": revised.get("projectPath"),
                "evidence": "confirmed",
            },
            *retained,
        ]
        frame_aligned = item.get("frameAlignedConform") or {}
        proofs = list(frame_aligned.get("proofs") or [])
        if frame_aligned:
            lineage[1].update(
                {
                    "kind": "premiere_frame_alignment",
                    "label": (
                        frame_aligned.get("sequence")
                        or revised.get("sequence")
                        or "Frame-aligned Premiere conform"
                    ),
                    "detail": (
                        f"Saved frame-aligned Premiere clip · "
                        f"{frame_aligned.get('adapterFrames') or 0} "
                        "one-frame adapter links · direct monotonic final-to-"
                        "render comparison · verified in exported .prproj"
                    ),
                    "path": frame_aligned.get("project"),
                    "projectPath": frame_aligned.get("project"),
                    "comparisonImage": (
                        proofs[0].get("screenshot") if proofs else None
                    ),
                    "confirmationMethod": (
                        "saved-project tick audit plus direct boundary frame "
                        "comparison"
                    ),
                }
            )
            cut["exportScreenshots"] = [
                *list(cut.get("exportScreenshots") or []),
                *[
                    {
                        "id": (
                            f"frame-aligned-{proof.get('id')}-"
                            f"{proof.get('role')}"
                        ),
                        "role": "frame_aligned_boundary",
                        "label": "Frame-aligned Premiere boundary proof",
                        "image": proof.get("screenshot"),
                        "exportPath": frame_aligned.get("project"),
                        "sourceTime": (
                            float(proof.get("frame") or 0)
                            / float(revised.get("timelineFrameRate") or 24)
                        ),
                        "detail": (
                            f"{proof.get('detail')} · this shot is the "
                            f"{proof.get('role')} side of reference frame "
                            f"{proof.get('frame')}."
                        ),
                        "evidence": "confirmed",
                        "producers": [
                            {
                                "kind": "premiere",
                                "label": frame_aligned.get("sequence"),
                                "projectPath": frame_aligned.get("project"),
                                "sequence": frame_aligned.get("sequence"),
                                "detail": (
                                    "Frame-aligned adapter sequence exported "
                                    "and independently parsed from Premiere"
                                ),
                                "evidence": "confirmed",
                            }
                        ],
                    }
                    for proof in proofs
                    if proof.get("screenshot")
                ],
            ]
        seen_render_paths: set[str] = set()
        for source in overlapping_sources:
            render_path = _normalized(source.get("renderDirectory"))
            if render_path in seen_render_paths:
                continue
            seen_render_paths.add(render_path)
            lineage.extend(
                _source_nodes(
                    source,
                    renders_by_path,
                    best_match_by_path,
                    alternates_by_source.get(str(source["id"])),
                )
            )
        for alternate in alternates_by_cut.get(str(item["canonicalId"]), []):
            lineage.extend(
                _alternate_nodes(
                    alternate,
                    renders_by_path,
                    best_match_by_path,
                    "Missing-source archive search",
                )
            )
        cut["lineage"] = lineage
        revised_cuts.append(cut)

    segment_records = [_source_segment(source) for source in sources]
    role_counts = Counter(str(source["role"]) for source in sources)
    conform = {
        "baseSequence": revised.get("sequence"),
        "project": revised.get("projectPath"),
        "authority": (
            revised.get("authority")
            or "Exact saved Premiere clip-instance timeline and source In/Out"
        ),
        "timelineFrameRate": revised.get("timelineFrameRate"),
        "sourceFrameRate": revised.get("sourceImageFrameRate"),
        "segments": segment_records,
        "omittedSubframeEvents": [],
        "summary": {
            "segments": len(segment_records),
            "omittedSubframeEvents": 0,
            "confirmed": (
                role_counts.get("exact_match", 0)
                + role_counts.get("newer_than_cut", 0)
            ),
            "strongInference": 0,
            "sections": dict(Counter(item["sectionCode"] for item in sources)),
            "roles": dict(role_counts),
        },
    }
    status_counts = Counter(
        str((cut.get("manualConform") or {}).get("status"))
        for cut in revised_cuts
        if not cut.get("isGap")
    )
    stats = {
        **copy.deepcopy(revised.get("summary") or {}),
        "statusCounts": dict(status_counts),
        "alternateSearch": copy.deepcopy(alternate_search.get("summary") or {}),
    }
    return (
        revised_cuts,
        conform,
        stats,
        _chapter_blocks(revised["inventory"], revised.get("chapterCuts")),
    )
