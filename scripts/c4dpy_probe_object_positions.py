"""Read-only multi-frame object-position probe with optional root-relative data."""

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
    parser.add_argument("--object-path", action="append", required=True)
    parser.add_argument("--relative-to")
    parser.add_argument("--frame", type=float, action="append", required=True)
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
        "fps": doc.GetFps(),
        "relativeTo": args.relative_to,
        "frames": [],
    }
    try:
        objects = {
            object_path(item): item
            for item in walk_objects(doc.GetFirstObject())
        }
        targets = []
        for path in args.object_path:
            item = objects.get(path)
            if item is None:
                raise RuntimeError(f"Object not found: {path}")
            targets.append((path, item))
        relative = (
            objects.get(args.relative_to) if args.relative_to else None
        )
        if args.relative_to and relative is None:
            raise RuntimeError(
                f"Relative root not found: {args.relative_to}"
            )
        for frame in args.frame:
            doc.SetTime(c4d.BaseTime(frame / doc.GetFps()))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                c4d.BUILDFLAGS_EXTERNALRENDERER,
            )
            root_inverse = ~relative.GetMg() if relative is not None else None
            report["frames"].append(
                {
                    "frame": frame,
                    "seconds": frame / doc.GetFps(),
                    "objects": [
                        {
                            "path": path,
                            "global": vector(item.GetMg().off),
                            "relative": (
                                vector((root_inverse * item.GetMg()).off)
                                if root_inverse is not None
                                else None
                            ),
                        }
                        for path, item in targets
                    ],
                }
            )
        print(
            "PARACOSM_OBJECT_POSITION_PROBE_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_OBJECT_POSITION_PROBE_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
