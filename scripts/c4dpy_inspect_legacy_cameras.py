"""Inspect legacy Redshift camera transforms and lens parameters read-only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


LEGACY_RS_CAMERA_OBJECT_ID = 1057516
TERMS = (
    "focal",
    "focus",
    "lens",
    "sensor",
    "aperture",
    "bokeh",
    "depth",
    "blur",
    "radius",
    "blade",
    "derive",
    "projection",
    "film",
    "angle",
    "shift",
    "offset",
    "crop",
    "aspect",
    "exposure",
)


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    result = []
    while op:
        result.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(result)


def vector(value) -> dict[str, float]:
    return {"x": value.x, "y": value.y, "z": value.z}


def parameter_payload(op) -> list[dict[str, object]]:
    result = []
    description = op.GetDescription(
        getattr(c4d, "DESCFLAGS_DESC_0", 0)
    )
    for container, desc_id, _group_id in description:
        name = str(container.GetString(c4d.DESC_NAME) or "")
        if not any(term in name.casefold() for term in TERMS):
            continue
        try:
            value = op[desc_id]
            if isinstance(value, c4d.Vector):
                value = vector(value)
            elif not isinstance(value, (str, int, float, bool, type(None))):
                value = str(value)
        except Exception as error:
            value = f"{type(error).__name__}: {error}"
        result.append(
            {
                "name": name,
                "id": [
                    desc_id[index].id
                    for index in range(desc_id.GetDepth())
                ],
                "value": value,
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional path for the complete structured camera inventory.",
    )
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        cameras = []
        for op in walk(doc.GetFirstObject()):
            if op.GetType() != LEGACY_RS_CAMERA_OBJECT_ID:
                continue
            matrix = op.GetMg()
            cameras.append(
                {
                    "name": op.GetName(),
                    "path": object_path(op),
                    "position": vector(matrix.off),
                    "matrix": {
                        "v1": vector(matrix.v1),
                        "v2": vector(matrix.v2),
                        "v3": vector(matrix.v3),
                    },
                    "parameters": parameter_payload(op),
                }
            )
        result = {
            "project": str(project),
            "frame": args.frame,
            "fps": doc.GetFps(),
            "cameras": cameras,
        }
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(result, indent=2),
                encoding="utf-8",
            )
        print(
            "PARACOSM_LEGACY_CAMERAS_JSON="
            + json.dumps(result, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_LEGACY_CAMERAS_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
