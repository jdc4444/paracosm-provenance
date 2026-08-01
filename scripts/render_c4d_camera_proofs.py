#!/usr/bin/env python3
"""Render small, read-only camera proof frames for canonical conform sources.

The saved Premiere clip instances define the target frame. Cinema 4D source
documents are loaded but never saved. Render settings are cloned in memory so
the source document's renderer, take, camera, and render data remain intact.
"""

from __future__ import annotations

import argparse
import json
import queue
import socket
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFORM = (
    APP_ROOT / "data" / "premiere" / "clean-conform-export.json"
)
DEFAULT_STATE = APP_ROOT / "public" / "data" / "state.json"
DEFAULT_CAMERA_ARCHIVE = APP_ROOT / "data" / "c4d-camera-export.json"
DEFAULT_CONFIRMATIONS = APP_ROOT / "data" / "camera-confirmations.json"
DEFAULT_SOURCE_CONFIRMATIONS = APP_ROOT / "data" / "source-confirmations.json"
DEFAULT_MANIFEST = APP_ROOT / "data" / "c4d-camera-proof-renders.json"
DEFAULT_OUTPUT = APP_ROOT / "public" / "archive" / "camera-proof-renders"
C4DPY = Path(
    "/Applications/Maxon Cinema 4D 2026/c4dpy.app/Contents/MacOS/c4dpy"
)
C4DPY_HELPER = APP_ROOT / "scripts" / "c4dpy_camera_proof.py"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized(path: str | None) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser().resolve())


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


def best_project_match(
    render: dict[str, Any] | None,
    state: dict[str, Any],
    assets_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not render:
        return None, None
    choices = state.get("renderProjectMatches", {}).get(str(render["id"]), [])
    ranked = []
    for match in choices:
        asset = assets_by_id.get(str(match.get("assetId") or ""))
        if not asset:
            continue
        ranked.append(
            (
                (
                    match.get("evidence") == "confirmed",
                    match.get("evidence") == "strong_inference",
                    float(match.get("score") or 0),
                ),
                match,
                asset,
            )
        )
    if not ranked:
        return None, None
    _, match, asset = max(ranked, key=lambda item: item[0])
    return match, asset


def overlapping_cut_ids(
    source_id: str,
    inventory: list[dict[str, Any]],
) -> list[str]:
    return [
        str(item["canonicalId"])
        for item in inventory
        if source_id in (item.get("sourceCoverage") or {}).get("sourceIds", [])
    ]


def make_plan(
    conform: dict[str, Any],
    state: dict[str, Any],
    camera_archive: dict[str, Any],
    confirmations: dict[str, Any],
    source_confirmations: dict[str, Any],
    output_dir: Path,
) -> list[dict[str, Any]]:
    assets_by_id = {
        str(asset["id"]): asset for asset in state.get("assets", [])
    }
    renders_by_path = {
        normalized(render.get("path")): render
        for render in state.get("renderSequences", [])
    }
    cameras_by_path = {
        normalized(item.get("projectPath")): item
        for item in camera_archive.get("projects", [])
        if item.get("projectPath")
    }
    confirmation_by_render = {
        normalized(item.get("renderPath")): item
        for item in confirmations.get("confirmations", [])
        if item.get("renderPath")
    }
    source_confirmation_by_render = {
        normalized(item.get("renderDirectory")): item
        for item in source_confirmations.get("confirmations", [])
        if item.get("renderDirectory")
    }
    source_confirmation_by_source = {
        normalized(item.get("sourcePath")): item
        for item in source_confirmations.get("confirmations", [])
        if item.get("sourcePath")
    }
    plan = []
    if conform.get("authorityKind") == "clean_v1_v2":
        source_groups = [
            (str(source.get("track") or 1), source)
            for source in conform.get("sources", [])
        ]
    else:
        source_groups = [
            (track, source)
            for track in ("6", "7")
            for source in conform.get("tracks", {}).get(track, [])
        ]
    for track, source in source_groups:
            render_path = normalized(source.get("renderDirectory"))
            render = renders_by_path.get(render_path)
            match, asset = best_project_match(render, state, assets_by_id)
            confirmation = confirmation_by_render.get(render_path)
            source_confirmation = source_confirmation_by_source.get(
                normalized(source.get("path"))
            ) or source_confirmation_by_render.get(render_path)
            source_camera = (source_confirmation or {}).get("camera") or {}
            project_path = normalized(
                (confirmation or {}).get("projectPath")
                or (source_confirmation or {}).get("projectPath")
                or (asset or {}).get("path")
            )
            if (
                source_confirmation
                and source_confirmation.get("projectCandidate")
                and not source_confirmation.get("projectPath")
            ):
                project_path = ""
            camera_record = cameras_by_path.get(project_path, {})
            camera_take = (
                (confirmation or {}).get("cameraTake")
                or (match or {}).get("cameraTake")
                or camera_record.get("activeTake")
                or "Main"
            )
            take_record = next(
                (
                    item
                    for item in camera_record.get("takes", [])
                    if item.get("name") == camera_take
                ),
                {},
            )
            camera_name = (
                (confirmation or {}).get("cameraName")
                or source_camera.get("name")
                or take_record.get("camera")
                or (match or {}).get("cameraName")
                or camera_record.get("activeCamera")
            )
            render_data = (
                (confirmation or {}).get("cameraRenderData")
                or source_camera.get("renderData")
                or (match or {}).get("cameraRenderData")
                or camera_record.get("activeRenderData")
            )
            selected_first = source.get("selectedFirstFrame")
            selected_last = source.get("selectedLastFrame")
            target_frame = (
                round((int(selected_first) + int(selected_last)) / 2)
                if selected_first is not None and selected_last is not None
                else int(source_confirmation["cameraProofFrame"])
                if source_confirmation
                and source_confirmation.get("cameraProofFrame") is not None
                else None
            )
            suffix = f"f{int(target_frame or 0):06d}"
            output_path = output_dir / (
                f"{source['id'].lower()}-v{track}-{suffix}.png"
            )
            try:
                public_path = (
                    "/" + output_path.relative_to(APP_ROOT / "public").as_posix()
                )
            except ValueError:
                public_path = (
                    "/archive/camera-proof-renders/" + output_path.name
                )
            match_evidence = (
                "confirmed_camera_audit"
                if confirmation
                else "confirmed_user_lineage"
                if (
                    source_confirmation
                    and source_confirmation.get("projectPath")
                    and source_camera.get("outputPath")
                )
                else str((match or {}).get("evidence") or "unresolved")
            )
            plan.append(
                {
                    "sourceId": source["id"],
                    "track": int(track),
                    "canonical": True,
                    "cutIds": overlapping_cut_ids(
                        str(source["id"]), conform.get("inventory", [])
                    ),
                    "timelineStartFrame": source.get("startFrame"),
                    "timelineEndFrame": source.get("endFrame"),
                    "renderPath": render_path,
                    "sourceFirstFrame": selected_first,
                    "sourceLastFrame": selected_last,
                    "targetFrame": target_frame,
                    "projectPath": project_path or None,
                    "projectName": Path(project_path).name if project_path else None,
                    "cameraName": camera_name,
                    "cameraTake": camera_take,
                    "cameraRenderData": render_data,
                    "cameraObject": (
                        take_record.get("cameraObject")
                        or (match or {}).get("cameraObject")
                        or camera_record.get("activeCameraObject")
                    ),
                    "mappingEvidence": match_evidence,
                    "mappingScore": (match or {}).get("score"),
                    "mappingMethod": (
                        (confirmation or {}).get("method")
                        or (source_confirmation or {}).get(
                            "confirmationMethod"
                        )
                        or (match or {}).get("outputAlignment")
                        or (match or {}).get("matchKind")
                    ),
                    "outputPath": str(output_path),
                    "publicPath": public_path,
                    "status": (
                        "pending"
                        if project_path
                        and camera_name
                        and target_frame is not None
                        else "unresolved"
                    ),
                    "candidateProjectPath": (
                        (
                            (source_confirmation or {}).get(
                                "projectCandidate"
                            )
                            or {}
                        ).get("path")
                    ),
                }
            )
    return plan


RENDER_SCRIPT = r"""
records = json.loads(__PARACOSM_RECORDS__)
target_project = __PARACOSM_PROJECT__
target_width = int(__PARACOSM_WIDTH__)
target_height = int(__PARACOSM_HEIGHT__)

def full_document_path(item):
    return (
        str(item.GetDocumentPath()).rstrip("/\\")
        + "/"
        + item.GetDocumentName()
    ).replace("\\", "/")

def find_document(path):
    item = c4d.documents.GetFirstDocument()
    while item:
        if full_document_path(item) == path.replace("\\", "/"):
            return item
        item = item.GetNext()
    return None

def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            for nested in walk_objects(child):
                yield nested
        op = op.GetNext()

def object_path(op):
    names = []
    current = op
    while current:
        names.insert(0, current.GetName())
        current = current.GetUp()
    return "/".join(names)

def find_camera(doc, name, expected_path):
    cameras = [
        op for op in walk_objects(doc.GetFirstObject())
        if op.CheckType(c4d.Ocamera)
    ]
    if expected_path:
        match = next(
            (op for op in cameras if object_path(op) == expected_path),
            None
        )
        if match:
            return match
    return next((op for op in cameras if op.GetName() == name), None)

def walk_takes(take):
    current = take
    while current:
        yield current
        child = current.GetDown()
        if child:
            for nested in walk_takes(child):
                yield nested
        current = current.GetNext()

def find_take(take_data, name):
    if not take_data:
        return None
    return next(
        (take for take in walk_takes(take_data.GetMainTake())
         if take.GetName() == name),
        None
    )

def find_render_data(doc, name):
    current = doc.GetFirstRenderData()
    while current:
        if not name or current.GetName() == name:
            return current
        current = current.GetNext()
    return doc.GetActiveRenderData()

def evaluate(doc):
    try:
        doc.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
    except Exception:
        pass

doc = find_document(target_project)
if doc is None:
    raise RuntimeError("Loaded Cinema 4D document was not found")
c4d.documents.SetActiveDocument(doc)

fps = doc.GetFps()
take_data = doc.GetTakeData()
original_take = take_data.GetCurrentTake() if take_data else None
original_time = doc.GetTime()
base_draw = doc.GetRenderBaseDraw()
original_camera = base_draw.GetSceneCamera(doc) if base_draw else None
results = []

try:
    for record in records:
        result = {
            "sourceId": record["sourceId"],
            "targetFrame": record["targetFrame"],
            "status": "failed",
        }
        try:
            take = find_take(take_data, record.get("cameraTake"))
            if take_data and take:
                take_data.SetCurrentTake(take)
                evaluate(doc)
            expected_object_path = (
                (record.get("cameraObject") or {}).get("objectPath")
            )
            camera = find_camera(
                doc, record.get("cameraName"), expected_object_path
            )
            if camera is None and base_draw:
                camera = base_draw.GetSceneCamera(doc)
            if camera is None:
                raise RuntimeError(
                    "Identified camera is not present in the loaded document"
                )
            if base_draw:
                base_draw.SetSceneCamera(camera)
            doc.SetTime(c4d.BaseTime(int(record["targetFrame"]), fps))
            evaluate(doc)

            render_data = find_render_data(
                doc, record.get("cameraRenderData")
            )
            if render_data is None:
                raise RuntimeError("No render data found")
            settings = render_data.GetData().GetClone(
                getattr(c4d, "COPYFLAGS_NONE", 0)
            )
            settings[c4d.RDATA_FRAMESEQUENCE] = (
                c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME
            )
            settings[c4d.RDATA_FRAMEFROM] = doc.GetTime()
            settings[c4d.RDATA_FRAMETO] = doc.GetTime()
            settings[c4d.RDATA_XRES] = float(target_width)
            settings[c4d.RDATA_YRES] = float(target_height)
            output_path = record["outputPath"]
            if hasattr(c4d, "RDATA_SAVEIMAGE"):
                settings[c4d.RDATA_SAVEIMAGE] = True
            settings[c4d.RDATA_PATH] = output_path
            settings[c4d.RDATA_FORMAT] = c4d.FILTER_PNG
            if hasattr(c4d, "RDATA_MULTIPASS_ENABLE"):
                settings[c4d.RDATA_MULTIPASS_ENABLE] = False

            bitmap = c4d.bitmaps.MultipassBitmap(
                target_width, target_height, c4d.COLORMODE_RGB
            )
            if bitmap is None:
                raise RuntimeError("Could not initialize proof bitmap")
            bitmap.AddChannel(True, True)

            flags = (
                c4d.RENDERFLAGS_EXTERNAL
                | c4d.RENDERFLAGS_CREATE_PICTUREVIEWER
                | c4d.RENDERFLAGS_SHOWERRORS
            )
            render_result = c4d.documents.RenderDocument(
                doc, settings, bitmap, flags
            )
            if render_result != c4d.RENDERRESULT_OK:
                raise RuntimeError(
                    "RenderDocument returned {}".format(render_result)
                )
            layer_count = bitmap.GetLayerCount()
            result.update({
                "status": "rendered",
                "outputPath": output_path,
                "cameraName": camera.GetName(),
                "cameraObjectPath": object_path(camera),
                "cameraGuid": str(camera.GetGUID()),
                "cameraTake": take.GetName() if take else None,
                "cameraRenderData": render_data.GetName(),
                "rendererId": settings[c4d.RDATA_RENDERENGINE],
                "multipassLayerCount": layer_count,
                "documentFps": fps,
                "documentMinFrame": doc.GetMinTime().GetFrame(fps),
                "documentMaxFrame": doc.GetMaxTime().GetFrame(fps),
                "width": target_width,
                "height": target_height,
            })
        except Exception as error:
            result["error"] = "{}: {}".format(
                type(error).__name__, str(error)
            )
        results.append(result)
finally:
    doc.SetTime(original_time)
    if take_data and original_take:
        take_data.SetCurrentTake(original_take)
    if base_draw:
        base_draw.SetSceneCamera(original_camera)
    evaluate(doc)

print("PARACOSM_CAMERA_PROOF_JSON=" + json.dumps(results))
"""


def parse_render_result(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("error"):
        raise RuntimeError(str(response["error"]))
    output = str(response.get("output") or "")
    marker = "PARACOSM_CAMERA_PROOF_JSON="
    line = next(
        (line for line in output.splitlines() if line.startswith(marker)),
        None,
    )
    if not line:
        raise RuntimeError(
            f"Camera-proof marker missing from Cinema 4D: {output[:1000]}"
        )
    return json.loads(line[len(marker) :])


def render_project(
    project_path: str,
    records: list[dict[str, Any]],
    width: int,
    height: int,
    timeout: int,
) -> list[dict[str, Any]]:
    loaded = send(
        {"command": "load_scene", "file_path": project_path},
        timeout=timeout,
    )
    if loaded.get("error"):
        raise RuntimeError(str(loaded["error"]))
    script = (
        RENDER_SCRIPT.replace("__PARACOSM_RECORDS__", repr(json.dumps(records)))
        .replace("__PARACOSM_PROJECT__", repr(project_path))
        .replace("__PARACOSM_WIDTH__", str(width))
        .replace("__PARACOSM_HEIGHT__", str(height))
    )
    return parse_render_result(
        send(
            {"command": "execute_python", "code": script},
            timeout=timeout,
        )
    )


def analyze_proof(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image, ImageStat

        image = Image.open(path).convert("RGB")
        stat = ImageStat.Stat(image)
        mean = round(sum(stat.mean) / 3, 3)
        maximum = max(channel[1] for channel in stat.extrema)
        if maximum <= 4:
            visual_status = "blank_black"
        elif mean < 8:
            visual_status = "very_dark"
        else:
            visual_status = "visible"
        return {
            "visualStatus": visual_status,
            "meanLuminance": mean,
            "maximumChannel": maximum,
            "width": image.width,
            "height": image.height,
        }
    except Exception as error:
        return {
            "visualStatus": "uninspected",
            "visualInspectionError": f"{type(error).__name__}: {error}",
        }


def render_project_c4dpy(
    project_path: str,
    records: list[dict[str, Any]],
    width: int,
    height: int,
    timeout: int,
) -> list[dict[str, Any]]:
    if not C4DPY.exists():
        raise FileNotFoundError(C4DPY)
    marker = "PARACOSM_C4DPY_PROOFS_JSON="
    with tempfile.TemporaryDirectory(
        prefix="paracosm-camera-proof-"
    ) as temp_dir:
        batch_path = Path(temp_dir) / "batch.json"
        batch_path.write_text(json.dumps(records), encoding="utf-8")
        command = [
            str(C4DPY),
            str(C4DPY_HELPER),
            "--project",
            project_path,
            "--batch-json",
            str(batch_path),
            "--width",
            str(width),
            "--height",
            str(height),
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_queue: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                output_queue.put(line.rstrip("\n"))
            output_queue.put(None)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        result_payload: list[dict[str, Any]] | None = None
        tail: list[str] = []
        missing_node_messages = 0
        while time.monotonic() < deadline:
            try:
                line = output_queue.get(timeout=0.5)
            except queue.Empty:
                if process.poll() is not None and not thread.is_alive():
                    break
                continue
            if line is None:
                break
            if line.startswith("ReplaceMissingAssetsInternal"):
                missing_node_messages += 1
            if line.startswith(marker):
                result_payload = json.loads(line[len(marker) :])
                break
            if line.strip():
                tail.append(line)
                tail = tail[-20:]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if result_payload is None:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"c4dpy camera proof timed out after {timeout}s"
                )
            raise RuntimeError(
                "c4dpy camera proof returned no result marker: "
                + " | ".join(tail[-5:])
            )
        for result in result_payload:
            result["backend"] = "c4dpy_hardware_preview"
            result["missingNodeMessages"] = missing_node_messages
            output_path = Path(str(result.get("outputPath") or ""))
            if result.get("status") == "rendered" and output_path.exists():
                result["fileSize"] = output_path.stat().st_size
                result.update(analyze_proof(output_path))
        return result_payload


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(
    path: Path,
    conform: dict[str, Any],
    records: list[dict[str, Any]],
    width: int,
    height: int,
) -> None:
    counts = defaultdict(int)
    for item in records:
        counts[str(item.get("status") or "unknown")] += 1
    payload = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "authority": (
            "User-cleaned Premiere V1/V2 clip instances are canonical; source "
            "documents are rendered read-only."
            if conform.get("authorityKind") == "clean_v1_v2"
            else "User-saved Premiere V6/V7 clip instances are canonical; "
            "source documents are rendered read-only."
        ),
        "conformProject": conform.get("projectPath"),
        "conformProjectSha256": conform.get("projectSha256"),
        "sequence": conform.get("sequence"),
        "timelineFrameRate": conform.get("timelineFrameRate"),
        "sourceFrameRate": conform.get("sourceImageFrameRate"),
        "width": width,
        "height": height,
        "summary": {
            "targets": len(records),
            "statuses": dict(counts),
            "identified": sum(
                bool(item.get("projectPath") and item.get("cameraName"))
                for item in records
            ),
            "rendered": counts.get("rendered", 0),
            "failed": counts.get("failed", 0),
            "unresolved": counts.get("unresolved", 0),
        },
        "proofs": records,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conform", type=Path, default=DEFAULT_CONFORM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--camera-archive", type=Path, default=DEFAULT_CAMERA_ARCHIVE
    )
    parser.add_argument(
        "--confirmations", type=Path, default=DEFAULT_CONFIRMATIONS
    )
    parser.add_argument(
        "--source-confirmations",
        type=Path,
        default=DEFAULT_SOURCE_CONFIRMATIONS,
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=270)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--limit-projects", type=int)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    conform = load_json(args.conform)
    state = load_json(args.state)
    camera_archive = load_json(args.camera_archive)
    confirmations = (
        load_json(args.confirmations)
        if args.confirmations.exists()
        else {"confirmations": []}
    )
    source_confirmations = (
        load_json(args.source_confirmations)
        if args.source_confirmations.exists()
        else {"confirmations": []}
    )
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records = make_plan(
        conform,
        state,
        camera_archive,
        confirmations,
        source_confirmations,
        output_dir,
    )
    prior_by_source: dict[str, dict[str, Any]] = {}
    prior_by_render: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if args.manifest.exists() and not args.no_resume:
        prior = load_json(args.manifest)
        prior_by_source = {
            str(item["sourceId"]): item for item in prior.get("proofs", [])
        }
        for prior_item in prior.get("proofs", []):
            prior_by_render[normalized(prior_item.get("renderPath"))].append(
                prior_item
            )
        for index, item in enumerate(records):
            old = prior_by_source.get(str(item["sourceId"]))
            if (
                old
                and old.get("status") == "rendered"
                and Path(str(old.get("outputPath") or "")).exists()
                and old.get("targetFrame") == item.get("targetFrame")
                and old.get("projectPath") == item.get("projectPath")
            ):
                records[index] = old
                continue
            if (
                old
                and old.get("status") == "failed"
                and old.get("targetFrame") == item.get("targetFrame")
                and old.get("projectPath") == item.get("projectPath")
            ):
                records[index] = old
                continue
            first = item.get("sourceFirstFrame")
            last = item.get("sourceLastFrame")
            low = min(int(first), int(last)) if first is not None and last is not None else None
            high = max(int(first), int(last)) if first is not None and last is not None else None
            reusable = next(
                (
                    candidate
                    for candidate in prior_by_render.get(
                        normalized(item.get("renderPath")),
                        [],
                    )
                    if candidate.get("status") == "rendered"
                    and Path(str(candidate.get("outputPath") or "")).exists()
                    and candidate.get("targetFrame") is not None
                    and low is not None
                    and high is not None
                    and low <= int(candidate["targetFrame"]) <= high
                ),
                None,
            )
            if reusable:
                identity = {
                    key: item.get(key)
                    for key in (
                        "sourceId",
                        "track",
                        "canonical",
                        "cutIds",
                        "timelineStartFrame",
                        "timelineEndFrame",
                        "renderPath",
                        "sourceFirstFrame",
                        "sourceLastFrame",
                    )
                }
                records[index] = {
                    **reusable,
                    **identity,
                    "reusedForCleanConform": True,
                    "reusedFromSourceId": reusable.get("sourceId"),
                }
                continue
            output_path = Path(str(item.get("outputPath") or ""))
            if output_path.exists() and output_path.stat().st_size > 1000:
                item.update(
                    {
                        "status": "rendered",
                        "renderer": "Cinema 4D Hardware Preview",
                        "rendererId": 300001061,
                        "backend": "c4dpy_hardware_preview",
                        "cameraObjectPath": (
                            (item.get("cameraObject") or {}).get("objectPath")
                        ),
                        "fileSize": output_path.stat().st_size,
                        "recoveredFromExistingProof": True,
                        **analyze_proof(output_path),
                    }
                )

    selected_source_ids = set(args.source_id)
    selected_projects = {normalized(item) for item in args.project}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        if selected_source_ids and item["sourceId"] not in selected_source_ids:
            continue
        if selected_projects and normalized(item.get("projectPath")) not in selected_projects:
            continue
        if item.get("status") == "rendered" and not args.no_resume:
            continue
        if item.get("status") != "pending":
            continue
        groups[str(item["projectPath"])].append(item)

    sorted_groups = sorted(
        groups.items(),
        key=lambda pair: (
            Path(pair[0]).stat().st_size if Path(pair[0]).exists() else 10**30,
            pair[0],
        ),
    )
    if args.limit_projects is not None:
        sorted_groups = sorted_groups[: args.limit_projects]

    write_manifest(args.manifest, conform, records, args.width, args.height)
    print(
        f"Camera-proof plan: {len(records)} canonical sources · "
        f"{sum(item['status'] == 'pending' for item in records)} pending · "
        f"{sum(item['status'] == 'unresolved' for item in records)} unresolved"
    )
    print(f"Selected {len(sorted_groups)} Cinema 4D projects")
    if args.plan_only:
        return

    records_by_source = {str(item["sourceId"]): item for item in records}
    for group_index, (project_path, group) in enumerate(sorted_groups, start=1):
        print(
            f"[{group_index}/{len(sorted_groups)}] {Path(project_path).name} · "
            f"{len(group)} proof frame(s)",
            flush=True,
        )
        started = time.time()
        try:
            results = render_project_c4dpy(
                project_path, group, args.width, args.height, args.timeout
            )
            results_by_source = {
                str(item["sourceId"]): item for item in results
            }
            for item in group:
                result = results_by_source.get(str(item["sourceId"]))
                if result is None:
                    item.update(
                        {
                            "status": "failed",
                            "error": "Cinema 4D returned no result for source",
                        }
                    )
                else:
                    item.update(result)
                    if item.get("status") == "rendered":
                        output_path = Path(str(item["outputPath"]))
                        item["fileSize"] = (
                            output_path.stat().st_size
                            if output_path.exists()
                            else 0
                        )
                records_by_source[str(item["sourceId"])] = item
        except Exception as error:
            for item in group:
                item.update(
                    {
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                records_by_source[str(item["sourceId"])] = item
        records = [
            records_by_source[str(item["sourceId"])] for item in records
        ]
        write_manifest(args.manifest, conform, records, args.width, args.height)
        rendered = sum(
            item.get("status") == "rendered" for item in group
        )
        print(
            f"  {rendered}/{len(group)} rendered in "
            f"{time.time() - started:.1f}s",
            flush=True,
        )

    write_manifest(args.manifest, conform, records, args.width, args.height)
    final = load_json(args.manifest)
    print(json.dumps(final["summary"], indent=2))


if __name__ == "__main__":
    main()
