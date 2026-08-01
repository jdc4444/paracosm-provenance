"""Create Abby's reusable Delighted Side Glance pose in Cinema 4D.

The facial-mocap source is opened read-only. Its evaluated frame-zero facial
state is frozen, the selected hand-authored expression is applied, and a
separate one-frame C4D document is saved. The source and material master are
never overwritten.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import c4d


MARKER_NAME = "EXP_DELIGHTED_SIDE_GLANCE_V13__CODEX_20260730"
PROOF_CAMERA_NAME = "RS Camera - Delighted Side Glance V13 Friendly"
LEGACY_RS_CAMERA_OBJECT_ID = 1057516
FPS = 30
LOOKMATCH_FOCAL = 74.62
LOOKMATCH_SENSOR_SCALE = 1.04
LOOKMATCH_TARGET = c4d.Vector(-2.98, 149.26, -2.25)
HAIR_MATERIAL_NAME = "Clay_Hair"
HAIR_OBJECT_PATH = (
    "root.002/pelvis/spine_01/spine_02/spine_03/spine_04/spine_05/"
    "neck_01/neck_02/head/FACIAL_C_FacialRoot/Hair"
)

POSE = {
    "eyeXLeft": 18.0,
    "eyeXRight": 18.0,
    "eyeY": -9.0,
    "jaw": 9.75,
    "chinUp": 0.3,
    "teethUpperY": 0.4,
    "lowerLip": 3.2,
    "upperY": 0.29,
    "corners": -6.0,
    "cornerUp": 0.46,
    "cornerOut": 0.30,
    "cheekUp": 0.30,
    "lowerLidUp": 0.09,
    "upperLidUp": 0.10,
    "foreheadUp": 0.10,
    "headX": 7.0,
}


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def find_control(doc, name: str):
    matches = [
        item
        for item in walk_objects(doc.GetFirstObject())
        if item.GetName() == name and "root.002/" in object_path(item)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one root.002 control named {name}; "
            f"found {[object_path(item) for item in matches]}"
        )
    return matches[0]


def find_object_path(doc, path: str):
    return next(
        (
            item
            for item in walk_objects(doc.GetFirstObject())
            if object_path(item) == path
        ),
        None,
    )


def find_material(doc, name: str):
    material = doc.GetFirstMaterial()
    while material:
        if material.GetName() == name:
            return material
        material = material.GetNext()
    return None


def restore_lookmatch_hair(doc, hair_source: Path) -> dict:
    source_doc = c4d.documents.LoadDocument(
        str(hair_source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if source_doc is None:
        raise RuntimeError(f"Cinema 4D could not load hair source {hair_source}")
    try:
        source_hair = find_object_path(source_doc, HAIR_OBJECT_PATH)
        target_hair = find_object_path(doc, HAIR_OBJECT_PATH)
        if source_hair is None or target_hair is None:
            raise RuntimeError("The exact 1:1 Hair object is missing")
        if not (
            isinstance(source_hair, c4d.PolygonObject)
            and isinstance(target_hair, c4d.PolygonObject)
        ):
            raise RuntimeError("The exact 1:1 Hair object is not polygonal")
        if (
            source_hair.GetPointCount() != target_hair.GetPointCount()
            or source_hair.GetPolygonCount() != target_hair.GetPolygonCount()
        ):
            raise RuntimeError("The retarget Hair topology differs from 1:1")

        source_material = find_material(source_doc, HAIR_MATERIAL_NAME)
        if source_material is None:
            raise RuntimeError(
                f"The hair source has no {HAIR_MATERIAL_NAME} material"
            )
        restored_hair = source_hair.GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        restored_hair.SetName("Hair")
        restored_material = source_material.GetClone(
            getattr(c4d, "COPYFLAGS_NONE", 0)
        )
        restored_material.SetName(f"{HAIR_MATERIAL_NAME}_1to1")
        doc.InsertMaterial(restored_material)

        reassigned = 0
        for tag in restored_hair.GetTags():
            if not tag.CheckType(c4d.Ttexture):
                continue
            material = tag[c4d.TEXTURETAG_MATERIAL]
            if material is None or material.GetName() != HAIR_MATERIAL_NAME:
                continue
            tag[c4d.TEXTURETAG_MATERIAL] = restored_material
            tag.Message(c4d.MSG_UPDATE)
            reassigned += 1
        if reassigned != 1:
            raise RuntimeError(
                "Expected one Clay_Hair texture tag on the retarget Hair; "
                f"reassigned {reassigned}"
            )

        target_parent = target_hair.GetUp()
        target_matrix = target_hair.GetMg()
        target_hair.Remove()
        restored_hair.InsertUnder(target_parent)
        restored_hair.SetMg(target_matrix)
        restored_hair.Message(c4d.MSG_UPDATE)
        return {
            "source": str(hair_source),
            "objectPath": HAIR_OBJECT_PATH,
            "pointCount": source_hair.GetPointCount(),
            "polygonCount": source_hair.GetPolygonCount(),
            "sourceMaterial": HAIR_MATERIAL_NAME,
            "restoredMaterial": restored_material.GetName(),
            "textureTagsReassigned": reassigned,
            "objectReplaced": True,
            "tagTypes": [tag.GetType() for tag in restored_hair.GetTags()],
        }
    finally:
        c4d.documents.KillDocument(source_doc)


def component_desc_id(vector_parameter: int, component: int) -> c4d.DescID:
    return c4d.DescID(
        c4d.DescLevel(vector_parameter, c4d.DTYPE_VECTOR, 0),
        c4d.DescLevel(component, c4d.DTYPE_REAL, 0),
    )


def add_pose_key(item, desc_id: c4d.DescID, value: float) -> None:
    existing = item.FindCTrack(desc_id)
    if existing is not None:
        existing.Remove()
    track = c4d.CTrack(item, desc_id)
    track[c4d.ID_CTRACK_ANIMOFF] = True
    item.InsertTrackSorted(track)
    curve = track.GetCurve()
    if curve is None:
        raise RuntimeError(f"Could not create curve for {item.GetName()}")
    added = curve.AddKey(c4d.BaseTime(0, FPS))
    key = added["key"]
    key.SetValue(curve, float(value))
    key.SetInterpolation(curve, c4d.CINTERPOLATION_LINEAR)


def strip_pose_control_animation(items) -> dict[str, int]:
    objects = 0
    tracks = 0
    for item in items:
        position = c4d.Vector(item.GetRelPos())
        rotation = c4d.Vector(item.GetRelRot())
        scale = c4d.Vector(item.GetRelScale())
        item_tracks = list(item.GetCTracks())
        for track in item_tracks:
            track.Remove()
            tracks += 1
        if item_tracks:
            objects += 1
            item.SetRelPos(position)
            item.SetRelRot(rotation)
            item.SetRelScale(scale)
    return {"objects": objects, "tracks": tracks}


def point_camera_at(camera, target: c4d.Vector) -> None:
    position = camera.GetMg().off
    forward = (target - position).GetNormalized()
    world_up = c4d.Vector(0.0, 1.0, 0.0)
    right = world_up.Cross(forward).GetNormalized()
    camera_up = forward.Cross(right).GetNormalized()
    camera.SetMg(c4d.Matrix(position, right, camera_up, forward))


def set_position_component(
    item,
    base: c4d.Vector,
    component: int,
    value: float,
) -> None:
    position = c4d.Vector(base)
    position[component - c4d.VECTOR_X] = value
    item.SetRelPos(position)
    add_pose_key(
        item,
        component_desc_id(c4d.ID_BASEOBJECT_REL_POSITION, component),
        value,
    )


def set_rotation_component(
    item,
    base: c4d.Vector,
    component: int,
    value: float,
) -> None:
    rotation = c4d.Vector(base)
    rotation[component - c4d.VECTOR_X] = value
    item.SetRelRot(rotation)
    add_pose_key(
        item,
        component_desc_id(c4d.ID_BASEOBJECT_REL_ROTATION, component),
        value,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hair-source", type=Path)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    hair_source = (
        args.hair_source.expanduser().resolve()
        if args.hair_source is not None
        else None
    )
    if source == output:
        raise RuntimeError("The expression scene cannot overwrite its source")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing scene: {output}")

    doc = c4d.documents.LoadDocument(
        str(source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Cinema 4D could not load {source}")

    report = {
        "source": str(source),
        "output": str(output),
        "sourceUntouched": True,
        "materialMasterUntouched": True,
        "pose": POSE,
        "controls": [],
        "keyedComponents": 0,
        "facialAnimationRemoved": None,
        "marker": MARKER_NAME,
        "proofCamera": None,
        "authoredLightingPreserved": True,
        "lookmatchHair": None,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        if hair_source is not None:
            report["lookmatchHair"] = restore_lookmatch_hair(
                doc, hair_source
            )
        doc.SetTime(c4d.BaseTime(0, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )

        names = (
            "head",
            "FACIAL_L_Eye",
            "FACIAL_R_Eye",
            "FACIAL_C_Jaw",
            "FACIAL_C_Chin",
            "FACIAL_C_TeethUpper",
            "FACIAL_C_LowerLipRotation",
            "FACIAL_C_MouthUpper",
            "FACIAL_L_LipCorner",
            "FACIAL_R_LipCorner",
            "FACIAL_L_CheekInner",
            "FACIAL_R_CheekInner",
            "FACIAL_L_CheekOuter",
            "FACIAL_R_CheekOuter",
            "FACIAL_L_EyelidLowerA",
            "FACIAL_R_EyelidLowerA",
            "FACIAL_L_EyelidUpperA",
            "FACIAL_R_EyelidUpperA",
            "FACIAL_L_ForeheadIn",
            "FACIAL_R_ForeheadIn",
            "FACIAL_L_ForeheadMid",
            "FACIAL_R_ForeheadMid",
            "FACIAL_L_ForeheadOut",
            "FACIAL_R_ForeheadOut",
        )
        controls = {name: find_control(doc, name) for name in names}
        base_positions = {
            name: c4d.Vector(item.GetRelPos())
            for name, item in controls.items()
        }
        base_rotations = {
            name: c4d.Vector(item.GetRelRot())
            for name, item in controls.items()
        }
        report["facialAnimationRemoved"] = strip_pose_control_animation(
            controls.values()
        )

        for name, horizontal_key in (
            ("FACIAL_L_Eye", "eyeXLeft"),
            ("FACIAL_R_Eye", "eyeXRight"),
        ):
            item = controls[name]
            set_rotation_component(
                item,
                base_rotations[name],
                c4d.VECTOR_X,
                base_rotations[name].x
                + math.radians(POSE[horizontal_key]),
            )
            current = c4d.Vector(item.GetRelRot())
            set_rotation_component(
                item,
                current,
                c4d.VECTOR_Y,
                base_rotations[name].y + math.radians(POSE["eyeY"]),
            )
            report["keyedComponents"] += 2

        set_rotation_component(
            controls["FACIAL_C_Jaw"],
            base_rotations["FACIAL_C_Jaw"],
            c4d.VECTOR_Y,
            base_rotations["FACIAL_C_Jaw"].y
            + math.radians(POSE["jaw"]),
        )
        report["keyedComponents"] += 1
        set_position_component(
            controls["FACIAL_C_Chin"],
            base_positions["FACIAL_C_Chin"],
            c4d.VECTOR_Y,
            base_positions["FACIAL_C_Chin"].y + POSE["chinUp"],
        )
        report["keyedComponents"] += 1
        set_position_component(
            controls["FACIAL_C_TeethUpper"],
            base_positions["FACIAL_C_TeethUpper"],
            c4d.VECTOR_Y,
            base_positions["FACIAL_C_TeethUpper"].y
            + POSE["teethUpperY"],
        )
        report["keyedComponents"] += 1
        set_rotation_component(
            controls["FACIAL_C_LowerLipRotation"],
            base_rotations["FACIAL_C_LowerLipRotation"],
            c4d.VECTOR_Y,
            base_rotations["FACIAL_C_LowerLipRotation"].y
            + math.radians(POSE["lowerLip"]),
        )
        report["keyedComponents"] += 1
        set_position_component(
            controls["FACIAL_C_MouthUpper"],
            base_positions["FACIAL_C_MouthUpper"],
            c4d.VECTOR_Y,
            base_positions["FACIAL_C_MouthUpper"].y + POSE["upperY"],
        )
        report["keyedComponents"] += 1

        for name, direction in (
            ("FACIAL_L_LipCorner", 1.0),
            ("FACIAL_R_LipCorner", -1.0),
        ):
            item = controls[name]
            set_rotation_component(
                item,
                base_rotations[name],
                c4d.VECTOR_X,
                base_rotations[name].x
                + math.radians(POSE["corners"] * direction),
            )
            position = c4d.Vector(base_positions[name])
            set_position_component(
                item,
                position,
                c4d.VECTOR_X,
                position.x + POSE["cornerOut"] * direction,
            )
            position = c4d.Vector(item.GetRelPos())
            set_position_component(
                item,
                position,
                c4d.VECTOR_Y,
                base_positions[name].y + POSE["cornerUp"],
            )
            report["keyedComponents"] += 3

        for name in (
            "FACIAL_L_CheekInner",
            "FACIAL_R_CheekInner",
            "FACIAL_L_CheekOuter",
            "FACIAL_R_CheekOuter",
        ):
            set_position_component(
                controls[name],
                base_positions[name],
                c4d.VECTOR_Y,
                base_positions[name].y + POSE["cheekUp"],
            )
            report["keyedComponents"] += 1

        for name in ("FACIAL_L_EyelidLowerA", "FACIAL_R_EyelidLowerA"):
            set_position_component(
                controls[name],
                base_positions[name],
                c4d.VECTOR_Y,
                base_positions[name].y + POSE["lowerLidUp"],
            )
            report["keyedComponents"] += 1

        for name in ("FACIAL_L_EyelidUpperA", "FACIAL_R_EyelidUpperA"):
            set_position_component(
                controls[name],
                base_positions[name],
                c4d.VECTOR_Y,
                base_positions[name].y + POSE["upperLidUp"],
            )
            report["keyedComponents"] += 1

        for name in (
            "FACIAL_L_ForeheadIn",
            "FACIAL_R_ForeheadIn",
            "FACIAL_L_ForeheadMid",
            "FACIAL_R_ForeheadMid",
            "FACIAL_L_ForeheadOut",
            "FACIAL_R_ForeheadOut",
        ):
            set_position_component(
                controls[name],
                base_positions[name],
                c4d.VECTOR_Y,
                base_positions[name].y + POSE["foreheadUp"],
            )
            report["keyedComponents"] += 1

        set_rotation_component(
            controls["head"],
            base_rotations["head"],
            c4d.VECTOR_X,
            base_rotations["head"].x + math.radians(POSE["headX"]),
        )
        report["keyedComponents"] += 1

        for item in controls.values():
            item.Message(c4d.MSG_UPDATE)
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )

        for existing in list(walk_objects(doc.GetFirstObject())):
            if existing.GetName() in (
                MARKER_NAME,
                PROOF_CAMERA_NAME,
            ):
                existing.Remove()
        marker = c4d.BaseObject(c4d.Onull)
        marker.SetName(MARKER_NAME)
        doc.InsertObject(marker)

        source_camera = next(
            (
                item
                for item in walk_objects(doc.GetFirstObject())
                if item.GetName() == "RS Camera"
                and item.GetType() == LEGACY_RS_CAMERA_OBJECT_ID
            ),
            None,
        )
        if source_camera is not None:
            proof_camera = source_camera.GetClone(
                getattr(c4d, "COPYFLAGS_NONE", 0)
            )
            proof_camera.SetName(PROOF_CAMERA_NAME)
            proof_camera[500] = LOOKMATCH_FOCAL
            proof_camera[7003] = LOOKMATCH_FOCAL
            proof_camera[1220] = 0.0
            sensor_size = proof_camera[7002]
            if not isinstance(sensor_size, c4d.Vector):
                raise RuntimeError(
                    "The legacy RS Camera has no vector sensor size"
                )
            proof_camera[7002] = c4d.Vector(
                sensor_size.x * LOOKMATCH_SENSOR_SCALE,
                sensor_size.y * LOOKMATCH_SENSOR_SCALE,
                sensor_size.z,
            )
            point_camera_at(proof_camera, LOOKMATCH_TARGET)
            doc.InsertObject(proof_camera)
            base_draw = doc.GetRenderBaseDraw()
            if base_draw is not None:
                base_draw.SetSceneCamera(proof_camera)
            report["proofCamera"] = {
                "name": proof_camera.GetName(),
                "sourceCamera": source_camera.GetName(),
                "focal": LOOKMATCH_FOCAL,
                "sensorScale": LOOKMATCH_SENSOR_SCALE,
                "exposure": 0.0,
                "target": [
                    LOOKMATCH_TARGET.x,
                    LOOKMATCH_TARGET.y,
                    LOOKMATCH_TARGET.z,
                ],
            }

        doc.SetFps(FPS)
        doc.SetMinTime(c4d.BaseTime(0, FPS))
        doc.SetMaxTime(c4d.BaseTime(0, FPS))
        doc.SetLoopMinTime(c4d.BaseTime(0, FPS))
        doc.SetLoopMaxTime(c4d.BaseTime(0, FPS))
        doc.SetTime(c4d.BaseTime(0, FPS))
        render_data = doc.GetActiveRenderData()
        render_data[c4d.RDATA_XRES] = 1280.0
        render_data[c4d.RDATA_YRES] = 720.0
        render_data[c4d.RDATA_FRAMESEQUENCE] = (
            c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        )
        render_data[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(0, FPS)
        render_data[c4d.RDATA_FRAMETO] = c4d.BaseTime(0, FPS)
        c4d.EventAdd()

        output.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        if not saved:
            raise RuntimeError(f"Cinema 4D could not save {output}")

        report["controls"] = [
            {"name": name, "path": object_path(item)}
            for name, item in controls.items()
        ]
        print(
            "ABBY_DELIGHTED_SIDE_GLANCE_POSE="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)
