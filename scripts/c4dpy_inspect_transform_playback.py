"""Inspect one object's transform curves and evaluated playback read-only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def path(op):
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def vec(value):
    return [float(value.x), float(value.y), float(value.z)]


def animation_state(item):
    result = []
    current = item
    while current:
        result.insert(
            0,
            {
                "name": current.GetName(),
                "path": path(current),
                "type": int(current.GetType()),
                "animationOffBit": bool(current.GetBit(c4d.BIT_ANIM_OFF)),
                "noAnimationNBit": bool(current.GetNBit(c4d.NBIT_NOANIM)),
                "editorMode": int(current.GetEditorMode()),
                "renderMode": int(current.GetRenderMode()),
                "tags": [
                    {
                        "name": tag.GetName(),
                        "type": int(tag.GetType()),
                        "animationOffBit": bool(tag.GetBit(c4d.BIT_ANIM_OFF)),
                        "noAnimationNBit": bool(tag.GetNBit(c4d.NBIT_NOANIM)),
                    }
                    for tag in current.GetTags()
                ],
            },
        )
        current = current.GetUp()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--object", required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument(
        "--skip-evaluation",
        action="store_true",
        help=(
            "Read saved tracks and curve values without SetTime or "
            "ExecutePasses. This is a static diagnostic for scenes whose "
            "expressions fail in the current runtime."
        ),
    )
    parser.add_argument(
        "--all-keys",
        action="store_true",
        help="Include every key time and value for each object track.",
    )
    parser.add_argument("--include-materials", action="store_true")
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    if args.include_materials:
        load_flags |= c4d.SCENEFILTER_MATERIALS
    doc = c4d.documents.LoadDocument(str(project), load_flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        matches = [
            item
            for item in walk(doc.GetFirstObject())
            if item.GetName() == args.object or path(item) == args.object
        ]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one object, found {len(matches)}")
        item = matches[0]
        tracks = []
        for track in item.GetCTracks():
            curve = track.GetCurve()
            desc = track.GetDescriptionID()
            tracks.append(
                {
                    "desc": [
                        [
                            int(desc[index].id),
                            int(desc[index].dtype),
                            int(desc[index].creator),
                        ]
                        for index in range(desc.GetDepth())
                    ],
                    "keys": curve.GetKeyCount() if curve else 0,
                    "values": (
                        [
                            float(curve.GetKey(index).GetValue())
                            for index in sorted(
                                set(
                                    [
                                        0,
                                        max(curve.GetKeyCount() // 2, 0),
                                        max(curve.GetKeyCount() - 1, 0),
                                    ]
                                )
                            )
                            if curve.GetKeyCount()
                        ]
                        if curve
                        else []
                    ),
                    "times": (
                        [
                            int(curve.GetKey(index).GetTime().GetFrame(doc.GetFps()))
                            for index in sorted(
                                set(
                                    [
                                        0,
                                        max(curve.GetKeyCount() // 2, 0),
                                        max(curve.GetKeyCount() - 1, 0),
                                    ]
                                )
                            )
                            if curve.GetKeyCount()
                        ]
                        if curve
                        else []
                    ),
                    "animOff": bool(track[c4d.ID_CTRACK_ANIMOFF]),
                    "allKeys": (
                        [
                            {
                                "frame": int(
                                    curve.GetKey(index)
                                    .GetTime()
                                    .GetFrame(doc.GetFps())
                                ),
                                "value": float(
                                    curve.GetKey(index).GetValue()
                                ),
                            }
                            for index in range(curve.GetKeyCount())
                        ]
                        if args.all_keys and curve
                        else None
                    ),
                    "evaluatedCurveValues": (
                        [
                            float(curve.GetValue(c4d.BaseTime(frame, doc.GetFps())))
                            for frame in args.frames
                        ]
                        if curve
                        else []
                    ),
                }
            )
        fps = doc.GetFps()
        evaluated = []
        for frame in args.frames:
            if not args.skip_evaluation:
                doc.SetTime(c4d.BaseTime(frame, fps))
                doc.ExecutePasses(None, True, True, True, 0)
            evaluated.append(
                {
                    "frame": frame,
                    "relPosition": vec(item.GetRelPos()),
                    "relRotation": vec(item.GetRelRot()),
                    "relScale": vec(item.GetRelScale()),
                    "worldPosition": vec(item.GetMg().off),
                }
            )
        take_data = doc.GetTakeData()
        payload = {
            "project": str(project),
            "object": path(item),
            "animationState": animation_state(item),
            "currentTake": (
                take_data.GetCurrentTake().GetName() if take_data else None
            ),
            "evaluatedScene": not args.skip_evaluation,
            "tracks": tracks,
            "evaluated": evaluated,
        }
        if args.result_json is not None:
            result_json = args.result_json.expanduser().resolve()
            result_json.parent.mkdir(parents=True, exist_ok=True)
            result_json.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        print(
            "C4D_TRANSFORM_PLAYBACK="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
