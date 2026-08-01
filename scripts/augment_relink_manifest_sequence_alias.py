#!/usr/bin/env python3
"""Add an explicitly verified same-frame sequence alias to a relink manifest.

This is for production caches whose directory and filename stem changed while
the frame numbering stayed authoritative. It edits only the generated JSON
manifest; the source Cinema 4D document remains read-only.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--required-stem",
        required=True,
        help="Filename stem before the zero-padded frame number.",
    )
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument(
        "--target-stem",
        required=True,
        help="Target filename stem before the zero-padded frame number.",
    )
    parser.add_argument("--extension", default=".rs")
    parser.add_argument("--frame-digits", type=int, default=4)
    parser.add_argument(
        "--evidence-note",
        required=True,
        help="Human-readable reason this sequence alias is authoritative.",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    target_dir = args.target_dir.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unresolved = list(manifest.get("unresolved") or [])
    unresolved_candidates = list(
        manifest.get("unresolvedCandidates") or []
    )
    extension = args.extension
    pattern = re.compile(
        rf"^{re.escape(args.required_stem)}"
        rf"(?P<frame>\d{{{args.frame_digits}}})"
        rf"{re.escape(extension)}$",
        re.IGNORECASE,
    )

    added: list[dict[str, object]] = []
    retained: list[str] = []
    mapped_required: set[str] = set()
    for required in unresolved:
        basename = Path(str(required).replace("\\", "/")).name
        match = pattern.match(basename)
        if match is None:
            retained.append(required)
            continue
        frame_text = match.group("frame")
        target = target_dir / (
            f"{args.target_stem}{frame_text}{extension}"
        )
        if not target.is_file():
            retained.append(required)
            continue
        added.append(
            {
                "requiredPath": required,
                "targetPath": str(target),
                "basename": basename,
                "selectionBasis": "verified_same_frame_sequence_alias",
                "targetBasename": target.name,
                "frame": int(frame_text),
                "targetSizeBytes": target.stat().st_size,
                "evidenceNote": args.evidence_note,
            }
        )
        mapped_required.add(required)

    if not added:
        raise RuntimeError("No unresolved paths matched the verified alias")

    manifest.setdefault("mappings", []).extend(added)
    manifest["unresolved"] = retained
    manifest["unresolvedCandidates"] = [
        item
        for item in unresolved_candidates
        if item.get("requiredPath") not in mapped_required
    ]
    manifest.setdefault("sequenceAliasEvidence", []).append(
        {
            "appliedAt": utc_now(),
            "requiredStem": args.required_stem,
            "targetDirectory": str(target_dir),
            "targetStem": args.target_stem,
            "extension": extension,
            "frameDigits": args.frame_digits,
            "mappedReferences": len(added),
            "uniqueTargetFrames": len(
                {int(item["frame"]) for item in added}
            ),
            "note": args.evidence_note,
        }
    )
    summary = manifest.setdefault("summary", {})
    summary["mappedPaths"] = len(manifest["mappings"])
    summary["unresolvedPaths"] = len(retained)
    summary["sameFrameSequenceAliasSelections"] = (
        summary.get("sameFrameSequenceAliasSelections", 0) + len(added)
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(
        f"Added {len(added)} same-frame mappings; "
        f"{len(retained)} unresolved paths remain"
    )


if __name__ == "__main__":
    main()
