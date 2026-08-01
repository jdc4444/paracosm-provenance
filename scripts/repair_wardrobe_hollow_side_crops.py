#!/usr/bin/env python3
"""Remove neighboring-sheet fragments from affected hollow side views."""

from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIRECTORY = (
    REPOSITORY_ROOT / "public/archive/objects/wardrobe/3d-inputs"
)
CONTAMINATED_OBJECT_IDS = [
    "black-deconstructed-coat-dress",
    "black-tiered-tulle-skirt",
    "blue-polka-dot-blouse",
    "blue-striped-fuzzy-sweater",
    "bronze-abstract-gown",
    "burgundy-cape-keyhole-top",
    "ivory-pleated-skirt",
    "multicolor-mesh-top",
    "multicolor-ribbed-top",
    "navy-bubble-skirt",
    "navy-pinstripe-ruffle-dress",
    "orange-sheer-shoulder-cape",
    "pink-striped-shag-sweater",
    "purple-plaid-tights",
    "red-shaggy-coat",
    "red-tiered-maxi-skirt",
    "silver-puff-sleeve-dress",
    "striped-long-sleeve-bodysuit",
    "striped-short-sleeve-top",
    "tartan-coat-dress",
    "teal-pleated-skirt",
    "white-lilac-corset-dress",
]


def foreground_bounds(image: Image.Image) -> tuple[int, int, int, int]:
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    corner_samples = np.concatenate(
        (
            pixels[:20, :20].reshape(-1, 3),
            pixels[:20, -20:].reshape(-1, 3),
            pixels[-20:, :20].reshape(-1, 3),
            pixels[-20:, -20:].reshape(-1, 3),
        ),
        axis=0,
    )
    background = np.median(corner_samples, axis=0)
    distance = np.sqrt(np.square(pixels - background).sum(axis=2))
    labels, count = ndimage.label(distance > 22)
    components = ndimage.find_objects(labels)
    largest = None
    largest_area = 0
    for component_id, slices in enumerate(components, start=1):
        if slices is None:
            continue
        area = int(np.count_nonzero(labels[slices] == component_id))
        if area > largest_area:
            largest_area = area
            largest = slices
    if largest is None:
        raise RuntimeError("No garment foreground found.")
    y_slice, x_slice = largest
    width = x_slice.stop - x_slice.start
    height = y_slice.stop - y_slice.start
    horizontal_margin = max(12, round(width * 0.05))
    vertical_margin = max(12, round(height * 0.04))
    return (
        max(0, x_slice.start - horizontal_margin),
        max(0, y_slice.start - vertical_margin),
        min(image.width, x_slice.stop + horizontal_margin),
        min(image.height, y_slice.stop + vertical_margin),
    )


def reframe(source_path: Path, output_path: Path) -> None:
    with Image.open(source_path) as source:
        source = source.convert("RGB")
        crop = source.crop(foreground_bounds(source))
        crop.thumbnail((900, 900), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (1024, 1024), "white")
        canvas.paste(
            crop,
            ((canvas.width - crop.width) // 2, (canvas.height - crop.height) // 2),
        )
        canvas.save(output_path, optimize=True)


for object_id in CONTAMINATED_OBJECT_IDS:
    source_path = INPUT_DIRECTORY / f"{object_id}-side.png"
    output_path = INPUT_DIRECTORY / f"{object_id}-side-clean.png"
    reframe(source_path, output_path)

print(f"Reframed {len(CONTAMINATED_OBJECT_IDS)} hollow side views.")
