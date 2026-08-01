"""Export one C4D polygon mesh's base points, polygons and UV corners."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


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
    parser.add_argument("--object", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    output = args.output_json.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        matches = [
            item
            for item in walk(doc.GetFirstObject())
            if item.GetName() == args.object or object_path(item) == args.object
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one object, found {len(matches)}")
        item = matches[0]
        if not isinstance(item, c4d.PolygonObject):
            raise RuntimeError(f"{object_path(item)} is not a polygon object")

        polygons = [
            [int(poly.a), int(poly.b), int(poly.c), int(poly.d)]
            for poly in item.GetAllPolygons()
        ]
        uvw_tag = next(
            (tag for tag in item.GetTags() if tag.CheckType(c4d.Tuvw)), None
        )
        uvw = []
        if uvw_tag is not None:
            for index in range(item.GetPolygonCount()):
                corners = uvw_tag.GetSlow(index)
                uvw.append(
                    [
                        vector(corners[name])
                        for name in ("a", "b", "c", "d")
                    ]
                )
        payload = {
            "project": str(project),
            "object": item.GetName(),
            "path": object_path(item),
            "points": [vector(point) for point in item.GetAllPoints()],
            "polygons": polygons,
            "uvw": uvw,
            "matrix": matrix(item.GetMg()),
            "pointCount": item.GetPointCount(),
            "polygonCount": item.GetPolygonCount(),
            "uvwTag": uvw_tag.GetName() if uvw_tag else None,
        }
        output.write_text(json.dumps(payload, separators=(",", ":")))
        print(
            "C4D_MESH_GEOMETRY="
            + json.dumps(
                {
                    "output": str(output),
                    "path": payload["path"],
                    "points": payload["pointCount"],
                    "polygons": payload["polygonCount"],
                    "uvw": len(uvw),
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
