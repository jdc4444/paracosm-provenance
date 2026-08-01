"""Convert one diagnostic linear RGB bitmap to an embedded sRGB PNG."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import c4d


def profile_info(profile) -> dict[str, object]:
    try:
        has_profile = bool(profile.HasProfile())
    except Exception:
        has_profile = False
    values = {}
    for key, label in (
        (c4d.COLORPROFILEINFO_DESCRIPTION, "description"),
        (c4d.COLORPROFILEINFO_NAME, "name"),
    ):
        try:
            values[label] = str(profile.GetInfo(key))
        except Exception:
            values[label] = ""
    return {"hasProfile": has_profile, **values}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    source = c4d.bitmaps.BaseBitmap()
    result, is_movie = source.InitWith(str(source_path))
    if result != c4d.IMAGERESULT_OK or is_movie:
        raise RuntimeError(
            f"Could not load still image {source_path}: {result}"
        )
    destination = c4d.bitmaps.BaseBitmap()
    init_result = destination.Init(source.GetBw(), source.GetBh(), 24)
    if init_result != c4d.IMAGERESULT_OK:
        raise RuntimeError(
            f"Could not initialize destination bitmap: {init_result}"
        )

    source_profile = c4d.bitmaps.ColorProfile.GetDefaultLinearRGB()
    destination_profile = c4d.bitmaps.ColorProfile.GetDefaultSRGB()
    width = source.GetBw()
    height = source.GetBh()

    def linear_byte_to_srgb(value: int) -> int:
        linear = max(0.0, min(1.0, value / 255.0))
        encoded = (
            linear * 12.92
            if linear <= 0.0031308
            else 1.055 * math.pow(linear, 1.0 / 2.4) - 0.055
        )
        return max(0, min(255, round(encoded * 255.0)))

    for y in range(source.GetBh()):
        for x in range(width):
            red, green, blue = source.GetPixel(x, y)
            destination.SetPixel(
                x,
                y,
                linear_byte_to_srgb(red),
                linear_byte_to_srgb(green),
                linear_byte_to_srgb(blue),
            )
    destination.SetColorProfile(destination_profile)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_result = destination.Save(
        str(output_path), c4d.FILTER_PNG, c4d.BaseContainer()
    )
    if save_result != c4d.IMAGERESULT_OK:
        raise RuntimeError(f"Bitmap save returned {save_result}")
    payload = {
        "input": str(source_path),
        "output": str(output_path),
        "width": width,
        "height": height,
        "inputEmbeddedProfile": profile_info(source.GetColorProfile()),
        "assumedSourceProfile": profile_info(source_profile),
        "outputProfile": profile_info(destination.GetColorProfile()),
        "conversionMethod": "IEC_61966_2_1_linear_to_srgb_transfer",
    }
    print(
        "PARACOSM_BITMAP_PROFILE_CONVERSION_JSON="
        + json.dumps(payload, separators=(",", ":")),
        flush=True,
    )
    os._exit(0)


if __name__ == "__main__":
    main()
