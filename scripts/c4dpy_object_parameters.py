"""Read one C4D object's exposed parameters without modifying the document."""

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


def walk_takes(take):
    current = take
    while current:
        yield current
        child = current.GetDown()
        if child:
            yield from walk_takes(child)
        current = current.GetNext()


def find_take(take_data, name):
    if not take_data or not name:
        return None
    return next(
        (
            take
            for take in walk_takes(take_data.GetMainTake())
            if take.GetName() == name
        ),
        None,
    )


def serialize(value, fps, depth=0):
    if isinstance(value, c4d.BaseTime):
        return {
            "seconds": value.Get(),
            "frame": value.GetFrame(fps),
        }
    if isinstance(value, c4d.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, c4d.Matrix):
        return {
            "off": serialize(value.off, fps, depth + 1),
            "v1": serialize(value.v1, fps, depth + 1),
            "v2": serialize(value.v2, fps, depth + 1),
            "v3": serialize(value.v3, fps, depth + 1),
        }
    if isinstance(value, c4d.BaseObject):
        return {
            "name": value.GetName(),
            "path": object_path(value),
            "typeId": value.GetType(),
            "globalMatrix": serialize(value.GetMg(), fps, depth + 1),
        }
    if isinstance(value, dict):
        return {
            str(key): serialize(item, fps, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [serialize(item, fps, depth + 1) for item in value]
    if isinstance(value, c4d.BaseContainer):
        if depth >= 8:
            return {"truncated": True, "size": len(value)}
        result = {}
        for index in range(len(value)):
            parameter_id = value.GetIndexId(index)
            type_id = value.GetType(parameter_id)
            try:
                item = value.GetData(parameter_id)
            except Exception as error:
                item = f"<inaccessible: {type(error).__name__}: {error}>"
                for getter in (
                    lambda: value.GetFilename(parameter_id).GetString(),
                    lambda: value.GetString(parameter_id),
                ):
                    try:
                        candidate = getter()
                    except Exception:
                        continue
                    if candidate:
                        item = candidate
                        break
                if isinstance(item, str) and item.startswith("<inaccessible:"):
                    try:
                        custom = value.GetCustomDataType(parameter_id)
                        item = {
                            "pythonType": str(type(custom)),
                            "repr": repr(custom),
                            "members": [
                                name
                                for name in dir(custom)
                                if not name.startswith("_")
                            ],
                        }
                    except Exception:
                        pass
            result[str(parameter_id)] = {
                "typeId": type_id,
                "value": serialize(item, fps, depth + 1),
            }
        return result
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object-path", required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--take")
    parser.add_argument("--raw-data", action="store_true")
    parser.add_argument(
        "--skip-evaluation",
        action="store_true",
        help=(
            "Read the object's saved values without SetTime or "
            "ExecutePasses. This keeps failing expressions and generators "
            "from blocking static scene-state inspection."
        ),
    )
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        fps = doc.GetFps()
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data and take:
            take_data.SetCurrentTake(take)
        elif args.take:
            raise RuntimeError(f"Take not found: {args.take}")
        if not args.skip_evaluation:
            doc.SetTime(c4d.BaseTime(args.frame, fps))
            doc.ExecutePasses(
                None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
            )
        target = next(
            (
                op
                for op in walk_objects(doc.GetFirstObject())
                if object_path(op) == args.object_path
            ),
            None,
        )
        if target is None:
            raise RuntimeError(f"Object not found: {args.object_path}")
        parameters = []
        description = target.GetDescription(c4d.DESCFLAGS_DESC_0)
        for container, parameter_id, _group_id in description:
            try:
                value = target[parameter_id]
            except Exception:
                continue
            parameters.append(
                {
                    "id": [
                        parameter_id[index].id
                        for index in range(parameter_id.GetDepth())
                    ],
                    "name": container.GetString(c4d.DESC_NAME),
                    "value": serialize(value, fps),
                    "cycle": serialize(
                        container.GetContainer(c4d.DESC_CYCLE),
                        fps,
                    ),
                }
            )
        payload = {
            "project": str(project),
            "objectPath": args.object_path,
            "objectType": target.GetType(),
            "fps": fps,
            "frame": args.frame,
            "evaluated": not args.skip_evaluation,
            "take": take.GetName() if take else None,
            "globalMatrix": serialize(target.GetMg(), fps),
            "parameters": parameters,
            "rawData": (
                serialize(target.GetDataInstance(), fps)
                if args.raw_data
                else None
            ),
        }
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        print(
            "PARACOSM_OBJECT_PARAMETERS_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_OBJECT_PARAMETERS_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
