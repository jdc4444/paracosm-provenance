"""Render and verify a saved Abby expression scene without modifying it."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


REDSHIFT_RENDERER_ID = 1036219
MARKER_NAME = "EXP_DELIGHTED_SIDE_GLANCE_V4__CODEX_20260729"
PROOF_CAMERA_NAME = "RS Camera - Delighted Side Glance V4 Proof"


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
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--marker", default=MARKER_NAME)
    parser.add_argument("--camera", default=PROOF_CAMERA_NAME)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")

    report = {
        "project": str(project),
        "output": str(output),
        "documentSaved": False,
        "marker": False,
        "camera": None,
        "poseKeyTracks": 0,
        "timeline": None,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        objects = list(walk_objects(doc.GetFirstObject()))
        report["marker"] = any(
            item.GetName() == args.marker for item in objects
        )
        camera = next(
            (
                item
                for item in objects
                if item.GetName() == args.camera
            ),
            None,
        )
        if camera is None:
            raise RuntimeError(f"Could not find {args.camera}")
        report["camera"] = camera.GetName()
        report["poseKeyTracks"] = sum(
            len(item.GetCTracks())
            for item in objects
            if (
                item.GetName().startswith("FACIAL_")
                or item.GetName() == "head"
            )
            and any(
                track.GetCurve() is not None
                and track.GetCurve().GetKeyCount() == 1
                for track in item.GetCTracks()
            )
        )
        report["timeline"] = {
            "fps": doc.GetFps(),
            "minFrame": doc.GetMinTime().GetFrame(doc.GetFps()),
            "maxFrame": doc.GetMaxTime().GetFrame(doc.GetFps()),
        }

        base_draw = doc.GetRenderBaseDraw()
        if base_draw is not None:
            base_draw.SetSceneCamera(camera)
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
        if hasattr(c4d, "RDATA_MULTIPASS_ENABLE"):
            settings[c4d.RDATA_MULTIPASS_ENABLE] = False

        bitmap = c4d.bitmaps.MultipassBitmap(
            args.width, args.height, c4d.COLORMODE_RGB
        )
        bitmap.AddChannel(True, True)
        render_flags = c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS
        render_flags |= getattr(c4d, "RENDERFLAGS_NODOCUMENTCLONE", 0)
        render_result = c4d.documents.RenderDocument(
            doc,
            settings,
            bitmap,
            render_flags,
        )
        report["renderResult"] = int(render_result)
        if render_result != c4d.RENDERRESULT_OK:
            raise RuntimeError(f"RenderDocument returned {render_result}")

        output.parent.mkdir(parents=True, exist_ok=True)
        layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
        save_result = layer.Save(
            str(output),
            c4d.FILTER_PNG,
            c4d.BaseContainer(),
        )
        report["saveResult"] = int(save_result)
        if save_result != c4d.IMAGERESULT_OK:
            raise RuntimeError(f"Bitmap save returned {save_result}")
        print(
            "ABBY_EXPRESSION_PROOF="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
