#!/usr/bin/env python3
"""Collect read-only evaluated camera transforms for candidate C4D scenes."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026/c4dpy.app/Contents/MacOS/c4dpy"
)
HELPER = ROOT / "scripts" / "c4dpy_probe_camera_state.py"
DEFAULT_TARGETS = ROOT / "data" / "c4d-unmapped-camera-candidates-20260726.json"
DEFAULT_OUTPUT = ROOT / "data" / "c4d-unmapped-camera-state-probes-20260726.json"
MARKER = "PARACOSM_CAMERA_STATE_JSON="


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    target_data = load(args.targets.expanduser().resolve())
    prior: dict[tuple[str, str, str], dict[str, Any]] = {}
    if args.output.exists():
        prior = {
            (
                str(item.get("cutId")),
                str(item.get("project")),
                str(item.get("cameraTake") or ""),
            ): item
            for item in load(args.output).get("records", [])
        }
    records: list[dict[str, Any]] = []
    tasks = [
        (target, Path(project).expanduser().resolve(), take)
        for target in target_data.get("targets", [])
        for project in target.get("projects", [])
        for take in (target.get("takes") or [None])
    ]
    for index, (target, project, take) in enumerate(tasks, start=1):
        key = (str(target["cutId"]), str(project), str(take or ""))
        existing = prior.get(key)
        if existing and existing.get("status") == "probed":
            records.append(existing)
            print(
                f"[{index}/{len(tasks)}] resume {target['cutId']} · "
                f"{project.name} · {take or 'saved take'}"
            )
            continue
        record: dict[str, Any] = {
            "cutId": target["cutId"],
            "targetFrame": int(target["targetFrame"]),
            "project": str(project),
            "aecPath": target.get("aecPath"),
            "cameraTake": take,
            "status": "failed",
        }
        print(
            f"[{index}/{len(tasks)}] {target['cutId']} · {project.name} · "
            f"{take or 'saved take'}",
            flush=True,
        )
        if not project.exists():
            record["error"] = "candidate project missing"
            records.append(record)
            continue
        command = [
            str(C4DPY),
            str(HELPER),
            "--project",
            str(project),
            "--frame",
            str(target["targetFrame"]),
        ]
        if take:
            command.extend(["--take", str(take)])
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            marker_line = next(
                (line for line in output.splitlines() if line.startswith(MARKER)),
                None,
            )
            if marker_line is None:
                raise RuntimeError(
                    f"c4dpy returned {completed.returncode} without marker: "
                    + output[-1200:]
                )
            payload = json.loads(marker_line[len(MARKER) :])
            record.update(payload)
            record["status"] = "probed"
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "generatedAt": datetime.now(timezone.utc).isoformat(),
                    "records": records,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(f"Wrote {len(records)} camera-state probes to {args.output}")


if __name__ == "__main__":
    main()
