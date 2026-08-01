"""Rank grey C4D camera proofs against a canonical color render silhouette."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import cv2
import numpy as np


def largest_cluster(mask: np.ndarray, dilation: int) -> tuple[np.ndarray, list[int]]:
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (dilation, dilation)
    )
    joined = cv2.dilate(mask, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(joined)
    if count <= 1:
        raise RuntimeError("No foreground cluster found")
    label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, width, height, _ = (int(value) for value in stats[label])
    component = np.zeros_like(mask)
    component[y : y + height, x : x + width] = mask[
        y : y + height, x : x + width
    ]
    return component, [x, y, width, height]


def canonical_mask(image: np.ndarray) -> tuple[np.ndarray, list[int]]:
    channels = image.astype(np.int16)
    chroma = channels.max(axis=2) - channels.min(axis=2)
    value = channels.max(axis=2)
    raw = np.where((chroma >= 10) & (value >= 15), 255, 0).astype(np.uint8)
    # The canonical frame contains sparse colored particles over black. A
    # density mask rejects those isolated points while retaining the compact
    # character silhouette, including its dark wardrobe bands.
    density = cv2.GaussianBlur(raw, (0, 0), max(5, image.shape[1] / 190))
    cluster, box = largest_cluster(
        np.where(density >= 10, 255, 0).astype(np.uint8), 3
    )
    x, y, width, height = box
    component = np.zeros_like(raw)
    component[y : y + height, x : x + width] = raw[
        y : y + height, x : x + width
    ]
    component = cv2.morphologyEx(
        component,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
    )
    return component, box


def proof_mask(image: np.ndarray) -> tuple[np.ndarray, list[int]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raw = np.where(gray >= 135, 255, 0).astype(np.uint8)
    density = cv2.GaussianBlur(raw, (0, 0), max(2, image.shape[1] / 240))
    _, box = largest_cluster(
        np.where(density >= 12, 255, 0).astype(np.uint8), 3
    )
    x, y, width, height = box
    component = np.zeros_like(raw)
    component[y : y + height, x : x + width] = raw[
        y : y + height, x : x + width
    ]
    component = cv2.morphologyEx(
        component,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    return component, box


def normalized(mask: np.ndarray, box: list[int], size: int = 256) -> np.ndarray:
    x, y, width, height = box
    crop = mask[y : y + height, x : x + width]
    scale = min((size - 16) / max(width, 1), (size - 16) / max(height, 1))
    resized = cv2.resize(
        crop,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_NEAREST,
    )
    canvas = np.zeros((size, size), dtype=np.uint8)
    y0 = (size - resized.shape[0]) // 2
    x0 = (size - resized.shape[1]) // 2
    canvas[y0 : y0 + resized.shape[0], x0 : x0 + resized.shape[1]] = resized
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--proof-glob", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    source = cv2.imread(str(args.source.expanduser().resolve()))
    if source is None:
        raise FileNotFoundError(args.source)
    source_mask, source_box = canonical_mask(source)
    source_normalized = normalized(source_mask, source_box)
    source_contours, _ = cv2.findContours(
        source_normalized, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    source_contour = max(source_contours, key=cv2.contourArea)

    results = []
    for proof_name in sorted(glob.glob(args.proof_glob)):
        proof_path = Path(proof_name).resolve()
        proof = cv2.imread(str(proof_path))
        if proof is None:
            continue
        try:
            mask, box = proof_mask(proof)
            proof_normalized = normalized(mask, box)
            contours, _ = cv2.findContours(
                proof_normalized, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            contour = max(contours, key=cv2.contourArea)
            shape_score = float(
                cv2.matchShapes(
                    source_contour, contour, cv2.CONTOURS_MATCH_I1, 0.0
                )
            )
            overlap = float(
                np.logical_and(
                    source_normalized > 0, proof_normalized > 0
                ).sum()
                / max(
                    1,
                    np.logical_or(
                        source_normalized > 0, proof_normalized > 0
                    ).sum(),
                )
            )
            source_aspect = source_box[2] / max(1, source_box[3])
            proof_aspect = box[2] / max(1, box[3])
            aspect_error = abs(np.log(max(proof_aspect, 1e-6) / source_aspect))
            score = shape_score + aspect_error + (1.0 - overlap)
            results.append(
                {
                    "path": str(proof_path),
                    "score": round(score, 6),
                    "shapeScore": round(shape_score, 6),
                    "aspectError": round(float(aspect_error), 6),
                    "normalizedOverlap": round(overlap, 6),
                    "box": box,
                }
            )
        except Exception as error:
            results.append(
                {"path": str(proof_path), "error": f"{type(error).__name__}: {error}"}
            )
    results.sort(key=lambda item: item.get("score", float("inf")))
    report = {
        "source": str(args.source.expanduser().resolve()),
        "sourceBox": source_box,
        "proofCount": len(results),
        "results": results,
    }
    payload = json.dumps(report, indent=2)
    print(payload)
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
