"""Inventory every classic Bitmap shader path in a C4D project read-only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk_shaders(shader):
    current = shader
    while current:
        yield current
        child = current.GetDown()
        if child:
            yield from walk_shaders(child)
        current = current.GetNext()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        records = []
        material = doc.GetFirstMaterial()
        material_index = 0
        while material:
            for shader in walk_shaders(material.GetFirstShader()):
                if shader.GetType() != c4d.Xbitmap:
                    continue
                filename = str(
                    shader[c4d.BITMAPSHADER_FILENAME] or ""
                )
                records.append(
                    {
                        "materialIndex": material_index,
                        "material": material.GetName(),
                        "shader": shader.GetName(),
                        "filename": filename,
                    }
                )
            material = material.GetNext()
            material_index += 1
        print(
            "PARACOSM_CLASSIC_BITMAP_INVENTORY_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "records": records,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
