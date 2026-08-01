"""Build a labeled contact sheet from explicit image paths."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--width", type=int, default=360)
    parser.add_argument("--height", type=int, default=203)
    parser.add_argument("--centering-y", type=float, default=0.5)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()

    label_height = 28
    margin = 8
    rows = (len(args.images) + args.columns - 1) // args.columns
    sheet = Image.new(
        "RGB",
        (
            args.columns * (args.width + margin) + margin,
            rows * (args.height + label_height + margin) + margin,
        ),
        "#111111",
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, path in enumerate(args.images):
        with Image.open(path) as source:
            panel = ImageOps.fit(
                source.convert("RGB"),
                (args.width, args.height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, args.centering_y),
            )
        column = index % args.columns
        row = index // args.columns
        x = margin + column * (args.width + margin)
        y = margin + row * (args.height + label_height + margin)
        sheet.paste(panel, (x, y))
        draw.text(
            (x + 4, y + args.height + 7),
            path.stem[:54],
            fill="#f4f4f4",
            font=font,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=92)


if __name__ == "__main__":
    main()
