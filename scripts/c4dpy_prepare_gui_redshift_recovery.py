"""Prepare a non-destructive C4D copy for an exact GUI Redshift test render.

Run this script with the Cinema 4D version that should open/render the saved
copy. It selects the requested take and render settings, parks the document on
the requested frame, and saves a new project without touching the input file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_render_data, find_take


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frame", required=True, type=int)
    parser.add_argument("--take", required=True)
    parser.add_argument("--render-data", required=True)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=405)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = {
        "project": str(args.project),
        "output": str(args.output),
        "frame": args.frame,
        "take": args.take,
        "renderData": args.render_data,
        "saved": False,
    }
    doc = None
    try:
        if not args.project.is_file():
            raise FileNotFoundError(args.project)
        if args.output.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing recovery: {args.output}"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)

        flags = (
            c4d.SCENEFILTER_OBJECTS
            | c4d.SCENEFILTER_MATERIALS
            | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
        )
        doc = c4d.documents.LoadDocument(str(args.project), flags)
        if doc is None:
            raise RuntimeError("Cinema 4D LoadDocument returned None")

        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        take_data.SetCurrentTake(take)

        render_data = find_render_data(doc, args.render_data)
        if render_data is None:
            raise RuntimeError(f"Render data not found: {args.render_data}")
        doc.SetActiveRenderData(render_data)
        settings = render_data.GetData()
        settings[c4d.RDATA_XRES] = args.width
        settings[c4d.RDATA_YRES] = args.height
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        render_data.SetData(settings)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))

        saved = c4d.documents.SaveDocument(
            doc,
            str(args.output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report["saved"] = bool(saved)
        report["fps"] = doc.GetFps()
        report["activeTake"] = take_data.GetCurrentTake().GetName()
        report["activeRenderData"] = doc.GetActiveRenderData().GetName()
        report["timeFrame"] = doc.GetTime().GetFrame(doc.GetFps())
        report["resolution"] = [args.width, args.height]
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        print(
            "PARACOSM_GUI_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        if doc is not None:
            c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
