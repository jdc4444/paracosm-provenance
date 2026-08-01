#!/usr/bin/env python3
"""Build exact production-Redshift camera confirmations for selected cuts.

This does not infer a camera from a similar-looking scene. It requires the
canonical conform's exact retained source frame, a render-safe dependency
audit, a non-proxy shot, the render project's saved take-effective camera, and
an existing shot-camera proof record.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "public" / "data" / "state.json"
SCENE_AUDIT = ROOT / "data" / "c4d-scene-state-audit.json"
FRAME_ARCHIVE = ROOT / "data" / "c4d-source-frame-archive-20260726.json"
CAMERA_PROOFS = ROOT / "data" / "c4d-camera-proof-renders.json"
OUTPUT = ROOT / "data" / "c4d-production-redshift-confirmations-20260726.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def image_metrics(
    reference_path: Path, source_path: Path
) -> dict[str, int | float]:
    reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    source = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    if reference is None or source is None:
        raise RuntimeError(f"Could not read {reference_path} or {source_path}")
    source = cv2.resize(
        source,
        (reference.shape[1], reference.shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    luma = float(
        np.corrcoef(reference_gray.reshape(-1), source_gray.reshape(-1))[0, 1]
    )
    reference_edges = cv2.Canny(reference_gray, 80, 160)
    source_edges = cv2.Canny(source_gray, 80, 160)
    edges = float(
        np.corrcoef(reference_edges.reshape(-1), source_edges.reshape(-1))[0, 1]
    )

    sift = cv2.SIFT_create(nfeatures=2500)
    reference_keys, reference_desc = sift.detectAndCompute(reference_gray, None)
    source_keys, source_desc = sift.detectAndCompute(source_gray, None)
    good = []
    inliers = 0
    if reference_desc is not None and source_desc is not None:
        pairs = cv2.BFMatcher().knnMatch(
            reference_desc, source_desc, k=2
        )
        good = [
            match
            for match, alternate in pairs
            if match.distance < 0.72 * alternate.distance
        ]
        if len(good) >= 4:
            reference_points = np.float32(
                [reference_keys[item.queryIdx].pt for item in good]
            )
            source_points = np.float32(
                [source_keys[item.trainIdx].pt for item in good]
            )
            _, mask = cv2.findHomography(
                source_points,
                reference_points,
                cv2.RANSAC,
                4.0,
            )
            if mask is not None:
                inliers = int(mask.sum())
    return {
        "lumaCorrelation": round(luma, 6),
        "edgeCorrelation": round(edges, 6),
        "siftGoodMatches": len(good),
        "siftRansacInliers": inliers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cut-id", action="append", required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    state = load(STATE)
    cuts = {
        str(item["id"]): item
        for item in state.get("cuts", [])
        if not item.get("isGap")
    }
    scene_projects = {
        str(item.get("projectPath") or ""): item
        for item in load(SCENE_AUDIT).get("projects", [])
    }
    source_frames = {
        str(item.get("cutId") or ""): item
        for item in load(FRAME_ARCHIVE).get("records", [])
    }
    camera_proofs = {
        str(cut_id): proof
        for proof in load(CAMERA_PROOFS).get("proofs", [])
        for cut_id in proof.get("cutIds", [])
    }
    records = []
    for cut_id in args.cut_id:
        cut = cuts.get(cut_id)
        if cut is None:
            raise RuntimeError(f"Unknown picture cut: {cut_id}")
        health = cut.get("c4dLinkStatus") or {}
        if health.get("status") not in {
            "fully_linked_confirmed",
            "render_safe_with_warnings",
        } or int(health.get("renderCriticalMissingFiles") or 0):
            raise RuntimeError(f"{cut_id} is not dependency-render-safe")
        proxy_status = str((cut.get("c4dProxyAudit") or {}).get("status") or "")
        if proxy_status not in {"not_used", "verified_rendered"}:
            raise RuntimeError(
                f"{cut_id} has unresolved proxy status {proxy_status!r}"
            )
        project_path = str(health.get("projectPath") or "")
        project = scene_projects.get(project_path)
        if project is None:
            raise RuntimeError(f"{cut_id} has no scene-state project audit")
        proof = camera_proofs.get(cut_id)
        source = source_frames.get(cut_id)
        if proof is None or source is None:
            raise RuntimeError(f"{cut_id} is missing proof/source-frame metadata")
        source_path = Path(str(source.get("sourceFramePath") or ""))
        archive_path = Path(str(source.get("outputPath") or ""))
        if not source_path.exists() or not archive_path.exists():
            raise RuntimeError(f"{cut_id} exact source frame is offline")
        take_name = str(proof.get("cameraTake") or "Main")
        take = next(
            (
                item
                for item in project.get("takes", [])
                if item.get("name") == take_name
            ),
            None,
        )
        if take is None:
            raise RuntimeError(f"{cut_id} take {take_name!r} was not audited")
        camera = take.get("effectiveCamera") or {}
        expected_camera = str(proof.get("cameraObjectPath") or "")
        if expected_camera and str(camera.get("path") or "") != expected_camera:
            raise RuntimeError(
                f"{cut_id} proof camera {expected_camera!r} does not match "
                f"take-effective camera {camera.get('path')!r}"
            )
        render_data = take.get("renderData") or {}
        reference_path = ROOT / "public" / str(cut["thumbnail"]).lstrip("/")
        metrics = image_metrics(reference_path, archive_path)
        if (
            metrics["siftRansacInliers"] < 12
            and metrics["lumaCorrelation"] < 0.55
        ):
            raise RuntimeError(
                f"{cut_id} exact-frame image evidence is too weak: {metrics}"
            )
        records.append(
            {
                "cutId": cut_id,
                "status": "confirmed",
                "sourceId": source.get("sourceId") or proof.get("sourceId"),
                "projectPath": project_path,
                "renderPath": source.get("renderPath"),
                "targetFrame": source.get("targetFrame"),
                "sourceFramePath": str(source_path),
                "sourceFrameOutputPath": str(archive_path),
                "sourceFramePublicPath": source.get("publicPath"),
                "sourceEditPath": source.get("sourceEditPath"),
                "sourceEditFrame": source.get("sourceEditFrame"),
                "sourceToRenderFrameOffset": source.get(
                    "sourceToRenderFrameOffset"
                ),
                "sourceMappingMethod": source.get("mappingMethod"),
                "sourceMappingEvidence": source.get("mappingEvidence"),
                "cameraTake": take_name,
                "cameraName": camera.get("name"),
                "cameraPath": camera.get("path"),
                "cameraTypeId": camera.get("typeId"),
                "cameraLegacyRedshift": camera.get("legacyRedshift"),
                "cameraFocalLength": camera.get("focalLength"),
                "cameraPosition": camera.get("position"),
                "cameraMatrix": camera.get("matrix"),
                "cameraRenderData": render_data.get("name"),
                "renderOutputPath": render_data.get("outputPath"),
                "renderRendererId": render_data.get("renderer"),
                "dependencyStatus": health.get("status"),
                "renderCriticalMissingFiles": 0,
                "proxyStatus": proxy_status,
                "metrics": metrics,
                "confirmationMethod": (
                    "Exact canonical conform source frame, saved Redshift "
                    "render output, and take-effective camera"
                ),
            }
        )

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Exact production Redshift source-frame confirmation; each record "
            "also requires render-safe current dependencies, no unresolved "
            "proxy, and the saved take-effective camera."
        ),
        "summary": {
            "confirmedCuts": len(records),
            "projects": len({item["projectPath"] for item in records}),
        },
        "records": records,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
