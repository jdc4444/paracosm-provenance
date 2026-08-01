#!/usr/bin/env python3
"""Write the first complete manual thumbnail-to-camera-proof review ledger.

This is intentionally a human-authored visual classification, not an image
similarity result. It records what is visible in the current proof archive so
later camera and dependency recovery work has an explicit baseline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "c4d-visual-review.json"
KEYS = ("location", "camera", "character", "hair", "wardrobe", "materials")


def elements(*values: str) -> dict[str, str]:
    return dict(zip(KEYS, values, strict=True))


def review(status: str, values: tuple[str, ...], notes: str) -> dict[str, object]:
    return {"status": status, "elements": elements(*values), "notes": notes}


NV = "not_visible"
NA = "not_verifiable"
M = "match"
P = "partial"
X = "mismatch"
MISS = "missing"


REVIEWS: dict[str, dict[str, object]] = {
    "CUT-001": review(X, (X, X, NV, NV, NV, X), "Canonical exterior house shot; proof is an unrelated interior/object view."),
    "CUT-002": review(X, (X, X, P, MISS, MISS, MISS), "Canonical grey-outfit sink shot; proof is a base character in an unrelated snowy environment."),
    "CUT-003": review(X, (X, X, MISS, MISS, MISS, MISS), "Canonical face close-up; proof is blank white."),
    "CUT-004": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-005": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-006": review(MISS, (NA, NA, NA, NA, NA, NA), "No source C4D project or rendered camera proof is linked."),
    "CUT-007": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-008": review(X, (P, X, MISS, MISS, MISS, X), "Canonical teacup/wave shot; proof shows only droplets and horizon with different framing."),
    "CUT-009": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-010": review(P, (P, X, NV, NV, NV, MISS), "Underwater fork/plate assets are related, but angle and composition differ and final materials are absent."),
    "CUT-011": review(X, (P, X, MISS, MISS, MISS, MISS), "Canonical underwater diving character is absent; proof contains utensils only."),
    "CUT-012": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-013": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-014": review(MISS, (NA, NA, NA, NA, NA, NA), "No source C4D project or rendered camera proof is linked."),
    "CUT-015": review(MISS, (NA, NA, NA, NA, NA, NA), "No source C4D project or rendered camera proof is linked."),
    "CUT-016": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-017": review(P, (P, P, NV, NV, NV, NA), "Broad mountain geometry is related, but exact camera and final materials are not established."),
    "CUT-018": review(P, (P, P, NV, NV, NV, NA), "Broad mountain geometry is related, but exact camera and final materials are not established."),
    "CUT-019": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical close character view; proof contains landscape only."),
    "CUT-020": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical close legs shot; proof contains landscape only."),
    "CUT-021": review(P, (P, P, MISS, MISS, MISS, NA), "Related mountain location, but the running character and final assets are absent."),
    "CUT-022": review(P, (P, P, NV, NV, NV, NA), "Related valley geometry, but exact framing and final materials are not established."),
    "CUT-023": review(X, (P, X, MISS, NA, NA, NA), "Mountain landscape is present, but the canonical character is absent and framing does not match."),
    "CUT-024": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical flying character/cloth is absent; proof shows landscape/grid only."),
    "CUT-025": review(P, (P, P, MISS, MISS, MISS, NA), "Buttons and landscape are related, but the canonical legs/character and final assets are absent."),
    "CUT-026": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical silhouetted character is absent; terrain framing does not match."),
    "CUT-027": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical climbing character is absent; proof shows terrain/mesh from another framing."),
    "CUT-028": review(P, (P, P, NV, NV, P, MISS), "Cloth geometry and close framing are related, but exact overlay and materials remain unverified."),
    "CUT-029": review(P, (P, P, P, MISS, MISS, MISS), "Knitted terrain composition is related; character/final hair, wardrobe, and materials are incomplete."),
    "CUT-030": review(P, (P, P, MISS, MISS, MISS, NA), "Peak and broad framing are related, but canonical character is absent."),
    "CUT-031": review(X, (X, X, MISS, MISS, MISS, X), "Canonical character/giant figure shot; proof is nearly blank/dark."),
    "CUT-032": review(X, (P, X, P, MISS, MISS, MISS), "Tested cameras render, but none reproduce the waist-up profile; final character assets are absent."),
    "CUT-033": review(P, (M, P, P, MISS, MISS, MISS), "Landscape and base character are visible; exact camera, hair, wardrobe, and materials remain incomplete."),
    "CUT-034": review(P, (M, X, P, MISS, MISS, MISS), "Same snowy scene and base character, but framing/pose differs and final assets are absent."),
    "CUT-035": review(X, (P, X, P, MISS, MISS, MISS), "Related village and base character, but proof is the wrong side/front angle and lacks final assets."),
    "CUT-036": review(X, (P, X, NV, NV, NV, NA), "Canonical ferris-wheel/rooftop composition; proof is a different village/bridge view."),
    "CUT-037": review(X, (P, X, MISS, NA, NA, NA), "Broad village assets may be related, but proof is a distant street view, not the canonical close rear character shot."),
    "CUT-038": review(X, (X, X, X, NA, NA, NA), "Proof frames carousel/house area while canonical shot is the girl near the bridge."),
    "CUT-039": review(X, (P, X, P, MISS, MISS, MISS), "Related carousel location, but camera angle/scale differ and final character assets are missing."),
    "CUT-040": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical carousel-front character shot; proof is a wide village/house view."),
    "CUT-041": review(X, (P, X, NV, NV, NV, NA), "Canonical carousel landscape; proof frames a different bridge/house view."),
    "CUT-042": review(P, (M, X, P, MISS, MISS, MISS), "Same scene and base character, but proof is from the back rather than the canonical frontal fence framing."),
    "CUT-043": review(X, (X, X, X, MISS, MISS, MISS), "Canonical horse-sculpture close-up; proof is a base-character medium shot."),
    "CUT-044": review(X, (P, X, X, MISS, MISS, MISS), "Canonical carousel horses; proof is a base-character side view."),
    "CUT-045": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical rear character shot; proof is an empty landscape from different framing."),
    "CUT-046": review(X, (X, X, MISS, MISS, MISS, NA), "Canonical giant head/city shot; proof is an unrelated empty village view."),
    "CUT-047": review(P, (M, P, MISS, MISS, MISS, NA), "Kitchen/fridge and camera are close, but the canonical grey-outfit character is absent."),
    "CUT-048": review(P, (M, X, MISS, MISS, MISS, NA), "Kitchen location matches, but camera differs and canonical character is absent."),
    "CUT-049": review(X, (M, X, MISS, MISS, MISS, NA), "Kitchen location is present, but proof frames the counter and omits the canonical character."),
    "CUT-050": review(X, (X, X, NV, NV, NV, X), "Canonical hands/object close-up; proof is unrelated wall/shell geometry."),
    "CUT-051": review(X, (X, X, MISS, MISS, MISS, X), "Canonical overhead character/rug shot; proof is an unrelated black-and-white crop."),
    "CUT-052": review(X, (X, X, NV, NV, NV, X), "Canonical top-down rubble shot; proof is an unrelated black-and-white crop."),
    "CUT-053": review(X, (X, X, MISS, MISS, MISS, X), "Canonical overhead character/rug shot; proof is an unrelated black-and-white crop."),
    "CUT-054": review(X, (X, X, NV, NV, NV, X), "Canonical top-down rubble close-up; proof is an unrelated black-and-white crop."),
    "CUT-055": review(X, (X, X, NV, NV, NV, X), "Canonical rubble wide shot; proof is a different bright top-down room crop."),
    "CUT-056": review(P, (M, P, MISS, MISS, MISS, NA), "Wall/location framing is related, but the canonical rear character and final assets are absent."),
    "CUT-057": review(X, (X, X, MISS, MISS, MISS, MISS), "Canonical face close-up; proof is blank white."),
    "CUT-058": review(X, (P, X, MISS, MISS, MISS, NA), "Related room assets, but proof frames bed/wall and omits the canonical character."),
    "CUT-059": review(P, (M, P, P, MISS, MISS, MISS), "Object cluster and base character are related; exact framing and final assets remain incomplete."),
    "CUT-061": review(X, (P, X, P, MISS, MISS, MISS), "Canonical dark profile shot; proof is a close view of legs."),
    "CUT-062": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical floating character is absent; proof shows particles only."),
    "CUT-063": review(P, (P, P, P, P, MISS, MISS), "Base face/hair geometry is related, but exact framing, wardrobe, and materials are incomplete."),
    "CUT-064": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-065": review(X, (P, X, MISS, MISS, MISS, NA), "Canonical dark character/object shot; proof is a top-down object field without the character."),
    "CUT-066": review(P, (M, P, P, P, MISS, MISS), "Character/button close framing is related; hair geometry is present but final wardrobe/materials are absent."),
    "CUT-067": review(X, (P, X, NV, NV, NV, NA), "Canonical pearl close-up; proof is a wide object field."),
    "CUT-068": review(P, (M, P, P, P, MISS, MISS), "Broad floating-character layout is related; exact camera and final wardrobe/materials are incomplete."),
    "CUT-069": review(P, (M, M, P, P, MISS, MISS), "Cube/character composition is a strong camera match, but final character, wardrobe, and materials are incomplete."),
    "CUT-070": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-071": review(P, (M, P, P, P, MISS, MISS), "Close character framing is related; exact overlay and final wardrobe/materials remain incomplete."),
    "CUT-072": review(X, (X, X, MISS, MISS, MISS, X), "Canonical bright-exit close-up; proof is a wide grid/object field."),
    "CUT-074": review(MISS, (NA, NA, NA, NA, NA, NA), "No rendered camera proof is available."),
    "CUT-075": review(P, (M, P, P, MISS, MISS, MISS), "Cabinet close framing and base character are related; final hair, wardrobe, and materials are absent."),
    "CUT-076": review(X, (M, X, P, MISS, MISS, MISS), "Canonical full rear cabinet shot; proof is a close front/base-character framing."),
    "CUT-077": review(P, (M, M, NV, NV, NV, NA), "Yarn-ball geometry and close framing appear to match; final materials remain unverified."),
    "CUT-078": review(X, (M, X, X, MISS, MISS, MISS), "Canonical hand/book shelf close-up; proof is a face-at-cabinet view."),
    "CUT-079": review(X, (M, X, MISS, MISS, MISS, NA), "Canonical character/book shot; proof is an empty cabinet wide view."),
    "CUT-080": review(P, (M, M, P, NV, P, MISS), "Shelf, elephant, and arm framing appear to match; sleeve/wardrobe and final materials are incomplete."),
    "CUT-081": review(P, (M, M, P, NV, P, MISS), "Hand/vase close framing appears to match; sleeve and final materials are incomplete."),
    "CUT-082": review(P, (M, M, P, MISS, MISS, MISS), "Base character pose/background and framing appear to match; final hair, wardrobe, and materials are absent."),
    "CUT-083": review(X, (M, X, P, MISS, MISS, MISS), "Canonical face close-up; proof is a distant full-character corridor framing."),
    "CUT-084": review(P, (M, M, P, MISS, MISS, MISS), "Corridor, base-character framing, and pose appear to match; final hair, wardrobe, and materials are absent."),
    "CUT-085": review(P, (M, M, P, MISS, MISS, MISS), "Room, base-character framing, and pose appear to match; final hair, wardrobe, and materials are absent."),
    "CUT-086": review(X, (P, X, NV, NV, NV, NA), "Canonical close exterior window/house shot; proof is a much wider exterior view."),
    "CUT-087": review(P, (M, M, NV, NV, NV, NA), "Tree-lined path and house geometry/camera appear to match; final materials remain unverified."),
}


def main() -> None:
    payload = {
        "schemaVersion": 2,
        "reviewedAt": datetime.now(timezone.utc).isoformat(),
        "authority": "manual canonical-thumbnail versus C4D camera-proof review",
        "elementStatuses": [
            "match",
            "partial",
            "mismatch",
            "missing",
            "not_visible",
            "not_verifiable",
        ],
        "reviews": REVIEWS,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"output": str(OUTPUT), "reviews": len(REVIEWS)}, indent=2))


if __name__ == "__main__":
    main()
