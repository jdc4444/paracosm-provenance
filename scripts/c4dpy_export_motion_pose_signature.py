"""Export rotation-invariant joint-distance signatures from a C4D rig."""

from __future__ import annotations

import argparse
import itertools
import json
import os
from pathlib import Path

import c4d


JOINTS = (
    "pelvis",
    "head",
    "hand_l",
    "hand_r",
    "foot_l",
    "foot_r",
    "upperarm_l",
    "upperarm_r",
)


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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root-marker", required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--step", type=int, default=1)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")

    try:
        c4d.documents.SetActiveDocument(doc)
        selected = {}
        for item in walk_objects(doc.GetFirstObject()):
            path = object_path(item)
            if args.root_marker not in path or item.GetName() not in JOINTS:
                continue
            if item.GetName() in selected:
                raise RuntimeError(
                    f"Ambiguous joint {item.GetName()!r} under {args.root_marker!r}"
                )
            selected[item.GetName()] = item
        missing = sorted(set(JOINTS) - set(selected))
        if missing:
            raise RuntimeError(f"Missing joints: {missing}")

        pairs = list(itertools.combinations(JOINTS, 2))
        fps = doc.GetFps()
        records = []
        for frame in range(args.start, args.end + 1, args.step):
            doc.SetTime(c4d.BaseTime(frame, fps))
            doc.ExecutePasses(None, True, True, True, 0)
            points = {name: selected[name].GetMg().off for name in JOINTS}
            scale = max((points["head"] - points["pelvis"]).GetLength(), 1.0e-8)
            signature = [
                (points[left] - points[right]).GetLength() / scale
                for left, right in pairs
            ]
            records.append({"frame": frame, "signature": signature})

        output.write_text(
            json.dumps(
                {
                    "source": str(project),
                    "fps": fps,
                    "rootMarker": args.root_marker,
                    "joints": JOINTS,
                    "pairs": pairs,
                    "records": records,
                },
                separators=(",", ":"),
            )
        )
        print(
            "CODEX_C4D_POSE_SIGNATURE="
            + json.dumps(
                {
                    "source": str(project),
                    "output": str(output),
                    "frames": len(records),
                    "rootMarker": args.root_marker,
                }
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
