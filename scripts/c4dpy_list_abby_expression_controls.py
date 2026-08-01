"""List Abby facial controls that are useful for hand-authored expressions.

The source document is opened read-only and is never saved.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


TERMS = (
    "brow",
    "cheek",
    "eye",
    "eyelid",
    "forehead",
    "jaw",
    "lip",
    "mouth",
    "nose",
)


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


def take_tree(take, take_data) -> list[dict[str, object]]:
    result = []
    while take:
        effective = take.GetEffectiveCamera(take_data)
        camera = effective[0] if isinstance(effective, tuple) else effective
        result.append(
            {
                "name": take.GetName(),
                "camera": camera.GetName() if camera else None,
                "children": take_tree(take.GetDown(), take_data),
            }
        )
        take = take.GetNext()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--names-only", action="store_true")
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")

    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        controls = []
        hair_objects = []
        for item in walk_objects(doc.GetFirstObject()):
            name = item.GetName()
            path = object_path(item)
            if "hair" in name.casefold():
                hair_objects.append(
                    {
                        "name": name,
                        "path": path,
                        "editorMode": int(item.GetEditorMode()),
                        "renderMode": int(item.GetRenderMode()),
                        "type": int(item.GetType()),
                    }
                )
            if (
                name.startswith("FACIAL_")
                and "root.002/" in path
                and any(term in name.casefold() for term in TERMS)
            ):
                controls.append(
                    {
                        "name": name,
                        "path": path,
                        "position": vector(item.GetRelPos()),
                        "rotation": vector(item.GetRelRot()),
                    }
                )
        take_data = doc.GetTakeData()
        main_take = take_data.GetMainTake() if take_data else None
        payload = {
            "project": str(project),
            "count": len(controls),
            "controls": (
                [item["name"] for item in controls]
                if args.names_only
                else controls
            ),
            "hairObjects": hair_objects,
            "currentTake": (
                take_data.GetCurrentTake().GetName()
                if take_data and take_data.GetCurrentTake()
                else None
            ),
            "takes": (
                take_tree(main_take, take_data)
                if main_take and take_data
                else []
            ),
        }
        if args.output_json:
            output = args.output_json.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2))
        print(
            "ABBY_EXPRESSION_CONTROLS="
            + json.dumps(
                {
                    "project": str(project),
                    "count": len(controls),
                    "output": (
                        str(args.output_json.expanduser().resolve())
                        if args.output_json
                        else None
                    ),
                    "controls": payload["controls"] if args.names_only else None,
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
