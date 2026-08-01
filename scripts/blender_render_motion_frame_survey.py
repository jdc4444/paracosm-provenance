"""Render a non-destructive camera-frame survey from an animated Blender file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument("--width", type=int, default=360)
    parser.add_argument("--height", type=int, default=640)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)

    scene = bpy.context.scene
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.studio_light = "rim.sl"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.background_type = "VIEWPORT"
    scene.display.shading.background_color = (0.18, 0.18, 0.18)
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    outputs = []
    for frame in args.frames:
        scene.frame_set(frame)
        output = output_dir / f"spin_motion_frame_{frame:04d}.png"
        scene.render.filepath = str(output)
        bpy.ops.render.render(write_still=True)
        outputs.append(str(output))
        print(
            "CODEX_MOTION_SURVEY_FRAME="
            + json.dumps({"frame": frame, "output": str(output)}),
            flush=True,
        )

    print(
        "CODEX_MOTION_SURVEY="
        + json.dumps(
            {
                "source": bpy.data.filepath,
                "camera": scene.camera.name if scene.camera else None,
                "frames": args.frames,
                "outputs": outputs,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
