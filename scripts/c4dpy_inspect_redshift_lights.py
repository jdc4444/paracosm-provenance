"""Inspect Redshift light transforms and presentation controls read-only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take


REDSHIFT_LIGHT_OBJECT_ID = 1036751
TERMS = (
    "intensity",
    "exposure",
    "color",
    "temperature",
    "shape",
    "area",
    "spread",
    "shadow",
    "contribution",
    "diffuse",
    "reflection",
    "specular",
)


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def vector(value):
    return [value.x, value.y, value.z]


def object_path(op) -> str:
    names = []
    while op:
        names.append(op.GetName())
        op = op.GetUp()
    return "/".join(reversed(names))


def safe_value(value):
    if isinstance(value, c4d.Vector):
        return vector(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--take")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--result-json", type=Path)
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
        take = None
        if args.take:
            take_data = doc.GetTakeData()
            take = find_take(take_data, args.take)
            if take is None:
                raise RuntimeError(f"Take not found: {args.take}")
            take_data.SetCurrentTake(take)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        lights = []
        for item in walk(doc.GetFirstObject()):
            if item.GetType() != REDSHIFT_LIGHT_OBJECT_ID:
                continue
            parameters = []
            for container, desc_id, _group in item.GetDescription(
                c4d.DESCFLAGS_DESC_0
            ):
                name = str(container.GetString(c4d.DESC_NAME) or "")
                if not any(term in name.casefold() for term in TERMS):
                    continue
                try:
                    value = item.GetParameter(
                        desc_id, c4d.DESCFLAGS_GET_0
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
                        "value": safe_value(value),
                    }
                )
            matrix = item.GetMg()
            lights.append(
                {
                    "name": item.GetName(),
                    "path": object_path(item),
                    "editorMode": int(item.GetEditorMode()),
                    "renderMode": int(item.GetRenderMode()),
                    "position": vector(matrix.off),
                    "v1": vector(matrix.v1),
                    "v2": vector(matrix.v2),
                    "v3": vector(matrix.v3),
                    "parameters": parameters,
                }
            )
        result = {
            "project": str(project),
            "take": take.GetName() if take else None,
            "frame": args.frame,
            "lights": lights,
        }
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
        print(
            "ABBY_REDSHIFT_LIGHTS="
            + json.dumps(result, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
