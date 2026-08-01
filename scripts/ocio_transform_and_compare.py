#!/usr/bin/env python3
"""Apply a named OCIO display/view transform and compare with a reference.

This script intentionally requires OpenColorIO rather than approximating an
ACEScg image with an sRGB transfer curve.  It is used for diagnostic and proof
images emitted by Cinema 4D's RenderDocument API, whose bitmap is in the
document render space rather than the display/output space.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import PyOpenColorIO as ocio
from PIL import Image, ImageCms


def load_rgb(path: Path) -> np.ndarray:
    if path.suffix.casefold() == ".pfm":
        with path.open("rb") as stream:
            if stream.readline().strip() != b"PF":
                raise RuntimeError(f"Expected RGB PFM data in {path}")
            dimensions = stream.readline().split()
            while dimensions and dimensions[0].startswith(b"#"):
                dimensions = stream.readline().split()
            if len(dimensions) != 2:
                raise RuntimeError(f"Invalid PFM dimensions in {path}")
            width, height = (int(value) for value in dimensions)
            scale = float(stream.readline())
            dtype = np.dtype("<f4" if scale < 0 else ">f4")
            pixels = np.frombuffer(stream.read(), dtype=dtype)
        expected = width * height * 3
        if pixels.size != expected:
            raise RuntimeError(
                f"Expected {expected} PFM values in {path}; "
                f"received {pixels.size}"
            )
        return np.ascontiguousarray(
            np.flipud(pixels.reshape(height, width, 3)),
            dtype=np.float32,
        )
    if path.suffix.casefold() == ".exr":
        try:
            import OpenImageIO as oiio
        except ImportError as error:
            raise RuntimeError(
                "OpenImageIO is required to read EXR input"
            ) from error
        image_input = oiio.ImageInput.open(str(path))
        if image_input is None:
            raise RuntimeError(f"OpenImageIO could not open {path}")
        try:
            pixels = image_input.read_image(oiio.FLOAT)
        finally:
            image_input.close()
        if pixels is None:
            raise RuntimeError(f"OpenImageIO could not read {path}")
        pixels = np.asarray(pixels, dtype=np.float32)
        if pixels.ndim != 3 or pixels.shape[2] < 3:
            raise RuntimeError(
                f"Expected at least three channels in {path}; "
                f"received shape {pixels.shape}"
            )
        pixels = pixels[..., :3]
        return np.ascontiguousarray(pixels)
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0


def save_srgb_png(path: Path, pixels: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = np.clip(np.rint(np.clip(pixels, 0.0, 1.0) * 255.0), 0, 255)
    image = Image.fromarray(encoded.astype(np.uint8), mode="RGB")
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    image.save(path, format="PNG", icc_profile=profile.tobytes())


def resize_reference(reference: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(
        np.clip(np.rint(reference * 255.0), 0, 255).astype(np.uint8),
        mode="RGB",
    )
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    return np.asarray(resized, dtype=np.float32) / 255.0


def compare(candidate: np.ndarray, reference: np.ndarray) -> dict[str, object]:
    delta = candidate - reference
    correlations = []
    for channel in range(3):
        left = candidate[..., channel].reshape(-1)
        right = reference[..., channel].reshape(-1)
        correlations.append(float(np.corrcoef(left, right)[0, 1]))
    return {
        "meanAbsoluteError": float(np.mean(np.abs(delta))),
        "rootMeanSquareError": float(np.sqrt(np.mean(np.square(delta)))),
        "perChannelCorrelation": correlations,
        "candidateMeanRgb": np.mean(candidate, axis=(0, 1)).tolist(),
        "referenceMeanRgb": np.mean(reference, axis=(0, 1)).tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-space", default="ACEScg")
    parser.add_argument("--display", default="sRGB")
    parser.add_argument("--view", required=True)
    parser.add_argument(
        "--exposure-ev",
        type=float,
        default=0.0,
        help=(
            "Optional linear exposure offset applied before the OCIO "
            "display/view transform. The default is zero."
        ),
    )
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()

    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    config_path = args.config.expanduser().resolve()
    source = load_rgb(input_path)

    config = ocio.Config.CreateFromFile(str(config_path))
    transform = ocio.DisplayViewTransform()
    transform.setSrc(args.source_space)
    transform.setDisplay(args.display)
    transform.setView(args.view)
    processor = config.getProcessor(transform).getDefaultCPUProcessor()
    transformed = np.ascontiguousarray(
        source * (2.0 ** args.exposure_ev),
        dtype=np.float32,
    )
    descriptor = ocio.PackedImageDesc(
        transformed,
        transformed.shape[1],
        transformed.shape[0],
        transformed.shape[2],
    )
    processor.apply(descriptor)
    save_srgb_png(output_path, transformed)

    payload: dict[str, object] = {
        "input": str(input_path),
        "output": str(output_path),
        "config": str(config_path),
        "sourceSpace": args.source_space,
        "display": args.display,
        "view": args.view,
        "exposureEv": args.exposure_ev,
        "width": int(transformed.shape[1]),
        "height": int(transformed.shape[0]),
        "inputPrecision": (
            "32-bit float render buffer"
            if input_path.suffix.casefold() in {".exr", ".pfm"}
            else "8-bit display file"
        ),
    }
    if args.reference is not None:
        reference_path = args.reference.expanduser().resolve()
        reference = load_rgb(reference_path)
        reference = resize_reference(
            reference,
            transformed.shape[1],
            transformed.shape[0],
        )
        payload["reference"] = str(reference_path)
        payload["comparison"] = compare(transformed, reference)

    if args.result_json is not None:
        result_path = args.result_json.expanduser().resolve()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
