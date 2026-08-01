"""Inspect the animated controls on Abby's native MetaHuman face hierarchy.

Run with Maxon's bundled c4dpy. The project is loaded read-only and never
saved. The report is intentionally limited to named controls so it is useful
while authoring a derived facial-animation scene without touching the master.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


DEFAULT_CONTROLS = (
    "head",
    "FACIAL_C_FacialRoot",
    "FACIAL_L_Eye",
    "FACIAL_R_Eye",
    "FACIAL_L_EyelidUpperA",
    "FACIAL_R_EyelidUpperA",
    "FACIAL_L_EyelidLowerA",
    "FACIAL_R_EyelidLowerA",
    "FACIAL_C_Jaw",
    "FACIAL_C_MouthUpper",
    "FACIAL_C_MouthLower",
    "FACIAL_L_LipCorner",
    "FACIAL_R_LipCorner",
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


def ancestor_animation_state(op) -> list[dict[str, object]]:
    result = []
    item = op
    while item:
        result.insert(
            0,
            {
                "name": item.GetName(),
                "animationOffBit": bool(item.GetBit(c4d.BIT_ANIM_OFF)),
                "noAnimationNBit": bool(item.GetNBit(c4d.NBIT_NOANIM)),
                "tags": [
                    {"name": tag.GetName(), "type": int(tag.GetType())}
                    for tag in item.GetTags()
                ],
            },
        )
        item = item.GetUp()
    return result


def vector(value: c4d.Vector) -> list[float]:
    return [float(value.x), float(value.y), float(value.z)]


def desc_id_payload(desc_id: c4d.DescID) -> list[dict[str, int]]:
    return [
        {
            "id": int(desc_id[index].id),
            "dtype": int(desc_id[index].dtype),
            "creator": int(desc_id[index].creator),
        }
        for index in range(desc_id.GetDepth())
    ]


def track_payload(track, fps: int) -> dict[str, object]:
    curve = track.GetCurve()
    keys = []
    if curve:
        for index in range(curve.GetKeyCount()):
            key = curve.GetKey(index)
            keys.append(
                {
                    "frame": int(key.GetTime().GetFrame(fps)),
                    "value": float(key.GetValue()),
                    "interpolation": int(key.GetInterpolation()),
                }
            )
    return {
        "name": track.GetName(),
        "animation": bool(track[c4d.ID_CTRACK_ANIMOFF]),
        "animationOffBit": bool(track.GetBit(c4d.BIT_ANIM_OFF)),
        "noAnimationNBit": bool(track.GetNBit(c4d.NBIT_NOANIM)),
        "solo": bool(track[c4d.ID_CTRACK_ANIMSOLO]),
        "descriptionId": desc_id_payload(track.GetDescriptionID()),
        "keys": keys,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--control", action="append", default=[])
    parser.add_argument("--frame", type=int, action="append", default=[0])
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    controls = set(args.control or DEFAULT_CONTROLS)
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")

    report = {
        "project": str(project),
        "saved": False,
        "fps": int(doc.GetFps()),
        "frames": sorted(set(args.frame)),
        "controls": [],
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        fps = doc.GetFps()
        take_data = doc.GetTakeData()
        current_take = take_data.GetCurrentTake() if take_data else None
        main_take = take_data.GetMainTake() if take_data else None
        report["currentTake"] = current_take.GetName() if current_take else None
        report["mainTake"] = main_take.GetName() if main_take else None
        objects = list(walk_objects(doc.GetFirstObject()))
        selected = [
            op
            for op in objects
            if op.GetName() in controls
            and (
                "root.002/" in object_path(op)
                or op.GetName() not in {"head"}
            )
        ]
        for op in selected:
            samples = []
            for frame in sorted(set(args.frame)):
                doc.SetTime(c4d.BaseTime(frame, fps))
                doc.ExecutePasses(
                    None,
                    True,
                    True,
                    True,
                    getattr(c4d, "BUILDFLAGS_NONE", 0),
                )
                samples.append(
                    {
                        "frame": frame,
                        "relativePosition": vector(op.GetRelPos()),
                        "relativeRotation": vector(op.GetRelRot()),
                        "relativeScale": vector(op.GetRelScale()),
                        "globalPosition": vector(op.GetMg().off),
                    }
                )
            report["controls"].append(
                {
                    "name": op.GetName(),
                    "path": object_path(op),
                    "ancestors": ancestor_animation_state(op),
                    "animationOffBit": bool(op.GetBit(c4d.BIT_ANIM_OFF)),
                    "noAnimationNBit": bool(op.GetNBit(c4d.NBIT_NOANIM)),
                    "samples": samples,
                    "tracks": [
                        track_payload(track, fps)
                        for track in op.GetCTracks()
                    ],
                }
            )
        print(
            "ABBY_FACE_TRACK_AUDIT="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "ABBY_FACE_TRACK_AUDIT_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
