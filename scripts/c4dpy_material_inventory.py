"""Read-only inventory of C4D materials and their object assignments."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def walk_shaders(shader):
    while shader:
        yield shader
        if shader.GetDown():
            yield from walk_shaders(shader.GetDown())
        shader = shader.GetNext()


def shader_record(shader) -> dict[str, object]:
    record: dict[str, object] = {
        "name": shader.GetName(),
        "typeId": shader.GetType(),
    }
    if shader.CheckType(c4d.Xbitmap):
        record["filename"] = str(
            shader[c4d.BITMAPSHADER_FILENAME] or ""
        )
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--term", action="append", default=[])
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    terms = tuple(item.casefold() for item in args.term if item)
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        material_records = []
        material = doc.GetFirstMaterial()
        while material:
            name = material.GetName()
            if not terms or any(term in name.casefold() for term in terms):
                node_reference = material.GetNodeMaterialReference()
                spaces = []
                if node_reference:
                    try:
                        spaces = [
                            str(item)
                            for item in node_reference.GetMaterialNodeSpaces()
                        ]
                    except Exception:
                        spaces = []
                material_records.append(
                    {
                        "name": name,
                        "typeId": material.GetType(),
                        "nodeSpaces": spaces,
                        "classicShaders": [
                            shader_record(shader)
                            for shader in walk_shaders(
                                material.GetFirstShader()
                            )
                        ],
                    }
                )
            material = material.GetNext()
        assignments = []
        for op in walk_objects(doc.GetFirstObject()):
            op_path = object_path(op)
            tag = op.GetFirstTag()
            while tag:
                if tag.CheckType(c4d.Ttexture):
                    material = tag.GetMaterial()
                    material_name = material.GetName() if material else None
                    if not terms or any(
                        term
                        in f"{op_path} {material_name or ''}".casefold()
                        for term in terms
                    ):
                        assignments.append(
                            {
                                "object": op.GetName(),
                                "objectPath": op_path,
                                "material": material_name,
                                "restriction": str(
                                    tag[c4d.TEXTURETAG_RESTRICTION] or ""
                                ),
                            }
                        )
                tag = tag.GetNext()
        payload = {
            "project": str(project),
            "materials": material_records,
            "assignments": assignments,
        }
        if args.result_json:
            output = args.result_json.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            "PARACOSM_MATERIAL_INVENTORY_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_MATERIAL_INVENTORY_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
