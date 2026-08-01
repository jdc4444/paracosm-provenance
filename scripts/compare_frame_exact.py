"""Compare decoded image pixels and emit machine-readable exact-match evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def load(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Could not decode {path}")
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    args = parser.parse_args()
    reference_path = args.reference.expanduser().resolve()
    reference = load(reference_path)
    records = []
    for item in args.candidate:
        candidate_path = item.expanduser().resolve()
        candidate = load(candidate_path)
        same_shape = candidate.shape == reference.shape
        if same_shape:
            delta = np.abs(
                reference.astype(np.float64) - candidate.astype(np.float64)
            )
            exact = bool(np.array_equal(reference, candidate))
            mae = float(delta.mean())
            max_error = float(delta.max())
            if reference.size and np.std(reference) and np.std(candidate):
                correlation = float(
                    np.corrcoef(reference.reshape(-1), candidate.reshape(-1))[0, 1]
                )
            else:
                correlation = 1.0 if exact else 0.0
        else:
            exact = False
            mae = None
            max_error = None
            correlation = None
        records.append(
            {
                "candidate": str(candidate_path),
                "shape": list(candidate.shape),
                "dtype": str(candidate.dtype),
                "sameShape": same_shape,
                "exactPixelMatch": exact,
                "mae": mae,
                "maxChannelError": max_error,
                "correlation": correlation,
            }
        )
    print(
        json.dumps(
            {
                "reference": str(reference_path),
                "referenceShape": list(reference.shape),
                "referenceDtype": str(reference.dtype),
                "records": records,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
