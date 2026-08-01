"""Probe whether c4dpy RenderDocument can invoke Cinema's native writer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import c4d


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--result-json", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    result_path = args.result_json.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = c4d.documents.BaseDocument()
    render_data = doc.GetActiveRenderData()
    settings = render_data.GetDataInstance()
    settings[c4d.RDATA_RENDERENGINE] = c4d.RDATA_RENDERENGINE_STANDARD
    settings[c4d.RDATA_XRES] = 16.0
    settings[c4d.RDATA_YRES] = 16.0
    settings[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
    settings[c4d.RDATA_PATH] = str(output)
    settings[c4d.RDATA_SAVEIMAGE] = True
    settings[c4d.RDATA_FORMAT] = c4d.FILTER_PNG
    settings[c4d.RDATA_FORMATDEPTH] = c4d.RDATA_FORMATDEPTH_8

    background = c4d.BaseObject(c4d.Obackground)
    doc.InsertObject(background)
    material = c4d.BaseMaterial(c4d.Mmaterial)
    material[c4d.MATERIAL_USE_COLOR] = True
    material[c4d.MATERIAL_COLOR_COLOR] = c4d.Vector(0.25, 0.5, 0.75)
    doc.InsertMaterial(material)
    tag = background.MakeTag(c4d.Ttexture)
    tag[c4d.TEXTURETAG_MATERIAL] = material

    bitmap = c4d.bitmaps.MultipassBitmap(16, 16, c4d.COLORMODE_RGB)
    bitmap.AddChannel(True, True)
    events: list[dict[str, object]] = []

    def write_progress(
        mode,
        written_bitmap,
        filename,
        main_image,
        write_frame,
        render_time,
        stream_number,
        stream_name,
    ):
        events.append(
            {
                "mode": int(mode),
                "filename": str(filename),
                "mainImage": bool(main_image),
                "frame": int(write_frame),
            }
        )

    code = c4d.documents.RenderDocument(
        doc,
        settings,
        bitmap,
        c4d.RENDERFLAGS_EXTERNAL
        | c4d.RENDERFLAGS_BATCHRENDER
        | c4d.RENDERFLAGS_NODOCUMENTCLONE,
        wprog=write_progress,
    )
    candidates = sorted(
        str(item.resolve())
        for item in output.parent.glob(output.name + "*")
        if item.is_file()
    )
    report = {
        "renderResult": int(code),
        "writeEvents": events,
        "outputCandidates": candidates,
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
