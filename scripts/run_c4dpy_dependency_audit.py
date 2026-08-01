#!/usr/bin/env python3
"""Run the isolated C4D dependency helper and retain only its JSON payload."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
HELPER = APP_ROOT / "scripts" / "c4dpy_audit_dependencies.py"
DEFAULT_C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026/"
    "c4dpy.app/Contents/MacOS/c4dpy"
)
MARKER = "PARACOSM_DEPENDENCY_AUDIT_JSON="
ERROR_MARKER = "PARACOSM_DEPENDENCY_AUDIT_ERROR="


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--take", default="Main")
    parser.add_argument("--frame", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--c4dpy", type=Path, default=DEFAULT_C4DPY)
    args = parser.parse_args()

    command = [
        str(args.c4dpy),
        str(HELPER),
        "--project",
        str(args.project),
        "--take",
        args.take,
        "--counts-only",
    ]
    if args.frame is not None:
        command.extend(["--frame", str(args.frame)])
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    marker_line = next(
        (
            line
            for line in completed.stdout.splitlines()
            if line.startswith(MARKER)
        ),
        None,
    )
    error_line = next(
        (
            line
            for line in completed.stdout.splitlines()
            if line.startswith(ERROR_MARKER)
        ),
        None,
    )
    if marker_line is None:
        tail = "\n".join(completed.stdout.splitlines()[-40:])
        raise RuntimeError(
            (error_line or "C4D dependency JSON marker missing")
            + f"\nExit code: {completed.returncode}\n{tail}"
        )

    payload = json.loads(marker_line[len(MARKER) :])
    payload["schemaVersion"] = 1
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["method"] = (
        "Isolated Maxon c4dpy GetAllAssetsNew audit evaluated under the "
        f"{args.take} take"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "project": payload["project"],
                "take": payload["take"],
                "dependencies": payload["dependencyReferences"],
                "linked": payload["linkedReferences"],
                "missing": payload["missingReferences"],
                "uniqueMissing": payload["uniqueMissingFiles"],
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
