"""Load a Cinema 4D project and save a version-converted copy.

The input is never modified. This is useful for testing whether a newer C4D
bridge can deserialize legacy plugin datatypes more completely.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

try:
    import redshift  # noqa: F401
except Exception:
    redshift = None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if input_path == output_path:
        raise RuntimeError("Input and output must be different paths")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_MERGESCENE
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(input_path), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {input_path}")
    try:
        saved = c4d.documents.SaveDocument(
            doc,
            str(output_path),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report = {
            "c4dVersion": c4d.GetC4DVersion(),
            "input": str(input_path),
            "output": str(output_path),
            "saved": bool(saved),
            "outputExists": output_path.exists(),
            "outputBytes": output_path.stat().st_size if output_path.exists() else 0,
        }
        print(
            "PARACOSM_RESAVE_COPY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
