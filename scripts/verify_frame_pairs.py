#!/usr/bin/env python3
"""Archive and score final-frame ↔ terminal source-frame comparison pairs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

APP_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = APP_ROOT / "data" / "conform-manifest.json"
REFERENCE_MOV = Path(
    "/Users/alphaone/Desktop/desktop 0705/Paracosm Full Copy 01.mov"
)
COMPARE_DIR = APP_ROOT / "public" / "archive" / "conform"
EXPORT_PATH = APP_ROOT / "data" / "conform-verification.json"
IMAGE_EXTENSIONS = {".tif", ".tiff", ".exr", ".png", ".jpg", ".jpeg"}


def run_ffmpeg(source: Path, target: Path, at: float | None = None) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if at is not None:
        command.extend(["-ss", f"{at:.6f}"])
    command.extend(
        [
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=720:-2",
            "-q:v",
            "3",
            "-y",
            str(target),
        ]
    )
    subprocess.run(command, check=True)


def correlation(first: np.ndarray, second: np.ndarray) -> float:
    first = first.astype(np.float32).reshape(-1)
    second = second.astype(np.float32).reshape(-1)
    first -= first.mean()
    second -= second.mean()
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    return float(np.dot(first, second) / denominator) if denominator else 0.0


def score_pair(final_path: Path, source_path: Path) -> dict[str, float]:
    with Image.open(final_path) as final_image, Image.open(source_path) as source_image:
        final_gray = np.asarray(
            ImageOps.fit(final_image.convert("L"), (160, 90), method=Image.Resampling.LANCZOS)
        )
        source_gray = np.asarray(
            ImageOps.fit(source_image.convert("L"), (160, 90), method=Image.Resampling.LANCZOS)
        )
    luminance = correlation(final_gray, source_gray)
    final_y, final_x = np.gradient(final_gray.astype(np.float32))
    source_y, source_x = np.gradient(source_gray.astype(np.float32))
    final_edges = np.hypot(final_x, final_y)
    source_edges = np.hypot(source_x, source_y)
    edges = correlation(final_edges, source_edges)
    score = max(0.0, min(1.0, 0.65 * ((luminance + 1) / 2) + 0.35 * ((edges + 1) / 2)))
    return {
        "score": round(score, 4),
        "luminanceCorrelation": round(luminance, 4),
        "edgeCorrelation": round(edges, 4),
    }


def neighboring_frames(path: Path) -> list[Path]:
    match = re.search(r"(\d+)(\.[^.]+)$", path.name)
    if not match:
        return [path]
    frame = int(match.group(1))
    width = len(match.group(1))
    candidates = []
    for offset in range(-2, 3):
        value = frame + offset
        candidate = path.with_name(
            path.name[: match.start(1)]
            + str(value).zfill(width)
            + match.group(2)
        )
        if candidate.exists():
            candidates.append(candidate)
    return candidates or [path]


def concrete_sequence_frame(source_path: str, frame_number: int) -> Path:
    range_match = re.search(r"\[(\d+)-(\d+)\](\.[^.]+)$", source_path)
    if range_match:
        return Path(
            source_path[: range_match.start()]
            + str(frame_number).zfill(len(range_match.group(1)))
            + range_match.group(3)
        )
    match = re.search(r"(\d+)(\.[^.]+)$", source_path)
    if not match:
        return Path(source_path)
    return Path(
        source_path[: match.start(1)]
        + str(frame_number).zfill(len(match.group(1)))
        + match.group(2)
    )


def comparison_sheet(final_path: Path, source_path: Path, target: Path) -> None:
    with Image.open(final_path) as final_image, Image.open(source_path) as source_image:
        final_rgb = ImageOps.fit(
            final_image.convert("RGB"), (720, 405), method=Image.Resampling.LANCZOS
        )
        source_rgb = ImageOps.fit(
            source_image.convert("RGB"), (720, 405), method=Image.Resampling.LANCZOS
        )
    sheet = Image.new("RGB", (1440, 441), "#111111")
    sheet.paste(final_rgb, (0, 36))
    sheet.paste(source_rgb, (720, 36))
    draw = ImageDraw.Draw(sheet)
    draw.text((14, 11), "FINAL REFERENCE", fill="#d7f452")
    draw.text((734, 11), "TERMINAL SOURCE FRAME", fill="#d7f452")
    sheet.save(target, quality=90)


def evidence_for(score: float) -> str:
    if score >= 0.82:
        return "visually_confirmed"
    if score >= 0.68:
        return "strong_inference"
    return "candidate"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--section",
        action="append",
        help="Limit verification to section codes. Defaults to every section.",
    )
    parser.add_argument("--limit", type=int, help="Verify at most this many segments.")
    args = parser.parse_args()
    sections = {value.upper() for value in args.section or []}

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    COMPARE_DIR.mkdir(parents=True, exist_ok=True)
    matches: list[dict[str, Any]] = []
    segments = [
        segment
        for segment in manifest.get("segments", [])
        if not sections or segment.get("sectionCode") in sections
    ]
    if args.limit:
        segments = segments[: args.limit]
    with tempfile.TemporaryDirectory(prefix="paracosm-frame-pairs-") as temp_value:
        temp = Path(temp_value)
        for segment in segments:
            try:
                source_start = int(segment["sourceStartFrame"])
                source_end = int(segment["sourceEndFrame"])
                source_frame = round(source_start + (source_end - source_start) / 2)
                final_time = (
                    float(segment["finalStart"]) + float(segment["finalEnd"])
                ) / 2
            except (KeyError, TypeError, ValueError):
                continue
            source_path = concrete_sequence_frame(
                str(segment.get("sourcePath") or ""), source_frame
            )
            if not source_path.exists():
                source_path = Path(str(segment.get("sourceFirstFramePath") or ""))
            if (
                not source_path.exists()
                or source_path.suffix.lower() not in IMAGE_EXTENSIONS
            ):
                continue
            segment_id = str(segment["id"])
            final_path = COMPARE_DIR / f"{segment_id}-final.jpg"
            source_archive = COMPARE_DIR / f"{segment_id}-source.jpg"
            pair_path = COMPARE_DIR / f"{segment_id}-pair.jpg"
            run_ffmpeg(REFERENCE_MOV, final_path, final_time)

            best = None
            for candidate_index, candidate in enumerate(neighboring_frames(source_path)):
                converted = temp / f"{segment_id}-{candidate_index}.jpg"
                try:
                    run_ffmpeg(candidate, converted)
                    metrics = score_pair(final_path, converted)
                except (OSError, subprocess.CalledProcessError):
                    continue
                if best is None or metrics["score"] > best["metrics"]["score"]:
                    best = {
                        "path": candidate,
                        "converted": converted,
                        "metrics": metrics,
                    }
            if not best:
                continue
            shutil.copy2(best["converted"], source_archive)
            comparison_sheet(final_path, source_archive, pair_path)
            metrics = best["metrics"]
            matches.append(
                {
                    "segmentId": segment_id,
                    "sectionCode": segment["sectionCode"],
                    "finalTime": round(final_time, 6),
                    "expectedSourceFrame": source_frame,
                    "sourceFramePath": str(best["path"]),
                    "finalImage": f"/archive/conform/{final_path.name}",
                    "sourceImage": f"/archive/conform/{source_archive.name}",
                    "pairImage": f"/archive/conform/{pair_path.name}",
                    **metrics,
                    "evidence": evidence_for(metrics["score"]),
                }
            )
            print(
                f"{segment_id} {segment['sectionCode']} "
                f"score={metrics['score']:.4f} {best['path'].name}",
                flush=True,
            )

    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "referencePath": str(REFERENCE_MOV),
        "manifestPath": str(MANIFEST_PATH),
        "matches": matches,
        "summary": {
            "requested": len(segments),
            "archived": len(matches),
            "visuallyConfirmed": sum(
                1 for item in matches if item["evidence"] == "visually_confirmed"
            ),
            "strongInference": sum(
                1 for item in matches if item["evidence"] == "strong_inference"
            ),
            "candidate": sum(
                1 for item in matches if item["evidence"] == "candidate"
            ),
        },
    }
    EXPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {len(matches)} frame pairs to {EXPORT_PATH}")


if __name__ == "__main__":
    main()
