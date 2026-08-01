"""Build a non-destructive CUT-016 recovery with the render-time AEC camera.

The retained ``1A_0106`` scene is the exact coordinate system used by the
final faucet render: five inactive AEC cameras match the saved project at the
same frame down to rounding.  The active render camera animation was never
saved, but Cinema 4D's adjacent AEC file preserves every frame.  This helper
clones the shot-authored legacy Redshift camera, removes its old tracks, bakes
the complete AEC position/rotation/focal animation, selects it as the scene
camera, and saves a new Codex-dated copy.  The input project is never saved.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from pathlib import Path

import c4d

from c4dpy_camera_proof import find_camera, find_take, object_path


CAMERA_RE = re.compile(r'^\s*CAMERA\s+"(?P<name>.*)"\s*$')
KEY_RE = re.compile(
    r"^\s*KEY\s+"
    r"(?P<frame>-?\d+)\s+"
    r"(?P<x>-?[\d.]+)\s+(?P<y>-?[\d.]+)\s+(?P<z>-?[\d.]+)\s+"
    r"(?P<rx>-?[\d.]+)\s+(?P<ry>-?[\d.]+)\s+(?P<rz>-?[\d.]+)\s+"
    r"(?P<fov>-?[\d.]+)\s+(?P<focus>-?[\d.]+)\s+"
    r"(?P<active>[01])\s*$"
)
RECOVERY_CAMERA_NAME = "CUT016_RS_Camera_AEC_codex_072526"


def parse_active_camera(path: Path) -> tuple[str, list[dict[str, float]]]:
    cameras: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw_line in path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        camera_match = CAMERA_RE.match(raw_line)
        if camera_match:
            current = {"name": camera_match.group("name"), "keys": []}
            cameras.append(current)
            continue
        key_match = KEY_RE.match(raw_line)
        if current is None or key_match is None:
            continue
        values = key_match.groupdict()
        if values["active"] != "1":
            continue
        current["keys"].append(
            {
                "frame": int(values["frame"]),
                "x": float(values["x"]),
                "y": float(values["y"]),
                "z": float(values["z"]),
                "rx": math.radians(float(values["rx"])),
                "ry": math.radians(float(values["ry"])),
                "rz": math.radians(float(values["rz"])),
                "fov": math.radians(float(values["fov"])),
            }
        )
    active = [item for item in cameras if item["keys"]]
    if len(active) != 1:
        raise RuntimeError(
            f"Expected one active AEC camera, found {len(active)}"
        )
    return str(active[0]["name"]), list(active[0]["keys"])


def remove_tracks(item) -> int:
    count = 0
    track = item.GetFirstCTrack()
    while track:
        next_track = track.GetNext()
        track.Remove()
        count += 1
        track = next_track
    return count


def component_desc_id(vector_parameter: int, component: int) -> c4d.DescID:
    return c4d.DescID(
        c4d.DescLevel(vector_parameter, c4d.DTYPE_VECTOR, 0),
        c4d.DescLevel(component, c4d.DTYPE_REAL, 0),
    )


def add_track(
    item,
    desc_id: c4d.DescID,
    samples: list[tuple[int, float]],
    fps: int,
) -> int:
    track = c4d.CTrack(item, desc_id)
    item.InsertTrackSorted(track)
    curve = track.GetCurve()
    for frame, value in samples:
        added = curve.AddKey(c4d.BaseTime(frame, fps))
        key = added["key"]
        key.SetValue(curve, value)
        key.SetInterpolation(curve, c4d.CINTERPOLATION_LINEAR)
    return curve.GetKeyCount()


def find_render_data(doc, name: str):
    current = doc.GetFirstRenderData()
    while current:
        if current.GetName() == name:
            return current
        current = current.GetNext()
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--aec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--template-camera-path", default="kitchen/RS Camera"
    )
    parser.add_argument("--take", default="Main")
    parser.add_argument("--render-data", default="My Render Setting")
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    aec = args.aec.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not project.is_file():
        raise FileNotFoundError(project)
    if not aec.is_file():
        raise FileNotFoundError(aec)
    if output == project:
        raise RuntimeError("Recovery output must not overwrite its source")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite recovery copy: {output}")
    if "_codex_072526" not in output.name or "_codex_072526" not in {
        parent.name for parent in output.parents
    }:
        raise RuntimeError(
            "Output must have a Codex-dated filename and parent folder"
        )

    aec_camera_name, keys = parse_active_camera(aec)
    if not keys:
        raise RuntimeError("AEC active camera has no animation keys")
    frames = [int(item["frame"]) for item in keys]
    if frames != list(range(min(frames), max(frames) + 1)):
        raise RuntimeError("AEC active camera keys are not frame-contiguous")

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    report: dict[str, object] = {
        "schemaVersion": 1,
        "sourceProject": str(project),
        "aecPath": str(aec),
        "outputProject": str(output),
        "sourcePreserved": True,
        "saved": False,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        fps = doc.GetFps()
        if fps != 24:
            raise RuntimeError(f"Expected 24 fps project, found {fps}")
        template = find_camera(
            doc, Path(args.template_camera_path).name, args.template_camera_path
        )
        if template is None:
            raise RuntimeError(
                f"Template camera not found: {args.template_camera_path}"
            )
        camera = template.GetClone(getattr(c4d, "COPYFLAGS_NONE", 0))
        removed_track_count = remove_tracks(camera)
        camera.SetName(RECOVERY_CAMERA_NAME)
        doc.InsertObject(camera)

        first = keys[0]
        camera.SetRelPos(c4d.Vector(first["x"], first["y"], first["z"]))
        camera.SetRelRot(c4d.Vector(first["rx"], first["ry"], first["rz"]))
        aperture = float(camera[c4d.CAMERAOBJECT_APERTURE] or 36.0)
        first_focal = aperture / (2.0 * math.tan(first["fov"] / 2.0))
        camera[c4d.CAMERA_FOCUS] = first_focal

        track_counts = {
            "positionX": add_track(
                camera,
                component_desc_id(
                    c4d.ID_BASEOBJECT_REL_POSITION, c4d.VECTOR_X
                ),
                [(int(item["frame"]), item["x"]) for item in keys],
                fps,
            ),
            "positionY": add_track(
                camera,
                component_desc_id(
                    c4d.ID_BASEOBJECT_REL_POSITION, c4d.VECTOR_Y
                ),
                [(int(item["frame"]), item["y"]) for item in keys],
                fps,
            ),
            "positionZ": add_track(
                camera,
                component_desc_id(
                    c4d.ID_BASEOBJECT_REL_POSITION, c4d.VECTOR_Z
                ),
                [(int(item["frame"]), item["z"]) for item in keys],
                fps,
            ),
            "rotationH": add_track(
                camera,
                component_desc_id(
                    c4d.ID_BASEOBJECT_REL_ROTATION, c4d.VECTOR_X
                ),
                [(int(item["frame"]), item["rx"]) for item in keys],
                fps,
            ),
            "rotationP": add_track(
                camera,
                component_desc_id(
                    c4d.ID_BASEOBJECT_REL_ROTATION, c4d.VECTOR_Y
                ),
                [(int(item["frame"]), item["ry"]) for item in keys],
                fps,
            ),
            "rotationB": add_track(
                camera,
                component_desc_id(
                    c4d.ID_BASEOBJECT_REL_ROTATION, c4d.VECTOR_Z
                ),
                [(int(item["frame"]), item["rz"]) for item in keys],
                fps,
            ),
            "focalLength": add_track(
                camera,
                c4d.DescID(c4d.CAMERA_FOCUS),
                [
                    (
                        int(item["frame"]),
                        aperture / (2.0 * math.tan(item["fov"] / 2.0)),
                    )
                    for item in keys
                ],
                fps,
            ),
        }

        frame_from = min(frames)
        frame_to = max(frames)
        doc.SetMinTime(c4d.BaseTime(frame_from, fps))
        doc.SetMaxTime(c4d.BaseTime(frame_to, fps))
        doc.SetLoopMinTime(c4d.BaseTime(frame_from, fps))
        doc.SetLoopMaxTime(c4d.BaseTime(frame_to, fps))
        proof_frame = 87 if 87 in frames else frames[len(frames) // 2]
        doc.SetTime(c4d.BaseTime(proof_frame, fps))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        base_draw = doc.GetRenderBaseDraw()
        if base_draw is None:
            raise RuntimeError("Document has no render BaseDraw")
        base_draw.SetSceneCamera(camera)
        take_data = doc.GetTakeData()
        take = find_take(take_data, args.take)
        if take_data is None or take is None:
            raise RuntimeError(f"Take not found: {args.take}")
        take.SetCamera(take_data, camera)
        take_data.SetCurrentTake(take)

        render_data = find_render_data(doc, args.render_data)
        if render_data is None:
            raise RuntimeError(f"Render data not found: {args.render_data}")
        doc.SetActiveRenderData(render_data)
        settings = render_data.GetData()
        settings[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_MANUAL
        settings[c4d.RDATA_FRAMEFROM] = c4d.BaseTime(frame_from, fps)
        settings[c4d.RDATA_FRAMETO] = c4d.BaseTime(frame_to, fps)
        settings[c4d.RDATA_XRES] = 1280.0
        settings[c4d.RDATA_YRES] = 720.0
        settings[c4d.RDATA_PATH] = str(
            output.parent
            / "renders"
            / "CUT016_1A_SG_FaucetTurnOff_AEC_codex_072526"
        )
        render_data.SetData(settings)

        evaluated = camera.GetMg()
        evaluated_rotation = c4d.utils.MatrixToHPB(evaluated)
        output.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report.update(
            {
                "saved": bool(saved),
                "fps": fps,
                "frameFrom": frame_from,
                "frameTo": frame_to,
                "aecCameraName": aec_camera_name,
                "recoveryCameraName": camera.GetName(),
                "templateCameraPath": object_path(template),
                "templateCameraType": template.GetType(),
                "removedTemplateTracks": removed_track_count,
                "bakedTrackKeyCounts": track_counts,
                "activeRenderData": render_data.GetName(),
                "activeTake": take.GetName(),
                "proofFrame": proof_frame,
                "proofFrameCamera": {
                    "position": {
                        "x": evaluated.off.x,
                        "y": evaluated.off.y,
                        "z": evaluated.off.z,
                    },
                    "rotationRadians": {
                        "x": evaluated_rotation.x,
                        "y": evaluated_rotation.y,
                        "z": evaluated_rotation.z,
                    },
                    "focalLength": float(camera[c4d.CAMERA_FOCUS]),
                },
            }
        )
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if args.report_json:
            report_path = args.report_json.expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
        print(
            "PARACOSM_CUT016_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
