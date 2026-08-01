"""Build a disposable six-pose eyelid-axis calibration scene for Abby."""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import c4d


FPS = 25


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def path(op):
    result = []
    while op:
        result.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(result)


def desc(vector_parameter, component):
    return c4d.DescID(
        c4d.DescLevel(vector_parameter, c4d.DTYPE_VECTOR, 0),
        c4d.DescLevel(component, c4d.DTYPE_REAL, 0),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")

    doc = c4d.documents.LoadDocument(
        str(source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {source}")
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        doc.ExecutePasses(None, True, True, True, 0)
        objects = list(walk_objects(doc.GetFirstObject()))
        for item in objects:
            position = item.GetRelPos()
            rotation = item.GetRelRot()
            scale = item.GetRelScale()
            for track in list(item.GetCTracks()):
                track.Remove()
            item.SetRelPos(position)
            item.SetRelRot(rotation)
            item.SetRelScale(scale)

        controls = [
            item
            for item in objects
            if item.GetName()
            in {
                f"FACIAL_{side}_EyelidUpper{row}{index}"
                for side in ("L", "R")
                for row in ("A", "B")
                for index in (1, 2, 3)
            }
            and "root.002/" in path(item)
        ]
        if len(controls) != 12:
            raise RuntimeError(
                f"Expected twelve weighted upper eyelid joints, found {len(controls)}"
            )

        doc.SetFps(FPS)
        for control in controls:
            base = control.GetRelPos()
            base_components = {
                c4d.VECTOR_X: base.x,
                c4d.VECTOR_Y: base.y,
                c4d.VECTOR_Z: base.z,
            }
            offsets = {
                c4d.VECTOR_X: [0.0, 0.7, -0.7, 0.0, 0.0, 0.0, 0.0],
                c4d.VECTOR_Y: [0.0, 0.0, 0.0, 0.7, -0.7, 0.0, 0.0],
                c4d.VECTOR_Z: [0.0, 0.0, 0.0, 0.0, 0.0, 0.7, -0.7],
            }
            for component, values in offsets.items():
                track = c4d.CTrack(
                    control,
                    desc(c4d.ID_BASEOBJECT_REL_POSITION, component),
                )
                control.InsertTrackSorted(track)
                curve = track.GetCurve()
                for second, value in enumerate(values):
                    added = curve.AddKey(c4d.BaseTime(second * FPS, FPS))
                    key = added["key"]
                    key.SetValue(
                        curve,
                        base_components[component] + value,
                    )
                    key.SetInterpolation(curve, c4d.CINTERPOLATION_LINEAR)

        doc.SetMinTime(c4d.BaseTime(0, FPS))
        doc.SetMaxTime(c4d.BaseTime(150, FPS))
        doc.SetLoopMinTime(c4d.BaseTime(0, FPS))
        doc.SetLoopMaxTime(c4d.BaseTime(150, FPS))
        render_data = doc.GetActiveRenderData()
        render_data[c4d.RDATA_XRES] = 480.0
        render_data[c4d.RDATA_YRES] = 270.0
        render_data[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_ALLFRAMES
        )
        render_data[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(0, FPS)
        render_data[c4d.RDATA_FRAMETO] = c4d.BaseTime(150, FPS)
        output.parent.mkdir(parents=True, exist_ok=True)
        if not c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        ):
            raise RuntimeError(f"Could not save {output}")
        print(f"ABBY_EYELID_CALIBRATION={output}", flush=True)
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
