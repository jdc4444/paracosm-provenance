#!/usr/bin/env python3
"""Build the lightweight, seek-friendly final-film proxy used by card scrubbing."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(
    "/Users/alphaone/Desktop/desktop 0705/Paracosm Full Copy 01.mov"
)
DEFAULT_OUTPUT = (
    APP_ROOT / "public" / "archive" / "reference" / "paracosm-hover.mp4"
)


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate:format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def valid_proxy(path: Path, source_duration: float) -> bool:
    if not path.exists() or path.stat().st_size < 1_000_000:
        return False
    try:
        metadata = probe(path)
        stream = metadata["streams"][0]
        duration = float(metadata["format"]["duration"])
        return (
            stream.get("codec_name") == "h264"
            and int(stream.get("width") or 0) == 640
            and abs(duration - source_duration) < 0.25
        )
    except (KeyError, ValueError, subprocess.CalledProcessError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        parser.error(f"reference film not found: {source}")

    source_metadata = probe(source)
    source_duration = float(source_metadata["format"]["duration"])
    if (
        not args.force
        and output.stat().st_mtime >= source.stat().st_mtime
        if output.exists()
        else False
    ) and valid_proxy(output, source_duration):
        print(f"Hover proxy is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.building.mp4")
    temporary.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "scale=640:-2:flags=lanczos",
        "-c:v",
        "h264_videotoolbox",
        "-profile:v",
        "high",
        "-b:v",
        "1100k",
        "-maxrate",
        "1600k",
        "-bufsize",
        "2200k",
        "-g",
        "6",
        "-force_key_frames",
        "expr:gte(t,n_forced*0.25)",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(temporary),
    ]

    print(
        "Building 640px hover proxy with quarter-second seek points "
        f"from {source.name}…",
        flush=True,
    )
    try:
        subprocess.run(command, check=True)
        if not valid_proxy(temporary, source_duration):
            raise RuntimeError("encoded proxy failed duration/codec validation")
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    metadata = probe(output)
    size_mb = int(metadata["format"]["size"]) / 1_000_000
    print(
        f"Created {output} · {source_duration:.3f}s · {size_mb:.1f} MB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Media command failed with exit code {error.returncode}", file=sys.stderr)
        raise
