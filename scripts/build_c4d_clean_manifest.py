#!/usr/bin/env python3
"""Build the all-cut clean C4D ledger and agent-ready recovery checklists."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "public" / "data" / "state.json"
STRICT_PATH = ROOT / "data" / "c4d-strict-audit.json"
CAMERA_PROOF_PATH = ROOT / "data" / "c4d-camera-proof-renders.json"
DEPENDENCY_PATH = ROOT / "data" / "c4d-dependency-export.json"
RECOVERY_PATH = ROOT / "data" / "c4d-dependency-recovery.json"
PRODUCTION_RS_PATH = (
    ROOT / "data" / "c4d-production-redshift-confirmations-20260726.json"
)
DATED_COPY_AUDIT_PATH = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "strict-dated-copy-audits.json"
)
CANDIDATE_COPY_AUDIT_PATH = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "candidate-dated-copy-audits.json"
)
STRUCTURAL_RECOVERY_PATH = (
    ROOT / "data" / "c4d-structural-recoveries.json"
)
NTH_RECOVERY_PATH = (
    ROOT / "data" / "c4d-nth-running-recovery-20260726.json"
)
SHOT_AUTHORED_PROXY_PATH = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "CUT-008-022-030-shot-authored-proxy-diagnosis.json"
)
UNRESOLVED_CAMERA_RECOVERY_PATH = (
    ROOT / "data" / "c4d-unresolved-camera-recoveries-20260727.json"
)
MAINFRAME_RECOVERY_PATH = (
    ROOT
    / "data"
    / "mainframe-recovery-evidence-20260730"
    / "CUT-019-021-run-forward-proxy.json"
)
OUTPUT_JSON = ROOT / "data" / "c4d-clean-manifest-20260726.json"
PUBLIC_JSON = ROOT / "public" / "data" / "c4d-clean-manifest.json"
OUTPUT_MARKDOWN = ROOT / "data" / "c4d-clean-manifest-20260726.md"

C4DPY = (
    "/Applications/Maxon Cinema 4D 2026/c4dpy.app/Contents/MacOS/c4dpy"
)
AUDIT_SCRIPT = str(ROOT / "scripts" / "c4dpy_audit_dependencies.py")
MATRIX_SCRIPT = str(ROOT / "scripts" / "c4dpy_camera_matrix.py")
CURRENT_CODEX_SUFFIX = f"_codex_{datetime.now().strftime('%m%d%y')}"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path, cache: dict[Path, str]) -> str | None:
    if not path.is_file():
        return None
    if path in cache:
        return cache[path]
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    cache[path] = digest.hexdigest()
    return cache[path]


def normalized_stem(value: str) -> str:
    value = re.sub(
        r"_codex_\d{6}(?:_v\d+)?(?:_c4d2025)?$", "", value
    )
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def recovery_date(path: Path) -> tuple[int, int, int]:
    match = re.fullmatch(r"_codex_(\d{2})(\d{2})(\d{2})", path.name)
    if not match:
        return (0, 0, 0)
    month, day, year = (int(part) for part in match.groups())
    return (2000 + year, month, day)


def recovery_project(source_value: str | None) -> Path | None:
    if not source_value:
        return None
    source = Path(source_value)
    if any(
        re.fullmatch(r"_codex_\d{6}", part) for part in source.parts
    ) and source.is_file():
        return source
    target = normalized_stem(source.stem)
    candidates = []
    for recovery_dir in source.parent.glob("_codex_[0-9][0-9][0-9][0-9][0-9][0-9]"):
        if not recovery_dir.is_dir():
            continue
        candidates.extend(
            item
            for item in recovery_dir.glob("*.c4d")
            if normalized_stem(item.stem) == target
        )
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            recovery_date(item.parent),
            "_c4d2025" in item.stem,
            item.stat().st_mtime,
        )
    )
    return candidates[-1]


def first_node(cut: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next(
        (item for item in cut.get("lineage", []) if item.get("kind") == kind),
        None,
    )


def source_render(cut: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in cut.get("lineage", [])
            if item.get("kind") == "render_sequence"
            and item.get("evidence") == "confirmed"
        ),
        first_node(cut, "render_sequence"),
    )


def camera_proof(cut: dict[str, Any]) -> dict[str, Any] | None:
    proofs = [
        item
        for item in cut.get("lineage", [])
        if item.get("kind") == "camera_proof"
        and "rejected"
        not in str(
            item.get("proofStatus") or item.get("status") or ""
        ).casefold()
        and not item.get("crossShotHairUsed")
    ]
    preferred = (
        next(
            (item for item in proofs if item.get("primaryRecoveryProof")),
            None,
        )
        or next(
            (item for item in proofs if item.get("recoveryProof")),
            None,
        )
        or next(
            (item for item in proofs if item.get("redshiftProof")),
            None,
        )
        or (proofs[0] if proofs else None)
    )
    if not preferred:
        return None
    frame_source = next(
        (
            item
            for item in proofs
            if item.get("targetFrame") is not None
            and (
                not preferred.get("projectPath")
                or item.get("projectPath") == preferred.get("projectPath")
            )
        ),
        None,
    )
    label = str(preferred.get("label") or "")
    return {
        **preferred,
        "targetFrame": (
            preferred.get("targetFrame")
            if preferred.get("targetFrame") is not None
            else (frame_source or {}).get("targetFrame")
        ),
        "cameraName": label.split(" · ", 1)[0] if label else None,
    }


def canonical_target_frame(cut: dict[str, Any]) -> int | None:
    segment = next(
        (
            item
            for item in cut.get("sourceSegments", [])
            if item.get("canonical")
            and item.get("selectedFirstFrame") is not None
            and item.get("selectedLastFrame") is not None
        ),
        None,
    )
    if not segment:
        return None
    start = int(segment["selectedFirstFrame"])
    end = int(segment["selectedLastFrame"])
    return start + max(0, end - start) // 2


def render_log_camera_record(
    cut: dict[str, Any], project_path: str | None
) -> dict[str, Any] | None:
    if not project_path:
        return None
    node = next(
        (
            item
            for item in reversed(cut.get("lineage", []))
            if item.get("kind") == "camera"
            and item.get("renderLogPath")
            and str(item.get("projectPath") or item.get("path") or "")
            == project_path
        ),
        None,
    )
    if not node:
        return None
    return {
        "projectPath": project_path,
        "cameraName": node.get("label"),
        "cameraTake": node.get("take") or "Main",
        "cameraRenderData": node.get("renderData"),
        "targetFrame": canonical_target_frame(cut),
        "renderLogPath": node.get("renderLogPath"),
        "confirmationMethod": node.get("confirmationMethod"),
    }


def project_path_for(
    cut: dict[str, Any], strict: dict[str, Any] | None
) -> str | None:
    render_log_project = next(
        (
            item
            for item in cut.get("lineage", [])
            if item.get("kind") == "cinema4d"
            and item.get("sourceProjectFromRenderLog")
        ),
        None,
    )
    if render_log_project:
        return (
            str(
                render_log_project.get("projectPath")
                or render_log_project.get("path")
                or ""
            )
            or None
        )
    health = cut.get("c4dLinkStatus") or {}
    if health.get("projectPath"):
        return str(health["projectPath"])
    node = first_node(cut, "cinema4d")
    if node:
        return str(node.get("projectPath") or node.get("path") or "") or None
    if strict and strict.get("projectPath"):
        return str(strict["projectPath"])
    return None


def dependencies_for(
    project: dict[str, Any] | None, take_name: str
) -> list[dict[str, Any]]:
    if not project:
        return []
    takes = project.get("takes") or {}
    take = takes.get(take_name)
    if take is None and take_name == "Main":
        take = project.get("fullScene")
    if take is None:
        take = project.get("fullScene")
    return list((take or {}).get("dependencies") or [])


def missing_dependencies(
    project: dict[str, Any] | None,
    take_name: str,
    recoveries: dict[tuple[str, str], dict[str, Any]],
    project_path: str | None,
) -> list[dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    for item in dependencies_for(project, take_name):
        if item.get("exists") or item.get("renderEnabled") is False:
            continue
        filename = str(item.get("filename") or item.get("assetName") or "")
        owner = str(item.get("ownerPath") or item.get("owner") or "")
        key = (filename, owner)
        recovery = recoveries.get((project_path or "", filename)) or {}
        records[key] = {
            "requiredPath": filename,
            "ownerPath": owner or None,
            "ownerName": item.get("ownerName"),
            "category": item.get("category") or "other",
            "characterRelated": bool(item.get("characterRelated")),
            "exactCandidates": [
                str(candidate.get("path") or candidate)
                for candidate in recovery.get("candidates", [])
                if candidate
            ],
            "recoveryStatus": recovery.get("status"),
        }
    return sorted(
        records.values(),
        key=lambda item: (
            str(item.get("category") or ""),
            str(item.get("requiredPath") or ""),
            str(item.get("ownerPath") or ""),
        ),
    )


def group_missing_dependencies(
    missing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in missing:
        required = str(item.get("requiredPath") or "")
        group = groups.setdefault(
            required,
            {
                "requiredPath": required,
                "category": item.get("category") or "other",
                "ownerPaths": [],
                "characterRelated": False,
                "exactCandidates": [],
                "recoveryStatuses": [],
            },
        )
        owner = item.get("ownerPath")
        if owner and owner not in group["ownerPaths"]:
            group["ownerPaths"].append(owner)
        group["characterRelated"] = bool(
            group["characterRelated"] or item.get("characterRelated")
        )
        for candidate in item.get("exactCandidates") or []:
            if candidate not in group["exactCandidates"]:
                group["exactCandidates"].append(candidate)
        status = item.get("recoveryStatus")
        if status and status not in group["recoveryStatuses"]:
            group["recoveryStatuses"].append(status)
    return sorted(groups.values(), key=lambda item: item["requiredPath"])


def visual_from_structural(
    record: dict[str, Any],
) -> dict[str, Any]:
    elements = dict(record.get("elementReview") or {})
    statuses = set(elements.values())
    status = (
        "match"
        if statuses and statuses <= {"match", "not_visible"}
        else (
            "mismatch"
            if "mismatch" in statuses
            else "partial"
        )
    )
    notes = " ".join(record.get("remainingBlockers") or [])
    return {
        "status": status,
        "elements": elements,
        "notes": notes or record.get("detail"),
    }


def quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def recovery_steps(
    cut: dict[str, Any],
    strict: dict[str, Any] | None,
    project_path: str | None,
    recovery_path: Path | None,
    missing: list[dict[str, Any]],
    proof: dict[str, Any] | None,
    camera_record: dict[str, Any] | None,
    visual: dict[str, Any],
    original_proxy: dict[str, Any] | None,
) -> list[dict[str, str]]:
    health = cut.get("c4dLinkStatus") or {}
    state_verification = cut.get("c4dVerification") or {}
    blockers = list(
        state_verification.get("blockers")
        or (strict or {}).get("blockers")
        or []
    )
    take = str(
        (proof or {}).get("cameraTake")
        or health.get("take")
        or (camera_record or {}).get("cameraTake")
        or "Main"
    )
    frame = (
        (proof or {}).get("targetFrame")
        or (camera_record or {}).get("targetFrame")
    )
    render_data = str(
        (proof or {}).get("cameraRenderData")
        or (camera_record or {}).get("cameraRenderData")
        or ""
    )
    camera_name = str(
        (proof or {}).get("cameraName")
        or (camera_record or {}).get("cameraName")
        or (proof or {}).get("label")
        or "effective take camera"
    )
    proxy_runtime_blocked = visual.get("status") == "runtime_blocked"
    material_audit = dict(
        (proof or {}).get("materialCompatibilityAudit") or {}
    )
    material_runtime_blocked = bool(
        material_audit.get("status")
        in {
            "asset_missing",
            "rendered_visual_mismatch",
            "runtime_incompatible",
            "source_compatible_runtime_required",
            "source_runtime_required",
        }
    )
    steps: list[dict[str, str]] = []
    if (
        original_proxy
        and original_proxy.get("status")
        in {
            "shot_authored_full_character_proxy_missing",
            "shot_authored_proxy_cache_missing_authored_hierarchy_present",
        }
    ):
        proxies = list(original_proxy.get("authoritativeProxies") or [])
        if not proxies:
            proxies = [original_proxy]
        proxy_lines = []
        for proxy in proxies:
            proxy_lines.append(
                f"{proxy.get('filePath')} "
                f"({proxy.get('requiredFrames')}, "
                f"{proxy.get('frameRate')} fps, "
                f"offset {proxy.get('frameOffset')})"
            )
        evidence = str(
            original_proxy.get("evidence")
            or (
                "data/c4d-clean-recoveries/"
                "CUT-019-021-original-proxy-diagnosis.json"
            )
        )
        authored = dict(original_proxy.get("authoredSceneAssets") or {})
        steps.append(
            {
                "action": "restore_original_shot_proxy",
                "instruction": (
                    "Restore every complete shot-authored Redshift proxy "
                    "sequence from the original Mainframe source machine or "
                    f"backup: {'; '.join(proxy_lines)}. Preserve each exact "
                    "path, filename, frame range, fps, and offset. The shot "
                    f"already contains its own character root "
                    f"{authored.get('characterRoot') or 'recorded in the scene'} "
                    f"and hair object "
                    f"{authored.get('hairObject') or 'recorded in the scene'}. "
                    "Do not substitute a generic character or import, clone, "
                    f"or replace hair. Full evidence is in {evidence}."
                ),
            }
        )
    if not project_path:
        render = source_render(cut) or {}
        steps.append(
            {
                "action": "resolve_source_project",
                "instruction": (
                    "Find the C4D document whose saved Redshift output resolves "
                    f"to {render.get('path') or 'the canonical render directory'}; "
                    "do not accept a basename-only candidate."
                ),
            }
        )
        return steps
    if "dependency_audit_missing" in blockers:
        steps.append(
            {
                "action": "audit_dependencies",
                "instruction": (
                    f"{quote(C4DPY)} {quote(AUDIT_SCRIPT)} "
                    f"--project {quote(project_path)} --take {quote(take)}"
                ),
            }
        )
    if missing:
        groups = group_missing_dependencies(missing)
        file_lines = []
        for group in groups:
            candidates = group.get("exactCandidates") or []
            candidate_text = (
                "; exact candidates: " + " | ".join(candidates)
                if candidates
                else "; exact candidate: NONE IN INDEXED DROPBOX"
            )
            file_lines.append(
                f"{group['requiredPath']} "
                f"({len(group['ownerPaths'])} owner references"
                f"{candidate_text})"
            )
        steps.append(
            {
                "action": "relink_render_dependencies",
                "instruction": (
                    f"Resolve {len(groups)} distinct render-critical files "
                    f"across {len(missing)} owner references in "
                    f"projectAudits[{project_path!r}]."
                    "renderCriticalMissingDependencies: "
                    + " || ".join(file_lines)
                    + ". "
                    "Re-audit the same take and require zero render-critical "
                    "missing files."
                ),
            }
        )
    if not recovery_path:
        steps.append(
            {
                "action": "save_dated_copy",
                "instruction": (
                    f"After the audit passes, save {project_path} as "
                    f"{Path(project_path).parent / CURRENT_CODEX_SUFFIX / (Path(project_path).stem + CURRENT_CODEX_SUFFIX + '.c4d')}; "
                    "never overwrite the source project."
                ),
            }
        )
    if (
        "camera_proof_missing" in blockers
        or "camera_or_asset_visual_mismatch" in blockers
    ):
        output_dir = (
            ROOT
            / "public"
            / "archive"
            / "redshift-clean-recovery-20260726"
            / str(cut["id"])
        )
        matrix_command = (
            f"{quote(C4DPY)} {quote(MATRIX_SCRIPT)} "
            f"--project {quote(str(recovery_path or project_path))} "
            f"--frame {int(frame or 0)} --output-dir {quote(str(output_dir))} "
            f"--prefix {quote(str(cut['id']).replace('-', ''))} "
            f"--take {quote(take)}"
        )
        if render_data:
            matrix_command += f" --render-data {quote(render_data)}"
        steps.append(
            {
                "action": "render_camera_matrix",
                "instruction": (
                    matrix_command
                    + f"; compare every saved camera against {cut.get('thumbnail')}. "
                    f"The current named camera is {camera_name}."
                ),
            }
        )
        elements = visual.get("elements") or {}
        unresolved = [
            f"{key}={value}"
            for key, value in elements.items()
            if value not in {"match", "not_visible"}
        ]
        if unresolved:
            steps.append(
                {
                    "action": (
                        "revalidate_exact_authored_proxy"
                        if proxy_runtime_blocked
                        else "repair_visible_assets"
                    ),
                    "instruction": (
                        (
                            "Do not repair these states with replacement "
                            "assets. Update Redshift until the already-linked "
                            "exact in-shot proxy loads, then verify its authored "
                            "character, hair, wardrobe, and materials against "
                            "the historical render. Runtime-blocked states: "
                            if proxy_runtime_blocked
                            else (
                                (
                                    "Do not import or clone hair from another "
                                    "shot. Restore the original full-character "
                                    "proxy first, then verify its authored "
                                    "character, hair, wardrobe, and materials "
                                    "against the exact historical render. "
                                    "Remaining diagnostic states: "
                                )
                                if original_proxy
                                else (
                                    "Repair only the visible mismatches "
                                    "identified by the canonical thumbnail: "
                                )
                            )
                        )
                        + ", ".join(unresolved)
                        + "."
                    ),
                }
            )
    if material_runtime_blocked:
        explicit_prescription = str(
            (proof or {}).get("recoveryPrescription") or ""
        )
        production_runtime = str(
            material_audit.get("productionRuntime")
            or "the production-time Cinema 4D and Redshift build"
        )
        current_runtime = str(
            material_audit.get("currentRuntime")
            or "the currently installed runtime"
        )
        result_path = str(
            material_audit.get("resultPath")
            or "the recorded material-render diagnostic"
        )
        comparison_path = str(
            material_audit.get("comparisonPath")
            or cut.get("thumbnail")
            or "the canonical thumbnail"
        )
        remaining_asset_errors = [
            str(value)
            for value in material_audit.get("remainingAssetErrors") or []
            if value
        ]
        runtime_detail = str(
            material_audit.get("runtimeDetail") or ""
        )
        steps.append(
            {
                "action": "restore_compatible_redshift_material_runtime",
                "instruction": (
                    f"The exact shot geometry and camera are already linked, "
                    f"but {current_runtime} does not reproduce the authored "
                    f"material graphs. Reopen the dated project with "
                    f"{production_runtime}, including the matching built-in "
                    "Redshift node database and required production plugins; "
                    "do not rebuild materials from another shot. Re-render "
                    f"frame {int(frame or 0)} from take {take}, camera "
                    f"{camera_name}, render data "
                    f"{render_data or 'the take-effective Redshift setting'}. "
                    f"Compare against {comparison_path}; the current rejected "
                    f"diagnostic is {result_path}. "
                    + (
                        "Restore these exact production assets or plugin "
                        "implementations: "
                        + " | ".join(remaining_asset_errors)
                        + ". "
                        if remaining_asset_errors
                        else ""
                    )
                    + (
                        f"Recorded runtime diagnosis: {runtime_detail}"
                        if runtime_detail
                        else ""
                    )
                    + (
                        f" Exact shot-specific procedure: "
                        f"{explicit_prescription}"
                        if explicit_prescription
                        else ""
                    )
                ),
            }
        )
    steps.append(
        {
            "action": "redshift_gate",
            "instruction": (
                (
                    "After updating Redshift to a build that reads proxy mesh "
                    "format 49, render the existing exact in-shot proxy at the "
                    "same frame "
                    if proxy_runtime_blocked
                    else "Render now with Redshift at the same frame "
                )
                + f"from take {take}, camera {camera_name}, render data "
                + f"{render_data or 'the take-effective Redshift setting'}. "
                + (
                    "Do not enable a different character or import hair. "
                    if proxy_runtime_blocked
                    else ""
                )
                + "Visually compare location, camera, character, hair, "
                "wardrobe, and materials to the canonical thumbnail."
            ),
        }
    )
    return steps


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Paracosm C4D clean manifest",
        "",
        f"Generated: {payload['generatedAt']}",
        "",
        "## Verified clean Redshift list",
        "",
        "| Cut | Chapter | Source project | Dated clean copy | Frame | Camera |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for item in payload["records"]:
        if item["status"] != "clean_strict_redshift_confirmed":
            continue
        lines.append(
            "| {cutId} | {sectionCode} | `{sourceProjectPath}` | "
            "`{recoveryProjectPath}` | {targetFrame} | {cameraName} |".format(
                **{
                    **item,
                    "targetFrame": item.get("targetFrame") or "",
                    "cameraName": item.get("cameraName") or "",
                }
            )
        )
    lines.extend(
        [
            "",
            "## Global Redshift runtime prerequisite",
            "",
        ]
    )
    for step in payload["globalRedshiftPrerequisite"]["checklist"]:
        lines.append(f"- {step}")
    lines.extend(["", "## Remaining per-cut prescriptions", ""])
    for item in payload["records"]:
        if item["status"] == "clean_strict_redshift_confirmed":
            continue
        lines.extend(
            [
                f"### {item['cutId']} · {item.get('sectionCode') or '-'}",
                "",
                f"- Source project: `{item.get('sourceProjectPath') or 'UNRESOLVED'}`",
                f"- Source render: `{item.get('sourceRenderPath') or 'UNRESOLVED'}`",
                f"- Camera proof: `{item.get('cameraProofPath') or 'MISSING'}`",
                f"- Canonical thumbnail: `{item.get('thumbnail')}`",
                f"- Blockers: {', '.join(item.get('blockers') or ['none recorded'])}",
            ]
        )
        for step in item.get("checklist") or []:
            lines.append(f"- [{step['action']}] {step['instruction']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    state = load(STATE_PATH)
    strict_archive = load(STRICT_PATH)
    camera_archive = load(CAMERA_PROOF_PATH)
    dependency_archive = load(DEPENDENCY_PATH)
    recovery_archive = load(RECOVERY_PATH)
    production_archive = load(PRODUCTION_RS_PATH)
    dated_copy_archive = load(DATED_COPY_AUDIT_PATH)
    candidate_copy_archive = load(CANDIDATE_COPY_AUDIT_PATH)
    structural_archive = load(STRUCTURAL_RECOVERY_PATH)
    nth_archive = load(NTH_RECOVERY_PATH)
    shot_proxy_archive = load(SHOT_AUTHORED_PROXY_PATH)
    unresolved_camera_archive = load(UNRESOLVED_CAMERA_RECOVERY_PATH)
    mainframe_recovery_archive = (
        load(MAINFRAME_RECOVERY_PATH)
        if MAINFRAME_RECOVERY_PATH.is_file()
        else {}
    )
    mainframe_recovered_cut_ids = {
        str(record.get("cutId"))
        for record in mainframe_recovery_archive.get(
            "freshRenderProofs", []
        )
        if record.get("cutId")
        and bool(
            (mainframe_recovery_archive.get("macRecovery") or {}).get(
                "c4dRelinkVerified"
            )
        )
        and bool(
            (mainframe_recovery_archive.get("macRecovery") or {}).get(
                "freshRenderVerified"
            )
        )
    }

    strict_by_cut = {
        str(item.get("cutId")): item
        for item in strict_archive.get("records", [])
    }
    camera_by_cut = {
        str(cut_id): proof
        for proof in camera_archive.get("proofs", [])
        for cut_id in proof.get("cutIds", [])
    }
    projects = {
        str(item.get("projectPath") or ""): item
        for item in dependency_archive.get("projects", [])
    }
    recoveries = {
        (
            str(item.get("projectPath") or ""),
            str(item.get("requiredPath") or ""),
        ): item
        for item in recovery_archive.get("projectDependencies", [])
    }
    production_by_cut = {
        str(item.get("cutId")): item
        for item in production_archive.get("records", [])
    }
    dated_copy_audits = {
        str(Path(str(item["recoveryProject"])).expanduser().resolve()): item
        for item in dated_copy_archive.get("projects", [])
        if item.get("recoveryProject")
    }
    candidate_copy_audits = {
        str(Path(str(item["recoveryProject"])).expanduser().resolve()): item
        for item in candidate_copy_archive.get("projects", [])
        if item.get("recoveryProject")
    }
    audited_recovery_by_source = {
        str(Path(str(item["sourceProject"])).expanduser().resolve()): Path(
            str(item["recoveryProject"])
        ).expanduser().resolve()
        for archive in (dated_copy_archive, candidate_copy_archive)
        for item in archive.get("projects", [])
        if item.get("sourceProject")
        and item.get("recoveryProject")
        and not item.get("cutIds")
    }
    audited_recovery_by_source_cut = {
        (
            str(Path(str(item["sourceProject"])).expanduser().resolve()),
            str(cut_id),
        ): Path(str(item["recoveryProject"])).expanduser().resolve()
        for archive in (dated_copy_archive, candidate_copy_archive)
        for item in archive.get("projects", [])
        if item.get("sourceProject") and item.get("recoveryProject")
        for cut_id in item.get("cutIds") or []
    }
    structural_by_cut = {
        str(item.get("cutId")): item
        for item in structural_archive.get("records", [])
    }
    nth_by_cut = {
        str(item.get("cutId")): item
        for item in nth_archive.get("records", [])
    }
    unresolved_camera_by_cut = {
        str(item.get("cutId")): item
        for item in unresolved_camera_archive.get("records", [])
        if item.get("cutId")
    }
    nth_recovery = Path(str(nth_archive.get("recoveryProject") or ""))
    nth_original_proxy = dict(
        nth_archive.get("originalProxyDiagnosis") or {}
    )
    shot_proxy_by_cut: dict[str, dict[str, Any]] = {}
    shot_proxy_evidence = (
        "data/c4d-clean-recoveries/"
        "CUT-008-022-030-shot-authored-proxy-diagnosis.json"
    )
    for project_record in shot_proxy_archive.get("projects", []):
        proxies = list(project_record.get("authoritativeProxies") or [])
        primary = dict(proxies[0]) if proxies else {}
        missing_file_count = 0
        for proxy in proxies:
            frame_range = str(proxy.get("requiredFrames") or "")
            match = re.fullmatch(r"(\d+)-(\d+)", frame_range)
            missing_file_count += (
                int(match.group(2)) - int(match.group(1)) + 1
                if match
                else 1
            )
        gate = {
            **primary,
            "status": project_record.get("status"),
            "sourceProject": project_record.get("sourceProject"),
            "authoritativeProxies": proxies,
            "authoredSceneAssets": project_record.get(
                "authoredSceneAssets"
            ),
            "missingFileCount": missing_file_count,
            "crossShotHairAllowed": False,
            "evidence": shot_proxy_evidence,
        }
        for cut_id in project_record.get("cutIds", []):
            shot_proxy_by_cut[str(cut_id)] = gate
    hash_cache: dict[Path, str] = {}
    project_audits: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()

    for cut in state.get("cuts", []):
        if cut.get("isGap"):
            continue
        cut_id = str(cut["id"])
        unresolved_camera = unresolved_camera_by_cut.get(cut_id)
        strict = strict_by_cut.get(cut_id)
        health = cut.get("c4dLinkStatus") or {}
        state_verification = cut.get("c4dVerification") or {}
        project_path = project_path_for(cut, strict)
        if (
            strict
            and project_path
            and strict.get("projectPath")
            and str(strict.get("projectPath")) != project_path
        ):
            strict = None
        project = projects.get(project_path or "")
        take = str(health.get("take") or "Main")
        missing = missing_dependencies(
            project, take, recoveries, project_path
        )
        nth_record = nth_by_cut.get(cut_id)
        if (
            nth_record
            and project_path
            and normalized_stem(Path(project_path).stem)
            != normalized_stem(nth_recovery.stem)
        ):
            nth_record = None
        original_proxy = (
            shot_proxy_by_cut.get(cut_id)
            or (nth_original_proxy if nth_record else None)
        )
        if cut_id in mainframe_recovered_cut_ids:
            recovered_dependency = dict(
                mainframe_recovery_archive.get("dependency") or {}
            )
            original_proxy = {
                **(original_proxy or {}),
                "status": "verified_rendered",
                "objectPath": recovered_dependency.get("objectName"),
                "filePath": (
                    str(recovered_dependency.get("sourceRoot") or "")
                    + "\\"
                    + str(
                        recovered_dependency.get("filenamePattern") or ""
                    ).replace("%04d", "0000")
                ),
                "requiredFrames": (
                    f"{int(recovered_dependency.get('firstFrame') or 0):04d}-"
                    f"{int(recovered_dependency.get('lastFrame') or 0):04d}"
                ),
                "missingFileCount": 0,
                "localSearchStatus": "recovered_and_sha256_verified",
                "evidence": str(
                    MAINFRAME_RECOVERY_PATH.relative_to(ROOT)
                ),
                "crossShotHairAllowed": False,
            }
        original_proxy_missing = bool(
            original_proxy
            and original_proxy.get("status")
            in {
                "shot_authored_full_character_proxy_missing",
                "shot_authored_proxy_cache_missing_authored_hierarchy_present",
            }
        )
        structural_record = structural_by_cut.get(cut_id)
        resolved_project_path = (
            str(Path(project_path).expanduser().resolve())
            if project_path
            else ""
        )
        discovered_recovery = recovery_project(project_path)
        discovered_recovery_audit = (
            (
                dated_copy_audits.get(str(discovered_recovery.resolve()))
                or candidate_copy_audits.get(
                    str(discovered_recovery.resolve())
                )
            )
            if discovered_recovery and discovered_recovery.is_file()
            else None
        )
        if (
            discovered_recovery_audit
            and discovered_recovery_audit.get("cutIds")
            and cut_id
            not in {
                str(value)
                for value in discovered_recovery_audit.get("cutIds") or []
            }
        ):
            discovered_recovery = None
        recovery = (
            nth_recovery
            if nth_record and nth_recovery.is_file()
            else (
                audited_recovery_by_source_cut.get(
                    (resolved_project_path, cut_id)
                )
                or audited_recovery_by_source.get(resolved_project_path)
            )
            or discovered_recovery
        )
        recovery_audit = (
            (
                dated_copy_audits.get(str(recovery.resolve()))
                or candidate_copy_audits.get(str(recovery.resolve()))
            )
            if recovery and recovery.is_file()
            else None
        )
        proof = camera_proof(cut)
        stale_project_proof = bool(
            proof
            and project_path
            and proof.get("projectPath")
            and str(proof.get("projectPath")) != project_path
        )
        if stale_project_proof:
            proof = None
        state_linkage = dict(
            (proof or {}).get("linkageAudit")
            or state_verification.get("linkageAudit")
            or health
        )
        state_linkage_counts_present = bool(
            "renderCriticalMissingReferences" in state_linkage
            or "renderCriticalMissingFiles" in state_linkage
        )
        state_linkage_render_safe = bool(
            state_linkage_counts_present
            and int(
                state_linkage.get("renderCriticalMissingReferences") or 0
            )
            == 0
            and int(
                state_linkage.get("renderCriticalMissingFiles") or 0
            )
            == 0
        )
        camera_record = (
            render_log_camera_record(cut, project_path)
            or camera_by_cut.get(cut_id)
        )
        recovery_visual_gate = dict(
            (recovery_audit or {}).get("visualGate") or {}
        )
        recovery_visual_passed = bool(
            recovery_visual_gate.get("status") == "passed"
        )
        recovery_redshift_proof = dict(
            (recovery_audit or {}).get("redshiftProof") or {}
        )
        recovery_redshift_image = Path(
            str(recovery_redshift_proof.get("imagePath") or "")
        ).expanduser()
        recovery_redshift_confirmed = bool(
            recovery_redshift_proof.get("status") == "confirmed"
            and recovery_redshift_image.is_file()
        )
        if recovery_visual_passed:
            audit_frame = recovery_audit.get("targetFrame")
            audit_camera = recovery_audit.get("cameraName")
            audit_camera_path = recovery_audit.get("cameraObjectPath")
            audit_take = recovery_audit.get("cameraTake") or "Main"
            audit_render_data = recovery_audit.get("cameraRenderData")
            proof = {
                **(proof or {}),
                "label": f"{audit_camera} · frame {audit_frame}",
                "projectPath": project_path,
                "comparisonImage": (
                    recovery_redshift_proof.get("publicPath")
                    or recovery_redshift_proof.get("imagePath")
                ),
                "confirmationMethod": (
                    "Fresh Redshift render from dated exact-relink copy"
                ),
                "evidence": "confirmed",
                "proofStatus": "confirmed",
                "targetFrame": audit_frame,
                "cameraName": audit_camera,
                "cameraTake": audit_take,
                "cameraRenderData": audit_render_data,
                "redshiftProof": recovery_redshift_confirmed,
                "redshiftSourceImage": (
                    recovery_redshift_proof.get("publicPath")
                    or recovery_redshift_proof.get("imagePath")
                ),
                "strictLinked": recovery_redshift_confirmed,
                "visualVerificationStatus": "match",
            }
            camera_record = {
                **(camera_record or {}),
                "projectPath": project_path,
                "cameraName": audit_camera,
                "cameraObjectPath": audit_camera_path,
                "cameraTake": audit_take,
                "cameraRenderData": audit_render_data,
                "targetFrame": audit_frame,
            }
        if (
            camera_record
            and project_path
            and camera_record.get("projectPath")
            and str(camera_record.get("projectPath")) != project_path
        ):
            camera_record = None
        if (
            camera_record
            and (proof or {}).get("targetFrame") is not None
            and camera_record.get("targetFrame") is not None
            and int(camera_record.get("targetFrame"))
            != int((proof or {}).get("targetFrame"))
        ):
            camera_record = None
        recovery_validation_frame = (
            recovery_audit.get("targetFrame") if recovery_audit else None
        )
        if (
            recovery_audit
            and recovery_audit.get("targetFrame") is not None
            and (proof or {}).get("targetFrame") is None
        ):
            proof = {
                **(proof or {}),
                "targetFrame": recovery_audit.get("targetFrame"),
            }
            camera_record = {
                **(camera_record or {}),
                "cameraName": recovery_audit.get("cameraName"),
                "cameraObjectPath": recovery_audit.get(
                    "cameraObjectPath"
                ),
                "cameraGuid": recovery_audit.get("cameraGuid"),
                "cameraTake": recovery_audit.get("cameraTake"),
                "cameraRenderData": recovery_audit.get(
                    "cameraRenderData"
                ),
                "targetFrame": recovery_audit.get("targetFrame"),
            }
        if nth_record and not proof:
            camera_record = {
                **(camera_record or {}),
                "cameraName": nth_record.get("cameraName"),
                "cameraTake": nth_record.get("cameraTake"),
                "cameraRenderData": nth_record.get("cameraRenderData"),
                "targetFrame": nth_record.get("targetFrame"),
            }
        production_record = production_by_cut.get(cut_id) or {}
        production_matches_project = bool(
            production_record.get("status") == "confirmed"
            and (
                not project_path
                or not production_record.get("projectPath")
                or str(production_record.get("projectPath")) == project_path
            )
        )
        redshift_confirmed = bool(
            production_matches_project
            or (proof or {}).get("redshiftProof")
            or recovery_redshift_confirmed
        )
        is_strict = bool(
            (
                (strict or {}).get("strictLinked")
                or health.get("strictLinked")
                or state_verification.get("strictLinked")
                or (
                    recovery_visual_passed
                    and recovery_redshift_confirmed
                    and int(
                        (recovery_audit or {}).get(
                            "renderCriticalMissingReferences"
                        )
                        or 0
                    )
                    == 0
                    and int(
                        (recovery_audit or {}).get(
                            "renderCriticalMissingFiles"
                        )
                        or 0
                    )
                    == 0
                )
            )
            and not original_proxy_missing
        )
        original = Path(project_path) if project_path else None
        original_hash = (
            sha256(original, hash_cache)
            if is_strict and original and original.is_file()
            else None
        )
        recovery_hash = (
            sha256(recovery, hash_cache)
            if is_strict and recovery and recovery.is_file()
            else None
        )
        recovery_byte_identical = bool(
            original_hash
            and recovery_hash
            and original_hash == recovery_hash
        )
        recovery_matches_active_project = bool(
            recovery
            and project_path
            and recovery.is_file()
            and recovery.resolve()
            == Path(project_path).expanduser().resolve()
        )
        recovery_render_safe = bool(
            (
                recovery_audit
                and recovery_audit.get("renderSafe")
                and int(
                    recovery_audit.get(
                        "renderCriticalMissingReferences"
                    )
                    or 0
                )
                == 0
                and int(
                    recovery_audit.get("renderCriticalMissingFiles") or 0
                )
                == 0
            )
            or (
                recovery_matches_active_project
                and state_linkage_render_safe
            )
        )
        effective_recovery_audit = recovery_audit
        if (
            not effective_recovery_audit
            and recovery_matches_active_project
            and state_linkage_counts_present
        ):
            effective_recovery_audit = {
                "status": health.get("status")
                or "state_linkage_audit",
                "renderSafe": state_linkage_render_safe,
                "projectPath": project_path,
                "take": (
                    (proof or {}).get("cameraTake")
                    or health.get("take")
                    or "Main"
                ),
                "dependencyAuditPath": (
                    (proof or {}).get("dependencyAuditPath")
                    or state_verification.get("dependencyAuditPath")
                ),
                "dependencyReferences": state_linkage.get(
                    "dependencyReferences"
                ),
                "linkedReferences": state_linkage.get(
                    "linkedReferences"
                ),
                "missingReferences": state_linkage.get(
                    "missingReferences"
                ),
                "renderCriticalMissingReferences": int(
                    state_linkage.get(
                        "renderCriticalMissingReferences"
                    )
                    or 0
                ),
                "renderCriticalMissingFiles": int(
                    state_linkage.get("renderCriticalMissingFiles") or 0
                ),
                "source": (
                    "current canonical state linkage audit for the same "
                    "dated recovery project"
                ),
            }
        recovery_proxy_gate = dict(
            (recovery_audit or {}).get("originalProxyGate") or {}
        )
        proxy_runtime_incompatible = bool(
            recovery_proxy_gate.get("status")
            == "exact_shot_proxy_linked_runtime_incompatible"
        )
        if (
            is_strict
            and redshift_confirmed
            and recovery
            and recovery_render_safe
        ):
            status = "clean_strict_redshift_confirmed"
        elif recovery:
            status = "candidate_recovery_present"
        else:
            status = "fallback_required"
        blockers = list(
            state_verification.get("blockers")
            or (strict or {}).get("blockers")
            or []
        )
        if recovery_render_safe or state_linkage_render_safe:
            blockers = [
                blocker
                for blocker in blockers
                if blocker != "render_critical_dependencies_missing"
            ]
        if recovery_visual_passed and recovery_redshift_confirmed:
            blockers = [
                blocker
                for blocker in blockers
                if blocker
                not in {
                    "source_project_missing",
                    "dependency_audit_missing",
                    "camera_proof_missing",
                    "camera_or_asset_visual_mismatch",
                    "production_redshift_proof_missing",
                }
            ]
        if original_proxy_missing:
            blockers.append("shot_authored_proxy_missing")
        if stale_project_proof:
            blockers.append("camera_proof_missing")
        if proxy_runtime_incompatible:
            blockers.append("redshift_proxy_runtime_incompatible")
        if is_strict and not redshift_confirmed:
            blockers.append("production_redshift_proof_missing")
        if is_strict and not recovery:
            blockers.append("dated_codex_copy_missing")
        if (
            is_strict
            and recovery
            and not recovery_audit
            and not state_linkage_render_safe
        ):
            blockers.append("dated_codex_copy_audit_missing")
        if is_strict and recovery_audit and not recovery_render_safe:
            blockers.append("dated_codex_copy_render_dependencies_missing")
        blockers = list(dict.fromkeys(blockers))
        if project_path and project_path not in project_audits:
            audit_missing = (
                []
                if recovery_render_safe or state_linkage_render_safe
                else list(missing)
            )
            if original_proxy_missing:
                original_proxies = list(
                    original_proxy.get("authoritativeProxies") or []
                )
                if not original_proxies:
                    original_proxies = [original_proxy]
                for proxy in original_proxies:
                    audit_missing.append(
                        {
                            "requiredPath": proxy.get("filePath"),
                            "ownerPath": proxy.get("objectPath"),
                            "ownerName": Path(
                                str(proxy.get("objectPath") or "")
                            ).name,
                            "category": "redshift_proxy_sequence",
                            "characterRelated": True,
                            "exactCandidates": [],
                            "recoveryStatus": "not_found_locally",
                            "requiredFrames": proxy.get("requiredFrames"),
                            "frameRate": proxy.get("frameRate"),
                            "frameOffset": proxy.get("frameOffset"),
                            "crossShotHairAllowed": False,
                        }
                    )
            project_audits[project_path] = {
                "projectPath": project_path,
                "take": take,
                "dependencyAuditPresent": bool(project),
                "dependencyStatus": (
                    original_proxy.get("status")
                    if original_proxy_missing
                    else (
                        "render_safe_with_noncritical_warnings"
                        if recovery_render_safe
                        else health.get("status")
                    )
                ),
                "renderCriticalMissingFiles": (
                    int(original_proxy.get("missingFileCount") or 212)
                    if original_proxy_missing
                    else len(
                        {item["requiredPath"] for item in audit_missing}
                    )
                ),
                "renderCriticalMissingReferences": len(audit_missing),
                "renderCriticalMissingDependencies": audit_missing,
                "renderCriticalMissingFileGroups": (
                    group_missing_dependencies(audit_missing)
                ),
            }

        render = source_render(cut) or {}
        camera_name = (
            (proof or {}).get("cameraName")
            or (camera_record or {}).get("cameraName")
            or (proof or {}).get("label")
        )
        target_frame = (
            (proof or {}).get("targetFrame")
            or (camera_record or {}).get("targetFrame")
        )
        visual_review = (
            (proof or {}).get("visualReview")
            or (strict or {}).get("visualReview")
            or {
                "status": state_verification.get("status"),
                "elements": state_verification.get("elements") or {},
                "notes": state_verification.get("notes"),
            }
        )
        if nth_record and not proof:
            visual_review = {
                "status": nth_record.get("visualStatus"),
                "elements": nth_record.get("elements") or {},
                "notes": nth_record.get("notes"),
            }
        if structural_record:
            visual_review = visual_from_structural(structural_record)
        if recovery_visual_passed:
            visual_review = {
                "status": "match",
                "elements": dict(
                    recovery_visual_gate.get("elements") or {}
                ),
                "notes": recovery_visual_gate.get("notes"),
            }
        if original_proxy_missing:
            authored = dict(
                original_proxy.get("authoredSceneAssets") or {}
            )
            visual_review = {
                "status": (
                    "exact_proxy_missing_authored_hierarchy_present"
                    if authored
                    else "exact_shot_proxy_missing"
                ),
                "elements": {
                    "location": "historical_render_confirmed",
                    "camera": "source_take_camera_identified",
                    "character": "authored_in_shot_proxy_cache_missing",
                    "hair": "authored_in_shot_proxy_cache_missing",
                    "wardrobe": "authored_in_shot_proxy_cache_missing",
                    "materials": "fresh_redshift_proof_required",
                },
                "notes": (
                    "The source project already contains its own authored "
                    f"character root {authored.get('characterRoot') or 'and proxy'}"
                    f", hair {authored.get('hairObject') or 'inside that shot'}, "
                    f"and wardrobe {authored.get('wardrobeObject') or 'inside that shot'}. "
                    "The render-time Redshift proxy cache is absent locally. "
                    "Restore that exact cache or validate the disabled in-shot "
                    "authored hierarchy. Never import or substitute hair."
                ),
            }
        if proxy_runtime_incompatible:
            visual_review = {
                "status": "runtime_blocked",
                "elements": {
                    "location": "historical_match_fresh_proxy_blocked",
                    "camera": "historical_family_match_fresh_proxy_blocked",
                    "character": "authored_in_exact_proxy_runtime_blocked",
                    "hair": "authored_in_exact_proxy_runtime_blocked",
                    "wardrobe": "authored_in_exact_proxy_runtime_blocked",
                    "materials": "authored_in_exact_proxy_runtime_blocked",
                },
                "notes": (
                    "The exact Group/RS Proxy contains character, curled hair, "
                    "and patchwork wardrobe. Redshift 2026.1.1 cannot load "
                    "proxy mesh format 49; update the renderer and revalidate "
                    "the existing proxy. Do not import or substitute hair."
                ),
            }
        record = {
            "cutId": cut_id,
            "index": cut.get("index"),
            "sectionCode": cut.get("sectionCode"),
            "plannedShotId": cut.get("plannedShotId"),
            "thumbnail": cut.get("thumbnail"),
            "status": status,
            "strictLinked": is_strict,
            "productionRedshiftConfirmed": redshift_confirmed,
            "sourceProjectPath": project_path,
            "sourceProjectExists": bool(original and original.is_file()),
            "sourceRenderPath": render.get("path"),
            "cameraProofPath": (
                nth_record.get("publicPath")
                if nth_record
                else (proof or {}).get("comparisonImage")
            ),
            "cameraName": camera_name,
            "cameraObjectPath": (
                (proof or {}).get("cameraObjectPath")
                or (camera_record or {}).get("cameraObjectPath")
            ),
            "cameraTake": (
                (proof or {}).get("cameraTake")
                or (camera_record or {}).get("cameraTake")
                or take
            ),
            "cameraRenderData": (
                (proof or {}).get("cameraRenderData")
                or (camera_record or {}).get("cameraRenderData")
            ),
            "targetFrame": target_frame,
            "recoveryValidationFrame": recovery_validation_frame,
            "dependencyStatus": (
                original_proxy.get("status")
                if original_proxy_missing
                else (
                    "render_safe_with_noncritical_warnings"
                    if recovery_render_safe
                    else health.get("status") or "audit_unavailable"
                )
            ),
            "renderCriticalMissingFiles": (
                int(original_proxy.get("missingFileCount") or 212)
                if original_proxy_missing
                else (
                    0
                    if recovery_render_safe or state_linkage_render_safe
                    else int(
                        health.get("renderCriticalMissingFiles")
                        or len(missing)
                    )
                )
            ),
            "renderCriticalMissingReferences": (
                int(original_proxy.get("missingFileCount") or 212)
                if original_proxy_missing
                else (
                    0
                    if recovery_render_safe or state_linkage_render_safe
                    else int(
                        health.get("renderCriticalMissingReferences")
                        or len(missing)
                    )
                )
            ),
            "projectAuditRef": project_path,
            "visualReview": visual_review,
            "materialCompatibilityAudit": (
                (proof or {}).get("materialCompatibilityAudit")
            ),
            "recoveryPrescription": (
                (proof or {}).get("recoveryPrescription")
            ),
            "blockers": blockers,
            "recoveryProjectPath": str(recovery) if recovery else None,
            "recoveryProjectExists": bool(recovery and recovery.is_file()),
            "sourceProjectSha256": original_hash,
            "recoveryProjectSha256": recovery_hash,
            "recoveryByteIdentical": recovery_byte_identical,
            "recoveryCopyRelationship": (
                (recovery_audit or {}).get("copyRelationship")
            ),
            "recoveryDependencyAudit": effective_recovery_audit,
            "recoveryRenderSafe": recovery_render_safe,
            "originalProxyGate": (
                {
                    **original_proxy,
                    "evidence": (
                        original_proxy.get("evidence")
                        or (
                            "data/c4d-clean-recoveries/"
                            "CUT-019-021-original-proxy-diagnosis.json"
                        )
                    ),
                    "crossShotHairAllowed": False,
                }
                if original_proxy
                else recovery_proxy_gate or None
            ),
            "checklist": (
                []
                if status == "clean_strict_redshift_confirmed"
                else (
                    (
                        [
                            {
                                "action": (
                                    "update_redshift_proxy_compatibility"
                                ),
                                "instruction": (
                                    "The exact in-shot Group/RS Proxy is linked "
                                    "and contains the authored character, curled "
                                    "hair, and patchwork wardrobe. Redshift "
                                    "2026.1.1 omits it because proxy mesh format "
                                    "49 is newer than renderer format 47. Save or "
                                    "discard the unsaved Cinema 4D document "
                                    "'Untitled 1 *', quit both C4D versions, update "
                                    "Redshift to 2026.8.0 in Maxon App, then run "
                                    "redshiftCmdLine -fileinfo against proxy frame "
                                    "0220 and require a successful load. Do not "
                                    "import hair or enable another character."
                                ),
                            }
                        ]
                        if proxy_runtime_incompatible
                        else []
                    )
                    + recovery_steps(
                        cut,
                        strict,
                        project_path,
                        recovery,
                        (
                            []
                            if recovery_render_safe
                            or state_linkage_render_safe
                            else missing
                        ),
                        proof,
                        camera_record,
                        visual_review,
                        original_proxy,
                    )
                )
            ),
        }
        if unresolved_camera:
            unresolved_checks = unresolved_camera.get("checks") or {}
            unresolved_production = (
                unresolved_camera.get("productionRender") or {}
            )
            unresolved_canonical = (
                unresolved_camera.get("canonical") or {}
            )
            record.update(
                {
                    "status": "fallback_required",
                    "strictLinked": False,
                    "productionRedshiftConfirmed": bool(
                        unresolved_checks.get(
                            "productionRenderConfirmed"
                        )
                    ),
                    "sourceProjectPath": (
                        unresolved_camera.get("candidateProject") or {}
                    ).get("path"),
                    "sourceProjectExists": bool(
                        Path(
                            str(
                                (
                                    unresolved_camera.get(
                                        "candidateProject"
                                    )
                                    or {}
                                ).get("path")
                                or ""
                            )
                        ).is_file()
                    ),
                    "sourceRenderPath": unresolved_canonical.get(
                        "sourceRenderPath"
                    ),
                    "cameraProofPath": unresolved_camera.get(
                        "comparisonPath"
                    ),
                    "cameraName": "Production camera state missing",
                    "cameraTake": unresolved_production.get("take")
                    or "Main",
                    "targetFrame": unresolved_canonical.get(
                        "targetFrame"
                    ),
                    "dependencyStatus": (
                        "withheld_until_exact_render_time_state_recovered"
                    ),
                    "renderCriticalMissingFiles": 0,
                    "projectAuditRef": (
                        unresolved_camera.get("candidateProject") or {}
                    ).get("path"),
                    "visualReview": unresolved_camera.get(
                        "visualReview"
                    ),
                    "blockers": unresolved_camera.get("blockers") or [],
                    "recoveryProjectPath": None,
                    "recoveryProjectExists": False,
                    "recoveryDependencyAudit": None,
                    "recoveryRenderSafe": False,
                    "recoveryEvidencePath": (
                        "data/"
                        "c4d-unresolved-camera-recoveries-20260727.json"
                    ),
                    "retentionFinding": unresolved_camera.get(
                        "retentionFinding"
                    ),
                    "checklist": [
                        {
                            "action": (
                                "recover_exact_render_time_camera_state"
                            ),
                            "instruction": instruction,
                        }
                        for instruction in (
                            unresolved_camera.get("remediation") or []
                        )
                    ],
                }
            )
        status_counts[str(record["status"])] += 1
        blocker_counts.update(record.get("blockers") or [])
        records.append(record)

    global_prerequisite = {
        "status": "redshift_update_required_for_proxy_mesh_v49",
        "scope": (
            "Cinema 4D 2025 can render on the Redshift CPU device after "
            "enabling HybridRendering, but Redshift 2026.1.1 cannot load "
            "shot proxies exported as mesh format 49. Historical node graphs "
            "can also load as dummy assets in Cinema 4D 2026."
        ),
        "observedFailure": (
            "CUT-062 now enters Redshift on CPU, but Group/RS Proxy is omitted: "
            "'Mesh version mismatch. Found version 49, current version is 47.' "
            "The installed Metal kernels are also missing, so the Apple M2 "
            "Ultra GPU remains unavailable. Maxon App offers Redshift 2026.8.0."
        ),
        "maxonApp": {
            "installedVersion": "2026.1.0",
            "availableVersion": "2026.5.0",
            "application": "/Applications/Maxon.app",
            "installHelper": (
                "/Library/PrivilegedHelperTools/net.maxon.installhelper"
            ),
            "launchDaemon": (
                "/Library/LaunchDaemons/net.maxon.installhelper.plist"
            ),
            "installHelperObserved": False,
            "registrationError": "0xc754877a0",
        },
        "redshift": {
            "installedVersion": "2026.1.1",
            "availableVersion": "2026.8.0",
            "root": "/Applications/redshift",
            "expectedKernelRoot": "/Applications/redshift/GPUKernels",
        },
        "checklist": [
            "Save or discard the unsaved Cinema 4D 2026 document 'Untitled 1 *'; do not let the updater close it unsafely.",
            "Quit Cinema 4D 2025, Cinema 4D 2026, and Maxon App.",
            "Update /Applications/Maxon.app from 2026.1.0 to 2026.5.0. If the updater stalls again, reinstall the signed Maxon App so net.maxon.installhelper is registered.",
            "Verify /Library/PrivilegedHelperTools/net.maxon.installhelper and /Library/LaunchDaemons/net.maxon.installhelper.plist exist.",
            "In Maxon App, run Cinema 4D > Install Missing Components and update Redshift from 2026.1.1 to 2026.8.0.",
            "Verify /Applications/redshift/GPUKernels exists and a new Redshift log no longer reports either the M2 Ultra kernel-file error or proxy mesh-version 49 versus 47.",
            "Run /Applications/redshift/bin/redshiftCmdLine -fileinfo against CUT-062 proxy frame 0220 and require a successful load before repeating the shot proof.",
            "Render CUT-062 from its exact Group/RS Proxy. Do not enable a different character or import hair; the exact proxy already contains the authored character, curled hair, and patchwork wardrobe.",
        ],
    }
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "All canonical picture cuts. Clean status requires strict visual "
            "linkage, archived production Redshift confirmation, and an "
            "existing dated _codex_MMDDYY C4D copy whose copy-level dependency "
            "audit has zero render-critical missing references. Every other "
            "cut carries an exact-path recovery checklist."
        ),
        "summary": {
            "pictureCuts": len(records),
            "cleanStrictRedshiftConfirmed": status_counts[
                "clean_strict_redshift_confirmed"
            ],
            "candidateRecoveryPresent": status_counts[
                "candidate_recovery_present"
            ],
            "fallbackRequired": status_counts["fallback_required"],
            "remaining": (
                len(records)
                - status_counts["clean_strict_redshift_confirmed"]
            ),
            "uniqueCleanProjects": len(
                {
                    item["recoveryProjectPath"]
                    for item in records
                    if item["status"] == "clean_strict_redshift_confirmed"
                }
            ),
            "strictDatedCopiesAudited": int(
                dated_copy_archive.get("summary", {}).get(
                    "datedCopiesPresent", 0
                )
            ),
            "strictDatedCopiesRenderSafe": int(
                dated_copy_archive.get("summary", {}).get(
                    "renderSafeDatedCopies", 0
                )
            ),
            "candidateDatedCopiesAudited": len(
                candidate_copy_archive.get("projects", [])
            ),
            "candidateDatedCopiesRenderSafe": sum(
                1
                for item in candidate_copy_archive.get("projects", [])
                if item.get("renderSafe")
            ),
            "blockers": dict(sorted(blocker_counts.items())),
        },
        "globalRedshiftPrerequisite": global_prerequisite,
        "datedCopyAudit": dated_copy_archive,
        "candidateDatedCopyAudit": candidate_copy_archive,
        "projectAudits": list(project_audits.values()),
        "records": records,
    }
    output = json.dumps(payload, indent=2) + "\n"
    OUTPUT_JSON.write_text(output, encoding="utf-8")
    PUBLIC_JSON.write_text(output, encoding="utf-8")
    OUTPUT_MARKDOWN.write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
