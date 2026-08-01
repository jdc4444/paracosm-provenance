#!/usr/bin/env python3
"""Render real Redshift grey proofs for scenes whose character is an RS proxy.

Hardware Preview cannot display Redshift proxy geometry. This runner therefore
uses the retained shot camera/take with Redshift itself, in isolated read-only
c4dpy processes, and never saves a source document.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026/c4dpy.app/Contents/MacOS/c4dpy"
)
HELPER = ROOT / "scripts" / "c4dpy_redshift_frame_test.py"
SCENE_AUDIT = ROOT / "data" / "c4d-scene-state-audit.json"
PROOFS = ROOT / "data" / "c4d-camera-proof-renders-corrected-20260726.json"
OUTPUT_DIR = ROOT / "public" / "archive" / "redshift-proxy-proofs-20260726"
MANIFEST = ROOT / "data" / "c4d-redshift-proxy-proofs-20260726.json"
MARKER = "PARACOSM_REDSHIFT_TEST_JSON="
LEGACY_RS_CAMERA_OBJECT_ID = 1057516


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "proof"


def write_manifest(path: Path, records: list[dict[str, Any]]) -> None:
    statuses = Counter(str(item.get("status") or "pending") for item in records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "authority": (
                    "Read-only Redshift grey proofs for render-enabled Redshift "
                    "proxy scenes and hardware-preview failures. Visual "
                    "comparison to the canonical thumbnail is still required "
                    "before any camera or asset is accepted."
                ),
                "summary": {
                    "targets": len(records),
                    "statuses": dict(statuses),
                    "cuts": len({str(item.get("cutId")) for item in records}),
                    "projects": len(
                        {str(item.get("projectPath")) for item in records}
                    ),
                },
                "records": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cut-id", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    proof_by_cut = {
        str(cut_id): proof
        for proof in load(PROOFS).get("proofs", [])
        for cut_id in proof.get("cutIds", [])
    }
    selected = set(args.cut_id)
    records: list[dict[str, Any]] = []
    for project in load(SCENE_AUDIT).get("projects", []):
        project_cut_proofs = [
            proof_by_cut.get(str(cut_id))
            for cut_id in project.get("cuts", [])
        ]
        has_failed_hardware_proof = any(
            proof and proof.get("status") == "failed"
            for proof in project_cut_proofs
        )
        has_active_proxy = bool(project.get("activeProxyCount")) and str(
            project.get("diagnosis") or ""
        ).startswith("proxy_")
        if not has_active_proxy and not has_failed_hardware_proof:
            continue
        cameras = {
            str(camera.get("path") or camera.get("name") or ""): camera
            for camera in project.get("cameras", [])
        }
        for cut_id in project.get("cuts", []):
            cut_id = str(cut_id)
            if selected and cut_id not in selected:
                continue
            proof = proof_by_cut.get(cut_id)
            if not proof or proof.get("targetFrame") is None:
                continue
            if (
                not has_active_proxy
                and proof.get("status") != "failed"
            ):
                continue
            camera_path = str(
                proof.get("cameraObjectPath")
                or (proof.get("cameraObject") or {}).get("objectPath")
                or proof.get("cameraName")
                or ""
            )
            camera_audit = cameras.get(camera_path) or {}
            output = (
                args.output_dir.expanduser().resolve()
                / f"{cut_id}-{slug(Path(str(project['projectPath'])).stem)}"
                f"-f{int(proof['targetFrame']):06d}.png"
            )
            records.append(
                {
                    "cutId": cut_id,
                    "projectPath": project["projectPath"],
                    "targetFrame": int(proof["targetFrame"]),
                    "cameraName": proof.get("cameraName"),
                    "cameraPath": camera_path,
                    "cameraTake": proof.get("cameraTake") or "Main",
                    "cameraRenderData": proof.get("cameraRenderData"),
                    "cameraTypeId": camera_audit.get("typeId"),
                    "proxyObjects": project.get("redshiftProxies", []),
                    "outputPath": str(output),
                    "publicPath": "/"
                    + output.relative_to(ROOT / "public").as_posix(),
                    "status": "pending",
                }
            )

    prior: dict[str, dict[str, Any]] = {}
    if args.manifest.exists():
        prior = {
            str(item["cutId"]): item
            for item in load(args.manifest).get("records", [])
        }
    for index, item in enumerate(records):
        previous = prior.get(str(item["cutId"]))
        if previous and previous.get("isolatedProofs"):
            records[index]["isolatedProofs"] = previous["isolatedProofs"]
        if (
            previous
            and previous.get("status") == "rendered"
            and Path(str(previous.get("outputPath") or "")).exists()
        ):
            records[index] = previous
    write_manifest(args.manifest, records)
    if args.plan_only:
        print(f"Planned {len(records)} Redshift proxy proofs")
        return

    for index, record in enumerate(records, start=1):
        if record.get("status") == "rendered":
            print(f"[{index}/{len(records)}] resume {record['cutId']}", flush=True)
            continue
        print(
            f"[{index}/{len(records)}] {record['cutId']} · "
            f"{Path(str(record['projectPath'])).name}",
            flush=True,
        )
        command = [
            str(C4DPY),
            str(HELPER),
            "--project",
            str(record["projectPath"]),
            "--output",
            str(record["outputPath"]),
            "--frame",
            str(record["targetFrame"]),
            "--camera",
            str(record["cameraName"]),
            "--camera-path",
            str(record["cameraPath"]),
            "--take",
            str(record["cameraTake"]),
            "--render-data",
            str(record["cameraRenderData"]),
            "--grey-override",
            "--width",
            "480",
            "--height",
            "270",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            marker = next(
                (line for line in output.splitlines() if line.startswith(MARKER)),
                None,
            )
            if marker is None:
                raise RuntimeError(
                    f"c4dpy returned {completed.returncode} without marker: "
                    + output[-1600:]
                )
            payload = json.loads(marker[len(MARKER) :])
            record.update(payload)
        except Exception as error:
            record["status"] = "failed"
            record["error"] = f"{type(error).__name__}: {error}"
        write_manifest(args.manifest, records)
    print(f"Wrote {len(records)} Redshift proxy proofs to {args.manifest}")


if __name__ == "__main__":
    main()
