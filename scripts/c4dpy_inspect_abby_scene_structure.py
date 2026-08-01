"""Read-only structural summary for an Abby Cinema 4D project."""

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
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
        objects = list(walk_objects(doc.GetFirstObject()))
        records = []
        for item in objects:
            tracks = list(item.GetCTracks())
            records.append(
                {
                    "name": item.GetName(),
                    "path": object_path(item),
                    "type": int(item.GetType()),
                    "tracks": len(tracks),
                    "children": sum(1 for _ in walk_objects(item.GetDown()))
                    if item.GetDown()
                    else 0,
                }
            )

        render_data = doc.GetActiveRenderData()
        video_posts = []
        video_post = render_data.GetFirstVideoPost() if render_data else None
        while video_post is not None:
            video_posts.append(
                {"name": video_post.GetName(), "type": int(video_post.GetType())}
            )
            video_post = video_post.GetNext()

        report = {
            "project": str(project),
            "saved": False,
            "fps": int(doc.GetFps()),
            "range": [
                int(doc.GetMinTime().GetFrame(doc.GetFps())),
                int(doc.GetMaxTime().GetFrame(doc.GetFps())),
            ],
            "objectCount": len(objects),
            "materialCount": len(doc.GetMaterials()),
            "renderEngine": int(render_data[c4d.RDATA_RENDERENGINE])
            if render_data
            else None,
            "videoPosts": video_posts,
            "topLevel": [
                {"name": item.GetName(), "type": int(item.GetType())}
                for item in objects
                if item.GetUp() is None
            ],
            "animated": [item for item in records if item["tracks"]],
            "named": [
                item
                for item in records
                if any(
                    term in item["name"].casefold()
                    for term in (
                        "abby",
                        "body",
                        "face",
                        "hair",
                        "dress",
                        "shirt",
                        "skirt",
                        "corset",
                        "sweater",
                        "shoe",
                        "boot",
                        "root",
                        "pelvis",
                        "hip",
                        "spine",
                        "hand",
                        "head",
                        "camera",
                        "light",
                        "dome",
                        "area",
                    )
                )
            ],
        }
        print(
            "ABBY_C4D_SCENE_STRUCTURE="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
