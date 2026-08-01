#!/usr/bin/env python3
"""Read the active render camera from a C4D project via the local MCP plugin.

Loading a document changes Cinema 4D's active tab but never saves the project.
"""

from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = APP_ROOT / "data" / "c4d-camera-export.json"


def send(command: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    payload = (json.dumps(command) + "\n").encode("utf-8")
    with socket.create_connection(("127.0.0.1", 5555), timeout=5) as connection:
        connection.settimeout(timeout)
        connection.sendall(payload)
        response = b""
        while b"\n" not in response:
            chunk = connection.recv(65536)
            if not chunk:
                break
            response += chunk
    if not response:
        raise RuntimeError("Cinema 4D closed the socket without a response")
    return json.loads(response.decode("utf-8").splitlines()[0])


CAMERA_SCRIPT = r"""
def vector_payload(value):
    if value is None:
        return None
    return {
        "x": value.x,
        "y": value.y,
        "z": value.z
    }

def object_path(op):
    names = []
    current = op
    while current:
        names.insert(0, current.GetName())
        current = current.GetUp()
    return "/".join(names)

def camera_payload(op, active_name):
    focal_length = None
    aperture = None
    try:
        focal_length = op[getattr(c4d, "CAMERA_FOCUS")]
    except Exception:
        pass
    try:
        aperture = op[getattr(c4d, "CAMERAOBJECT_APERTURE")]
    except Exception:
        pass
    return {
        "name": op.GetName(),
        "objectPath": object_path(op),
        "guid": str(op.GetGUID()),
        "typeId": op.GetType(),
        "active": op.GetName() == active_name,
        "position": vector_payload(op.GetAbsPos()),
        "rotationRadians": vector_payload(op.GetAbsRot()),
        "focalLength": focal_length,
        "aperture": aperture
    }

def walk(op, result):
    while op:
        if op.CheckType(c4d.Ocamera):
            result.append(op)
        child = op.GetDown()
        if child:
            walk(child, result)
        op = op.GetNext()

def render_data_payload(item):
    if item is None:
        return None
    return {
        "name": item.GetName(),
        "outputPath": str(item[c4d.RDATA_PATH] or ""),
        "frameFrom": item[c4d.RDATA_FRAMEFROM].GetFrame(doc.GetFps()),
        "frameTo": item[c4d.RDATA_FRAMETO].GetFrame(doc.GetFps()),
        "width": item[c4d.RDATA_XRES],
        "height": item[c4d.RDATA_YRES]
    }

def evaluate_document():
    try:
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
    except Exception:
        pass

def take_payload(take, take_data, depth, parent_name):
    camera_result = take.GetEffectiveCamera(take_data)
    declared_camera = (
        camera_result[0] if isinstance(camera_result, tuple) else camera_result
    )
    render_result = take.GetEffectiveRenderData(take_data)
    take_render_data = (
        render_result[0] if isinstance(render_result, tuple) else render_result
    )
    take_data.SetCurrentTake(take)
    evaluate_document()
    take_base_draw = doc.GetRenderBaseDraw()
    scene_camera = (
        take_base_draw.GetSceneCamera(doc) if take_base_draw else None
    )
    camera = declared_camera or scene_camera
    return {
        "name": take.GetName(),
        "depth": depth,
        "parent": parent_name,
        "checked": bool(take.IsChecked()),
        "camera": camera.GetName() if camera else None,
        "cameraObject": (
            camera_payload(camera, camera.GetName()) if camera else None
        ),
        "renderData": take_render_data.GetName() if take_render_data else None,
        "render": render_data_payload(take_render_data)
    }

def walk_takes(take, take_data, result, depth=0, parent_name=None):
    current = take
    while current:
        result.append(take_payload(current, take_data, depth, parent_name))
        child = current.GetDown()
        if child:
            walk_takes(child, take_data, result, depth + 1, current.GetName())
        current = current.GetNext()

camera_objects = []
walk(doc.GetFirstObject(), camera_objects)
render_data = doc.GetActiveRenderData()
base_draw = doc.GetRenderBaseDraw()
active_camera = base_draw.GetSceneCamera(doc) if base_draw else None
active_name = active_camera.GetName() if active_camera else None
cameras = [camera_payload(item, active_name) for item in camera_objects]
active_camera_object = camera_payload(active_camera, active_name) if active_camera else None
if active_camera and not any(item["guid"] == active_camera_object["guid"] for item in cameras):
    cameras.insert(0, active_camera_object)

take_data = doc.GetTakeData()
active_take = take_data.GetCurrentTake() if take_data else None
take_records = []
if take_data:
    try:
        walk_takes(take_data.GetMainTake(), take_data, take_records)
    finally:
        if active_take:
            take_data.SetCurrentTake(active_take)
            evaluate_document()
render_data_records = []
next_render_data = doc.GetFirstRenderData()
while next_render_data:
    render_data_records.append(render_data_payload(next_render_data))
    next_render_data = next_render_data.GetNext()
payload = {
    "document": doc.GetDocumentName(),
    "documentPath": doc.GetDocumentPath(),
    "activeRenderData": render_data.GetName() if render_data else None,
    "activeCamera": active_name,
    "activeCameraObject": active_camera_object,
    "activeTake": active_take.GetName() if active_take else None,
    "fps": doc.GetFps(),
    "frame": doc.GetTime().GetFrame(doc.GetFps()),
    "renderFrameFrom": render_data[c4d.RDATA_FRAMEFROM].GetFrame(doc.GetFps()) if render_data else None,
    "renderFrameTo": render_data[c4d.RDATA_FRAMETO].GetFrame(doc.GetFps()) if render_data else None,
    "width": render_data[c4d.RDATA_XRES] if render_data else None,
    "height": render_data[c4d.RDATA_YRES] if render_data else None,
    "outputPath": render_data[c4d.RDATA_PATH] if render_data else None,
    "cameras": cameras,
    "takes": take_records,
    "renderDatas": render_data_records
}
print("PARACOSM_CAMERA_JSON=" + json.dumps(payload))
"""


def parse_camera_result(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("error"):
        raise RuntimeError(response["error"])
    output = response.get("output") or ""
    marker = "PARACOSM_CAMERA_JSON="
    line = next((line for line in output.splitlines() if line.startswith(marker)), None)
    if not line:
        raise RuntimeError(f"Camera marker missing from Cinema 4D response: {output[:500]}")
    return json.loads(line[len(marker) :])


def probe_project(project: Path) -> dict[str, Any]:
    project = project.expanduser().resolve()
    if not project.exists() or project.suffix.lower() != ".c4d":
        raise ValueError(f"Not a C4D project: {project}")

    loaded = send({"command": "load_scene", "file_path": str(project)})
    if loaded.get("error"):
        raise RuntimeError(loaded["error"])
    result = parse_camera_result(
        send({"command": "execute_python", "code": CAMERA_SCRIPT}, timeout=300)
    )
    result["projectPath"] = str(project)
    result["exportedAt"] = datetime.now(timezone.utc).isoformat()
    return result


def probe_open_project(project: Path) -> dict[str, Any]:
    """Probe a project that is already open, avoiding a second expensive load."""

    project = project.expanduser().resolve()
    escaped_target = json.dumps(str(project))
    select_script = rf"""
target_path = {escaped_target}
candidate_doc = c4d.documents.GetFirstDocument()
found_doc = None
while candidate_doc:
    candidate_path = (
        str(candidate_doc.GetDocumentPath()).rstrip("/\\")
        + "/"
        + candidate_doc.GetDocumentName()
    )
    if candidate_path == target_path:
        found_doc = candidate_doc
        break
    candidate_doc = candidate_doc.GetNext()
if found_doc is None:
    raise RuntimeError("Requested Cinema 4D project is not currently open")
doc = found_doc
c4d.documents.SetActiveDocument(doc)
""" + CAMERA_SCRIPT
    result = parse_camera_result(
        send({"command": "execute_python", "code": select_script}, timeout=300)
    )
    result["projectPath"] = str(project)
    result["exportedAt"] = datetime.now(timezone.utc).isoformat()
    return result


def archive_result(result: dict[str, Any]) -> None:
    archive = {"schemaVersion": 1, "projects": []}
    if EXPORT_PATH.exists():
        archive = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    projects = [
        item
        for item in archive.get("projects", [])
        if item.get("projectPath") != result["projectPath"]
    ]
    projects.append(result)
    archive["projects"] = projects
    archive["updatedAt"] = datetime.now(timezone.utc).isoformat()
    EXPORT_PATH.write_text(json.dumps(archive, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument(
        "--already-open",
        action="store_true",
        help="Select and probe an existing open document instead of loading it",
    )
    args = parser.parse_args()
    try:
        result = (
            probe_open_project(args.file)
            if args.already_open
            else probe_project(args.file)
        )
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
    archive_result(result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
