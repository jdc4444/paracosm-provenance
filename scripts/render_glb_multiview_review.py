import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blender_source_faithful_repairs import import_glb, render_preview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    script_args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(script_args)

    input_path = args.input.resolve()
    output_directory = args.output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    objects = import_glb(input_path)

    views = {
        "front": (1.45, -3.8, 1.3),
        "rear": (-1.45, 3.8, 1.3),
        "left": (4.0, 0.0, 0.3),
        "right": (-4.0, 0.0, 0.3),
        "top": (0.0, 0.0, 4.0),
        "bottom": (0.0, 0.0, -4.0),
    }
    outputs = {}
    for view, direction in views.items():
        output_path = output_directory / f"{args.prefix}-{view}.png"
        render_preview(
            output_path,
            objects,
            view_direction=direction,
            orthographic_padding=1.18,
        )
        outputs[view] = str(output_path)

    print("MULTIVIEW_REVIEW=" + json.dumps(outputs))


if __name__ == "__main__":
    main()
