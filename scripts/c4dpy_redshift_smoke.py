"""Render a tiny generated Redshift scene to validate the local renderer."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


REDSHIFT_RENDERER_ID = 1036219


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()

    doc = c4d.documents.BaseDocument()
    sphere = c4d.BaseObject(c4d.Osphere)
    sphere[c4d.PRIM_SPHERE_RAD] = 100.0
    doc.InsertObject(sphere)
    material = c4d.BaseMaterial(c4d.Mmaterial)
    material.SetName("PARACOSM STANDARD MATERIAL TRANSLATION TEST")
    material[c4d.MATERIAL_COLOR_COLOR] = c4d.Vector(0.8, 0.03, 0.02)
    doc.InsertMaterial(material)
    material_tag = c4d.BaseTag(c4d.Ttexture)
    material_tag.SetMaterial(material)
    sphere.InsertTag(material_tag)
    light = c4d.BaseObject(c4d.Olight)
    light.SetAbsPos(c4d.Vector(250, 250, -250))
    light[c4d.LIGHT_BRIGHTNESS] = 2.0
    doc.InsertObject(light)
    camera = c4d.BaseObject(c4d.Ocamera)
    camera.SetAbsPos(c4d.Vector(0, 0, -500))
    doc.InsertObject(camera)
    doc.GetRenderBaseDraw().SetSceneCamera(camera)
    render_data = doc.GetActiveRenderData()
    settings = render_data.GetData().GetClone(
        getattr(c4d, "COPYFLAGS_NONE", 0)
    )
    settings[c4d.RDATA_RENDERENGINE] = REDSHIFT_RENDERER_ID
    settings[c4d.RDATA_XRES] = 360.0
    settings[c4d.RDATA_YRES] = 203.0
    settings[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
    settings[c4d.RDATA_SAVEIMAGE] = False
    bitmap = c4d.bitmaps.MultipassBitmap(360, 203, c4d.COLORMODE_RGB)
    bitmap.AddChannel(True, True)
    result = c4d.documents.RenderDocument(
        doc,
        settings,
        bitmap,
        c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
    )
    payload = {"renderResult": int(result), "output": str(output)}
    if result == c4d.RENDERRESULT_OK:
        output.parent.mkdir(parents=True, exist_ok=True)
        layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
        payload["saveResult"] = int(
            layer.Save(str(output), c4d.FILTER_PNG, c4d.BaseContainer())
        )
    print("PARACOSM_REDSHIFT_SMOKE_JSON=" + json.dumps(payload), flush=True)
    c4d.documents.KillDocument(doc)
    os._exit(0)


if __name__ == "__main__":
    main()
