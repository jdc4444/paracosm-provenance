"""Probe the exact joints referenced by a polygon object's Weight tag.

The source document is loaded read-only. This is used to compare C4D's native
FBX coordinate basis with another importer without modifying any scene asset.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def vector(value: c4d.Vector) -> list[float]:
    return [value.x, value.y, value.z]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object-path", required=True)
    parser.add_argument("--frame", type=int, action="append", required=True)
    parser.add_argument("--joint", action="append", default=[])
    parser.add_argument("--joint-term", action="append", default=[])
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    report = {
        "project": str(project),
        "objectPath": args.object_path,
        "fps": doc.GetFps(),
        "frames": [],
    }
    try:
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
        weight = target.GetTag(c4d.Tweights)
        if weight is None:
            raise RuntimeError("Object has no Weight tag")
        joint_count = weight.GetJointCount()
        joints = [
            weight.GetJoint(index, doc) for index in range(joint_count)
        ]
        terms = tuple(item.casefold() for item in args.joint_term)
        names = set(args.joint)
        selected = [
            item
            for item in joints
            if item is not None
            and (
                not terms
                and not names
                or item.GetName() in names
                or any(term in item.GetName().casefold() for term in terms)
            )
        ]
        for frame in args.frame:
            doc.SetTime(c4d.BaseTime(frame, doc.GetFps()))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                c4d.BUILDFLAGS_EXTERNALRENDERER,
            )
            report["frames"].append(
                {
                    "frame": frame,
                    "joints": [
                        {
                            "name": joint.GetName(),
                            "path": object_path(joint),
                            "position": vector(joint.GetMg().off),
                        }
                        for joint in selected
                    ],
                }
            )
        report["jointCount"] = joint_count
        report["selectedJointCount"] = len(selected)
        print(
            "PARACOSM_WEIGHT_JOINT_PROBE_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_WEIGHT_JOINT_PROBE_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
