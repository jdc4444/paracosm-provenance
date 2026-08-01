"""Render in-memory eyelid translation poses from the repaired Abby 1:1 scene."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


REDSHIFT_RENDERER_ID = 1036219


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    result = []
    while op:
        result.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    report = {"project": str(project), "saved": False, "renders": []}
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        doc.ExecutePasses(None, True, True, True, 0)
        names = {
            f"FACIAL_{side}_EyelidUpper{row}{index}"
            for side in ("L", "R")
            for row in ("A", "B")
            for index in (1, 2, 3)
        }
        controls = [
            item
            for item in walk_objects(doc.GetFirstObject())
            if item.GetName() in names and "root.002/" in object_path(item)
        ]
        if len(controls) != 12:
            raise RuntimeError(f"Expected 12 weighted eyelid joints, found {len(controls)}")
        bases = {item: item.GetRelPos() for item in controls}
        poses = (
            ("00_neutral", None, 0.0),
            ("01_x_plus", "x", 0.7),
            ("02_x_minus", "x", -0.7),
            ("03_y_plus", "y", 0.7),
            ("04_y_minus", "y", -0.7),
            ("05_z_plus", "z", 0.7),
            ("06_z_minus", "z", -0.7),
        )
        render_data = doc.GetActiveRenderData()
        settings = render_data.GetData().GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
        settings[c4d.RDATA_XRES] = 320.0
        settings[c4d.RDATA_YRES] = 180.0
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_SAVEIMAGE] = False
        output_dir.mkdir(parents=True, exist_ok=True)
        for label, component, offset in poses:
            for item, base in bases.items():
                position = c4d.Vector(base)
                if component:
                    setattr(position, component, getattr(position, component) + offset)
                item.SetRelPos(position)
                item.Message(c4d.MSG_UPDATE)
            doc.ExecutePasses(None, True, True, True, 0)
            c4d.EventAdd()
            bitmap = c4d.bitmaps.MultipassBitmap(
                320, 180, c4d.COLORMODE_RGB
            )
            bitmap.AddChannel(True, True)
            result = c4d.documents.RenderDocument(
                doc,
                settings,
                bitmap,
                c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
            )
            if result != c4d.RENDERRESULT_OK:
                raise RuntimeError(f"RenderDocument returned {result} for {label}")
            output = output_dir / f"{label}.png"
            layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
            save_result = layer.Save(
                str(output), c4d.FILTER_PNG, c4d.BaseContainer()
            )
            if save_result != c4d.IMAGERESULT_OK:
                raise RuntimeError(f"Bitmap save failed for {label}")
            report["renders"].append(str(output))
        print(
            "ABBY_WEIGHTED_EYELID_CALIBRATION="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
