"""Inspect asset-like parameters on exact C4D objects without saving."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


REDSHIFT_RSFILE_DATATYPE_ID = 1036765


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    current = op
    while current:
        names.insert(0, current.GetName())
        current = current.GetUp()
    return "/".join(names)


def private_rsfile_value(scene_object, parameter_id: int) -> str:
    try:
        return str(
            scene_object.GetParameter(
                c4d.DescID(
                    c4d.DescLevel(
                        parameter_id,
                        REDSHIFT_RSFILE_DATATYPE_ID,
                        scene_object.GetType(),
                    ),
                    c4d.DescLevel(1000, c4d.DTYPE_FILENAME, 0),
                ),
                c4d.DESCFLAGS_GET_0,
            )
            or ""
        )
    except Exception as error:
        return f"<{type(error).__name__}: {error}>"


def container_records(container, prefix: str = "") -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index in range(len(container)):
        key = container.GetIndexId(index)
        try:
            value = container.GetIndexData(index)
        except Exception as error:
            records.append(
                {
                    "path": f"{prefix}{key}",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            continue
        record = {
            "path": f"{prefix}{key}",
            "valueType": type(value).__name__,
            "value": str(value),
            "repr": repr(value),
        }
        records.append(record)
        if isinstance(value, c4d.BaseContainer):
            records.extend(
                container_records(value, f"{prefix}{key}/")
            )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object-name", action="append", default=[])
    parser.add_argument("--result-json", type=Path, required=True)
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
    output = args.result_json.expanduser().resolve()
    try:
        wanted = set(args.object_name)
        objects: list[dict[str, object]] = []
        for scene_object in walk_objects(doc.GetFirstObject()):
            if wanted and scene_object.GetName() not in wanted:
                continue
            descriptions: list[dict[str, object]] = []
            try:
                description = scene_object.GetDescription(
                    c4d.DESCFLAGS_DESC_0
                )
            except Exception:
                description = []
            for container, desc_id, _group_id in description:
                try:
                    value = scene_object.GetParameter(
                        desc_id, c4d.DESCFLAGS_GET_0
                    )
                except Exception as error:
                    value = (
                        f"{type(error).__name__}: {error}"
                    )
                text = str(value)
                filename_type = getattr(c4d, "Filename", None)
                if not (
                    (
                        filename_type is not None
                        and isinstance(value, filename_type)
                    )
                    or any(
                        term in text.casefold()
                        for term in (
                            ".ies",
                            ".exr",
                            "softbox",
                            "mainframe",
                        )
                    )
                ):
                    continue
                descriptions.append(
                    {
                        "descId": str(desc_id),
                        "name": str(
                            container.GetString(c4d.DESC_NAME) or ""
                        ),
                        "valueType": type(value).__name__,
                        "value": text,
                        "repr": repr(value),
                    }
                )
            raw = [
                record
                for record in container_records(
                    scene_object.GetDataInstance()
                )
                if any(
                    term in (record.get("value") or "").casefold()
                    for term in (
                        ".ies",
                        ".exr",
                        "softbox",
                        "mainframe",
                    )
                )
            ]
            objects.append(
                {
                    "name": scene_object.GetName(),
                    "path": object_path(scene_object),
                    "typeId": scene_object.GetType(),
                    "descriptionMatches": descriptions,
                    "containerMatches": raw,
                    "privateFileParameters": [
                        {
                            "parameterId": parameter_id,
                            "value": private_rsfile_value(
                                scene_object, parameter_id
                            ),
                        }
                        for parameter_id in (
                            11001,
                            11026,
                            12000,
                            12008,
                            13000,
                            13002,
                            13003,
                        )
                    ],
                }
            )
        payload = {"project": str(project), "objects": objects}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            "PARACOSM_OBJECT_ASSET_DIAGNOSTIC_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        payload = {
            "project": str(project),
            "error": f"{type(error).__name__}: {error}",
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            "PARACOSM_OBJECT_ASSET_DIAGNOSTIC_ERROR="
            + payload["error"],
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
