"""Inspect document and render-output color settings without modifying them."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def value_record(value) -> dict[str, object]:
    return {
        "type": type(value).__name__,
        "value": str(value),
        "repr": repr(value),
    }


def safe_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, c4d.Vector):
        return [value.x, value.y, value.z]
    try:
        return str(value)
    except Exception:
        return f"<{type(value).__name__}>"


def describe_video_posts(render_data) -> list[dict[str, object]]:
    records = []
    video_post = render_data.GetFirstVideoPost()
    while video_post is not None:
        parameters = []
        try:
            description = video_post.GetDescription(c4d.DESCFLAGS_DESC_0)
        except Exception:
            description = []
        for container, desc_id, _group_id in description:
            try:
                value = video_post.GetParameter(
                    desc_id, c4d.DESCFLAGS_GET_0
                )
            except Exception:
                continue
            name = container.GetString(c4d.DESC_NAME)
            if not name:
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
        records.append(
            {
                "name": video_post.GetName(),
                "typeId": video_post.GetType(),
                "parameters": parameters,
            }
        )
        video_post = video_post.GetNext()
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--render-data", required=True)
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
        render_data = doc.GetFirstRenderData()
        while render_data and render_data.GetName() != args.render_data:
            render_data = render_data.GetNext()
        if render_data is None:
            raise RuntimeError(
                f"Render data not found: {args.render_data}"
            )
        settings = render_data.GetDataInstance()
        document_settings = doc.GetDataInstance()
        payload = {
            "project": str(project),
            "renderData": render_data.GetName(),
            "document": {
                name: value_record(document_settings[constant])
                for name, constant in (
                    ("colorManagement", c4d.DOCUMENT_COLOR_MANAGEMENT),
                    ("colorProfile", c4d.DOCUMENT_COLORPROFILE),
                    (
                        "currentRenderColorSpace",
                        c4d.DOCUMENT_CURRENT_RENDER_COLORSPACE,
                    ),
                    (
                        "ocioRenderColorSpace",
                        c4d.DOCUMENT_OCIO_RENDER_COLORSPACE,
                    ),
                    (
                        "ocioRenderColorSpaceName",
                        c4d.DOCUMENT_OCIO_RENDER_COLORSPACE_NAME,
                    ),
                    (
                        "ocioDisplayColorSpace",
                        c4d.DOCUMENT_OCIO_DISPLAY_COLORSPACE,
                    ),
                    (
                        "ocioDisplayColorSpaceName",
                        c4d.DOCUMENT_OCIO_DISPLAY_COLORSPACE_NAME,
                    ),
                )
            },
            "renderSettings": {
                name: value_record(settings[constant])
                for name, constant in (
                    ("saveImage", c4d.RDATA_SAVEIMAGE),
                    ("path", c4d.RDATA_PATH),
                    ("format", c4d.RDATA_FORMAT),
                    ("formatDepth", c4d.RDATA_FORMATDEPTH),
                    ("imageColorProfile", c4d.RDATA_IMAGECOLORPROFILE),
                    ("renderer", c4d.RDATA_RENDERENGINE),
                )
            },
            "videoPosts": describe_video_posts(render_data),
        }
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        print(
            "PARACOSM_RENDER_COLOR_DIAGNOSTIC_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
