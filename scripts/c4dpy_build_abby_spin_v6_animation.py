"""Bake the full Blender Spin body motion onto the accepted Abby C4D look.

All authority files are opened read-only.  The output is a new versioned C4D
scene.  Body and head motion are retargeted for frames 0-365; the accepted
facial pose is frozen deliberately until the authored Blender facial shapes
have a separately verified target-rig transfer.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import c4d

from c4dpy_build_abby_spin_v6_still import (
    BONE_MAP,
    FINGER_TARGETS,
    HAIR_OBJECT_PATH,
    by_unique_name,
    collect_assets,
    descendants,
    file_sha256,
    find_object_path,
    find_top,
    find_unique,
    normalized_matrix,
    remove_transform_tracks,
)


TRANSFORM_PARAMETERS = (
    c4d.ID_BASEOBJECT_REL_POSITION,
    c4d.ID_BASEOBJECT_REL_ROTATION,
    c4d.ID_BASEOBJECT_REL_SCALE,
)
VECTOR_COMPONENTS = (c4d.VECTOR_X, c4d.VECTOR_Y, c4d.VECTOR_Z)


def component_desc_id(parameter: int, component: int) -> c4d.DescID:
    return c4d.DescID(
        c4d.DescLevel(parameter, c4d.DTYPE_VECTOR, 0),
        c4d.DescLevel(component, c4d.DTYPE_REAL, 0),
    )


def vector_values(value: c4d.Vector) -> tuple[float, float, float]:
    return float(value.x), float(value.y), float(value.z)


def unwrap_angles(values: list[float]) -> list[float]:
    if not values:
        return values
    result = [values[0]]
    for value in values[1:]:
        previous = result[-1]
        while value - previous > math.pi:
            value -= 2.0 * math.pi
        while value - previous < -math.pi:
            value += 2.0 * math.pi
        result.append(value)
    return result


def add_vector_tracks(
    item: c4d.BaseObject,
    parameter: int,
    frame_values: list[tuple[int, tuple[float, float, float]]],
    fps: int,
) -> tuple[int, int]:
    track_count = 0
    key_count = 0
    for component_index, component in enumerate(VECTOR_COMPONENTS):
        values = [value[component_index] for _frame, value in frame_values]
        if parameter == c4d.ID_BASEOBJECT_REL_ROTATION:
            values = unwrap_angles(values)
        track = c4d.CTrack(item, component_desc_id(parameter, component))
        track[c4d.ID_CTRACK_ANIMOFF] = False
        item.InsertTrackSorted(track)
        curve = track.GetCurve()
        if curve is None:
            raise RuntimeError(f"Could not create track on {item.GetName()}")
        for (frame, _value), scalar in zip(frame_values, values):
            added = curve.AddKey(c4d.BaseTime(frame, fps))
            key = added["key"]
            key.SetValue(curve, float(scalar))
            key.SetInterpolation(curve, c4d.CINTERPOLATION_LINEAR)
        track_count += 1
        key_count += len(frame_values)
    return track_count, key_count


def local_matrix(node: c4d.BaseObject) -> c4d.Matrix:
    return c4d.Matrix(node.GetMl())


def load_document(path: Path) -> c4d.documents.BaseDocument:
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(path), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {path}")
    return doc


def evaluate(doc, frame: int, force_main_take: bool = False) -> None:
    c4d.documents.SetActiveDocument(doc)
    take_data = doc.GetTakeData()
    if force_main_take and take_data:
        take_data.SetCurrentTake(take_data.GetMainTake())
    doc.SetTime(c4d.BaseTime(frame, doc.GetFps()))
    doc.ExecutePasses(None, True, True, True, 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-fbx", type=Path, required=True)
    parser.add_argument("--rest-fbx", type=Path, required=True)
    parser.add_argument("--target-rest-source", type=Path, required=True)
    parser.add_argument("--scene-source", type=Path, required=True)
    parser.add_argument("--output-project", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=365)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--finger-mode",
        choices=("static", "local-rotation"),
        default="local-rotation",
    )
    parser.add_argument(
        "--root-placement", choices=("studio", "source"), default="studio"
    )
    parser.add_argument("--bake-on-main-take", action="store_true")
    args = parser.parse_args()

    paths = {
        name: value.expanduser().resolve()
        for name, value in {
            "motion": args.motion_fbx,
            "rest": args.rest_fbx,
            "targetRest": args.target_rest_source,
            "scene": args.scene_source,
            "output": args.output_project,
            "report": args.report_json,
        }.items()
    }
    for name in ("motion", "rest", "targetRest", "scene"):
        if not paths[name].is_file():
            raise RuntimeError(f"Missing {name}: {paths[name]}")
    for name in ("output", "report"):
        if paths[name].exists():
            raise RuntimeError(f"Refusing to overwrite {paths[name]}")
        paths[name].parent.mkdir(parents=True, exist_ok=True)

    motion_doc = load_document(paths["motion"])
    rest_doc = load_document(paths["rest"])
    target_rest_doc = load_document(paths["targetRest"])
    scene_doc = load_document(paths["scene"])
    reload_doc = None
    try:
        evaluate(motion_doc, args.start, True)
        evaluate(rest_doc, 0, True)
        evaluate(target_rest_doc, 0, False)
        evaluate(scene_doc, 0, False)

        motion_root = find_top(motion_doc, "1_cut0_AbbyCharacter-BODY_character")
        rest_root = find_top(rest_doc, "1_cut0_AbbyCharacter-BODY_character")
        target_rest_body_root = find_top(target_rest_doc, "root.003")
        body_root = find_top(scene_doc, "root.003")
        face_root = find_top(scene_doc, "root.002")
        motion_nodes = by_unique_name(motion_root)
        rest_nodes = by_unique_name(rest_root)
        target_rest_nodes = by_unique_name(target_rest_body_root)
        body_nodes = by_unique_name(body_root)
        face_nodes = by_unique_name(face_root)

        take_data = scene_doc.GetTakeData()
        source_take = take_data.GetCurrentTake() if take_data else None
        source_take_name = source_take.GetName() if source_take else None
        active_camera = scene_doc.GetActiveBaseDraw().GetSceneCamera(scene_doc)
        if active_camera is None:
            active_camera = find_unique(
                scene_doc, "RS Camera - Abby Spin Full Body f0170 v001"
            )
        camera_matrix = c4d.Matrix(active_camera.GetMg())
        light_parameters = {}
        for light_name, parameter_ids in {
            "RS Dome Light": (12024, 10034),
            "RS Area Light.1": (11004, 10034),
            "RS Area Fill - Abby Spin v001": (11004, 10034),
        }.items():
            light = find_unique(scene_doc, light_name)
            light_parameters[light_name] = {
                parameter_id: light[parameter_id]
                for parameter_id in parameter_ids
            }

        missing = []
        for source_name, target_name in BONE_MAP:
            for label, nodes, name in (
                ("motion", motion_nodes, source_name),
                ("rest", rest_nodes, source_name),
                ("targetRest", target_rest_nodes, target_name),
                ("body", body_nodes, target_name),
            ):
                if name not in nodes:
                    missing.append(f"{label}:{name}")
        if missing:
            raise RuntimeError("Missing mapped bones: " + ", ".join(missing))

        face_carrier_map = tuple(
            (source_name, target_name)
            for source_name, target_name in BONE_MAP
            if target_name in face_nodes and target_name not in FINGER_TARGETS
        )
        if not face_carrier_map:
            raise RuntimeError("No face-carrier body chain found")

        # Freeze the accepted v056 face, eyes, lashes and oral pose exactly at
        # frame zero.  Only the duplicated body/head carrier chain is rebaked.
        face_items = descendants(face_root)
        frozen_face_locals = {item: local_matrix(item) for item in face_items}
        if args.bake_on_main_take and take_data:
            take_data.SetCurrentTake(take_data.GetMainTake())
            scene_doc.SetTime(c4d.BaseTime(0, scene_doc.GetFps()))
            scene_doc.ExecutePasses(None, True, True, True, 0)
            for item in face_items:
                item.SetMl(frozen_face_locals[item])
            active_camera.SetMg(camera_matrix)
            scene_doc.GetActiveBaseDraw().SetSceneCamera(active_camera)
            for light_name, parameters in light_parameters.items():
                light = find_unique(scene_doc, light_name)
                for parameter_id, value in parameters.items():
                    light[parameter_id] = value
                light.Message(c4d.MSG_UPDATE)
        removed_face_tracks = sum(remove_transform_tracks(item) for item in face_items)
        for item in face_items:
            item.SetMl(frozen_face_locals[item])

        mapped_body_targets = {target for _source, target in BONE_MAP}
        removed_body_tracks = sum(
            remove_transform_tracks(body_nodes[name]) for name in mapped_body_targets
        )

        target_rest_world = {
            target_name: normalized_matrix(target_rest_nodes[target_name].GetMg())
            for _source_name, target_name in BONE_MAP
        }
        target_rest_local = {
            target_name: normalized_matrix(target_rest_nodes[target_name].GetMl())
            for _source_name, target_name in BONE_MAP
        }
        source_rest_world = {
            source_name: normalized_matrix(rest_nodes[source_name].GetMg())
            for source_name, _target_name in BONE_MAP
        }
        source_rest_local = {
            source_name: normalized_matrix(rest_nodes[source_name].GetMl())
            for source_name, _target_name in BONE_MAP
        }
        source_height = max(
            (source_rest_world["Head"].off - source_rest_world["Hips"].off).GetLength(),
            1.0e-8,
        )
        target_height = max(
            (target_rest_world["head"].off - target_rest_world["pelvis"].off).GetLength(),
            1.0e-8,
        )
        root_scale = target_height / source_height

        # Use the accepted v056 scene root and static facial expression.
        face_root.SetMg(body_root.GetMg())
        samples: dict[tuple[str, str], dict[int, list[tuple[int, tuple[float, float, float]]]]] = {}
        assignments: dict[tuple[str, str], c4d.BaseObject] = {}
        for _source_name, target_name in BONE_MAP:
            assignments[("body", target_name)] = body_nodes[target_name]
        for _source_name, target_name in face_carrier_map:
            assignments[("face", target_name)] = face_nodes[target_name]
        for key in assignments:
            samples[key] = {parameter: [] for parameter in TRANSFORM_PARAMETERS}

        sample_frames = []
        for frame in range(args.start, args.end + 1):
            evaluate(motion_doc, frame, True)
            c4d.documents.SetActiveDocument(scene_doc)
            source_pose_world = {
                source_name: normalized_matrix(motion_nodes[source_name].GetMg())
                for source_name, _target_name in BONE_MAP
            }
            source_pose_local = {
                source_name: normalized_matrix(motion_nodes[source_name].GetMl())
                for source_name, _target_name in BONE_MAP
            }
            source_root_delta = (
                source_pose_world["Hips"].off - source_rest_world["Hips"].off
            ) * root_scale
            applied_root_delta = (
                source_root_delta if args.root_placement == "source" else c4d.Vector()
            )
            target_pose_origin = target_rest_world["pelvis"].off + applied_root_delta
            target_positions = {
                target_name: target_pose_origin
                + (source_pose_world[source_name].off - source_pose_world["Hips"].off)
                * root_scale
                for source_name, target_name in BONE_MAP
            }

            for source_name, target_name in BONE_MAP:
                target_carriers = [("body", body_nodes)]
                if target_name in {target for _source, target in face_carrier_map}:
                    target_carriers.append(("face", face_nodes))
                for label, nodes in target_carriers:
                    node = nodes[target_name]
                    if target_name in FINGER_TARGETS:
                        if args.finger_mode == "static":
                            node.SetMl(target_rest_local[target_name])
                        else:
                            delta_local = (
                                source_pose_local[source_name]
                                * ~source_rest_local[source_name]
                            )
                            desired_local = normalized_matrix(
                                delta_local * target_rest_local[target_name],
                                position=target_rest_local[target_name].off,
                            )
                            node.SetMl(desired_local)
                    else:
                        delta_world = (
                            source_pose_world[source_name]
                            * ~source_rest_world[source_name]
                        )
                        desired_world = normalized_matrix(
                            delta_world * target_rest_world[target_name],
                            position=target_positions[target_name],
                        )
                        node.SetMg(desired_world)
                scene_doc.ExecutePasses(None, True, True, True, 0)

            for key, node in assignments.items():
                samples[key][c4d.ID_BASEOBJECT_REL_POSITION].append(
                    (frame, vector_values(node.GetRelPos()))
                )
                samples[key][c4d.ID_BASEOBJECT_REL_ROTATION].append(
                    (frame, vector_values(node.GetRelRot()))
                )
                samples[key][c4d.ID_BASEOBJECT_REL_SCALE].append(
                    (frame, vector_values(node.GetRelScale()))
                )
            if frame in {args.start, 90, 170, 270, args.end}:
                sample_frames.append(
                    {
                        "frame": frame,
                        "pelvis": vector_values(body_nodes["pelvis"].GetMg().off),
                        "head": vector_values(body_nodes["head"].GetMg().off),
                        "handL": vector_values(body_nodes["hand_l"].GetMg().off),
                        "handR": vector_values(body_nodes["hand_r"].GetMg().off),
                    }
                )

        track_count = 0
        key_count = 0
        for key, node in assignments.items():
            for parameter in TRANSFORM_PARAMETERS:
                created_tracks, created_keys = add_vector_tracks(
                    node, parameter, samples[key][parameter], args.fps
                )
                track_count += created_tracks
                key_count += created_keys

        scene_doc.SetFps(args.fps)
        scene_doc.SetMinTime(c4d.BaseTime(args.start, args.fps))
        scene_doc.SetMaxTime(c4d.BaseTime(args.end, args.fps))
        scene_doc.SetLoopMinTime(c4d.BaseTime(args.start, args.fps))
        scene_doc.SetLoopMaxTime(c4d.BaseTime(args.end, args.fps))
        scene_doc.SetTime(c4d.BaseTime(170, args.fps))
        scene_doc.ExecutePasses(None, True, True, True, 0)
        hair = find_object_path(scene_doc, HAIR_OBJECT_PATH)
        if not isinstance(hair, c4d.PolygonObject):
            raise RuntimeError("The accepted 1:1 Hair mesh is missing")

        render_data = scene_doc.GetActiveRenderData()
        render_data[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_ALLFRAMES
        render_data[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(args.start, args.fps)
        render_data[c4d.RDATA_FRAMETO] = c4d.BaseTime(args.end, args.fps)
        render_data[c4d.RDATA_FRAMESTEP] = 1
        render_data[c4d.RDATA_SAVEIMAGE] = False

        if not c4d.documents.SaveDocument(
            scene_doc,
            str(paths["output"]),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        ):
            raise RuntimeError("Could not save full animation project")

        reload_doc = load_document(paths["output"])
        evaluate(reload_doc, 170, False)
        remaining_missing = [
            str(asset.get("filename") or "")
            for asset in collect_assets(reload_doc)
            if not asset.get("exists")
        ]
        reload_body = by_unique_name(find_top(reload_doc, "root.003"))
        reload_face = by_unique_name(find_top(reload_doc, "root.002"))
        reload_hair = find_object_path(reload_doc, HAIR_OBJECT_PATH)
        if not isinstance(reload_hair, c4d.PolygonObject):
            raise RuntimeError("Reload lost accepted Hair mesh")
        reload_track_count = sum(
            len(node.GetCTracks())
            for node in list(reload_body.values()) + list(reload_face.values())
        )

        report = {
            "motionSource": str(paths["motion"]),
            "restSource": str(paths["rest"]),
            "targetRestSource": str(paths["targetRest"]),
            "sceneSource": str(paths["scene"]),
            "outputProject": str(paths["output"]),
            "sourcesUntouched": True,
            "range": [args.start, args.end],
            "fps": args.fps,
            "frames": args.end - args.start + 1,
            "bodyMotion": "full authored Blender Spin body/head motion",
            "fingerMode": args.finger_mode,
            "fingerPolicy": (
                "source local-rotation deltas on target rest lengths"
                if args.finger_mode == "local-rotation"
                else "accepted C4D rest articulation held static"
            ),
            "facialStatus": (
                "accepted v056 C4D facial pose frozen; authored Blender Pose Morph "
                "carrier is archived separately and not yet applied to the target rig"
            ),
            "rootTranslationPolicy": args.root_placement,
            "sourceTake": source_take_name,
            "bakedTake": (
                take_data.GetCurrentTake().GetName()
                if take_data and take_data.GetCurrentTake()
                else None
            ),
            "bakeOnMainTake": args.bake_on_main_take,
            "rootTranslationScale": root_scale,
            "mappedBodyTargets": len(BONE_MAP),
            "mappedFaceCarrierTargets": len(face_carrier_map),
            "trackCountCreated": track_count,
            "keyCountCreated": key_count,
            "removedBodyTracks": removed_body_tracks,
            "removedFaceTracks": removed_face_tracks,
            "sampleFrames": sample_frames,
            "hair": {
                "objectPath": HAIR_OBJECT_PATH,
                "points": reload_hair.GetPointCount(),
                "polygons": reload_hair.GetPolygonCount(),
                "mode": "accepted exact 1:1 C4D mesh, rigidly following facial/head carrier",
            },
            "eyesAndLashes": (
                "accepted v056 C4D weighted geometry/materials preserved on frozen facial rig"
            ),
            "remainingMissingDependencies": remaining_missing,
            "reloadTrackCount": reload_track_count,
            "outputSha256": file_sha256(paths["output"]),
            "saved": True,
            "reloaded": True,
        }
        paths["report"].write_text(json.dumps(report, indent=2))
        print(
            "ABBY_SPIN_V6_ANIMATION="
            + json.dumps(
                {
                    "project": str(paths["output"]),
                    "report": str(paths["report"]),
                    "frames": report["frames"],
                    "tracks": track_count,
                    "keys": key_count,
                    "missing": len(remaining_missing),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        for doc in (motion_doc, rest_doc, target_rest_doc, scene_doc, reload_doc):
            if doc is not None:
                c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
