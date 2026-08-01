"""Render one Cinema 4D hardware-viewport proof from an identified camera.

Run with Maxon's bundled c4dpy, not the system Python. The source document is
loaded read-only and never saved.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

import c4d


LEGACY_RS_CAMERA_OBJECT_ID = 1057516
LEGACY_RS_LIGHT_OBJECT_ID = 1036751


def bridge_legacy_redshift_camera(source_camera):
    """Build an in-memory native camera without losing legacy framing state."""
    native_camera = c4d.BaseObject(c4d.Ocamera)
    native_camera.SetName(source_camera.GetName())
    native_camera.SetMg(source_camera.GetMg())
    try:
        native_camera[c4d.CAMERA_FOCUS] = float(source_camera[500])
    except Exception:
        pass
    # Legacy Redshift cameras store their two-axis film shift in parameter
    # 7012. The hardware renderer cannot look through those camera objects
    # directly, so preserve the shift on the temporary native camera too.
    try:
        shift = source_camera[7012]
        if isinstance(shift, c4d.Vector):
            native_camera[c4d.CAMERAOBJECT_FILM_OFFSET_X] = float(shift.x)
            native_camera[c4d.CAMERAOBJECT_FILM_OFFSET_Y] = float(shift.y)
    except Exception:
        pass
    # The retired Redshift object exposes its projection through an obsolete
    # plugin container (14007), not the modern 1001 parameter. Reading 1001
    # emits a C4D container stop even when caught, so retain the native
    # perspective default. Non-perspective legacy cameras must be marked
    # unverified rather than silently translated.
    return native_camera


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    current = op
    while current:
        names.insert(0, current.GetName())
        current = current.GetUp()
    return "/".join(names)


def find_camera(doc, name: str, expected_path: str | None):
    cameras = [
        op
        for op in walk_objects(doc.GetFirstObject())
        if op.CheckType(c4d.Ocamera)
        or op.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
    ]
    if expected_path:
        camera = next(
            (item for item in cameras if object_path(item) == expected_path),
            None,
        )
        if camera:
            return camera
    return next((item for item in cameras if item.GetName() == name), None)


def find_active_base_draw_camera(doc, name: str | None = None):
    """Return the document's saved BaseDraw camera when explicitly requested.

    Cinema 4D can render through a saved editor camera that is not a scene
    object and therefore is absent from the object hierarchy.  This is distinct
    from the old permissive take-camera fallback: callers must explicitly opt
    in, and an expected name still has to match.
    """
    base_draw = doc.GetRenderBaseDraw()
    camera = base_draw.GetSceneCamera(doc) if base_draw is not None else None
    if (
        camera is None
        and base_draw is not None
        and hasattr(base_draw, "GetEditorCamera")
    ):
        camera = base_draw.GetEditorCamera()
    if camera is None:
        return None
    if name and camera.GetName() != name:
        return None
    return camera


def walk_takes(take):
    current = take
    while current:
        yield current
        child = current.GetDown()
        if child:
            yield from walk_takes(child)
        current = current.GetNext()


def find_take(take_data, name: str | None):
    if not take_data or not name:
        return None
    return next(
        (
            take
            for take in walk_takes(take_data.GetMainTake())
            if take.GetName() == name
        ),
        None,
    )


def find_render_data(doc, name: str | None):
    if not name:
        return None
    current = doc.GetFirstRenderData()
    while current:
        if current.GetName() == name:
            return current
        current = current.GetNext()
    return None


def effective_item(result):
    return result[0] if isinstance(result, tuple) else result


def clean_base_draw(base_draw) -> None:
    """Remove viewport guides and labels from hardware proof renders."""
    base_draw[c4d.BASEDRAW_DATA_SDISPLAYACTIVE] = (
        c4d.BASEDRAW_SDISPLAY_GOURAUD
    )
    base_draw[c4d.BASEDRAW_DATA_SDISPLAYINACTIVE] = (
        c4d.BASEDRAW_SDISPLAY_GOURAUD
    )
    base_draw[c4d.BASEDRAW_DATA_EDITOR_AXIS_POS] = (
        c4d.BASEDRAW_AXIS_POS_OFF
    )
    base_draw[c4d.BASEDRAW_DATA_EDIT_AXIS_SCALE] = 0.0
    base_draw[c4d.BASEDRAW_DATA_OBJECTAXIS_SCALE] = 0.0
    base_draw[c4d.BASEDRAW_DATA_EDIT_AXIS_TEXT] = False
    if hasattr(c4d, "BASEDRAW_INSTANTRENDER_WORLDAXIS"):
        base_draw[c4d.BASEDRAW_INSTANTRENDER_WORLDAXIS] = False
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
        c4d.BASEDRAW_DISPLAYFILTER_NULL,
        c4d.BASEDRAW_DISPLAYFILTER_NGONLINES,
        c4d.BASEDRAW_DISPLAYFILTER_OBJECTHANDLES,
        c4d.BASEDRAW_DISPLAYFILTER_OBJECTHIGHLIGHTING,
        c4d.BASEDRAW_DISPLAYFILTER_ONION,
        c4d.BASEDRAW_DISPLAYFILTER_OTHER,
        c4d.BASEDRAW_DISPLAYFILTER_PARTICLE,
        c4d.BASEDRAW_DISPLAYFILTER_POI,
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


def render_record(
    doc,
    take_data,
    base_draw,
    proof_light,
    record: dict,
    width: int,
    height: int,
) -> dict:
    started = time.time()
    temporary_camera = None
    temporary_dependency_relinks = []
    temporary_object_modes = []
    result = {
        "sourceId": record.get("sourceId"),
        "targetFrame": record.get("targetFrame"),
        "status": "failed",
    }
    try:
        take = find_take(take_data, record.get("cameraTake"))
        if take_data and take:
            take_data.SetCurrentTake(take)
        requested_relinks = {
            str(item["requiredPath"]): str(item["targetPath"])
            for item in record.get("exactDependencyRelinks") or []
            if item.get("requiredPath") and item.get("targetPath")
        }
        for scene_object in walk_objects(doc.GetFirstObject()):
            if scene_object.GetType() != 1028083:
                continue
            parameter = c4d.DescID(1000)
            current_value = str(scene_object[parameter])
            target_value = requested_relinks.get(current_value)
            if not target_value:
                continue
            temporary_dependency_relinks.append(
                (scene_object, parameter, scene_object[parameter])
            )
            filename_type = getattr(c4d, "Filename", None)
            scene_object[parameter] = (
                filename_type(target_value)
                if filename_type is not None
                else target_value
            )
            scene_object.Message(c4d.MSG_UPDATE)
        if temporary_dependency_relinks:
            c4d.EventAdd()
        result["temporaryExactDependencyRelinks"] = [
            {
                "objectPath": object_path(scene_object),
                "requiredPath": str(original_value),
                "targetPath": str(scene_object[parameter]),
            }
            for scene_object, parameter, original_value
            in temporary_dependency_relinks
        ]
        mode_values = {
            "on": c4d.MODE_ON,
            "off": c4d.MODE_OFF,
            "undefined": c4d.MODE_UNDEF,
        }
        requested_mode_overrides = record.get("objectModeOverrides") or []
        if requested_mode_overrides:
            scene_objects = list(walk_objects(doc.GetFirstObject()))
            top_level_objects = []
            top_level_object = doc.GetFirstObject()
            while top_level_object:
                top_level_objects.append(top_level_object)
                top_level_object = top_level_object.GetNext()
            for override in requested_mode_overrides:
                requested_guid = str(override.get("guid") or "")
                scene_object = next(
                    (
                        item
                        for item in scene_objects
                        if requested_guid
                        and str(item.GetGUID()) == requested_guid
                    ),
                    None,
                )
                requested_name = str(override.get("name") or "")
                requested_occurrence = int(override.get("occurrence") or 0)
                if scene_object is None and requested_name:
                    named_objects = [
                        item
                        for item in top_level_objects
                        if item.GetName() == requested_name
                    ]
                    if requested_occurrence < len(named_objects):
                        scene_object = named_objects[requested_occurrence]
                if scene_object is None:
                    raise RuntimeError(
                        "Object mode override target is absent from project: "
                        + str(
                            {
                                "guid": requested_guid or None,
                                "name": requested_name or None,
                                "occurrence": requested_occurrence,
                            }
                        )
                    )
                original_editor_mode = scene_object.GetEditorMode()
                original_render_mode = scene_object.GetRenderMode()
                editor_mode = mode_values.get(
                    str(override.get("editorMode") or "").casefold(),
                    original_editor_mode,
                )
                render_mode = mode_values.get(
                    str(override.get("renderMode") or "").casefold(),
                    original_render_mode,
                )
                temporary_object_modes.append(
                    (
                        scene_object,
                        original_editor_mode,
                        original_render_mode,
                    )
                )
                scene_object.SetEditorMode(editor_mode)
                scene_object.SetRenderMode(render_mode)
            c4d.EventAdd()
        result["temporaryObjectModeOverrides"] = [
            {
                "objectPath": object_path(scene_object),
                "guid": str(scene_object.GetGUID()),
                "editorMode": scene_object.GetEditorMode(),
                "renderMode": scene_object.GetRenderMode(),
            }
            for scene_object, _, _ in temporary_object_modes
        ]
        only_object_paths = set(record.get("onlyObjectPaths") or [])
        if only_object_paths:
            for scene_object in walk_objects(doc.GetFirstObject()):
                path = object_path(scene_object)
                keep = (
                    scene_object.CheckType(c4d.Ocamera)
                    or scene_object.CheckType(c4d.Olight)
                    or scene_object.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                    or any(
                        path == target
                        or path.startswith(target + "/")
                        or target.startswith(path + "/")
                        for target in only_object_paths
                    )
                )
                scene_object.SetEditorMode(
                    c4d.MODE_ON if keep else c4d.MODE_OFF
                )
                scene_object.SetRenderMode(
                    c4d.MODE_ON if keep else c4d.MODE_OFF
                )
        target_frame = int(record["targetFrame"])
        simulation_frames_stepped = 0
        simulation_start_frame = record.get("simulationStartFrame")
        if record.get("simulateFromStart") or simulation_start_frame is not None:
            start_frame = (
                int(simulation_start_frame)
                if simulation_start_frame is not None
                else doc.GetMinTime().GetFrame(doc.GetFps())
            )
            if start_frame > target_frame:
                raise RuntimeError(
                    "simulationStartFrame cannot exceed targetFrame"
                )
            frame_step = max(1, int(record.get("simulationFrameStep") or 1))
            simulation_build_flags = int(
                record.get("simulationBuildFlags")
                or c4d.BUILDFLAGS_EXTERNALRENDERER
            )
            frames = list(range(start_frame, target_frame + 1, frame_step))
            if not frames or frames[-1] != target_frame:
                frames.append(target_frame)
            for frame in frames:
                doc.SetTime(c4d.BaseTime(frame, doc.GetFps()))
                doc.ExecutePasses(
                    None,
                    True,
                    True,
                    True,
                    simulation_build_flags,
                )
                simulation_frames_stepped += 1
        else:
            doc.SetTime(c4d.BaseTime(target_frame, doc.GetFps()))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
        # A shot-specific camera selection must win over the take's effective
        # camera. Previously every request carrying cameraTake="Main" silently
        # rendered the same take camera, which produced plausible-looking but
        # false proof images for legacy Redshift camera scenes.
        force_reconstructed_camera = bool(
            record.get("forceReconstructedCamera")
        )
        camera = (
            None
            if force_reconstructed_camera
            else find_camera(
                doc,
                str(record.get("cameraName") or ""),
                (record.get("cameraObject") or {}).get("objectPath"),
            )
        )
        if camera is None and record.get("useActiveBaseDrawCamera"):
            camera = find_active_base_draw_camera(
                doc, str(record.get("cameraName") or "") or None
            )
        reconstructed_camera = False
        fallback_to_take_camera = False
        source_camera_path = object_path(camera) if camera is not None else None
        if (
            camera is None
            and not force_reconstructed_camera
            and take_data
            and take
        ):
            camera = effective_item(take.GetEffectiveCamera(take_data))
            fallback_to_take_camera = camera is not None
            source_camera_path = (
                object_path(camera) if camera is not None else None
            )
        if camera is None:
            archived = record.get("cameraObject") or {}
            position = archived.get("position") or {}
            rotation = archived.get("rotationRadians") or {}
            rotation_degrees = archived.get("rotationDegrees") or {}
            if not all(axis in rotation for axis in ("x", "y", "z")) and all(
                axis in rotation_degrees for axis in ("x", "y", "z")
            ):
                rotation = {
                    axis: math.radians(float(rotation_degrees[axis]))
                    for axis in ("x", "y", "z")
                }
            if all(axis in position for axis in ("x", "y", "z")) and all(
                axis in rotation for axis in ("x", "y", "z")
            ):
                camera = c4d.BaseObject(c4d.Ocamera)
                camera.SetName(
                    str(record.get("cameraName") or "Archived Camera")
                )
                camera.SetAbsPos(
                    c4d.Vector(
                        float(position["x"]),
                        float(position["y"]),
                        float(position["z"]),
                    )
                )
                camera.SetAbsRot(
                    c4d.Vector(
                        float(rotation["x"]),
                        float(rotation["y"]),
                        float(rotation["z"]),
                    )
                )
                aperture = float(archived.get("aperture") or 36.0)
                camera[c4d.CAMERAOBJECT_APERTURE] = aperture
                focal_length = archived.get("focalLength")
                if (
                    focal_length is None
                    and archived.get("fieldOfViewDegrees") is not None
                ):
                    field_of_view = math.radians(
                        float(archived["fieldOfViewDegrees"])
                    )
                    focal_length = aperture / (
                        2.0 * math.tan(field_of_view / 2.0)
                    )
                if focal_length is not None:
                    camera[c4d.CAMERA_FOCUS] = float(focal_length)
                doc.InsertObject(camera)
                temporary_camera = camera
                reconstructed_camera = True
                source_camera_path = str(
                    archived.get("objectPath")
                    or record.get("cameraName")
                    or ""
                )
        if camera is None:
            raise RuntimeError("Identified camera is absent from the project")
        if camera.GetType() == LEGACY_RS_CAMERA_OBJECT_ID:
            # Hardware Preview cannot use the legacy Redshift camera object's
            # projection model directly. Rebuild a temporary native camera
            # from its evaluated transform and Redshift focal length (ID 500).
            # This changes only the in-memory helper document.
            source_camera = camera
            native_camera = bridge_legacy_redshift_camera(source_camera)
            doc.InsertObject(native_camera)
            camera = native_camera
            temporary_camera = native_camera
            reconstructed_camera = True
        # Hardware Preview can otherwise burn the selected object's transform
        # gizmo into the proof bitmap. Clear document/object selection after
        # resolving the camera; the requested camera remains assigned directly
        # to the BaseDraw and the source document is never saved.
        try:
            doc.SetActiveObject(None)
        except Exception:
            pass
        for scene_object in walk_objects(doc.GetFirstObject()):
            scene_object.DelBit(c4d.BIT_ACTIVE)
            if scene_object is proof_light:
                continue
            if (
                scene_object.CheckType(c4d.Ocamera)
                or scene_object.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
                or scene_object.CheckType(c4d.Olight)
                or scene_object.GetType() == LEGACY_RS_LIGHT_OBJECT_ID
                or scene_object.GetRenderMode() == c4d.MODE_OFF
                or (
                    scene_object.GetDown() is None
                    and scene_object.GetCache() is None
                    and scene_object.GetDeformCache() is None
                    and not isinstance(scene_object, c4d.PolygonObject)
                    and not (
                        scene_object.GetInfo()
                        & getattr(c4d, "OBJECT_GENERATOR", 0)
                    )
                )
            ):
                scene_object.SetEditorMode(c4d.MODE_OFF)
        base_draw.SetSceneCamera(camera)
        clean_base_draw(base_draw)
        proof_light.SetAbsPos(camera.GetMg().off)
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        render_data = find_render_data(
            doc, record.get("cameraRenderData")
        )
        if render_data is None and take_data and take:
            render_data = effective_item(take.GetEffectiveRenderData(take_data))
        if render_data is None:
            render_data = doc.GetActiveRenderData()
        if render_data is None:
            raise RuntimeError("Document has no render data")
        settings = render_data.GetData().GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        settings[c4d.RDATA_RENDERENGINE] = (
            c4d.RDATA_RENDERENGINE_PREVIEWHARDWARE
        )
        settings[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        settings[c4d.RDATA_FRAMEFROM] = doc.GetTime()
        settings[c4d.RDATA_FRAMETO] = doc.GetTime()
        settings[c4d.RDATA_XRES] = float(width)
        settings[c4d.RDATA_YRES] = float(height)
        settings[c4d.VP_PREVIEWHARDWARE_ENHANCEDOPENGL] = True
        settings[c4d.VP_PREVIEWHARDWARE_ONLY_GEOMETRY] = True
        settings[c4d.VP_PREVIEWHARDWARE_GEOMETRY_ONLY] = True
        settings[c4d.VP_PREVIEWHARDWARE_SHADOW] = False
        settings[c4d.VP_PREVIEWHARDWARE_POSTEFFECT] = False
        settings[c4d.VP_PREVIEWHARDWARE_TRANSPARENCY] = False
        # Hardware Preview has its own display-filter container; BaseDraw
        # filters alone do not prevent axes, light outlines, camera frusta,
        # splines, or helper guides from being burned into the saved bitmap.
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
            width, height, c4d.COLORMODE_RGB
        )
        if bitmap is None:
            raise RuntimeError("Could not initialize proof bitmap")
        bitmap.AddChannel(True, True)
        render_result = c4d.documents.RenderDocument(
            doc,
            settings,
            bitmap,
            c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS,
        )
        if render_result != c4d.RENDERRESULT_OK:
            render_error_names = {
                c4d.RENDERRESULT_OUTOFMEMORY: "out_of_memory",
                c4d.RENDERRESULT_ASSETMISSING: "asset_missing",
                c4d.RENDERRESULT_FAILED: "failed",
                c4d.RENDERRESULT_UNAVAILABLE: "unavailable",
            }
            raise RuntimeError(
                "RenderDocument returned result "
                f"{render_result} "
                f"({render_error_names.get(render_result, 'unknown')})"
            )
        layer_count = bitmap.GetLayerCount()
        save_bitmap = (
            bitmap.GetLayerNum(0) if layer_count > 0 else bitmap
        )
        output = Path(record["outputPath"]).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        save_result = save_bitmap.Save(
            str(output), c4d.FILTER_PNG, c4d.BaseContainer()
        )
        if save_result != c4d.IMAGERESULT_OK:
            raise RuntimeError(
                f"Bitmap save returned result {save_result}"
            )
        evaluated_matrix = camera.GetMg()
        evaluated_rotation = c4d.utils.MatrixToHPB(evaluated_matrix)
        result.update(
            {
                "status": "rendered",
                "outputPath": str(output),
                "cameraName": camera.GetName(),
                "cameraObjectPath": source_camera_path or object_path(camera),
                "cameraGuid": str(camera.GetGUID()),
                "cameraTake": take.GetName() if take else None,
                "cameraRenderData": render_data.GetName(),
                "cameraReconstructedFromArchive": reconstructed_camera,
                "cameraFallbackToTake": fallback_to_take_camera,
                "cameraAnimationRetained": not reconstructed_camera,
                "simulationStartFrame": (
                    int(simulation_start_frame)
                    if simulation_start_frame is not None
                    else (
                        doc.GetMinTime().GetFrame(doc.GetFps())
                        if record.get("simulateFromStart")
                        else None
                    )
                ),
                "simulationFramesStepped": simulation_frames_stepped,
                "evaluatedCamera": {
                    "position": {
                        "x": evaluated_matrix.off.x,
                        "y": evaluated_matrix.off.y,
                        "z": evaluated_matrix.off.z,
                    },
                    "rotationRadians": {
                        "x": evaluated_rotation.x,
                        "y": evaluated_rotation.y,
                        "z": evaluated_rotation.z,
                    },
                    "focalLength": float(camera[c4d.CAMERA_FOCUS]),
                },
                "requestedCameraName": record.get("cameraName"),
                "requestedCameraObjectPath": (
                    record.get("cameraObject") or {}
                ).get("objectPath"),
                "renderer": "Cinema 4D Hardware Preview",
                "rendererId": c4d.RDATA_RENDERENGINE_PREVIEWHARDWARE,
                "documentFps": doc.GetFps(),
                "documentMinFrame": doc.GetMinTime().GetFrame(doc.GetFps()),
                "documentMaxFrame": doc.GetMaxTime().GetFrame(doc.GetFps()),
                "width": width,
                "height": height,
                "multipassLayerCount": layer_count,
                "onlyObjectPaths": sorted(only_object_paths),
            }
        )
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    if temporary_camera is not None:
        temporary_camera.Remove()
    for scene_object, editor_mode, render_mode in temporary_object_modes:
        scene_object.SetEditorMode(editor_mode)
        scene_object.SetRenderMode(render_mode)
    for scene_object, parameter, original_value in temporary_dependency_relinks:
        scene_object[parameter] = original_value
        scene_object.Message(c4d.MSG_UPDATE)
    result["renderSeconds"] = round(time.time() - started, 3)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--batch-json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--frame", type=int)
    parser.add_argument("--camera")
    parser.add_argument("--camera-path")
    parser.add_argument("--take")
    parser.add_argument("--only-object-path", action="append", default=[])
    parser.add_argument("--simulate-from-start", action="store_true")
    parser.add_argument("--simulation-frame-step", type=int, default=1)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=270)
    parser.add_argument("--proof-gray", type=float, default=0.72)
    parser.add_argument("--proof-light-brightness", type=float, default=1.5)
    args = parser.parse_args()
    if not 0.0 <= args.proof_gray <= 1.0:
        parser.error("--proof-gray must be between 0 and 1")
    if args.proof_light_brightness < 0.0:
        parser.error("--proof-light-brightness cannot be negative")

    project = args.project.expanduser().resolve()
    if not project.exists():
        raise FileNotFoundError(project)
    if args.batch_json:
        records = json.loads(
            args.batch_json.expanduser().resolve().read_text(encoding="utf-8")
        )
    else:
        if args.output is None or args.frame is None or not args.camera:
            parser.error(
                "--output, --frame, and --camera are required without "
                "--batch-json"
            )
        records = [
            {
                "sourceId": "single",
                "outputPath": str(args.output.expanduser().resolve()),
                "targetFrame": args.frame,
                "cameraName": args.camera,
                "cameraTake": args.take,
                "onlyObjectPaths": args.only_object_path,
                "simulateFromStart": args.simulate_from_start,
                "simulationFrameStep": args.simulation_frame_step,
                "cameraObject": {"objectPath": args.camera_path},
            }
        ]

    load_flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), load_flags)
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {project}")
    try:
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        clean_base_draw(base_draw)
        for scene_object in walk_objects(doc.GetFirstObject()):
            scene_object.DelBit(c4d.BIT_ACTIVE)
            if scene_object.CheckType(c4d.Olight):
                scene_object[c4d.LIGHT_BRIGHTNESS] = 0.0
            else:
                scene_object[c4d.ID_BASEOBJECT_USECOLOR] = (
                    c4d.ID_BASEOBJECT_USECOLOR_ALWAYS
                )
                scene_object[c4d.ID_BASEOBJECT_COLOR] = c4d.Vector(
                    args.proof_gray,
                    args.proof_gray,
                    args.proof_gray,
                )
        proof_light = c4d.BaseObject(c4d.Olight)
        proof_light.SetName("PARACOSM_CAMERA_PROOF_LIGHT")
        proof_light[c4d.LIGHT_TYPE] = c4d.LIGHT_TYPE_OMNI
        proof_light[c4d.LIGHT_COLOR] = c4d.Vector(1.0, 1.0, 1.0)
        proof_light[c4d.LIGHT_BRIGHTNESS] = (
            args.proof_light_brightness
        )
        proof_light[c4d.LIGHT_SHADOWTYPE] = 0
        doc.InsertObject(proof_light)
        results = [
            render_record(
                doc,
                take_data,
                base_draw,
                proof_light,
                record,
                args.width,
                args.height,
            )
            for record in records
        ]
        print(
            "PARACOSM_C4DPY_PROOFS_JSON="
            + json.dumps(results, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
    # Some Redshift-era documents leave plugin worker threads alive after the
    # proof marker is emitted. The helper is an isolated read-only subprocess,
    # so exit explicitly once the document is killed.
    os._exit(0)


if __name__ == "__main__":
    main()
