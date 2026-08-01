#!/usr/bin/env python3
"""Render and rank every retained camera for visually mismatched cuts.

The exact canonical source-render frame is preferred when it is archived; the
final cut thumbnail remains a fallback and editorial guide. This sweep does
not promote a camera automatically.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from render_c4d_camera_proofs import render_project_c4dpy


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "public" / "data" / "state.json"
SCENE_AUDIT_PATH = ROOT / "data" / "c4d-scene-state-audit.json"
REVIEW_PATH = ROOT / "data" / "c4d-visual-review.json"
PRIMARY_PROOFS_PATH = (
    ROOT / "data" / "c4d-camera-proof-renders-corrected-20260726.json"
)
OUTPUT_DIR = ROOT / "public" / "archive" / "camera-candidates-v2"
MANIFEST_PATH = ROOT / "data" / "c4d-camera-candidate-sweep-v2.json"
SOURCE_FRAMES_PATH = (
    ROOT / "data" / "c4d-source-frame-archive-20260726.json"
)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "camera"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_path(cut: dict[str, Any]) -> str:
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
        {},
    )
    return str(node.get("projectPath") or node.get("path") or "")


def correlation(left: np.ndarray, right: np.ndarray) -> float:
    left_flat = left.reshape(-1).astype(np.float32)
    right_flat = right.reshape(-1).astype(np.float32)
    if float(left_flat.std()) < 1e-6 or float(right_flat.std()) < 1e-6:
        return 0.0
    return float(np.corrcoef(left_flat, right_flat)[0, 1])


def image_metrics(reference_path: Path, proof_path: Path) -> dict[str, float]:
    reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    proof = cv2.imread(str(proof_path), cv2.IMREAD_COLOR)
    if reference is None or proof is None:
        raise RuntimeError("Could not read comparison image")
    proof = cv2.resize(
        proof,
        (reference.shape[1], reference.shape[0]),
        interpolation=cv2.INTER_AREA,
    )
    reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    proof_gray = cv2.cvtColor(proof, cv2.COLOR_BGR2GRAY)
    reference_edges = cv2.Canny(reference_gray, 60, 140)
    proof_edges = cv2.Canny(proof_gray, 60, 140)
    edge = correlation(reference_edges, proof_edges)
    luma = correlation(reference_gray, proof_gray)
    return {
        "edgeCorrelation": round(edge, 6),
        "lumaCorrelation": round(luma, 6),
        "rankScore": round(edge * 0.75 + luma * 0.25, 6),
    }


def public_path(path: Path) -> str:
    return "/" + path.resolve().relative_to(ROOT / "public").as_posix()


def contact_sheet(
    cut_id: str,
    thumbnail: Path,
    ranked: list[dict[str, Any]],
    output: Path,
) -> None:
    width, height = 384, 216
    header = 22
    entries = [
        {
            "path": str(thumbnail),
            "cameraName": "SOURCE RENDER",
            "metrics": {},
        },
        *ranked[:5],
    ]
    page = Image.new("RGB", (width * 3, (height + header) * 2), "#050505")
    font = ImageFont.load_default()
    for index, item in enumerate(entries):
        source = Path(str(item["path"]))
        if source.exists():
            with Image.open(source) as image:
                panel = ImageOps.fit(
                    image.convert("RGB"),
                    (width, height),
                    Image.Resampling.LANCZOS,
                )
        else:
            panel = Image.new("RGB", (width, height), "#111111")
        x = (index % 3) * width
        y = (index // 3) * (height + header)
        page.paste(panel, (x, y))
        draw = ImageDraw.Draw(page)
        metrics = item.get("metrics") or {}
        score = metrics.get("rankScore")
        label = str(
            item.get("displayLabel")
            or item.get("cameraName")
            or "camera"
        )
        if score is not None:
            label += f" · {float(score):.3f}"
        draw.text((x + 6, y + height + 6), label[:58], fill="#d2cec6", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    page.save(output, quality=88)


def write_manifest(
    path: Path,
    records: list[dict[str, Any]],
    rankings: dict[str, Any],
) -> None:
    statuses: dict[str, int] = defaultdict(int)
    for item in records:
        statuses[str(item.get("status") or "pending")] += 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Read-only exhaustive retained-camera candidates. Automated "
            "ranking is triage only; direct source renders and final cut "
            "thumbnails require manual visual confirmation before acceptance."
        ),
        "summary": {
            "candidateProofs": len(records),
            "statuses": dict(statuses),
            "cuts": len({str(item.get("cutId")) for item in records}),
            "projects": len({str(item.get("projectPath")) for item in records}),
        },
        "records": records,
        "rankings": rankings,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cut-id", action="append", default=[])
    parser.add_argument("--exclude-cut-id", action="append", default=[])
    parser.add_argument(
        "--camera-status",
        action="append",
        default=["mismatch"],
        help="Visual-review camera state to include; repeat as needed.",
    )
    parser.add_argument("--limit-projects", type=int)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--source-frames", type=Path, default=SOURCE_FRAMES_PATH)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    state = load(STATE_PATH)
    scene_audit = load(SCENE_AUDIT_PATH)
    reviews = load(REVIEW_PATH).get("reviews", {})
    primary_proofs = load(PRIMARY_PROOFS_PATH)
    source_frames = {}
    if args.source_frames.exists():
        source_frames = {
            str(item["cutId"]): item
            for item in load(args.source_frames).get("records", [])
            if item.get("status") == "archived"
            and Path(str(item.get("outputPath") or "")).exists()
        }
    proofs_by_cut = {
        str(cut_id): proof
        for proof in primary_proofs.get("proofs", [])
        for cut_id in proof.get("cutIds", [])
    }
    cameras_by_project = {
        str(item.get("projectPath")): item.get("cameras", [])
        for item in scene_audit.get("projects", [])
        if item.get("projectPath")
    }
    cuts_by_id = {
        str(item["id"]): item
        for item in state.get("cuts", [])
        if not item.get("isGap")
    }
    selected_ids = set(args.cut_id)
    excluded_ids = set(args.exclude_cut_id)
    selected_statuses = set(args.camera_status)
    records: list[dict[str, Any]] = []
    for cut_id, cut in cuts_by_id.items():
        if selected_ids and cut_id not in selected_ids:
            continue
        if cut_id in excluded_ids:
            continue
        review = reviews.get(cut_id) or {}
        camera_status = str((review.get("elements") or {}).get("camera") or "")
        if camera_status not in selected_statuses:
            continue
        proof = proofs_by_cut.get(cut_id) or {}
        frame = proof.get("targetFrame")
        project = project_path(cut)
        if frame is None or not project or not Path(project).exists():
            continue
        cameras = cameras_by_project.get(project) or []
        final_thumbnail = str(
            ROOT / "public" / str(cut["thumbnail"]).lstrip("/")
        )
        source_frame = source_frames.get(cut_id) or {}
        reference_image = str(source_frame.get("outputPath") or final_thumbnail)
        for camera_index, camera in enumerate(cameras, start=1):
            camera_name = str(camera.get("name") or f"camera-{camera_index}")
            camera_path = str(camera.get("path") or camera.get("objectPath") or camera_name)
            output = (
                args.output_dir.expanduser().resolve()
                / cut_id
                / f"{camera_index:03d}-{slug(camera_path)}-f{int(frame):06d}.png"
            )
            records.append(
                {
                    "sourceId": f"{cut_id}__camera_{camera_index:03d}",
                    "cutId": cut_id,
                    "targetFrame": int(frame),
                    "projectPath": project,
                    "cameraName": camera_name,
                    "displayLabel": camera_path,
                    "cameraObject": {"objectPath": camera_path},
                    "cameraTake": proof.get("cameraTake") or "Main",
                    "cameraRenderData": proof.get("cameraRenderData"),
                    "outputPath": str(output),
                    "publicPath": public_path(output),
                    "canonicalThumbnail": final_thumbnail,
                    "sourceFrameReference": source_frame.get("sourceFramePath"),
                    "referenceImage": reference_image,
                    "status": "pending",
                }
            )

    prior_by_id: dict[str, dict[str, Any]] = {}
    if args.manifest.exists():
        prior_by_id = {
            str(item["sourceId"]): item
            for item in load(args.manifest).get("records", [])
        }
    for index, item in enumerate(records):
        prior = prior_by_id.get(str(item["sourceId"]))
        if (
            prior
            and prior.get("status") == "rendered"
            and Path(str(prior.get("outputPath") or "")).exists()
        ):
            records[index] = {
                **prior,
                "canonicalThumbnail": item["canonicalThumbnail"],
                "sourceFrameReference": item.get("sourceFrameReference"),
                "referenceImage": item["referenceImage"],
            }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        if item.get("status") == "pending":
            groups[str(item["projectPath"])].append(item)
    project_groups = sorted(groups.items())
    if args.limit_projects is not None:
        project_groups = project_groups[: args.limit_projects]
    print(
        f"Camera candidate sweep: {len(records)} proofs · "
        f"{len({item['cutId'] for item in records})} cuts · "
        f"{len(project_groups)} pending projects",
        flush=True,
    )
    if args.plan_only:
        write_manifest(args.manifest, records, {})
        return

    by_id = {str(item["sourceId"]): item for item in records}
    for group_index, (project, group) in enumerate(project_groups, start=1):
        print(
            f"[{group_index}/{len(project_groups)}] {Path(project).name} · "
            f"{len(group)} candidates",
            flush=True,
        )
        try:
            results = render_project_c4dpy(
                project, group, 480, 270, args.timeout
            )
            results_by_id = {
                str(item.get("sourceId")): item for item in results
            }
            for record in group:
                result = results_by_id.get(str(record["sourceId"]))
                if result is None:
                    record.update(
                        {
                            "status": "failed",
                            "error": "Cinema 4D returned no candidate result",
                        }
                    )
                else:
                    record.update(result)
                by_id[str(record["sourceId"])] = record
        except Exception as error:
            for record in group:
                record.update(
                    {
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                by_id[str(record["sourceId"])] = record
        records = [by_id[str(item["sourceId"])] for item in records]
        write_manifest(args.manifest, records, {})

    rankings: dict[str, Any] = {}
    for cut_id in sorted({str(item["cutId"]) for item in records}):
        ranked: list[dict[str, Any]] = []
        cut_records = [
            item for item in records if str(item.get("cutId")) == cut_id
        ]
        thumbnail = Path(
            str(
                (cut_records[0] if cut_records else {}).get("referenceImage")
                or (
                    ROOT
                    / "public"
                    / str(cuts_by_id[cut_id]["thumbnail"]).lstrip("/")
                )
            )
        )
        for item in records:
            if item.get("cutId") != cut_id or item.get("status") != "rendered":
                continue
            proof_path = Path(str(item.get("outputPath") or ""))
            try:
                metrics = image_metrics(thumbnail, proof_path)
            except Exception as error:
                metrics = {"error": f"{type(error).__name__}: {error}"}
            item["metrics"] = metrics
            ranked.append(
                {
                    "sourceId": item["sourceId"],
                    "cameraName": item.get("cameraName"),
                    "cameraObjectPath": item.get("cameraObjectPath")
                    or (item.get("cameraObject") or {}).get("objectPath"),
                    "path": str(proof_path),
                    "publicPath": item.get("publicPath"),
                    "metrics": metrics,
                }
            )
        ranked.sort(
            key=lambda item: float(
                (item.get("metrics") or {}).get("rankScore") or -999
            ),
            reverse=True,
        )
        contact = args.output_dir.expanduser().resolve() / cut_id / "contact-top5.jpg"
        contact_sheet(cut_id, thumbnail, ranked, contact)
        rankings[cut_id] = {
            "status": "automated_ranking_requires_manual_review",
            "referenceImage": str(thumbnail),
            "canonicalThumbnail": str(
                ROOT
                / "public"
                / str(cuts_by_id[cut_id]["thumbnail"]).lstrip("/")
            ),
            "contactSheet": public_path(contact),
            "candidates": ranked,
        }

    write_manifest(args.manifest, records, rankings)
    print(
        json.dumps(
            {
                "rendered": sum(
                    item.get("status") == "rendered" for item in records
                ),
                "failed": sum(
                    item.get("status") == "failed" for item in records
                ),
                "rankedCuts": len(rankings),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
