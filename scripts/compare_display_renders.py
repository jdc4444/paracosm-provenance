#!/usr/bin/env python3
"""Compare two display-referred renders and optionally write a contact sheet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def load_rgb(path: Path) -> tuple[np.ndarray, Image.Image]:
    image = Image.open(path).convert("RGB")
    pixels = np.asarray(image, dtype=np.float32) / 255.0
    return pixels, image


def metrics(candidate: np.ndarray, reference: np.ndarray) -> dict[str, object]:
    delta = candidate - reference
    correlations: list[float | None] = []
    for channel in range(3):
        left = candidate[..., channel].reshape(-1)
        right = reference[..., channel].reshape(-1)
        if np.std(left) == 0 or np.std(right) == 0:
            correlations.append(None)
        else:
            correlations.append(float(np.corrcoef(left, right)[0, 1]))
    return {
        "candidateMeanRgb": np.mean(candidate, axis=(0, 1)).tolist(),
        "referenceMeanRgb": np.mean(reference, axis=(0, 1)).tolist(),
        "meanAbsoluteError": float(np.mean(np.abs(delta))),
        "rootMeanSquareError": float(np.sqrt(np.mean(np.square(delta)))),
        "perChannelCorrelation": correlations,
    }


def save_contact(
    path: Path,
    candidate: Image.Image,
    reference: Image.Image,
    scale: int,
) -> None:
    width, height = candidate.size
    label_height = 28
    sheet = Image.new(
        "RGB",
        (width * scale * 2, height * scale + label_height),
        "black",
    )
    resized_reference = reference.resize(
        (width * scale, height * scale),
        Image.Resampling.NEAREST,
    )
    resized_candidate = candidate.resize(
        (width * scale, height * scale),
        Image.Resampling.NEAREST,
    )
    sheet.paste(resized_reference, (0, label_height))
    sheet.paste(resized_candidate, (width * scale, label_height))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 7), "CANONICAL", fill="white")
    draw.text((width * scale + 8, 7), "CANDIDATE", fill="white")
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--result-json", type=Path)
    parser.add_argument("--contact-sheet", type=Path)
    parser.add_argument("--contact-scale", type=int, default=4)
    args = parser.parse_args()

    candidate_path = args.candidate.expanduser().resolve()
    reference_path = args.reference.expanduser().resolve()
    candidate_pixels, candidate_image = load_rgb(candidate_path)
    reference_pixels, reference_image = load_rgb(reference_path)
    if reference_image.size != candidate_image.size:
        reference_image = reference_image.resize(
            candidate_image.size,
            Image.Resampling.LANCZOS,
        )
        reference_pixels = (
            np.asarray(reference_image, dtype=np.float32) / 255.0
        )

    result = {
        "candidate": str(candidate_path),
        "reference": str(reference_path),
        "width": candidate_image.width,
        "height": candidate_image.height,
        "comparison": metrics(candidate_pixels, reference_pixels),
    }
    if args.contact_sheet is not None:
        if args.contact_scale < 1:
            raise ValueError("--contact-scale must be at least 1")
        contact_path = args.contact_sheet.expanduser().resolve()
        save_contact(
            contact_path,
            candidate_image,
            reference_image,
            args.contact_scale,
        )
        result["contactSheet"] = str(contact_path)
    if args.result_json is not None:
        result_path = args.result_json.expanduser().resolve()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
