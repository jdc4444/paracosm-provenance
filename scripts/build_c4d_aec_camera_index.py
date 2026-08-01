#!/usr/bin/env python3
"""Index exact active-camera frames preserved beside C4D render exports."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROOFS = (
    ROOT / "data" / "c4d-camera-proof-renders-corrected-20260726.json"
)
DEFAULT_OUTPUT = ROOT / "data" / "c4d-aec-camera-index-20260726.json"
SUPPLEMENTAL_AEC = [
    {
        "cutId": "CUT-086",
        "sourceId": "CLEAN-SRC-084",
        "targetFrame": 242,
        "renderPath": (
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
            "SG/C4D/_renders/AS/IJDKYY/0416/house zoom out"
        ),
        "aecPath": (
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
            "SG/C4D/_renders/AS/IJDKYY/zoom out/zoom out.aec"
        ),
        "projectCandidates": [
            (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/AS/0 Finishing/02 Projects/06 IJDKYY/"
                "zoom out house/zoom out house.c4d"
            ),
            (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/AS/0 Finishing/02 Projects/06 IJDKYY/"
                "zoom out house/zoom out house v2.c4d"
            ),
        ],
        "evidence": (
            "The source-era zoom out AEC preserves one active RS Camera "
            "transform at the canonical frame."
        ),
    },
    {
        "cutId": "CUT-087",
        "sourceId": "CLEAN-SRC-085",
        "targetFrame": 174,
        "renderPath": (
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
            "SG/C4D/_renders/AS/IJDKYY/0416/house zoom out - Copy"
        ),
        "aecPath": (
            "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely/"
            "SG/C4D/_renders/AS/IJDKYY/zoom out/zoom out.aec"
        ),
        "projectCandidates": [
            (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/AS/0 Finishing/02 Projects/06 IJDKYY/"
                "zoom out house/zoom out house.c4d"
            ),
            (
                "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/"
                "Absolutely/AS/0 Finishing/02 Projects/06 IJDKYY/"
                "zoom out house/zoom out house v2.c4d"
            ),
        ],
        "evidence": (
            "The source-era zoom out AEC preserves one active RS Camera "
            "transform at the canonical frame."
        ),
    },
]
CAMERA_RE = re.compile(r'^CAMERA\s+"(?P<name>.*)"\s*$')
KEY_RE = re.compile(
    r"^\s*KEY\s+"
    r"(?P<frame>-?\d+)\s+"
    r"(?P<x>-?[\d.]+)\s+(?P<y>-?[\d.]+)\s+(?P<z>-?[\d.]+)\s+"
    r"(?P<rx>-?[\d.]+)\s+(?P<ry>-?[\d.]+)\s+(?P<rz>-?[\d.]+)\s+"
    r"(?P<fov>-?[\d.]+)\s+(?P<focus>-?[\d.]+)\s+"
    r"(?P<active>[01])\s*$"
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_aec(path: Path) -> list[dict[str, Any]]:
    cameras: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        camera_match = CAMERA_RE.match(raw_line)
        if camera_match:
            current = {"name": camera_match.group("name"), "keys": []}
            cameras.append(current)
            continue
        key_match = KEY_RE.match(raw_line)
        if current is None or key_match is None:
            continue
        values = key_match.groupdict()
        current["keys"].append(
            {
                "frame": int(values["frame"]),
                "position": {
                    "x": float(values["x"]),
                    "y": float(values["y"]),
                    "z": float(values["z"]),
                },
                "rotationDegrees": {
                    "x": float(values["rx"]),
                    "y": float(values["ry"]),
                    "z": float(values["rz"]),
                },
                "fieldOfViewDegrees": float(values["fov"]),
                "focusDistance": float(values["focus"]),
                "active": values["active"] == "1",
            }
        )
    return cameras


def exact_target_keys(
    cameras: list[dict[str, Any]], target_frame: int
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for camera in cameras:
        for key in camera["keys"]:
            if key["frame"] != target_frame:
                continue
            matches.append({"cameraName": camera["name"], **key})
    return matches


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proofs", type=Path, default=DEFAULT_PROOFS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    for proof in load(args.proofs.expanduser().resolve()).get("proofs", []):
        render_path = Path(str(proof["renderPath"])).expanduser().resolve()
        aec_paths = sorted(render_path.glob("*.aec")) if render_path.is_dir() else []
        if not aec_paths:
            continue
        for aec_path in aec_paths:
            cameras = parse_aec(aec_path)
            target_frame = int(proof["targetFrame"])
            target_keys = exact_target_keys(cameras, target_frame)
            active_keys = [item for item in target_keys if item["active"]]
            active_snapshots = [
                {"cameraName": camera["name"], **key}
                for camera in cameras
                for key in camera["keys"]
                if key["active"]
            ]
            records.append(
                {
                    "cutId": proof["cutIds"][0],
                    "sourceId": proof["sourceId"],
                    "targetFrame": target_frame,
                    "renderPath": str(render_path),
                    "projectPath": proof.get("projectPath"),
                    "savedCameraName": proof.get("cameraName"),
                    "savedCameraObjectPath": proof.get("cameraObjectPath"),
                    "aecPath": str(aec_path),
                    "cameraCount": len(cameras),
                    "targetKeys": target_keys,
                    "activeTargetKeys": active_keys,
                    "activeSnapshots": active_snapshots,
                    "activeCameraNames": sorted(
                        {
                            str(item["cameraName"])
                            for item in active_snapshots
                        }
                    ),
                    "status": (
                        "exact_active_camera_preserved"
                        if len(active_keys) == 1
                        else "ambiguous_active_camera"
                        if len(active_keys) > 1
                        else "active_camera_name_preserved_at_other_frame"
                        if active_snapshots
                        else "target_frame_not_preserved"
                    ),
                }
            )

    for supplemental in SUPPLEMENTAL_AEC:
        aec_path = Path(str(supplemental["aecPath"])).expanduser().resolve()
        if not aec_path.exists():
            continue
        cameras = parse_aec(aec_path)
        target_frame = int(supplemental["targetFrame"])
        target_keys = exact_target_keys(cameras, target_frame)
        active_keys = [item for item in target_keys if item["active"]]
        active_snapshots = [
            {"cameraName": camera["name"], **key}
            for camera in cameras
            for key in camera["keys"]
            if key["active"]
        ]
        records.append(
            {
                **supplemental,
                "aecPath": str(aec_path),
                "cameraCount": len(cameras),
                "targetKeys": target_keys,
                "activeTargetKeys": active_keys,
                "activeSnapshots": active_snapshots,
                "activeCameraNames": sorted(
                    {
                        str(item["cameraName"])
                        for item in active_snapshots
                    }
                ),
                "status": (
                    "exact_active_camera_preserved"
                    if len(active_keys) == 1
                    else "ambiguous_active_camera"
                    if len(active_keys) > 1
                    else "target_frame_not_preserved"
                ),
            }
        )

    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Read-only parse of C4D After Effects camera exports stored "
            "beside canonical source-render sequences."
        ),
        "summary": {
            "records": len(records),
            "cuts": len({str(item["cutId"]) for item in records}),
            "statuses": status_counts,
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
