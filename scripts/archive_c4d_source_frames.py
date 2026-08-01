#!/usr/bin/env python3
"""Archive one exact beauty-frame candidate from each canonical render source."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROOFS = (
    ROOT / "data" / "c4d-camera-proof-renders-corrected-20260726.json"
)
DEFAULT_OUTPUT_DIR = ROOT / "public" / "archive" / "c4d-source-frames-20260726"
DEFAULT_MANIFEST = ROOT / "data" / "c4d-source-frame-archive-20260726.json"
DEFAULT_TARGET_OVERRIDES = (
    ROOT / "data" / "c4d-unmapped-camera-candidates-20260726.json"
)
IMAGE_EXTENSIONS = {".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg"}
PASS_TOKENS = (
    "puzzlematte",
    "puzzle matte",
    "cryptomatte",
    "ambientocclusion",
    "albedo",
    "diffuse",
    "reflection",
    "refraction",
    "specular",
    "shadow",
    "depth",
    "motionvector",
    "normal",
    "emission",
    "denoising",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def frame_numbers(path: Path) -> list[int]:
    return [int(value) for value in re.findall(r"\d+", path.stem)]


def candidate_score(path: Path, target_frame: int) -> tuple[int, int, int, str]:
    numbers = frame_numbers(path)
    exact_last = bool(numbers and numbers[-1] == target_frame)
    normalized = path.stem.casefold().replace("_", " ")
    pass_penalty = sum(token in normalized for token in PASS_TOKENS)
    return (
        pass_penalty,
        0 if exact_last else 1,
        len(path.name),
        path.name.casefold(),
    )


def find_source_frame(render_path: Path, target_frame: int) -> Path | None:
    if not render_path.is_dir():
        return None
    candidates = [
        path
        for path in render_path.iterdir()
        if path.is_file()
        and path.suffix.casefold() in IMAGE_EXTENSIONS
        and target_frame in frame_numbers(path)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda path: candidate_score(path, target_frame))


def archive_frame(source: Path, output: Path) -> tuple[bool, str | None]:
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-frames:v",
            "1",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not output.exists():
        return False, (completed.stderr or completed.stdout or "ffmpeg failed")[-1200:]
    return True, None


def public_path(path: Path) -> str:
    return "/" + str(path.resolve().relative_to((ROOT / "public").resolve()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proofs", type=Path, default=DEFAULT_PROOFS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cut-id", action="append", default=[])
    parser.add_argument(
        "--target-overrides",
        type=Path,
        default=DEFAULT_TARGET_OVERRIDES,
    )
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    proofs = load(args.proofs.expanduser().resolve()).get("proofs", [])
    selected_cuts = set(args.cut_id)
    if selected_cuts:
        proofs = [
            proof
            for proof in proofs
            if str(proof["cutIds"][0]) in selected_cuts
        ]
    target_overrides = {}
    if args.target_overrides.exists():
        target_overrides = {
            str(item["cutId"]): item.get("targetFrame")
            for item in load(args.target_overrides).get("targets", [])
            if item.get("targetFrame") is not None
        }
    for index, proof in enumerate(proofs, start=1):
        cut_id = str(proof["cutIds"][0])
        target_value = proof.get("targetFrame")
        if target_value is None:
            target_value = target_overrides.get(cut_id)
        if target_value is None:
            records.append(
                {
                    "cutId": cut_id,
                    "sourceId": proof["sourceId"],
                    "targetFrame": None,
                    "renderPath": str(proof.get("renderPath") or ""),
                    "sourceFramePath": None,
                    "outputPath": None,
                    "publicPath": None,
                    "status": "target_frame_unresolved",
                }
            )
            print(
                f"[{index}/{len(proofs)}] {cut_id} · target_frame_unresolved",
                flush=True,
            )
            continue
        target_frame = int(target_value)
        render_path = Path(str(proof["renderPath"])).expanduser().resolve()
        source = find_source_frame(render_path, target_frame)
        output = args.output_dir.expanduser().resolve() / f"{cut_id}.png"
        record: dict[str, Any] = {
            "cutId": cut_id,
            "sourceId": proof["sourceId"],
            "targetFrame": target_frame,
            "renderPath": str(render_path),
            "sourceFramePath": str(source) if source else None,
            "outputPath": str(output),
            "publicPath": public_path(output),
            "status": "source_frame_missing",
        }
        if source is not None:
            ok, error = archive_frame(source, output)
            record["status"] = "archived" if ok else "archive_failed"
            if error:
                record["error"] = error
        records.append(record)
        print(
            f"[{index}/{len(proofs)}] {cut_id} · {record['status']}",
            flush=True,
        )

    statuses: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        statuses[status] = statuses.get(status, 0) + 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Exact source-frame candidates resolved from canonical C4D render "
            "directories and archived without modifying source media."
        ),
        "summary": {
            "records": len(records),
            "statuses": statuses,
        },
        "records": records,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
