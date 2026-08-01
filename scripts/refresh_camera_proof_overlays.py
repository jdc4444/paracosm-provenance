#!/usr/bin/env python3
"""Refresh camera-proof evidence in the saved UI state without a full scan.

The complete Dropbox inventory scan is intentionally expensive. Camera-proof
recovery records are already self-contained and can be safely overlaid onto the
last complete state while another memory-intensive process is running.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scan import (
    apply_as_finishing_chronology,
    merge_camera_proof_recovery_overrides,
)


APP_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = APP_ROOT / "public/data/state.json"
PROOF_ARCHIVE_PATH = (
    APP_ROOT / "data/as-finishing-camera-proofs-20260727.json"
)
PROOF_OVERRIDE_PATH = (
    APP_ROOT
    / "data/as-finishing-camera-proof-recovery-overrides-20260727.json"
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def verification_summary(cuts: list[dict[str, Any]]) -> dict[str, int]:
    statuses: Counter[str] = Counter()
    strict_linked = 0
    for cut in cuts:
        if cut.get("isGap"):
            continue
        verification = cut.get("c4dVerification") or {}
        status = str(verification.get("status") or "unreviewed")
        strict_linked += int(bool(verification.get("strictLinked")))
        if status in {"strictly_verified", "match"}:
            statuses["match"] += 1
        elif status in {"partial", "partial_match"}:
            statuses["partial"] += 1
        elif status == "mismatch":
            statuses["mismatch"] += 1
        elif status in {"missing", "missing_proof"}:
            statuses["missing"] += 1
        else:
            statuses["unreviewed"] += 1
    return {
        "c4dStrictLinkedCuts": strict_linked,
        "c4dFullyLinkedCuts": strict_linked,
        "c4dVisualMatchCuts": statuses["match"],
        "c4dVisualPartialCuts": statuses["partial"],
        "c4dVisualMismatchCuts": statuses["mismatch"],
        "c4dVisualMissingProofCuts": statuses["missing"],
        "c4dVisualUnreviewedCuts": statuses["unreviewed"],
    }


def main() -> None:
    state = load_json(STATE_PATH)
    proof_archive = load_json(PROOF_ARCHIVE_PATH)
    proof_overrides = load_json(PROOF_OVERRIDE_PATH)
    merged_proofs = merge_camera_proof_recovery_overrides(
        proof_archive, proof_overrides
    )

    removed = 0
    for cut in state.get("cuts", []):
        lineage = cut.get("lineage", [])
        retained = [
            node
            for node in lineage
            if not (
                node.get("kind") == "camera_proof"
                and (
                    node.get("recoveryProof")
                    or node.get("primaryRecoveryProof")
                )
            )
        ]
        removed += len(lineage) - len(retained)
        cut["lineage"] = retained

    counts = apply_as_finishing_chronology(
        state,
        {"renderLogs": [], "cutLineageLeads": {}},
        merged_proofs,
    )
    refreshed_at = datetime.now(timezone.utc).isoformat()
    state["proofOverlayRefreshedAt"] = refreshed_at
    state.setdefault("cameraProofs", {}).update(
        {
            "overlayAuthority": merged_proofs.get("authority"),
            "overlayManifest": str(PROOF_ARCHIVE_PATH),
            "overlayRefreshedAt": refreshed_at,
            "overlayProofRecords": len(merged_proofs.get("proofs", [])),
            "overlayAppliedProofs": counts.get("newCameraProofs", 0),
        }
    )
    state.setdefault("c4dVerification", {})["summary"] = (
        verification_summary(state.get("cuts", []))
    )
    state.setdefault("asFinishingAudit", {})[
        "cameraProofOverlayRefresh"
    ] = {
        "refreshedAt": refreshed_at,
        "proofRecords": len(merged_proofs.get("proofs", [])),
        "removedPriorRecoveryProofNodes": removed,
        **counts,
        "note": (
            "Low-memory evidence overlay onto the last complete inventory; "
            "not a replacement for a future full filesystem rescan."
        ),
    }

    temporary_path = STATE_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(state, indent=2) + "\n")
    temporary_path.replace(STATE_PATH)
    print(
        json.dumps(
            {
                "state": str(STATE_PATH),
                "removedPriorRecoveryProofNodes": removed,
                **counts,
                "verificationSummary": state["c4dVerification"]["summary"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
