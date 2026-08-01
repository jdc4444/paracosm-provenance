#!/usr/bin/env python3
"""Build a strict, per-cut C4D verification ledger and visual contact sheets.

A source project is only strict-linked when it has:
1. a shot-specific C4D project path,
2. a completed dependency audit with no render-critical missing files,
3. a rendered camera proof, and
4. a manual visual match for location, camera, character, hair, wardrobe,
   and visible materials against the canonical cut thumbnail.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "public" / "data" / "state.json"
REVIEW_PATH = ROOT / "data" / "c4d-visual-review.json"
SHOT_AUTHORED_PROXY_PATH = (
    ROOT
    / "data"
    / "c4d-clean-recoveries"
    / "CUT-008-022-030-shot-authored-proxy-diagnosis.json"
)
OUTPUT_PATH = ROOT / "data" / "c4d-strict-audit.json"
ARCHIVE_DIR = ROOT / "public" / "archive" / "c4d-strict-audit"

ELEMENT_KEYS = (
    "location",
    "camera",
    "character",
    "hair",
    "wardrobe",
    "materials",
)
# Elements that are genuinely absent from the canonical thumbnail do not block
# a visual match. "not_verifiable" is deliberately excluded: a grey proof can
# establish framing/geometry, but it cannot establish final materials.
MATCH_STATUSES = {"match", "not_visible"}
RENDER_SAFE_STATUSES = {
    "fully_linked_confirmed",
    "render_safe_with_warnings",
}


def local_archive_path(public_path: str | None) -> Path | None:
    if not public_path:
        return None
    if public_path.startswith("/archive/"):
        return ROOT / "public" / public_path.lstrip("/")
    candidate = Path(public_path).expanduser()
    return candidate if candidate.is_absolute() else ROOT / candidate


def load_image(path: Path | None, size: tuple[int, int]) -> Image.Image:
    if path and path.exists():
        with Image.open(path) as image:
            return ImageOps.fit(image.convert("RGB"), size, Image.Resampling.LANCZOS)
    placeholder = Image.new("RGB", size, "#111111")
    draw = ImageDraw.Draw(placeholder)
    draw.text((12, 12), "NO PROOF", fill="#b35d68", font=ImageFont.load_default())
    return placeholder


def image_metrics(reference_path: Path | None, proof_path: Path | None) -> dict[str, float] | None:
    if not reference_path or not proof_path:
        return None
    reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    proof = cv2.imread(str(proof_path), cv2.IMREAD_COLOR)
    if reference is None or proof is None:
        return None
    proof = cv2.resize(
        proof,
        (reference.shape[1], reference.shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY).astype(np.float32)
    proof_gray = cv2.cvtColor(proof, cv2.COLOR_BGR2GRAY).astype(np.float32)
    ref_edge = cv2.Canny(reference, 80, 160).astype(np.float32)
    proof_edge = cv2.Canny(proof, 80, 160).astype(np.float32)

    def correlation(left: np.ndarray, right: np.ndarray) -> float:
        left_flat = left.reshape(-1)
        right_flat = right.reshape(-1)
        if float(left_flat.std()) < 1e-6 or float(right_flat.std()) < 1e-6:
            return 0.0
        return float(np.corrcoef(left_flat, right_flat)[0, 1])

    return {
        "lumaCorrelation": round(correlation(ref_gray, proof_gray), 4),
        "edgeCorrelation": round(correlation(ref_edge, proof_edge), 4),
    }


def proof_node(cut: dict[str, Any]) -> dict[str, Any] | None:
    proofs = [
        node
        for node in cut.get("lineage", [])
        if node.get("kind") == "camera_proof"
        and str(node.get("proofStatus") or "") != "rejected"
    ]
    return (
        next(
            (
                node
                for node in proofs
                if node.get("primaryRecoveryProof")
            ),
            None,
        )
        or next(
            (node for node in proofs if node.get("redshiftProof")),
            None,
        )
        or (proofs[0] if proofs else None)
    )


def c4d_project(cut: dict[str, Any]) -> str | None:
    health = cut.get("c4dLinkStatus") or {}
    if health.get("projectPath"):
        return str(health["projectPath"])
    node = next(
        (
            item
            for item in cut.get("lineage", [])
            if item.get("kind") == "cinema4d"
            and (item.get("projectPath") or item.get("path"))
        ),
        None,
    )
    return str(node.get("projectPath") or node.get("path")) if node else None


def normalize_review(review: dict[str, Any] | None) -> dict[str, Any]:
    if not review:
        return {
            "status": "unreviewed",
            "elements": {key: "not_verifiable" for key in ELEMENT_KEYS},
            "notes": "Manual thumbnail-to-proof review pending.",
        }
    elements = {
        key: str((review.get("elements") or {}).get(key) or "not_verifiable")
        for key in ELEMENT_KEYS
    }
    return {
        "status": str(review.get("status") or "unreviewed"),
        "elements": elements,
        "notes": str(review.get("notes") or ""),
    }


def build_record(
    cut: dict[str, Any],
    reviews: dict[str, Any],
    shot_proxy_missing_cuts: set[str],
) -> dict[str, Any]:
    proof = proof_node(cut)
    health = cut.get("c4dLinkStatus") or {}
    project_path = c4d_project(cut)
    proof_public = (
        str(proof.get("comparisonImage"))
        if proof and proof.get("comparisonImage")
        else None
    )
    thumbnail_public = str(cut.get("thumbnail") or "")
    proof_path = local_archive_path(proof_public)
    thumbnail_path = local_archive_path(thumbnail_public)
    state_verification = cut.get("c4dVerification") or {}
    state_review = (
        state_verification
        if state_verification.get("elements")
        else None
    )
    review = normalize_review(
        state_review or reviews.get(str(cut["id"]))
    )
    visual_match = (
        review["status"] in {"match", "strictly_verified"}
        and all(
            review["elements"][key] in MATCH_STATUSES
            for key in ELEMENT_KEYS
        )
    )
    shot_proxy_missing = str(cut["id"]) in shot_proxy_missing_cuts
    dependency_audited = bool(health) and health.get("status") != "audit_unavailable"
    dependency_render_safe = (
        dependency_audited
        and health.get("status") in RENDER_SAFE_STATUSES
        and int(health.get("renderCriticalMissingFiles") or 0) == 0
    )
    camera_proof_rendered = bool(
        proof
        and proof.get("proofStatus") == "rendered"
        and proof_path
        and proof_path.exists()
    )
    project_linked = bool(project_path and Path(project_path).exists())
    strict_linked = all(
        (
            project_linked,
            dependency_audited,
            dependency_render_safe,
            camera_proof_rendered,
            visual_match,
            not shot_proxy_missing,
        )
    )
    blockers = []
    if not project_linked:
        blockers.append("source_project_missing")
    if not dependency_audited:
        blockers.append("dependency_audit_missing")
    elif not dependency_render_safe:
        blockers.append("render_critical_dependencies_missing")
    if not camera_proof_rendered:
        blockers.append("camera_proof_missing")
    if not visual_match:
        blockers.append(
            "visual_review_pending"
            if review["status"] == "unreviewed"
            else "camera_or_asset_visual_mismatch"
        )
    if shot_proxy_missing:
        blockers.append("shot_authored_proxy_missing")
    return {
        "cutId": cut["id"],
        "plannedShotId": cut.get("plannedShotId"),
        "sectionCode": cut.get("sectionCode"),
        "sourceId": proof.get("sourceId") if proof else None,
        "projectPath": project_path,
        "thumbnail": thumbnail_public,
        "cameraProof": proof_public,
        "cameraName": proof.get("label") if proof else None,
        "cameraProofStatus": proof.get("proofStatus") if proof else "missing",
        "dependencyStatus": health.get("status") or "audit_unavailable",
        "renderCriticalMissingFiles": int(
            health.get("renderCriticalMissingFiles") or 0
        ),
        "checks": {
            "projectLinked": project_linked,
            "dependencyAudited": dependency_audited,
            "dependencyRenderSafe": dependency_render_safe,
            "cameraProofRendered": camera_proof_rendered,
            "visualMatch": visual_match,
            "shotAuthoredProxyPresent": not shot_proxy_missing,
        },
        "visualReview": review,
        "metrics": image_metrics(thumbnail_path, proof_path),
        "strictLinked": strict_linked,
        "blockers": blockers,
    }


def panel_for(record: dict[str, Any]) -> Image.Image:
    image_width, image_height = 360, 203
    header_height = 31
    footer_height = 35
    panel = Image.new(
        "RGB",
        (image_width * 2, header_height + image_height + footer_height),
        "#0d0d0d",
    )
    draw = ImageDraw.Draw(panel)
    font = ImageFont.load_default()
    status = str(record["visualReview"]["status"]).upper()
    status_color = {
        "MATCH": "#d7f452",
        "PARTIAL": "#e6bd61",
        "MISMATCH": "#e06c75",
        "UNREVIEWED": "#85857f",
    }.get(status, "#85857f")
    draw.text(
        (8, 7),
        f"{record['cutId']}  {record.get('plannedShotId') or '-'}",
        fill="#f2f1eb",
        font=font,
    )
    draw.text((260, 7), status, fill=status_color, font=font)
    draw.text((image_width + 8, 7), "C4D CAMERA PROOF", fill="#b8b8b1", font=font)
    final_image = load_image(
        local_archive_path(record.get("thumbnail")),
        (image_width, image_height),
    )
    proof_image = load_image(
        local_archive_path(record.get("cameraProof")),
        (image_width, image_height),
    )
    panel.paste(final_image, (0, header_height))
    panel.paste(proof_image, (image_width, header_height))
    blockers = ", ".join(record["blockers"]) or "strict linked"
    draw.text(
        (8, header_height + image_height + 7),
        blockers[:108],
        fill=status_color,
        font=font,
    )
    return panel


def write_visual_archive(records: list[dict[str, Any]]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    panels = []
    for record in records:
        panel = panel_for(record)
        pair_path = ARCHIVE_DIR / f"{record['cutId']}-pair.jpg"
        panel.save(pair_path, quality=90)
        record["comparisonSheet"] = (
            f"/archive/c4d-strict-audit/{record['cutId']}-pair.jpg"
        )
        panels.append((record, panel))
    for sheet_index in range(0, len(panels), 6):
        page_records = panels[sheet_index : sheet_index + 6]
        sheet = Image.new("RGB", (1440, 807), "#050505")
        for slot, (_, panel) in enumerate(page_records):
            x = (slot % 2) * 720
            y = (slot // 2) * 269
            sheet.paste(panel, (x, y))
        start_id = page_records[0][0]["cutId"]
        end_id = page_records[-1][0]["cutId"]
        sheet.save(
            ARCHIVE_DIR / f"sheet-{start_id}-{end_id}.jpg",
            quality=88,
        )


def main() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    review_archive = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    reviews = review_archive.get("reviews", {})
    shot_proxy_archive = json.loads(
        SHOT_AUTHORED_PROXY_PATH.read_text(encoding="utf-8")
    )
    shot_proxy_missing_cuts = {
        str(cut_id)
        for project in shot_proxy_archive.get("projects", [])
        if project.get("status")
        in {
            "shot_authored_full_character_proxy_missing",
            "shot_authored_proxy_cache_missing_authored_hierarchy_present",
        }
        for cut_id in project.get("cutIds", [])
    }
    picture_cuts = [cut for cut in state.get("cuts", []) if not cut.get("isGap")]
    records = [
        build_record(cut, reviews, shot_proxy_missing_cuts)
        for cut in picture_cuts
    ]
    write_visual_archive(records)
    blockers = Counter(
        blocker for record in records for blocker in record["blockers"]
    )
    visual_statuses = Counter(
        record["visualReview"]["status"] for record in records
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "strict C4D linkage requires source project, dependency audit, "
            "render-safe dependencies, camera proof, and manual element match"
        ),
        "requiredVisualElements": list(ELEMENT_KEYS),
        "summary": {
            "pictureCuts": len(records),
            "projectLinked": sum(
                bool(record["checks"]["projectLinked"]) for record in records
            ),
            "dependencyAudited": sum(
                bool(record["checks"]["dependencyAudited"]) for record in records
            ),
            "dependencyRenderSafe": sum(
                bool(record["checks"]["dependencyRenderSafe"])
                for record in records
            ),
            "cameraProofRendered": sum(
                bool(record["checks"]["cameraProofRendered"])
                for record in records
            ),
            "visuallyMatched": sum(
                bool(record["checks"]["visualMatch"]) for record in records
            ),
            "strictLinked": sum(
                bool(record["strictLinked"]) for record in records
            ),
            "visualStatuses": dict(sorted(visual_statuses.items())),
            "blockers": dict(sorted(blockers.items())),
        },
        "records": records,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
