"""Read-only mesh/topology inventory for an Abby Cinema 4D scene."""

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
        meshes = []
        for item in walk_objects(doc.GetFirstObject()):
            if not item.CheckType(c4d.Opolygon) or not hasattr(
                item, "GetPointCount"
            ):
                continue
            meshes.append(
                {
                    "name": item.GetName(),
                    "path": object_path(item),
                    "points": item.GetPointCount(),
                    "polygons": item.GetPolygonCount(),
                    "uvwTags": sum(
                        1 for tag in item.GetTags() if tag.CheckType(c4d.Tuvw)
                    ),
                    "weightTags": sum(
                        1 for tag in item.GetTags() if tag.CheckType(c4d.Tweights)
                    ),
                    "materials": [
                        tag.GetMaterial().GetName()
                        for tag in item.GetTags()
                        if tag.CheckType(c4d.Ttexture)
                        and tag.GetMaterial() is not None
                    ],
                }
            )
        print(
            "ABBY_C4D_MESH_INVENTORY="
            + json.dumps(
                {"project": str(project), "saved": False, "meshes": meshes},
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
