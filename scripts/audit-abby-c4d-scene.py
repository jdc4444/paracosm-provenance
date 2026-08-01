"""Read-only audit of Abby's Cinema 4D look-development scene.

Run with Cinema 4D's ``c4dpy`` executable. The script prints a single JSON
payload describing objects, materials, legacy shaders, cameras, lights, render
settings, and external assets. It never saves the source document.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import c4d


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def walk_shaders(shader):
    while shader:
        yield shader
        child = shader.GetDown()
        if child:
            yield from walk_shaders(child)
        shader = shader.GetNext()


def vector_payload(value):
    return [float(value.x), float(value.y), float(value.z)]


def matrix_payload(value):
    return {
        "off": vector_payload(value.off),
        "v1": vector_payload(value.v1),
        "v2": vector_payload(value.v2),
        "v3": vector_payload(value.v3),
    }


def safe_value(value):
    if isinstance(value, c4d.Vector):
        return vector_payload(value)
    if isinstance(value, c4d.Matrix):
        return matrix_payload(value)
    if isinstance(value, c4d.BaseTime):
        return float(value.Get())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def parameter_values(node):
    values = []
    description = node.GetDescription(c4d.DESCFLAGS_DESC_0)
    if description is None:
        return values
    for container, parameter_id, _ in description:
        name = container.GetString(c4d.DESC_NAME)
        if not name:
            continue
        try:
            value = node[parameter_id]
        except Exception:
            continue
        if isinstance(value, (str, int, float, bool, c4d.Vector, c4d.BaseTime)):
            values.append(
                {
                    "id": repr(parameter_id),
                    "name": name,
                    "value": safe_value(value),
                }
            )
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print compact object, material, camera, light, and render facts.",
    )
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
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )

        objects = []
        for scene_object in walk_objects(doc.GetFirstObject()):
            tags = []
            tag = scene_object.GetFirstTag()
            while tag:
                tags.append(
                    {
                        "name": tag.GetName(),
                        "type": int(tag.GetType()),
                        "material": (
                            tag.GetMaterial().GetName()
                            if hasattr(tag, "GetMaterial") and tag.GetMaterial()
                            else None
                        ),
                        "parameters": parameter_values(tag),
                    }
                )
                tag = tag.GetNext()
            objects.append(
                {
                    "name": scene_object.GetName(),
                    "type": int(scene_object.GetType()),
                    "matrix": matrix_payload(scene_object.GetMg()),
                    "editorMode": int(scene_object.GetEditorMode()),
                    "renderMode": int(scene_object.GetRenderMode()),
                    "tags": tags,
                    "parameters": parameter_values(scene_object),
                }
            )

        materials = []
        material = doc.GetFirstMaterial()
        while material:
            materials.append(
                {
                    "name": material.GetName(),
                    "type": int(material.GetType()),
                    "parameters": parameter_values(material),
                    "shaders": [
                        {
                            "name": shader.GetName(),
                            "type": int(shader.GetType()),
                            "parameters": parameter_values(shader),
                        }
                        for shader in walk_shaders(material.GetFirstShader())
                    ],
                }
            )
            material = material.GetNext()

        render_data = doc.GetActiveRenderData()
        payload = {
            "project": str(project),
            "fps": int(doc.GetFps()),
            "time": float(doc.GetTime().Get()),
            "objects": objects,
            "materials": materials,
            "render": {
                "name": render_data.GetName(),
                "parameters": parameter_values(render_data),
            },
        }
        if args.summary:
            light_fields = {
                "Type",
                "Intensity",
                "Exposure (EV)",
                "Color",
                "Temperature (K)",
                "Area Shape",
                "Size X",
                "Size Y",
                "Texture",
                "Texture Path",
                "File",
            }
            camera_fields = {
                "Focal Length (mm)",
                "Shift",
                "Exposure (EV)",
                "Focus Distance",
                "Aperture (f/#)",
                "Tone-Mapping",
                "Highlights",
                "Desaturate Highlights",
                "Blacks",
                "Saturation",
                "Contrast",
            }
            render_fields = {
                "Renderer",
                "Width",
                "Height",
                "Resolution",
                "Frame Range",
                "From",
                "To",
                "Format",
                "Depth",
            }
            payload["objects"] = [
                {
                    "name": item["name"],
                    "type": item["type"],
                    "matrix": item["matrix"],
                    "midpoint": vector_payload(scene_object.GetMp()),
                    "radius": vector_payload(scene_object.GetRad()),
                    "tags": [
                        {
                            "name": tag["name"],
                            "type": tag["type"],
                            "material": tag["material"],
                        }
                        for tag in item["tags"]
                    ],
                    "parameters": [
                        field
                        for field in item["parameters"]
                        if field["name"]
                        in (
                            camera_fields
                            if item["type"] in {c4d.Ocamera, 1057516}
                            else light_fields
                            if item["type"] in {c4d.Olight, 1036751}
                            else set()
                        )
                    ],
                }
                for scene_object, item in zip(
                    walk_objects(doc.GetFirstObject()), objects
                )
                if item["type"]
                in {
                    c4d.Opolygon,
                    c4d.Ocamera,
                    c4d.Olight,
                    1036751,
                    1057516,
                }
            ]
            payload["materials"] = [
                {
                    "name": item["name"],
                    "type": item["type"],
                    "shaders": [
                        {
                            "name": shader["name"],
                            "type": shader["type"],
                            "parameters": [
                                field
                                for field in shader["parameters"]
                                if field["name"]
                                in {
                                    "File",
                                    "Filename",
                                    "Texture",
                                    "Color",
                                    "Gamma",
                                }
                            ],
                        }
                        for shader in item["shaders"]
                    ],
                }
                for item in materials
            ]
            payload["render"]["parameters"] = [
                field
                for field in payload["render"]["parameters"]
                if field["name"] in render_fields
            ]
        print(
            "ABBY_C4D_SCENE_AUDIT="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
