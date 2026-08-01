"""Compact, read-only audit of dense facial-animation tracks in a C4D file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


FOCUS_TERMS = (
    "eye",
    "eyelid",
    "jaw",
    "lip",
    "mouth",
    "brow",
    "facialroot",
    "head",
)


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


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
        objects = list(walk_objects(doc.GetFirstObject()))
        track_count = 0
        key_count = 0
        varying_track_count = 0
        varying_objects = set()
        focus = {}
        for item in objects:
            item_tracks = list(item.GetCTracks())
            track_count += len(item_tracks)
            item_varying = 0
            item_keys = 0
            max_range = 0.0
            for track in item_tracks:
                curve = track.GetCurve()
                if curve is None:
                    continue
                values = [
                    float(curve.GetKey(index).GetValue())
                    for index in range(curve.GetKeyCount())
                ]
                item_keys += len(values)
                key_count += len(values)
                value_range = max(values, default=0.0) - min(
                    values, default=0.0
                )
                max_range = max(max_range, value_range)
                if value_range > 1.0e-7:
                    varying_track_count += 1
                    item_varying += 1
                    varying_objects.add(item)
            if any(term in item.GetName().casefold() for term in FOCUS_TERMS):
                focus[item.GetName()] = {
                    "tracks": len(item_tracks),
                    "varyingTracks": item_varying,
                    "keys": item_keys,
                    "maxCurveRange": max_range,
                }

        take_data = doc.GetTakeData()
        current_take = take_data.GetCurrentTake() if take_data else None
        main_take = take_data.GetMainTake() if take_data else None
        report = {
            "project": str(project),
            "saved": False,
            "fps": int(doc.GetFps()),
            "range": [
                int(doc.GetMinTime().GetFrame(doc.GetFps())),
                int(doc.GetMaxTime().GetFrame(doc.GetFps())),
            ],
            "objectCount": len(objects),
            "trackCount": track_count,
            "keyCount": key_count,
            "varyingTrackCount": varying_track_count,
            "varyingObjectCount": len(varying_objects),
            "currentTake": current_take.GetName() if current_take else None,
            "mainTake": main_take.GetName() if main_take else None,
            "focus": dict(
                sorted(
                    focus.items(),
                    key=lambda item: (
                        -float(item[1]["maxCurveRange"]),
                        item[0],
                    ),
                )[:100]
            ),
        }
        print(
            "ABBY_C4D_MOCAP_TRACKS="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
