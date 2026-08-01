"""Read-only compatibility check between facial FBX and Abby's C4D rig."""

from __future__ import annotations

import argparse
import collections
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


def load(path: Path):
    doc = c4d.documents.LoadDocument(
        str(path),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {path}")
    return doc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fbx", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    fbx = args.fbx.expanduser().resolve()
    target = args.target.expanduser().resolve()
    source_doc = load(fbx)
    try:
        source_objects = list(walk_objects(source_doc.GetFirstObject()))
        source_records = [
            {
                "name": item.GetName(),
                "path": object_path(item),
                "type": int(item.GetType()),
            }
            for item in source_objects
            if list(item.GetCTracks())
        ]
        source_object_count = len(source_objects)
    finally:
        c4d.documents.KillDocument(source_doc)

    target_doc = load(target)
    try:
        target_objects = list(walk_objects(target_doc.GetFirstObject()))
        target_by_name = collections.defaultdict(list)
        matched = []
        ambiguous = []
        missing = []
        type_mismatches = []
        for item in target_objects:
            target_by_name[item.GetName()].append(item)
        for record in source_records:
            candidates = target_by_name.get(record["name"], [])
            if not candidates:
                missing.append(record["path"])
                continue
            if len(candidates) > 1:
                ambiguous.append(
                    {
                        "source": record["path"],
                        "targets": [object_path(node) for node in candidates],
                    }
                )
                continue
            target_item = candidates[0]
            matched.append(record["name"])
            if record["type"] != target_item.GetType():
                type_mismatches.append(
                    {
                        "name": record["name"],
                        "sourceType": record["type"],
                        "targetType": int(target_item.GetType()),
                    }
                )

        print(
            "ABBY_FBX_TARGET_COMPATIBILITY="
            + json.dumps(
                {
                    "fbx": str(fbx),
                    "target": str(target),
                    "sourceObjectCount": source_object_count,
                    "sourceAnimatedObjectCount": len(source_records),
                    "targetObjectCount": len(target_objects),
                    "matchedAnimatedObjectCount": len(matched),
                    "uniqueMatchedNames": len(set(matched)),
                    "missing": missing,
                    "ambiguous": ambiguous,
                    "typeMismatches": type_mismatches,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(target_doc)


if __name__ == "__main__":
    main()
    os._exit(0)
