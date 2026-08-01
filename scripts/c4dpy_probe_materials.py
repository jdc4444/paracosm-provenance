"""Report conventional channels and node spaces for named C4D materials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def value_payload(value):
    if isinstance(value, c4d.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--name", action="append", required=True)
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
        wanted = {name.casefold() for name in args.name}
        payload = []
        material = doc.GetFirstMaterial()
        while material:
            if material.GetName().casefold() in wanted:
                channels = {}
                for constant in (
                    "MATERIAL_USE_COLOR",
                    "MATERIAL_COLOR_COLOR",
                    "MATERIAL_COLOR_BRIGHTNESS",
                    "MATERIAL_USE_ALPHA",
                    "MATERIAL_ALPHA_COLOR",
                    "MATERIAL_ALPHA_BRIGHTNESS",
                    "MATERIAL_USE_TRANSPARENCY",
                    "MATERIAL_TRANSPARENCY_COLOR",
                    "MATERIAL_TRANSPARENCY_BRIGHTNESS",
                    "MATERIAL_USE_REFLECTION",
                    "MATERIAL_USE_SPECULAR",
                    "MATERIAL_SPECULAR_COLOR",
                    "MATERIAL_SPECULAR_BRIGHTNESS",
                ):
                    parameter_id = getattr(c4d, constant, None)
                    if parameter_id is None:
                        continue
                    try:
                        channels[constant] = value_payload(material[parameter_id])
                    except Exception:
                        continue
                node_spaces = []
                reference = material.GetNodeMaterialReference()
                if reference is not None:
                    try:
                        node_spaces = [
                            str(space)
                            for space in reference.GetMaterialNodeSpaces()
                        ]
                    except Exception:
                        node_spaces = []
                payload.append(
                    {
                        "name": material.GetName(),
                        "type": int(material.GetType()),
                        "channels": channels,
                        "nodeSpaces": node_spaces,
                    }
                )
            material = material.GetNext()
        print(
            "C4D_MATERIAL_PROBE="
            + json.dumps({"source": str(project), "materials": payload}),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
