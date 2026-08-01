"""Render Abby's canonical Cinema 4D material study at high resolution.

The C4D source document is loaded read-only. Render settings are cloned and
overridden in memory so the original project remains untouched.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


LEGACY_RS_CAMERA_OBJECT_ID = 1057516
LEGACY_RS_LIGHT_OBJECT_ID = 1036751


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def bridge_legacy_redshift_camera(source_camera):
    camera = c4d.BaseObject(c4d.Ocamera)
    camera.SetName("ABBY_AVATAR_GUIDE_CAMERA")
    camera.SetMg(source_camera.GetMg())
    try:
        camera[c4d.CAMERA_FOCUS] = float(source_camera[500])
    except Exception:
        camera[c4d.CAMERA_FOCUS] = 35.0
    try:
        shift = source_camera[7012]
        if isinstance(shift, c4d.Vector):
            camera[c4d.CAMERAOBJECT_FILM_OFFSET_X] = float(shift.x)
            camera[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = float(shift.y)
    except Exception:
        pass
    return camera


def clean_base_draw(base_draw) -> None:
    base_draw[c4d.BASEDRAW_DATA_SDISPLAYACTIVE] = (
        c4d.BASEDRAW_SDISPLAY_GOURAUD
    )
    base_draw[c4d.BASEDRAW_DATA_SDISPLAYINACTIVE] = (
        c4d.BASEDRAW_SDISPLAY_GOURAUD
    )
    base_draw[c4d.BASEDRAW_DATA_EDITOR_AXIS_POS] = c4d.BASEDRAW_AXIS_POS_OFF
    base_draw[c4d.BASEDRAW_DATA_EDIT_AXIS_SCALE] = 0.0
    base_draw[c4d.BASEDRAW_DATA_OBJECTAXIS_SCALE] = 0.0
    base_draw[c4d.BASEDRAW_DATA_EDIT_AXIS_TEXT] = False
    for setting in (
        c4d.BASEDRAW_DATA_SHOWSAFEFRAME,
        c4d.BASEDRAW_DATA_RENDERSAFE,
        c4d.BASEDRAW_DATA_TITLESAFE,
        c4d.BASEDRAW_DATA_ACTIONSAFE,
    ):
        base_draw[setting] = False
    for display_filter in (
        c4d.BASEDRAW_DISPLAYFILTER_BASEGRID,
        c4d.BASEDRAW_DISPLAYFILTER_CAMERA,
        c4d.BASEDRAW_DISPLAYFILTER_DEFORMER,
        c4d.BASEDRAW_DISPLAYFILTER_FIELD,
        c4d.BASEDRAW_DISPLAYFILTER_GENERATOR,
        c4d.BASEDRAW_DISPLAYFILTER_GRADIENT,
        c4d.BASEDRAW_DISPLAYFILTER_GRID,
        c4d.BASEDRAW_DISPLAYFILTER_GUIDELINES,
        c4d.BASEDRAW_DISPLAYFILTER_HANDLEBANDS,
        c4d.BASEDRAW_DISPLAYFILTER_HANDLES,
        c4d.BASEDRAW_DISPLAYFILTER_HIGHLIGHTING,
        c4d.BASEDRAW_DISPLAYFILTER_HIGHLIGHTING_HANDLES,
        c4d.BASEDRAW_DISPLAYFILTER_HORIZON,
        c4d.BASEDRAW_DISPLAYFILTER_HUD,
        c4d.BASEDRAW_DISPLAYFILTER_JOINT,
        c4d.BASEDRAW_DISPLAYFILTER_LIGHT,
        c4d.BASEDRAW_DISPLAYFILTER_MULTIAXIS,
        c4d.BASEDRAW_DISPLAYFILTER_NGONLINES,
        c4d.BASEDRAW_DISPLAYFILTER_NULL,
        c4d.BASEDRAW_DISPLAYFILTER_OBJECTHANDLES,
        c4d.BASEDRAW_DISPLAYFILTER_ONION,
        c4d.BASEDRAW_DISPLAYFILTER_OTHER,
        c4d.BASEDRAW_DISPLAYFILTER_PARTICLE,
        c4d.BASEDRAW_DISPLAYFILTER_SDSCAGE,
        c4d.BASEDRAW_DISPLAYFILTER_SPLINE,
        c4d.BASEDRAW_DISPLAYFILTER_WORLDAXIS,
    ):
        base_draw[display_filter] = False
    for hud_setting in (
        c4d.BASEDRAW_HUD_FPS,
        c4d.BASEDRAW_HUD_FRAMETIME,
        c4d.BASEDRAW_HUD_CAMERADISTANCE,
        c4d.BASEDRAW_HUD_FRAME,
        c4d.BASEDRAW_HUD_OBJECTS,
        c4d.BASEDRAW_HUD_CAMERA_NAME,
        c4d.BASEDRAW_HUD_PROJECTION_NAME,
        c4d.BASEDRAW_HUD_ROOT_OBJECT,
        c4d.BASEDRAW_HUD_PARENT_OBJECT,
        c4d.BASEDRAW_HUD_ACTIVE_OBJECT,
        c4d.BASEDRAW_HUD_SELECTED,
        c4d.BASEDRAW_HUD_SELECTED_OBJECTS,
        c4d.BASEDRAW_HUD_SELECTED_POINTS,
        c4d.BASEDRAW_HUD_SELECTED_EDGES,
        c4d.BASEDRAW_HUD_SELECTED_POLYGONS,
        c4d.BASEDRAW_HUD_SELECTED_NGONS,
        c4d.BASEDRAW_HUD_TOOL,
        c4d.BASEDRAW_HUD_DRAW_STATISTICS,
        c4d.BASEDRAW_HUD_SCULPT_STATISTICS,
        c4d.BASEDRAW_HUD_WORKPLANE_STATISTICS,
        c4d.BASEDRAW_HUD_TAKE,
        c4d.BASEDRAW_HUD_RENDERSETTINGS,
        c4d.BASEDRAW_HUD_TIMELINE_MARKERS,
        c4d.BASEDRAW_HUD_VIEW_COLORSPACE,
    ):
        base_draw[hud_setting] = False


def diagnostic_color(name: str) -> c4d.Vector:
    lowered = name.casefold()
    if "hair" in lowered:
        return c4d.Vector(0.22, 0.035, 0.018)
    if "lash" in lowered:
        return c4d.Vector(0.018, 0.01, 0.01)
    if "eye" in lowered or "sclera" in lowered:
        return c4d.Vector(0.62, 0.56, 0.46)
    if "garment" in lowered or "cloth" in lowered or "outfit" in lowered:
        return c4d.Vector(0.16, 0.028, 0.045)
    if "shoe" in lowered:
        return c4d.Vector(0.07, 0.02, 0.016)
    return c4d.Vector(0.46, 0.19, 0.11)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--frame", type=int, default=0)
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

    payload = {
        "project": str(project),
        "output": str(output),
        "width": args.width,
        "height": args.height,
        "frame": args.frame,
    }
    succeeded = False
    try:
        c4d.documents.SetActiveDocument(doc)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        cameras = [
            item
            for item in walk_objects(doc.GetFirstObject())
            if item.CheckType(c4d.Ocamera)
            or item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
        ]
        camera = next(
            (item for item in cameras if item.GetName() == "RS Camera"),
            cameras[0] if cameras else None,
        )
        if camera is None:
            raise RuntimeError("The C4D material study has no camera")

        if camera.GetType() == LEGACY_RS_CAMERA_OBJECT_ID:
            camera = bridge_legacy_redshift_camera(camera)
            doc.InsertObject(camera)

        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("The C4D material study has no render view")
        base_draw.SetSceneCamera(camera)
        clean_base_draw(base_draw)
        for scene_object in walk_objects(doc.GetFirstObject()):
            scene_object.DelBit(c4d.BIT_ACTIVE)
            if scene_object is camera:
                continue
            if (
                scene_object.CheckType(c4d.Ocamera)
                or scene_object.CheckType(c4d.Olight)
                or scene_object.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                or scene_object.GetType() == LEGACY_RS_LIGHT_OBJECT_ID
            ):
                scene_object.SetEditorMode(c4d.MODE_OFF)
                scene_object.SetRenderMode(c4d.MODE_OFF)
                continue
            scene_object[c4d.ID_BASEOBJECT_USECOLOR] = (
                c4d.ID_BASEOBJECT_USECOLOR_ALWAYS
            )
            scene_object[c4d.ID_BASEOBJECT_COLOR] = diagnostic_color(
                scene_object.GetName()
            )
        proof_light = c4d.BaseObject(c4d.Olight)
        proof_light.SetName("ABBY_AVATAR_GUIDE_LIGHT")
        proof_light.SetAbsPos(camera.GetMg().off + c4d.Vector(-45, 25, -10))
        proof_light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        proof_light[c4d.LIGHT_BRIGHTNESS] = 1.35
        proof_light[c4d.LIGHT_SHADOWTYPE] = 0
        doc.InsertObject(proof_light)
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )

        render_data = doc.GetActiveRenderData()
        settings = render_data.GetData().GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_FRAMEFROM] = doc.GetTime()
        settings[c4d.RDATA_FRAMETO] = doc.GetTime()
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        # The archived Redshift graph crashes before returning in current
        # c4dpy. Use Cinema 4D's native high-resolution hardware renderer for
        # a deterministic material/geometry inspection without altering the
        # project or silently translating its shader graph.
        settings[c4d.RDATA_RENDERENGINE] = (
            c4d.RDATA_RENDERENGINE_PREVIEWHARDWARE
        )
        settings[c4d.VP_PREVIEWHARDWARE_ENHANCEDOPENGL] = True
        settings[c4d.VP_PREVIEWHARDWARE_ONLY_GEOMETRY] = True
        settings[c4d.VP_PREVIEWHARDWARE_GEOMETRY_ONLY] = True
        settings[c4d.VP_PREVIEWHARDWARE_SHADOW] = False
        settings[c4d.VP_PREVIEWHARDWARE_POSTEFFECT] = False
        settings[c4d.VP_PREVIEWHARDWARE_TRANSPARENCY] = False
        for display_filter in (
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_BASEGRID,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_CAMERA,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_DEFORMER,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_FIELD,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_GRID,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_GROUP,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_GUIDELINES,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_HANDLES,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_HORIZON,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_HUD,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_JOINT,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_LIGHT,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_MULTIAXIS,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_NGONLINES,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_NULL,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_OBJECTHANDLES,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_ONION,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_OTHER,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_PARTICLE,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_SDSCAGE,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_SPLINE,
            c4d.VP_PREVIEWHARDWARE_DISPLAYFILTER_WORLDAXIS,
        ):
            settings[display_filter] = False
        if hasattr(c4d, "RDATA_SAVEIMAGE"):
            settings[c4d.RDATA_SAVEIMAGE] = False
        if hasattr(c4d, "RDATA_MULTIPASS_ENABLE"):
            settings[c4d.RDATA_MULTIPASS_ENABLE] = False

        bitmap = c4d.bitmaps.MultipassBitmap(
            args.width, args.height, c4d.COLORMODE_RGB
        )
        bitmap.AddChannel(True, True)
        render_result = c4d.documents.RenderDocument(
            doc,
            settings,
            bitmap,
            c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
        )
        payload["renderResult"] = int(render_result)
        payload["camera"] = camera.GetName()
        payload["rendererId"] = int(settings[c4d.RDATA_RENDERENGINE])
        if render_result != c4d.RENDERRESULT_OK:
            raise RuntimeError(f"RenderDocument returned {render_result}")

        output.parent.mkdir(parents=True, exist_ok=True)
        save_bitmap = (
            bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
        )
        save_result = save_bitmap.Save(
            str(output), c4d.FILTER_PNG, c4d.BaseContainer()
        )
        payload["saveResult"] = int(save_result)
        if save_result != c4d.IMAGERESULT_OK:
            raise RuntimeError(f"Bitmap save returned {save_result}")
        print(
            "ABBY_C4D_AVATAR_GUIDE_RENDERED="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
        succeeded = True
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"
        print(
            "ABBY_C4D_AVATAR_GUIDE_FAILED="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
    os._exit(0 if succeeded else 1)


if __name__ == "__main__":
    main()
