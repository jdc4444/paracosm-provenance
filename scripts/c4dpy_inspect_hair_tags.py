"""Inspect the exact Abby Hair tags and render visibility parameters."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


TERMS = (
    "visible",
    "visibility",
    "ray",
    "camera",
    "primary",
    "render",
    "matte",
    "shadow",
    "reflection",
    "refraction",
    "object",
)
HAIR_PATH = (
    "root.002/pelvis/spine_01/spine_02/spine_03/spine_04/spine_05/"
    "neck_01/neck_02/head/FACIAL_C_FacialRoot/Hair"
)


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def object_path(op):
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def value_payload(value):
    if isinstance(value, c4d.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main():
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
        hair = next(
            (
                item
                for item in walk(doc.GetFirstObject())
                if object_path(item) == HAIR_PATH
            ),
            None,
        )
        if hair is None:
            raise RuntimeError("Hair not found")
        ancestors = []
        ancestor = hair
        while ancestor:
            ancestors.insert(
                0,
                {
                    "name": ancestor.GetName(),
                    "editorMode": int(ancestor.GetEditorMode()),
                    "renderMode": int(ancestor.GetRenderMode()),
                },
            )
            ancestor = ancestor.GetUp()
        tags = []
        for tag in hair.GetTags():
            parameters = []
            for container, desc_id, _group in tag.GetDescription(
                c4d.DESCFLAGS_DESC_0
            ):
                name = str(container.GetString(c4d.DESC_NAME) or "")
                if not any(term in name.casefold() for term in TERMS):
                    continue
                try:
                    value = value_payload(
                        tag.GetParameter(desc_id, c4d.DESCFLAGS_GET_0)
                    )
                except Exception:
                    continue
                parameters.append(
                    {
                        "name": name,
                        "id": [
                            desc_id[index].id
                            for index in range(desc_id.GetDepth())
                        ],
                        "value": value,
                    }
                )
            tags.append(
                {
                    "name": tag.GetName(),
                    "type": int(tag.GetType()),
                    "material": (
                        tag[c4d.TEXTURETAG_MATERIAL].GetName()
                        if tag.CheckType(c4d.Ttexture)
                        and tag[c4d.TEXTURETAG_MATERIAL] is not None
                        else None
                    ),
                    "restriction": (
                        str(tag[c4d.TEXTURETAG_RESTRICTION] or "")
                        if tag.CheckType(c4d.Ttexture)
                        else None
                    ),
                    "projection": (
                        int(tag[c4d.TEXTURETAG_PROJECTION])
                        if tag.CheckType(c4d.Ttexture)
                        else None
                    ),
                    "parameters": parameters,
                }
            )
        print(
            "ABBY_HAIR_TAGS="
            + json.dumps(
                {
                    "source": str(project),
                    "editorMode": int(hair.GetEditorMode()),
                    "renderMode": int(hair.GetRenderMode()),
                    "ancestors": ancestors,
                    "tags": tags,
                }
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
