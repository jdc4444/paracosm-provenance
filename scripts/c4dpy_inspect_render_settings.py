"""Inspect one saved C4D RenderData and its VideoPost parameters read-only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


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


def find_render_data(doc, name):
    current = doc.GetFirstRenderData()
    while current:
        if current.GetName() == name:
            return current
        current = current.GetNext()
    return None


def serialize(value, fps):
    if isinstance(value, c4d.BaseTime):
        return {"seconds": value.Get(), "frame": value.GetFrame(fps)}
    if isinstance(value, c4d.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return str(value)
    except Exception:
        return repr(value)


def describe(base_list, fps):
    parameters = []
    description = base_list.GetDescription(c4d.DESCFLAGS_DESC_0)
    for container, parameter_id, _group_id in description:
        try:
            value = base_list[parameter_id]
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
            }
        )
    return parameters


def describe_linked_base_lists(base_list, fps):
    """Expand direct BaseList2D-valued parameters without following cycles."""
    linked = []
    seen = set()
    description = base_list.GetDescription(c4d.DESCFLAGS_DESC_0)
    for container, parameter_id, _group_id in description:
        try:
            value = base_list[parameter_id]
        except Exception:
            continue
        if not isinstance(value, c4d.BaseList2D):
            continue
        key = (value.GetType(), value.GetName())
        if key in seen:
            continue
        seen.add(key)
        linked.append(
            {
                "ownerParameterId": [
                    parameter_id[index].id
                    for index in range(parameter_id.GetDepth())
                ],
                "ownerParameterName": container.GetString(c4d.DESC_NAME),
                "name": value.GetName(),
                "typeId": value.GetType(),
                "parameters": describe(value, fps),
            }
        )
    return linked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--render-data", required=True)
    parser.add_argument("--take")
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    payload = {"status": "failed", "project": str(project)}
    doc = None
    try:
        doc = c4d.documents.LoadDocument(
            str(project),
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
        )
        if doc is None:
            raise RuntimeError(f"Could not load {project}")
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if args.take and take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        if take_data and take:
            take_data.SetCurrentTake(take)
        fps = doc.GetFps()
        doc.SetTime(c4d.BaseTime(args.frame, fps))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        render_data = find_render_data(doc, args.render_data)
        if render_data is None:
            raise RuntimeError(
                f"Render data not found: {args.render_data}"
            )
        video_posts = []
        video_post = render_data.GetFirstVideoPost()
        while video_post:
            video_posts.append(
                {
                    "name": video_post.GetName(),
                    "typeId": video_post.GetType(),
                    "parameters": describe(video_post, fps),
                }
            )
            video_post = video_post.GetNext()
        payload = {
            "status": "inspected",
            "project": str(project),
            "take": take.GetName() if take else None,
            "frame": args.frame,
            "fps": fps,
            "renderData": {
                "name": render_data.GetName(),
                "parameters": describe(render_data, fps),
                "linkedBaseLists": describe_linked_base_lists(
                    render_data, fps
                ),
                "videoPosts": video_posts,
            },
        }
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"
    finally:
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        print(
            "PARACOSM_RENDER_SETTINGS_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
        if doc is not None:
            c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
