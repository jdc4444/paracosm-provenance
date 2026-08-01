"""Render selected Blender Spin frames through the accepted Abby C4D rig.

The imported MetaHuman hierarchy in the derived animation project preserves
transform curves but does not evaluate them after a document reload.  This
preview driver therefore applies the same retargeted matrices directly for
each requested source frame immediately before Redshift rendering.  Authority
projects remain read-only and no canonical asset is modified.
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
from pathlib import Path
import sys
import traceback

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


def vector(value: c4d.Vector) -> list[float]:
    return [float(value.x), float(value.y), float(value.z)]


def segment_vector(node: c4d.BaseObject) -> c4d.Vector:
    child = node.GetDown()
    if child is not None:
        value = child.GetMg().off - node.GetMg().off
        if value.GetLength() > 1.0e-8:
            return value
    return node.GetMg().v1


def swing_matrix(source: c4d.Vector, target: c4d.Vector) -> c4d.Matrix:
    a = source.GetNormalized()
    b = target.GetNormalized()
    dot = max(-1.0, min(1.0, float(a.Dot(b))))
    axis = a.Cross(b)
    axis_length = axis.GetLength()
    if axis_length <= 1.0e-8:
        if dot >= 0.0:
            return c4d.Matrix()
        fallback = a.Cross(c4d.Vector(1.0, 0.0, 0.0))
        if fallback.GetLength() <= 1.0e-8:
            fallback = a.Cross(c4d.Vector(0.0, 1.0, 0.0))
        return c4d.utils.RotAxisToMatrix(fallback.GetNormalized(), math.pi)
    return c4d.utils.RotAxisToMatrix(
        axis / axis_length, math.acos(dot)
    )


def transform_direction(matrix: c4d.Matrix, value: c4d.Vector) -> c4d.Vector:
    return matrix.v1 * value.x + matrix.v2 * value.y + matrix.v3 * value.z


def read_point_frame(
    path: Path, point_count: int, frame: int, start_frame: int = 0
) -> list[c4d.Vector]:
    scalar_count = point_count * 3
    offset = (frame - start_frame) * scalar_count * 4
    values = array.array("f")
    with path.open("rb") as handle:
        handle.seek(offset)
        values.fromfile(handle, scalar_count)
    if len(values) != scalar_count:
        raise RuntimeError(f"Short point-cache frame {frame} in {path}")
    if sys.byteorder != "little":
        values.byteswap()
    return [
        c4d.Vector(values[index], values[index + 1], values[index + 2])
        for index in range(0, scalar_count, 3)
    ]


def read_facial_curves(path: Path) -> tuple[dict[str, list[float]], dict]:
    payload = json.loads(path.read_text())
    curves = {
        str(item["name"]): [float(value) for value in item["samples"]]
        for item in payload.get("curves", [])
    }
    required = {"eyeL", "eyeR", "eyeUp", "eyeDn", "jawOpen"}
    missing = sorted(required - set(curves))
    if missing:
        raise RuntimeError(
            "Facial curve file is missing: " + ", ".join(missing)
        )
    return curves, payload


def facial_value(curves: dict[str, list[float]], name: str, frame: int) -> float:
    samples = curves[name]
    if frame < 0 or frame >= len(samples):
        raise RuntimeError(
            f"Facial curve {name!r} has no sample for source frame {frame}"
        )
    return float(samples[frame])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-fbx", type=Path, required=True)
    parser.add_argument("--rest-fbx", type=Path, required=True)
    parser.add_argument("--target-rest-source", type=Path, required=True)
    parser.add_argument("--scene-source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=540)
    parser.add_argument("--height", type=int, default=960)
    parser.add_argument("--face-cache-bin", type=Path)
    parser.add_argument("--lashes-cache-bin", type=Path)
    parser.add_argument("--facial-curves-json", type=Path)
    parser.add_argument("--eye-horizontal-degrees", type=float, default=18.0)
    parser.add_argument("--eye-vertical-degrees", type=float, default=12.0)
    parser.add_argument("--lower-teeth-shift", type=float, default=1.8)
    parser.add_argument(
        "--camera-mode", choices=("accepted", "face-closeup"), default="accepted"
    )
    parser.add_argument("--face-camera-distance", type=float, default=42.0)
    parser.add_argument(
        "--finger-mode",
        choices=(
            "hand-local-swing",
            "swing-only",
            "world-rotation",
            "local-rotation",
            "static",
        ),
        default="hand-local-swing",
    )
    parser.add_argument(
        "--root-placement", choices=("studio", "source"), default="studio"
    )
    args = parser.parse_args()

    paths = {
        name: value.expanduser().resolve()
        for name, value in {
            "motion": args.motion_fbx,
            "rest": args.rest_fbx,
            "targetRest": args.target_rest_source,
            "scene": args.scene_source,
            "outputDir": args.output_dir,
            "report": args.report_json,
            "faceCache": args.face_cache_bin,
            "lashesCache": args.lashes_cache_bin,
            "facialCurves": args.facial_curves_json,
        }.items()
        if value is not None
    }
    for name in ("motion", "rest", "targetRest", "scene"):
        if not paths[name].is_file():
            raise RuntimeError(f"Missing {name}: {paths[name]}")
    cache_enabled = "faceCache" in paths or "lashesCache" in paths
    if cache_enabled and not {"faceCache", "lashesCache"}.issubset(paths):
        raise RuntimeError("Face and lash caches must be provided together")
    for name in ("faceCache", "lashesCache"):
        if name in paths and not paths[name].is_file():
            raise RuntimeError(f"Missing {name}: {paths[name]}")
    if "facialCurves" in paths and not paths["facialCurves"].is_file():
        raise RuntimeError(f"Missing facialCurves: {paths['facialCurves']}")
    if "facialCurves" in paths and not cache_enabled:
        raise RuntimeError(
            "Facial controls require the face and lash caches so the authored "
            "surface remains authoritative"
        )
    if paths["report"].exists():
        raise RuntimeError(f"Refusing to overwrite {paths['report']}")
    paths["outputDir"].mkdir(parents=True, exist_ok=True)
    paths["report"].parent.mkdir(parents=True, exist_ok=True)

    frames = sorted(set(args.frames))
    facial_curves = None
    facial_curve_payload = None
    if "facialCurves" in paths:
        facial_curves, facial_curve_payload = read_facial_curves(
            paths["facialCurves"]
        )
    outputs = {
        frame: paths["outputDir"] / f"Abby_Spin_v6_motion_f{frame:04d}.png"
        for frame in frames
    }
    existing = [str(path) for path in outputs.values() if path.exists()]
    if existing:
        raise RuntimeError("Refusing to overwrite: " + ", ".join(existing))

    motion_doc = load_document(paths["motion"])
    rest_doc = load_document(paths["rest"])
    target_rest_doc = load_document(paths["targetRest"])
    scene_doc = load_document(paths["scene"])
    try:
        evaluate(motion_doc, frames[0], True)
        evaluate(rest_doc, 0, True)
        evaluate(target_rest_doc, 0, False)
        evaluate(scene_doc, 0, False)

        motion_root = find_top(motion_doc, "1_cut0_AbbyCharacter-BODY_character")
        rest_root = find_top(rest_doc, "1_cut0_AbbyCharacter-BODY_character")
        target_rest_root = find_top(target_rest_doc, "root.003")
        target_rest_face_root = find_top(target_rest_doc, "root.002")
        body_root = find_top(scene_doc, "root.003")
        face_root = find_top(scene_doc, "root.002")
        motion_nodes = by_unique_name(motion_root)
        rest_nodes = by_unique_name(rest_root)
        target_rest_nodes = by_unique_name(target_rest_root)
        target_rest_face_nodes = by_unique_name(target_rest_face_root)
        body_nodes = by_unique_name(body_root)
        face_nodes = by_unique_name(face_root)

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
        face_items = descendants(face_root)
        frozen_face_locals = {item: c4d.Matrix(item.GetMl()) for item in face_items}
        neutral_face_locals = {
            item: c4d.Matrix(target_rest_face_nodes[item.GetName()].GetMl())
            for item in face_items
            if item.GetName() in target_rest_face_nodes
        }
        face_root_matrix = c4d.Matrix(body_root.GetMg())
        facial_controls = {
            name: face_nodes[name]
            for name in (
                "FACIAL_L_Eye",
                "FACIAL_R_Eye",
                "FACIAL_C_TeethLower",
            )
            if name in face_nodes
        }
        if facial_curves is not None:
            missing_controls = sorted(
                {
                    "FACIAL_L_Eye",
                    "FACIAL_R_Eye",
                    "FACIAL_C_TeethLower",
                }
                - set(facial_controls)
            )
            if missing_controls:
                raise RuntimeError(
                    "Missing native C4D facial controls: "
                    + ", ".join(missing_controls)
                )

        face_mesh = find_unique(scene_doc, "Face.001")
        lashes_mesh = find_unique(scene_doc, "Eye_Lashes.001")
        if not isinstance(face_mesh, c4d.PolygonObject):
            raise RuntimeError("Face.001 is not a polygon object")
        if not isinstance(lashes_mesh, c4d.PolygonObject):
            raise RuntimeError("Eye_Lashes.001 is not a polygon object")

        for node in body_nodes.values():
            remove_transform_tracks(node)
        for node in face_items:
            remove_transform_tracks(node)

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

        active_camera = scene_doc.GetActiveBaseDraw().GetSceneCamera(scene_doc)
        if active_camera is None:
            active_camera = find_unique(
                scene_doc, "RS Camera - Abby Spin Full Body f0170 v001"
            )
        scene_doc.GetActiveBaseDraw().SetSceneCamera(active_camera)
        accepted_camera_matrix = c4d.Matrix(active_camera.GetMg())
        settings = scene_doc.GetActiveRenderData().GetDataInstance()
        settings[c4d.RDATA_XRES] = float(args.width)
        settings[c4d.RDATA_YRES] = float(args.height)
        settings[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
        settings[c4d.RDATA_SAVEIMAGE] = False
        if hasattr(c4d, "RDATA_MULTIPASS_ENABLE"):
            settings[c4d.RDATA_MULTIPASS_ENABLE] = False

        frame_reports = []
        for frame in frames:
            evaluate(motion_doc, frame, True)
            c4d.documents.SetActiveDocument(scene_doc)

            facial_locals = neutral_face_locals if cache_enabled else frozen_face_locals
            for item, matrix in facial_locals.items():
                item.SetMl(matrix)
            face_root.SetMg(face_root_matrix)
            if cache_enabled:
                face_mesh.SetAllPoints(
                    read_point_frame(
                        paths["faceCache"], face_mesh.GetPointCount(), frame
                    )
                )
                lashes_mesh.SetAllPoints(
                    read_point_frame(
                        paths["lashesCache"], lashes_mesh.GetPointCount(), frame
                    )
                )
                face_mesh.Message(c4d.MSG_UPDATE)
                lashes_mesh.Message(c4d.MSG_UPDATE)

            facial_sample = None
            if facial_curves is not None:
                eye_horizontal = (
                    facial_value(facial_curves, "eyeR", frame)
                    - facial_value(facial_curves, "eyeL", frame)
                )
                eye_vertical = (
                    facial_value(facial_curves, "eyeDn", frame)
                    - facial_value(facial_curves, "eyeUp", frame)
                )
                eye_x_degrees = eye_horizontal * args.eye_horizontal_degrees
                eye_y_degrees = eye_vertical * args.eye_vertical_degrees
                for name in ("FACIAL_L_Eye", "FACIAL_R_Eye"):
                    # Recover the rest object's HPB values for the independent
                    # eye-globe rotation layer.
                    rest_rotation = c4d.utils.MatrixToHPB(
                        neutral_face_locals[facial_controls[name]]
                    )
                    rest_rotation.x += math.radians(eye_x_degrees)
                    rest_rotation.y += math.radians(eye_y_degrees)
                    facial_controls[name].SetRelRot(rest_rotation)

                jaw_open = max(
                    0.0, facial_value(facial_curves, "jawOpen", frame)
                )
                teeth_lower = facial_controls["FACIAL_C_TeethLower"]
                teeth_position = c4d.Vector(
                    neutral_face_locals[teeth_lower].off
                )
                teeth_position.y -= jaw_open * args.lower_teeth_shift
                teeth_lower.SetRelPos(teeth_position)
                facial_sample = {
                    "eyeHorizontal": eye_horizontal,
                    "eyeVertical": eye_vertical,
                    "eyeXDegrees": eye_x_degrees,
                    "eyeYDegrees": eye_y_degrees,
                    "jawOpen": jaw_open,
                    "lowerTeethShift": jaw_open * args.lower_teeth_shift,
                }

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
                source_root_delta
                if args.root_placement == "source"
                else c4d.Vector()
            )
            target_pose_origin = target_rest_world["pelvis"].off + applied_root_delta
            target_positions = {
                target_name: target_pose_origin
                + (source_pose_world[source_name].off - source_pose_world["Hips"].off)
                * root_scale
                for source_name, target_name in BONE_MAP
            }

            for source_name, target_name in BONE_MAP:
                target_carriers = [body_nodes]
                if target_name in {target for _source, target in face_carrier_map}:
                    target_carriers.append(face_nodes)
                for nodes in target_carriers:
                    node = nodes[target_name]
                    if target_name in FINGER_TARGETS:
                        if args.finger_mode == "static":
                            node.SetMl(target_rest_local[target_name])
                        elif args.finger_mode == "local-rotation":
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
                            if args.finger_mode == "hand-local-swing":
                                is_left = target_name.endswith("_l")
                                source_hand_name = "LeftHand" if is_left else "RightHand"
                                target_hand_name = "hand_l" if is_left else "hand_r"
                                source_rest_hand_inverse = ~source_rest_world[source_hand_name]
                                source_pose_hand_inverse = ~source_pose_world[source_hand_name]
                                target_rest_hand_inverse = ~target_rest_world[target_hand_name]

                                source_rest_direction_local = transform_direction(
                                    source_rest_hand_inverse,
                                    segment_vector(rest_nodes[source_name]),
                                )
                                source_pose_direction_local = transform_direction(
                                    source_pose_hand_inverse,
                                    segment_vector(motion_nodes[source_name]),
                                )
                                source_finger_delta_local = swing_matrix(
                                    source_rest_direction_local,
                                    source_pose_direction_local,
                                )
                                target_rest_direction_local = transform_direction(
                                    target_rest_hand_inverse,
                                    segment_vector(target_rest_nodes[target_name]),
                                )
                                desired_target_direction_local = transform_direction(
                                    source_finger_delta_local,
                                    target_rest_direction_local,
                                )
                                desired_target_direction_world = transform_direction(
                                    body_nodes[target_hand_name].GetMg(),
                                    desired_target_direction_local,
                                )
                                delta_world = swing_matrix(
                                    segment_vector(node),
                                    desired_target_direction_world,
                                )
                                desired_world = normalized_matrix(
                                    delta_world * node.GetMg(),
                                    position=node.GetMg().off,
                                )
                                node.SetMg(desired_world)
                                continue
                            if args.finger_mode == "swing-only":
                                # Match the visible source segment direction but
                                # discard incompatible source joint roll/twist.
                                # This preserves the authored curl silhouette and
                                # Abby's native joint positions and segment lengths.
                                delta_world = swing_matrix(
                                    segment_vector(rest_nodes[source_name]),
                                    segment_vector(motion_nodes[source_name]),
                                )
                            else:
                                # Transfer the complete global rotational delta
                                # while retaining Abby's native joint positions.
                                delta_world = (
                                    source_pose_world[source_name]
                                    * ~source_rest_world[source_name]
                                )
                            desired_world = normalized_matrix(
                                delta_world * target_rest_world[target_name],
                                position=node.GetMg().off,
                            )
                            node.SetMg(desired_world)
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

            hair = find_object_path(scene_doc, HAIR_OBJECT_PATH)
            if not isinstance(hair, c4d.PolygonObject):
                raise RuntimeError("Accepted exact Hair mesh is missing")

            if args.camera_mode == "face-closeup":
                active_camera.SetMg(accepted_camera_matrix)
                eye_center = (
                    facial_controls["FACIAL_L_Eye"].GetMg().off
                    + facial_controls["FACIAL_R_Eye"].GetMg().off
                ) * 0.5
                camera_matrix = c4d.Matrix(accepted_camera_matrix)
                camera_matrix.off = (
                    eye_center
                    - camera_matrix.v3.GetNormalized()
                    * args.face_camera_distance
                )
                active_camera.SetMg(camera_matrix)
                scene_doc.ExecutePasses(None, True, True, True, 0)

            bitmap = c4d.bitmaps.MultipassBitmap(
                args.width, args.height, c4d.COLORMODE_RGB
            )
            bitmap.AddChannel(True, True)
            render_flags = (
                c4d.RENDERFLAGS_EXTERNAL
                | c4d.RENDERFLAGS_SHOWERRORS
                | getattr(c4d, "RENDERFLAGS_NODOCUMENTCLONE", 0)
            )
            result = c4d.documents.RenderDocument(
                scene_doc, settings, bitmap, render_flags
            )
            if result != c4d.RENDERRESULT_OK:
                raise RuntimeError(f"RenderDocument returned {result} at {frame}")
            layer = bitmap.GetLayerNum(0) if bitmap.GetLayerCount() else bitmap
            if (
                layer.Save(str(outputs[frame]), c4d.FILTER_PNG, c4d.BaseContainer())
                != c4d.IMAGERESULT_OK
            ):
                raise RuntimeError(f"Could not save {outputs[frame]}")
            frame_reports.append(
                {
                    "frame": frame,
                    "output": str(outputs[frame]),
                    "sha256": file_sha256(outputs[frame]),
                    "pelvis": vector(body_nodes["pelvis"].GetMg().off),
                    "head": vector(body_nodes["head"].GetMg().off),
                    "handL": vector(body_nodes["hand_l"].GetMg().off),
                    "handR": vector(body_nodes["hand_r"].GetMg().off),
                    "facialControls": facial_sample,
                }
            )

        missing_assets = [
            str(asset.get("filename") or "")
            for asset in collect_assets(scene_doc)
            if not asset.get("exists")
        ]
        report = {
            "motionSource": str(paths["motion"]),
            "restSource": str(paths["rest"]),
            "targetRestSource": str(paths["targetRest"]),
            "sceneSource": str(paths["scene"]),
            "sourcesUntouched": True,
            "driver": "direct per-source-frame target-rig matrix application",
            "reason": "saved MetaHuman transform tracks do not evaluate after reload",
            "fingerPolicy": {
                "hand-local-swing": (
                    "source hand-local segment curl and spread rebuilt at target segment lengths with roll discarded"
                ),
                "swing-only": (
                    "source segment-direction swing with source roll discarded and target positions preserved"
                ),
                "world-rotation": (
                    "source world-rotation deltas with target joint positions preserved"
                ),
                "local-rotation": (
                    "source local-rotation deltas on target rest lengths"
                ),
                "static": "accepted C4D rest articulation held static",
            }[args.finger_mode],
            "fingerMode": args.finger_mode,
            "faceCache": str(paths["faceCache"]) if cache_enabled else None,
            "lashesCache": str(paths["lashesCache"]) if cache_enabled else None,
            "facialCurves": (
                str(paths["facialCurves"])
                if facial_curves is not None
                else None
            ),
            "facialCurveSource": (
                facial_curve_payload.get("source")
                if facial_curve_payload is not None
                else None
            ),
            "eyeControlPolicy": (
                "source eyeL/eyeR and eyeUp/eyeDn drive both native C4D eye "
                "globes at bounded calibrated angles"
                if facial_curves is not None
                else None
            ),
            "mouthInteriorPolicy": (
                "source jawOpen lowers native C4D lower teeth and tongue while "
                "the UV-transferred facial surface remains authoritative"
                if facial_curves is not None
                else None
            ),
            "facePolicy": (
                "UV-transferred authored Blender facial shape cache on neutral C4D facial rig"
                if cache_enabled
                else "accepted v056 facial pose retained while face transfer remains separate"
            ),
            "hairPolicy": "accepted exact 1:1 C4D hair follows the facial/head carrier",
            "frames": frame_reports,
            "width": args.width,
            "height": args.height,
            "cameraMode": args.camera_mode,
            "faceCameraDistance": (
                args.face_camera_distance
                if args.camera_mode == "face-closeup"
                else None
            ),
            "rootTranslationScale": root_scale,
            "remainingMissingDependencies": missing_assets,
        }
        paths["report"].write_text(json.dumps(report, indent=2))
        print(
            "ABBY_SPIN_V6_MOTION_PREVIEW="
            + json.dumps(
                {
                    "frames": frames,
                    "outputs": [str(outputs[frame]) for frame in frames],
                    "report": str(paths["report"]),
                    "missing": len(missing_assets),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        for doc in (motion_doc, rest_doc, target_rest_doc, scene_doc):
            c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        traceback.print_exc()
        print(
            "ABBY_SPIN_V6_MOTION_PREVIEW_ERROR="
            + f"{type(error).__name__}: {error}",
            flush=True,
        )
        os._exit(1)
    os._exit(0)
