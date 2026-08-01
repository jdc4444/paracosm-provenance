"""List Redshift proxy objects and their private RSFILE paths.

Redshift exposes the file path as a nested custom-datatype channel even when
the top-level RSFILE value is not accessible from Python.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d
import redshift


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op: c4d.BaseObject) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def vector(value: c4d.Vector) -> dict[str, float]:
    return {"x": value.x, "y": value.y, "z": value.z}


def nested_parameter(
    op: c4d.BaseObject,
    sub_id: int,
    dtype: int,
):
    desc_id = c4d.DescID(
        c4d.DescLevel(
            getattr(c4d, "REDSHIFT_PROXY_FILE", 10000),
            redshift.CUSTOMDATATYPE_RSFILE,
            op.GetType(),
        ),
        c4d.DescLevel(sub_id, dtype, 0),
    )
    return op.GetParameter(desc_id, getattr(c4d, "DESCFLAGS_GET_0", 0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
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
        records = []
        for op in walk_objects(doc.GetFirstObject()):
            if op.GetType() != redshift.Orsproxy:
                continue
            record = {
                "name": op.GetName(),
                "objectPath": object_path(op),
                "typeId": op.GetType(),
                "editorMode": op.GetEditorMode(),
                "renderMode": op.GetRenderMode(),
                "position": vector(op.GetRelPos()),
                "rotation": vector(op.GetRelRot()),
                "scale": vector(op.GetRelScale()),
            }
            attempts = (
                (
                    "filePath",
                    getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                    c4d.DTYPE_FILENAME,
                ),
                (
                    "animationMode",
                    getattr(c4d, "REDSHIFT_FILE_ANIMATION_MODE", 1001),
                    c4d.DTYPE_LONG,
                ),
                (
                    "timingMode",
                    getattr(c4d, "REDSHIFT_FILE_ANIMATION_TIMING_MODE", 1002),
                    c4d.DTYPE_LONG,
                ),
                (
                    "frameStart",
                    getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_START", 1003),
                    c4d.DTYPE_REAL,
                ),
                (
                    "frameEnd",
                    getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_END", 1004),
                    c4d.DTYPE_REAL,
                ),
                (
                    "frameRate",
                    getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_RATE", 1005),
                    c4d.DTYPE_REAL,
                ),
                (
                    "frameOffset",
                    getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_OFFSET", 1008),
                    c4d.DTYPE_REAL,
                ),
            )
            for label, sub_id, dtype in attempts:
                try:
                    value = nested_parameter(op, sub_id, dtype)
                    if isinstance(value, c4d.BaseTime):
                        value = value.Get()
                    record[label] = value
                except Exception as error:
                    record[label + "Error"] = f"{type(error).__name__}: {error}"
            records.append(record)
        print(
            "PARACOSM_RS_PROXIES_JSON="
            + json.dumps(
                {
                    "c4dVersion": c4d.GetC4DVersion(),
                    "project": str(project),
                    "proxyCount": len(records),
                    "records": records,
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
