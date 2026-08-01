"""Read-only material-tag inventory for one C4D object hierarchy."""

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


def walk_hierarchy(op):
    yield op
    child = op.GetDown()
    if child:
        yield from walk_objects(child)


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


def safe_parameter(node, parameter_id, default=None):
    try:
        return node[parameter_id]
    except Exception:
        return default


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object-path", required=True)
    parser.add_argument("--frame", type=int, default=0)
    parser.add_argument("--take", default="Main")
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
        take_data = doc.GetTakeData()
        if take_data:
            take = next(
                (
                    item
                    for item in walk_takes(take_data.GetMainTake())
                    if item.GetName() == args.take
                ),
                None,
            )
            if take is None:
                raise RuntimeError(f"Take not found: {args.take}")
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
        target = next(
            (
                item
                for item in walk_objects(doc.GetFirstObject())
                if object_path(item) == args.object_path
            ),
            None,
        )
        if target is None:
            raise RuntimeError(f"Object not found: {args.object_path}")

        materials = []
        material = doc.GetFirstMaterial()
        while material:
            materials.append(material)
            material = material.GetNext()

        def material_index_for(linked):
            if linked is None:
                return None
            for index, candidate in enumerate(materials):
                try:
                    if candidate == linked:
                        return index
                except Exception:
                    continue
            return None

        objects = []
        for scene_object in walk_hierarchy(target):
            tags = []
            tag = scene_object.GetFirstTag()
            while tag:
                record = {
                    "name": tag.GetName(),
                    "typeId": int(tag.GetType()),
                    "typeName": str(tag.GetTypeName()),
                }
                if tag.CheckType(c4d.Ttexture):
                    linked = tag.GetMaterial()
                    record.update(
                        {
                            "material": linked.GetName() if linked else None,
                            "materialIndex": (
                                material_index_for(linked)
                                if linked
                                else None
                            ),
                            "restriction": str(
                                safe_parameter(
                                    tag,
                                    c4d.TEXTURETAG_RESTRICTION,
                                    "",
                                )
                            ),
                            "projection": int(
                                safe_parameter(
                                    tag,
                                    c4d.TEXTURETAG_PROJECTION,
                                    -1,
                                )
                            ),
                            "side": int(
                                safe_parameter(
                                    tag,
                                    c4d.TEXTURETAG_SIDE,
                                    -1,
                                )
                            ),
                        }
                    )
                tags.append(record)
                tag = tag.GetNext()
            objects.append(
                {
                    "name": scene_object.GetName(),
                    "path": object_path(scene_object),
                    "typeId": int(scene_object.GetType()),
                    "editorMode": int(scene_object.GetEditorMode()),
                    "renderMode": int(scene_object.GetRenderMode()),
                    "tags": tags,
                }
            )
        print(
            "PARACOSM_OBJECT_MATERIAL_TAGS_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "objectPath": args.object_path,
                    "frame": args.frame,
                    "take": args.take,
                    "objects": objects,
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
