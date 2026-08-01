"""Probe Maxon's legacy-to-native Redshift camera conversion in memory."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_take, object_path, walk_objects


LEGACY_RS_CAMERA_OBJECT_ID = 1057516
NATIVE_CAMERA_OBJECT_ID = c4d.Ocamera
RS_CAMERA_TAG_ID = 1036760
CONVERT_SELECTED_CAMERAS_COMMAND_ID = 1057472


def safe_value(value):
    if isinstance(value, c4d.Vector):
        return {"x": value.x, "y": value.y, "z": value.z}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def parameters(item, ids: set[int]) -> list[dict[str, object]]:
    result = []
    for container, desc_id, _group_id in item.GetDescription(
        c4d.DESCFLAGS_DESC_0
    ):
        top_id = desc_id[0].id if desc_id.GetDepth() else None
        if top_id not in ids:
            continue
        try:
            value = item.GetParameter(desc_id, c4d.DESCFLAGS_GET_0)
        except Exception as error:
            value = f"{type(error).__name__}: {error}"
        result.append(
            {
                "name": str(container.GetString(c4d.DESC_NAME) or ""),
                "id": [
                    desc_id[index].id
                    for index in range(desc_id.GetDepth())
                ],
                "value": safe_value(value),
            }
        )
    return result


def camera_payload(item) -> dict[str, object]:
    tags = []
    tag = item.GetFirstTag()
    while tag:
        tags.append(
            {
                "name": tag.GetName(),
                "typeId": tag.GetType(),
                "parameters": parameters(
                    tag,
                    set(range(10000, 11013))
                    | set(range(11000, 11013))
                    | {1000, 1001, 2000},
                ),
            }
        )
        tag = tag.GetNext()
    return {
        "name": item.GetName(),
        "path": object_path(item),
        "typeId": item.GetType(),
        "guid": str(item.GetGUID()),
        "position": safe_value(item.GetMg().off),
        "parameters": parameters(
            item,
            {
                c4d.CAMERA_FOCUS,
                c4d.CAMERAOBJECT_APERTURE,
                1000,
                1001,
                1010,
                1201,
                7002,
                7003,
                8002,
            },
        ),
        "tags": tags,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--camera-path")
    parser.add_argument("--take", default="Main")
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    result_path = args.result_json.expanduser().resolve()
    report: dict[str, object] = {
        "status": "failed",
        "project": str(project),
        "camera": args.camera,
        "cameraPath": args.camera_path,
        "take": args.take,
        "frame": args.frame,
        "sourcePreserved": True,
        "commandId": CONVERT_SELECTED_CAMERAS_COMMAND_ID,
    }
    doc = None
    try:
        doc = c4d.documents.LoadDocument(
            str(project),
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
        )
        if doc is None:
            raise RuntimeError("Cinema 4D could not load the source project")
        c4d.documents.SetActiveDocument(doc)
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
        cameras_before = [
            item
            for item in walk_objects(doc.GetFirstObject())
            if item.CheckType(NATIVE_CAMERA_OBJECT_ID)
            or item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
        ]
        source = next(
            (
                item
                for item in cameras_before
                if (
                    args.camera_path
                    and object_path(item) == args.camera_path
                )
                or (
                    not args.camera_path
                    and item.GetName() == args.camera
                )
            ),
            None,
        )
        if source is None:
            raise RuntimeError("Requested legacy camera was not found")
        source_guid = str(source.GetGUID())
        report["sourceBefore"] = camera_payload(source)
        before_guids = {str(item.GetGUID()) for item in cameras_before}

        doc.SetActiveObject(source, c4d.SELECTION_NEW)
        command_result = bool(
            c4d.CallCommand(CONVERT_SELECTED_CAMERAS_COMMAND_ID)
        )
        c4d.EventAdd()
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        cameras_after = [
            item
            for item in walk_objects(doc.GetFirstObject())
            if item.CheckType(NATIVE_CAMERA_OBJECT_ID)
            or item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
        ]
        converted = [
            item
            for item in cameras_after
            if str(item.GetGUID()) not in before_guids
            or (
                str(item.GetGUID()) == source_guid
                and item.GetType() != LEGACY_RS_CAMERA_OBJECT_ID
            )
        ]
        tagged = [
            item
            for item in cameras_after
            if any(tag.GetType() == RS_CAMERA_TAG_ID for tag in item.GetTags())
        ]
        report.update(
            {
                "status": "probed",
                "commandReturned": command_result,
                "cameraCountBefore": len(cameras_before),
                "cameraCountAfter": len(cameras_after),
                "convertedCandidates": [
                    camera_payload(item) for item in converted
                ],
                "redshiftTaggedCameras": [
                    camera_payload(item) for item in tagged
                ],
            }
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            "PARACOSM_RS_CAMERA_CONVERSION_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        if doc is not None:
            c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
