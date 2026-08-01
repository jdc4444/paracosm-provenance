"""Inspect one Cinema 4D object's tags and selected parameters read-only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


TERMS = (
    "shadow",
    "visibility",
    "visible",
    "camera",
    "reflection",
    "refraction",
    "primary",
    "secondary",
    "ray",
    "matte",
    "cast",
    "receive",
)


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def safe_value(value):
    if isinstance(value, c4d.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object", required=True)
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
        target = next(
            (
                item
                for item in walk(doc.GetFirstObject())
                if item.GetName() == args.object
                or object_path(item) == args.object
            ),
            None,
        )
        if target is None:
            raise RuntimeError(f"Object not found: {args.object}")
        tags = []
        tag = target.GetFirstTag()
        while tag:
            parameters = []
            for container, desc_id, _group in tag.GetDescription(
                c4d.DESCFLAGS_DESC_0
            ):
                name = str(container.GetString(c4d.DESC_NAME) or "")
                if not any(term in name.casefold() for term in TERMS):
                    continue
                try:
                    value = tag.GetParameter(desc_id, c4d.DESCFLAGS_GET_0)
                except Exception:
                    continue
                parameters.append(
                    {
                        "name": name,
                        "id": [
                            desc_id[index].id
                            for index in range(desc_id.GetDepth())
                        ],
                        "value": safe_value(value),
                    }
                )
            tags.append(
                {
                    "name": tag.GetName(),
                    "typeId": tag.GetType(),
                    "parameters": parameters,
                }
            )
            tag = tag.GetNext()
        print(
            "PARACOSM_OBJECT_TAGS_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "object": target.GetName(),
                    "objectPath": object_path(target),
                    "tags": tags,
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
