"""Read-only report of Abby mesh weight-tag joint roots."""

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


def root_name(op) -> str | None:
    if op is None:
        return None
    while op.GetUp() is not None:
        op = op.GetUp()
    return op.GetName()


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
        records = []
        for item in walk_objects(doc.GetFirstObject()):
            for tag in item.GetTags():
                if tag.GetType() != c4d.Tweights:
                    continue
                joint_count = tag.GetJointCount()
                roots = collections.Counter()
                samples = []
                for index in range(joint_count):
                    joint = tag.GetJoint(index, doc)
                    roots[root_name(joint)] += 1
                    if len(samples) < 12 and joint is not None:
                        samples.append(object_path(joint))
                records.append(
                    {
                        "mesh": object_path(item),
                        "jointCount": joint_count,
                        "jointRoots": dict(roots),
                        "jointSamples": samples,
                    }
                )
        print(
            "ABBY_C4D_SKIN_BINDINGS="
            + json.dumps(
                {
                    "project": str(project),
                    "saved": False,
                    "weightTags": len(records),
                    "bindings": records,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
