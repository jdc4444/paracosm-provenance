#!/usr/bin/env python3
"""Build reviewed final/source/AEC camera comparisons for preserved exports."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from build_c4d_source_camera_comparisons import pair_sheet


ROOT = Path(__file__).resolve().parents[1]
PROOFS = ROOT / "data" / "c4d-aec-camera-proofs-20260726.json"
SOURCE_FRAMES = ROOT / "data" / "c4d-source-frame-archive-20260726.json"
OUTPUT_DIR = ROOT / "public" / "archive" / "camera-aec-review-20260726"
MANIFEST = ROOT / "data" / "c4d-aec-camera-review-20260726.json"

REVIEWS: dict[str, dict[str, Any]] = {
    "CUT-012": {
        "status": "proof_failed_out_of_memory",
        "selectedProjectName": None,
        "detail": (
            "The exact AEC camera is preserved, but the complete project "
            "cannot produce a hardware proof within available memory. The "
            "existing isolated Redshift root proof is asset evidence only."
        ),
    },
    "CUT-016": {
        "status": "camera_transform_preserved_scene_state_mismatch",
        "selectedProjectName": None,
        "detail": (
            "The exact export camera transform was tested in all three "
            "source-era project candidates. None recreates the canonical "
            "underwater close-up; the matching scene state/project remains "
            "unresolved."
        ),
    },
    "CUT-048": {
        "status": "camera_match_assets_incomplete",
        "selectedProjectName": "3P_4A WalkingHouseCarousel_SG_v004.c4d",
        "detail": (
            "The AEC camera exactly aligns the kitchen, refrigerator, "
            "doorway, and suspended forms. Character, hair, complete "
            "wardrobe, and final materials do not evaluate."
        ),
    },
    "CUT-049": {
        "status": "camera_match_assets_incomplete",
        "selectedProjectName": "3P_4A WalkingHouseCarousel_SG_v004.c4d",
        "detail": (
            "The AEC camera exactly aligns the wide kitchen and prop layout. "
            "Character, hair, grey wardrobe, and final materials do not "
            "evaluate."
        ),
    },
    "CUT-086": {
        "status": "camera_match_assets_incomplete",
        "selectedProjectName": "zoom out house.c4d",
        "detail": (
            "The source-era AEC camera in zoom out house.c4d aligns the "
            "window, wall divisions, sill, and garden framing. Final "
            "materials and the visible interior contents remain unverified."
        ),
    },
    "CUT-087": {
        "status": "camera_transform_preserved_scene_state_mismatch",
        "selectedProjectName": None,
        "detail": (
            "The source-era AEC transform is preserved, but neither surviving "
            "project recreates the canonical wide offset: the house is "
            "centered and larger, proving scene-state drift."
        ),
    },
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def public_path(path: Path) -> str:
    return "/" + path.resolve().relative_to(ROOT / "public").as_posix()


def main() -> None:
    source_by_cut = {
        str(item["cutId"]): item
        for item in load(SOURCE_FRAMES).get("records", [])
    }
    records = []
    project_counts: Counter[str] = Counter()
    for proof in load(PROOFS).get("records", []):
        cut_id = str(proof["cutId"])
        review = REVIEWS.get(cut_id)
        if review is None:
            continue
        project_name = Path(str(proof["projectPath"])).name
        project_counts[cut_id] += 1
        project_index = project_counts[cut_id]
        selected = (
            proof.get("status") == "rendered"
            and review.get("selectedProjectName") == project_name
        )
        output = OUTPUT_DIR / f"{cut_id}-p{project_index:02d}.jpg"
        source = source_by_cut.get(cut_id) or {}
        source_path = Path(str(source.get("outputPath") or ""))
        proof_path = Path(str(proof.get("outputPath") or ""))
        if source_path.exists():
            pair_sheet(
                cut_id,
                ROOT / "public" / "archive" / "cuts" / f"{cut_id}.jpg",
                source_path,
                proof_path if proof_path.exists() else None,
                (
                    f"AEC {project_name}"
                    if proof_path.exists()
                    else "AEC PROOF FAILED"
                ),
                output,
            )
        records.append(
            {
                "cutId": cut_id,
                "projectPath": proof.get("projectPath"),
                "projectName": project_name,
                "targetFrame": proof.get("targetFrame"),
                "aecPath": proof.get("aecPath"),
                "aecCameraName": proof.get("aecCameraName"),
                "proofStatus": proof.get("status"),
                "proofImage": proof.get("publicPath"),
                "comparisonImage": (
                    public_path(output) if output.exists() else None
                ),
                "selected": selected,
                "reviewStatus": (
                    review["status"]
                    if selected
                    or review.get("selectedProjectName") is None
                    else "ruled_out_project_state_mismatch"
                ),
                "detail": review["detail"],
                "error": proof.get("error"),
            }
        )
    statuses = Counter(str(item["reviewStatus"]) for item in records)
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Exact AEC camera transforms rendered read-only in source-era "
            "C4D projects and manually compared to both canonical source "
            "frames and final-cut thumbnails."
        ),
        "summary": {
            "records": len(records),
            "selectedCameraMatches": sum(
                bool(item["selected"]) for item in records
            ),
            "statuses": dict(statuses),
        },
        "records": records,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {MANIFEST}")


if __name__ == "__main__":
    main()
