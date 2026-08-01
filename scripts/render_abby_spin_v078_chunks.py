"""Render and package the accepted Abby Spin v078 animation in safe chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_stream(command: list[str]) -> int:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return process.wait()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--c4dpy", type=Path, required=True)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--motion-fbx", type=Path, required=True)
    parser.add_argument("--rest-fbx", type=Path, required=True)
    parser.add_argument("--target-rest-source", type=Path, required=True)
    parser.add_argument("--scene-source", type=Path, required=True)
    parser.add_argument("--face-cache-bin", type=Path, required=True)
    parser.add_argument("--lashes-cache-bin", type=Path, required=True)
    parser.add_argument("--facial-curves-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--analysis-dir", type=Path, required=True)
    parser.add_argument("--final-mp4", type=Path, required=True)
    parser.add_argument("--manifest-json", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--width", type=int, default=540)
    parser.add_argument("--height", type=int, default=960)
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    paths = {
        name: value.expanduser().resolve()
        for name, value in {
            "c4dpy": args.c4dpy,
            "driver": args.driver,
            "motion": args.motion_fbx,
            "rest": args.rest_fbx,
            "targetRest": args.target_rest_source,
            "scene": args.scene_source,
            "faceCache": args.face_cache_bin,
            "lashesCache": args.lashes_cache_bin,
            "facialCurves": args.facial_curves_json,
            "outputDir": args.output_dir,
            "analysisDir": args.analysis_dir,
            "finalMp4": args.final_mp4,
            "manifest": args.manifest_json,
        }.items()
    }
    for name in (
        "c4dpy",
        "driver",
        "motion",
        "rest",
        "targetRest",
        "scene",
        "faceCache",
        "lashesCache",
        "facialCurves",
    ):
        if not paths[name].is_file():
            raise RuntimeError(f"Missing {name}: {paths[name]}")
    if paths["finalMp4"].exists() or paths["manifest"].exists():
        raise RuntimeError("Refusing to overwrite final v078 outputs")
    paths["outputDir"].mkdir(parents=True, exist_ok=True)
    paths["analysisDir"].mkdir(parents=True, exist_ok=True)

    all_frames = list(range(args.start, args.end + 1))

    def output_path(frame: int) -> Path:
        return paths["outputDir"] / f"Abby_Spin_v6_motion_f{frame:04d}.png"

    reports: list[str] = []
    started = time.time()
    chunks = [
        all_frames[index : index + args.chunk_size]
        for index in range(0, len(all_frames), args.chunk_size)
    ]
    for chunk_index, chunk in enumerate(chunks):
        missing = [frame for frame in chunk if not output_path(frame).is_file()]
        if not missing:
            print(
                f"ABBY_SPIN_V078_CHUNK_SKIP={chunk_index + 1}/{len(chunks)}",
                flush=True,
            )
            continue
        report = paths["analysisDir"] / (
            "Abby_Spin_C4D_RedshiftV6_FullAnimation_v078_"
            f"chunk_{missing[0]:04d}_{missing[-1]:04d}.json"
        )
        if report.exists():
            report = report.with_name(report.stem + "_retry1.json")
        command = [
            str(paths["c4dpy"]),
            str(paths["driver"]),
            "--motion-fbx",
            str(paths["motion"]),
            "--rest-fbx",
            str(paths["rest"]),
            "--target-rest-source",
            str(paths["targetRest"]),
            "--scene-source",
            str(paths["scene"]),
            "--face-cache-bin",
            str(paths["faceCache"]),
            "--lashes-cache-bin",
            str(paths["lashesCache"]),
            "--facial-curves-json",
            str(paths["facialCurves"]),
            "--output-dir",
            str(paths["outputDir"]),
            "--report-json",
            str(report),
            "--frames",
            *[str(frame) for frame in missing],
            "--width",
            str(args.width),
            "--height",
            str(args.height),
            "--fps",
            str(args.fps),
            "--finger-mode",
            "hand-local-swing",
        ]
        print(
            "ABBY_SPIN_V078_CHUNK_START="
            + json.dumps(
                {
                    "index": chunk_index + 1,
                    "count": len(chunks),
                    "frames": [missing[0], missing[-1]],
                }
            ),
            flush=True,
        )
        result = run_stream(command)
        remaining = [frame for frame in missing if not output_path(frame).is_file()]
        if result != 0 or remaining or not report.is_file():
            print(
                "ABBY_SPIN_V078_CHUNK_RETRY="
                + json.dumps(
                    {
                        "result": result,
                        "remaining": remaining,
                        "report": str(report),
                    }
                ),
                flush=True,
            )
            for frame in remaining:
                retry_report = paths["analysisDir"] / (
                    "Abby_Spin_C4D_RedshiftV6_FullAnimation_v078_"
                    f"frame_{frame:04d}_retry1.json"
                )
                retry_command = command[:]
                frames_index = retry_command.index("--frames")
                width_index = retry_command.index("--width")
                retry_command[frames_index + 1 : width_index] = [str(frame)]
                report_index = retry_command.index("--report-json")
                retry_command[report_index + 1] = str(retry_report)
                retry_result = run_stream(retry_command)
                if retry_result != 0 or not output_path(frame).is_file():
                    raise RuntimeError(
                        f"Frame {frame} failed its single safe retry"
                    )
                reports.append(str(retry_report))
        if report.is_file():
            reports.append(str(report))
        completed = sum(output_path(frame).is_file() for frame in all_frames)
        print(
            "ABBY_SPIN_V078_PROGRESS="
            + json.dumps(
                {
                    "completed": completed,
                    "total": len(all_frames),
                    "elapsedSeconds": round(time.time() - started, 1),
                }
            ),
            flush=True,
        )

    missing_final = [frame for frame in all_frames if not output_path(frame).is_file()]
    if missing_final:
        raise RuntimeError(f"Missing final frames: {missing_final}")

    ffmpeg = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-framerate",
        str(args.fps),
        "-start_number",
        str(args.start),
        "-i",
        str(paths["outputDir"] / "Abby_Spin_v6_motion_f%04d.png"),
        "-frames:v",
        str(len(all_frames)),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(paths["finalMp4"]),
    ]
    if run_stream(ffmpeg) != 0 or not paths["finalMp4"].is_file():
        raise RuntimeError("ffmpeg could not create the final v078 MP4")

    source_paths = {
        key: paths[key]
        for key in (
            "driver",
            "motion",
            "rest",
            "targetRest",
            "scene",
            "faceCache",
            "lashesCache",
            "facialCurves",
        )
    }
    manifest = {
        "version": "v078",
        "status": "complete",
        "runtime": str(paths["c4dpy"]),
        "frames": [args.start, args.end],
        "frameCount": len(all_frames),
        "fps": args.fps,
        "resolution": [args.width, args.height],
        "policies": {
            "body": "direct authored Blender matrix retarget to Abby C4D body rig",
            "fingers": "hand-local source swing at Abby segment lengths with incompatible roll discarded",
            "face": "UV-transferred authored Blender shape cache",
            "eyes": "authored eye direction curves on native C4D eye controls",
            "mouthInterior": "authored jawOpen lowers native lower teeth and tongue",
            "hair": "exact accepted C4D hair rigidly follows head, matching rigid source behavior",
            "look": "accepted C4D Redshift v6 camera, lighting, materials, wardrobe and shoes",
        },
        "sourcesUntouched": True,
        "sources": {
            key: {"path": str(path), "sha256": sha256(path)}
            for key, path in source_paths.items()
        },
        "chunkReports": reports,
        "frameDirectory": str(paths["outputDir"]),
        "finalMp4": {
            "path": str(paths["finalMp4"]),
            "sha256": sha256(paths["finalMp4"]),
            "bytes": paths["finalMp4"].stat().st_size,
        },
        "elapsedSeconds": round(time.time() - started, 1),
    }
    paths["manifest"].write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        "ABBY_SPIN_V078_COMPLETE="
        + json.dumps(
            {
                "frames": len(all_frames),
                "mp4": str(paths["finalMp4"]),
                "manifest": str(paths["manifest"]),
                "elapsedSeconds": manifest["elapsedSeconds"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
