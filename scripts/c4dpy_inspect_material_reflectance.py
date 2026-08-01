"""Inspect one classic C4D material's reflectance layers read-only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def safe(callable_value):
    try:
        value = callable_value()
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, c4d.Vector):
            return {"x": value.x, "y": value.y, "z": value.z}
        return str(value)
    except Exception as error:
        return f"<{type(error).__name__}: {error}>"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--material", required=True)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    document = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if document is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        material = next(
            (
                item
                for item in document.GetMaterials()
                if item.GetName() == args.material
            ),
            None,
        )
        if material is None:
            raise RuntimeError(f"Material not found: {args.material}")
        methods = sorted(
            name
            for name in dir(material)
            if "reflect" in name.casefold() or "layer" in name.casefold()
        )
        constants = {
            name: getattr(c4d, name)
            for name in dir(c4d)
            if name.startswith("REFLECTION_LAYER_")
            and isinstance(getattr(c4d, name), int)
        }
        layers = []
        count_method = getattr(material, "GetReflectionLayerCount", None)
        index_method = getattr(material, "GetReflectionLayerIndex", None)
        count = int(count_method()) if callable(count_method) else 0
        for index in range(count):
            layer = index_method(index) if callable(index_method) else None
            if layer is None:
                continue
            data_id_method = getattr(layer, "GetDataID", None)
            data_id = (
                int(data_id_method()) if callable(data_id_method) else None
            )
            values = {}
            if data_id is not None:
                for name, offset in constants.items():
                    if not any(
                        token in name
                        for token in (
                            "ROUGH",
                            "REFLECTION",
                            "SPECULAR",
                            "BUMP",
                            "FRESNEL",
                            "COLOR",
                            "DISTRIBUTION",
                        )
                    ):
                        continue
                    try:
                        value = material[data_id + offset]
                    except Exception:
                        continue
                    if value in (None, ""):
                        continue
                    values[name] = safe(lambda value=value: value)
            layers.append(
                {
                    "index": index,
                    "name": safe(layer.GetName),
                    "dataId": data_id,
                    "layerId": safe(
                        getattr(layer, "GetLayerID", lambda: None)
                    ),
                    "values": values,
                }
            )
        print(
            "PARACOSM_MATERIAL_REFLECTANCE_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "material": material.GetName(),
                    "typeId": material.GetType(),
                    "methods": methods,
                    "layers": layers,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(document)
        os._exit(0)


if __name__ == "__main__":
    main()
