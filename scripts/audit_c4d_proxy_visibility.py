"""Build a resumable proxy/character visibility census for mapped C4D cuts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRICT_AUDIT = ROOT / "data" / "c4d-strict-audit.json"
OUTPUT = ROOT / "data" / "c4d-scene-state-audit.json"
C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026/c4dpy.app/Contents/MacOS/c4dpy"
)
HELPER = ROOT / "scripts" / "c4dpy_inspect_scene_state.py"
MARKER = "PARACOSM_SCENE_STATE_JSON="


def frame_from_record(record: dict) -> int:
    match = re.search(r"\bframe\s+(\d+)\b", record.get("cameraName") or "")
    return int(match.group(1)) if match else 0


def active_count(scene: dict, category: str) -> int:
    return sum(
        1
        for item in scene.get("assetGroups", {}).get(category, [])
        if item.get("effectiveRenderEnabled")
    )


def active_root_count(scene: dict, category: str) -> int:
    return sum(
        1
        for item in scene.get("assetRoots", {}).get(category, [])
        if item.get("effectiveRenderEnabled")
    )


def classify(scene: dict) -> str:
    active_proxies = sum(
        1
        for item in scene.get("redshiftProxies", [])
        if item.get("effectiveRenderEnabled")
    )
    active_characters = active_count(scene, "character")
    if active_proxies and not active_characters:
        return "proxy_active_character_hidden"
    if active_proxies and active_characters:
        return "proxy_and_character_active"
    if active_characters:
        return "character_active_no_proxy"
    return "no_character_or_proxy_active"


def summarize(projects: list[dict]) -> dict:
    picture_cuts = sum(len(item.get("cuts", [])) for item in projects)
    inspected = [item for item in projects if item.get("status") == "inspected"]
    diagnoses = defaultdict(int)
    proxy_cuts = 0
    active_proxy_objects = 0
    for item in inspected:
        diagnoses[item["diagnosis"]] += len(item["cuts"])
        if item["activeProxyCount"]:
            proxy_cuts += len(item["cuts"])
            active_proxy_objects += item["activeProxyCount"]
    return {
        "mappedC4dProjects": len(projects),
        "mappedPictureCuts": picture_cuts,
        "inspectedProjects": len(inspected),
        "inspectedPictureCuts": sum(len(item["cuts"]) for item in inspected),
        "failedProjects": sum(item.get("status") == "failed" for item in projects),
        "activeProxyCuts": proxy_cuts,
        "activeProxyObjects": active_proxy_objects,
        "diagnosisCuts": dict(sorted(diagnoses.items())),
    }


def persist(projects: list[dict]) -> None:
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Read-only C4D 2026 scene/take inspection. An active Redshift proxy "
            "with a disabled editable character is evidence that the baked "
            "proxy is render-critical, not proof that its file is linked."
        ),
        "summary": summarize(projects),
        "projects": projects,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")


def inspect(project: Path, frame: int, timeout: int) -> dict:
    command = [
        str(C4DPY),
        str(HELPER),
        "--project",
        str(project),
        "--frame",
        str(frame),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    combined = completed.stdout + "\n" + completed.stderr
    marker_line = next(
        (line for line in reversed(combined.splitlines()) if line.startswith(MARKER)),
        None,
    )
    if not marker_line:
        raise RuntimeError(
            f"c4dpy returned {completed.returncode} without result marker: "
            + combined[-1200:]
        )
    return json.loads(marker_line[len(MARKER) :])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    strict = json.loads(STRICT_AUDIT.read_text())
    grouped = defaultdict(list)
    for record in strict["records"]:
        path = record.get("projectPath")
        if not path or Path(path).suffix.casefold() != ".c4d":
            continue
        grouped[path].append(record)

    existing = {}
    if OUTPUT.exists() and not args.refresh:
        for record in json.loads(OUTPUT.read_text()).get("projects", []):
            existing[record["projectPath"]] = record

    requested = {str(Path(item).expanduser().resolve()) for item in args.project}
    project_paths = sorted(
        grouped,
        key=lambda path: (
            -Path(path).stat().st_size if Path(path).exists() else 0,
            path.casefold(),
        ),
    )
    if requested:
        project_paths = [path for path in project_paths if path in requested]
    if args.limit:
        project_paths = project_paths[: args.limit]

    records_by_path = dict(existing)
    completed_this_run = 0
    for index, path_string in enumerate(project_paths, 1):
        if path_string in existing and not args.refresh:
            continue
        path = Path(path_string)
        source_records = grouped[path_string]
        frame = frame_from_record(source_records[0])
        base = {
            "projectPath": path_string,
            "projectName": path.name,
            "sizeBytes": path.stat().st_size if path.exists() else None,
            "frameInspected": frame,
            "cuts": [item["cutId"] for item in source_records],
            "plannedShotIds": [
                item.get("plannedShotId") for item in source_records
            ],
        }
        print(
            f"[{index}/{len(project_paths)}] {path.name} "
            f"({', '.join(base['cuts'])})",
            flush=True,
        )
        try:
            if not path.exists():
                raise FileNotFoundError(path)
            scene = inspect(path, frame, args.timeout)
            active_proxies = [
                item
                for item in scene.get("redshiftProxies", [])
                if item.get("effectiveRenderEnabled")
            ]
            base.update(
                {
                    "status": "inspected",
                    "diagnosis": classify(scene),
                    "activeProxyCount": len(active_proxies),
                    "activeCharacterObjectCount": active_count(
                        scene, "character"
                    ),
                    "activeCharacterRootCount": active_root_count(
                        scene, "character"
                    ),
                    "activeHairObjectCount": active_count(scene, "hair"),
                    "activeWardrobeObjectCount": active_count(
                        scene, "wardrobe"
                    ),
                    "redshiftProxies": scene.get("redshiftProxies", []),
                    "assetGroups": scene.get("assetGroups", {}),
                    "assetRoots": scene.get("assetRoots", {}),
                    "cameras": scene.get("cameras", []),
                    "takes": scene.get("takes", []),
                }
            )
        except Exception as error:
            base.update(
                {
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
        records_by_path[path_string] = base
        completed_this_run += 1
        persist(
            [
                records_by_path[key]
                for key in sorted(records_by_path, key=str.casefold)
            ]
        )
        print(
            f"  {base['status']}: {base.get('diagnosis', base.get('error'))}",
            flush=True,
        )

    projects = [
        records_by_path[key]
        for key in sorted(records_by_path, key=str.casefold)
    ]
    persist(projects)
    print(
        "PARACOSM_PROXY_VISIBILITY_AUDIT_JSON="
        + json.dumps(
            {
                "output": str(OUTPUT),
                "completedThisRun": completed_this_run,
                "summary": summarize(projects),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
