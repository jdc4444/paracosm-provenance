"""Export compact transforms for named Abby facial controls.

The document is loaded read-only.  This intentionally omits animation tracks
and hierarchy metadata so calibration comparisons stay small and auditable.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def vector(value: c4d.Vector) -> list[float]:
    return [float(value.x), float(value.y), float(value.z)]


def matrix(value: c4d.Matrix) -> dict[str, list[float]]:
    return {
        "off": vector(value.off),
        "v1": vector(value.v1),
        "v2": vector(value.v2),
        "v3": vector(value.v3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--control", action="append", required=True)
    parser.add_argument("--frame", type=int, default=0)
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
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(None, True, True, True, 0)
        objects = list(walk_objects(doc.GetFirstObject()))
        rows = []
        for name in args.control:
            matches = [
                item
                for item in objects
                if item.GetName() == name and "root.002/" in object_path(item)
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"Expected one root.002 control named {name}; "
                    f"found {[object_path(item) for item in matches]}"
                )
            item = matches[0]
            rows.append(
                {
                    "name": name,
                    "path": object_path(item),
                    "relativePosition": vector(item.GetRelPos()),
                    "relativeRotation": vector(item.GetRelRot()),
                    "relativeRotationDegrees": vector(
                        c4d.Vector(
                            c4d.utils.RadToDeg(item.GetRelRot().x),
                            c4d.utils.RadToDeg(item.GetRelRot().y),
                            c4d.utils.RadToDeg(item.GetRelRot().z),
                        )
                    ),
                    "relativeScale": vector(item.GetRelScale()),
                    "localMatrix": matrix(item.GetMl()),
                    "globalMatrix": matrix(item.GetMg()),
                }
            )
        print(
            "ABBY_CONTROL_TRANSFORMS="
            + json.dumps(
                {
                    "project": str(project),
                    "frame": args.frame,
                    "fps": int(doc.GetFps()),
                    "controls": rows,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
