"""Render Abby's derived slide-7 facial loop from its embedded C4D driver."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


REDSHIFT_RENDERER_ID = 1036219
DRIVER_TAG_NAME = "Slide 7 Facial Animation Driver"


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def find_driver_tag(doc):
    for item in walk_objects(doc.GetFirstObject()):
        for tag in item.GetTags():
            if tag.GetName() == DRIVER_TAG_NAME and tag.GetType() == c4d.Tpython:
                return tag
    raise RuntimeError(f"Could not find {DRIVER_TAG_NAME}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=396)
    parser.add_argument("--step", type=int, default=2)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=270)
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

    report = {
        "project": str(project),
        "outputDir": str(output_dir),
        "frames": [],
        "saved": False,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        driver_tag = find_driver_tag(doc)
        namespace = {"doc": doc, "op": driver_tag}
        exec(driver_tag[c4d.TPYTHON_CODE], namespace)
        driver = namespace["main"]

        settings = doc.GetActiveRenderData().GetData().GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_SAVEIMAGE] = False
        output_dir.mkdir(parents=True, exist_ok=True)

        render_flags = c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS
        render_flags |= getattr(c4d, "RENDERFLAGS_NODOCUMENTCLONE", 0)
        fps = doc.GetFps()
        for frame in range(args.start, args.end + 1, args.step):
            doc.SetTime(c4d.BaseTime(frame, fps))
            doc.ExecutePasses(None, True, True, True, 0)
            driver()
            doc.ExecutePasses(None, False, False, True, 0)
            bitmap = c4d.bitmaps.MultipassBitmap(
                args.width, args.height, c4d.COLORMODE_RGB
            )
            bitmap.AddChannel(True, True)
            result = c4d.documents.RenderDocument(
                doc, settings, bitmap, render_flags
            )
            if result != c4d.RENDERRESULT_OK:
                raise RuntimeError(
                    f"RenderDocument returned {result} at frame {frame}"
                )
            output = output_dir / f"frame{frame:04d}.tif"
            layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
            save_result = layer.Save(
                str(output), c4d.FILTER_TIF, c4d.BaseContainer()
            )
            if save_result != c4d.IMAGERESULT_OK:
                raise RuntimeError(f"Bitmap save failed at frame {frame}")
            report["frames"].append(frame)
            print(
                "ABBY_SLIDE7_PREVIEW_FRAME="
                + json.dumps(
                    {
                        "frame": frame,
                        "completed": len(report["frames"]),
                        "total": len(
                            range(args.start, args.end + 1, args.step)
                        ),
                        "output": str(output),
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
        print(
            "ABBY_SLIDE7_PREVIEW="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
