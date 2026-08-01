"""List Abby's lower-face controls without modifying the Cinema 4D source."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk_objects(item):
    while item:
        yield item
        child = item.GetDown()
        if child:
            yield from walk_objects(child)
        item = item.GetNext()


def object_path(item) -> str:
    names = []
    while item:
        names.insert(0, item.GetName())
        item = item.GetUp()
    return "/".join(names)


def vector_values(value: c4d.Vector) -> list[float]:
    return [value.x, value.y, value.z]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    document = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if document is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")
    try:
        matches = []
        for item in walk_objects(document.GetFirstObject()):
            path = object_path(item)
            name = item.GetName()
            if "root.002/" not in path:
                continue
            if not any(
                token in name.casefold()
                for token in ("chin", "jaw", "lip", "mouth")
            ):
                continue
            matches.append(
                {
                    "name": name,
                    "path": path,
                    "type": item.GetType(),
                    "position": vector_values(item.GetRelPos()),
                    "rotation": vector_values(item.GetRelRot()),
                }
            )
        print(
            "ABBY_LOWER_FACE_CONTROLS="
            + json.dumps(matches, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(document)
    os._exit(0)


if __name__ == "__main__":
    main()
