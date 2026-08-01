"""Build a dated, non-destructive NTH running proxy recovery project.

The March 19 backup is the project state that directly produced the retained
CU_FACE, CU_LEGS, and MainWide renders.  Its Redshift proxy sequence is
offline, but the exact body/face/shoes FBX and wardrobe Alembic animation are
present.  This helper imports those sources, restores their animation timing
and recovered export-origin transform, adds the embedded source hair as a
separate animated branch, disables only the offline proxy object, and saves a
new ``_codex_072526`` project.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


PROXY_NAME = "02NTHI2_slow_walk_into_run_v2_Proxy_01_0016"
BODY_ROOT_NAME = "Null"
HAIR_ROOT_NAME = "abby running"
RECOVERY_ROOT_NAME = "NTH_RUNNING_PROXY_RECOVERY_codex_072526"
BODY_RECOVERY_NAME = "NTH_RUNNING_BODY_FACE_SHOES_codex_072526"
CLOTH_RECOVERY_NAME = "NTH_RUNNING_CLOTH_codex_072526"
HAIR_RECOVERY_NAME = "NTH_RUNNING_HAIR_codex_072526"


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    result = []
    while op:
        result.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(result)


def top_named(doc, name: str):
    current = doc.GetFirstObject()
    while current:
        if current.GetName() == name:
            return current
        current = current.GetNext()
    return None


def find_object(doc, name: str):
    return next(
        (
            op
            for op in walk_objects(doc.GetFirstObject())
            if op.GetName() == name or object_path(op) == name
        ),
        None,
    )


def shift_tracks(root, seconds: float) -> tuple[int, int]:
    shifted_tracks = 0
    shifted_keys = 0
    for op in walk_objects(root):
        track = op.GetFirstCTrack()
        while track:
            curve = track.GetCurve()
            if curve:
                keys = [
                    curve.GetKey(index)
                    for index in range(curve.GetKeyCount())
                ]
                for key in keys:
                    key.SetTime(curve, key.GetTime() + c4d.BaseTime(seconds))
                    shifted_keys += 1
                if keys:
                    shifted_tracks += 1
            track = track.GetNext()
    return shifted_tracks, shifted_keys


def clone_materials_and_root(source, target, source_root):
    alias = c4d.AliasTrans()
    if not alias.Init(source):
        raise RuntimeError("Could not initialize source alias translator")
    materials = []
    material = source.GetFirstMaterial()
    while material:
        clone = material.GetClone(c4d.COPYFLAGS_NONE, alias)
        clone.SetName(f"{material.GetName()} [NTH CODEX RECOVERY]")
        materials.append(clone)
        material = material.GetNext()
    root_clone = source_root.GetClone(c4d.COPYFLAGS_NONE, alias)
    alias.Translate(True)
    for material_clone in materials:
        target.InsertMaterial(material_clone)
    return root_clone, materials


def geometry_summary(root) -> dict:
    records = []
    root_path = object_path(root)
    for op in walk_objects(root):
        path = object_path(op)
        if op is not root and not path.startswith(root_path + "/"):
            break
        cache = op.GetDeformCache() or op.GetCache()
        evaluated = cache or op
        if not isinstance(evaluated, c4d.PolygonObject):
            continue
        records.append(
            {
                "path": path,
                "pointCount": evaluated.GetPointCount(),
                "polygonCount": evaluated.GetPolygonCount(),
            }
        )
    return {
        "meshCount": len(records),
        "pointCount": sum(item["pointCount"] for item in records),
        "polygonCount": sum(item["polygonCount"] for item in records),
        "meshes": records,
    }


def matrix_record(value: c4d.Matrix) -> dict:
    def vector(item):
        return {"x": item.x, "y": item.y, "z": item.z}

    return {
        "off": vector(value.off),
        "v1": vector(value.v1),
        "v2": vector(value.v2),
        "v3": vector(value.v3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--cloth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-frame-offset", type=int, default=16)
    parser.add_argument(
        "--proxy-world-offset",
        nargs=3,
        type=float,
        default=(-39.0, 2.0, 11.0),
        metavar=("X", "Y", "Z"),
    )
    parser.add_argument(
        "--hair-world-offset",
        nargs=3,
        type=float,
        default=(-5.1, 1.3, -12.93),
        metavar=("X", "Y", "Z"),
    )
    parser.add_argument("--verification-frame", type=int, default=60)
    args = parser.parse_args()

    target_path = args.target.expanduser().resolve()
    body_path = args.body.expanduser().resolve()
    cloth_path = args.cloth.expanduser().resolve()
    output = args.output.expanduser().resolve()
    source_paths = {target_path, body_path, cloth_path}
    if output in source_paths:
        raise RuntimeError("Recovery output must not overwrite a source")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite recovery copy: {output}")
    if (
        "_codex_072526" not in output.name
        or output.parent.name != "_codex_072526"
    ):
        raise RuntimeError(
            "Output must be in a _codex_072526 folder and filename"
        )
    for path in source_paths:
        if not path.is_file():
            raise FileNotFoundError(path)

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    target = c4d.documents.LoadDocument(str(target_path), flags)
    body = c4d.documents.LoadDocument(str(body_path), flags)
    cloth = c4d.documents.LoadDocument(
        str(cloth_path),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if target is None or body is None or cloth is None:
        raise RuntimeError("Could not load target/body/cloth documents")

    report = {
        "schemaVersion": 1,
        "sourceTarget": str(target_path),
        "sourceBody": str(body_path),
        "sourceCloth": str(cloth_path),
        "outputProject": str(output),
        "saved": False,
    }
    try:
        c4d.documents.SetActiveDocument(target)
        proxy = find_object(target, PROXY_NAME)
        source_hair_root = top_named(target, HAIR_ROOT_NAME)
        body_root = top_named(body, BODY_ROOT_NAME)
        cloth_root = cloth.GetFirstObject()
        if proxy is None:
            raise RuntimeError(f"Offline proxy object not found: {PROXY_NAME}")
        if source_hair_root is None:
            raise RuntimeError(f"Embedded hair root missing: {HAIR_ROOT_NAME}")
        if body_root is None:
            raise RuntimeError(f"Body source root missing: {BODY_ROOT_NAME}")
        if cloth_root is None:
            raise RuntimeError("Cloth source has no object")

        target_fps = target.GetFps()
        body_fps = body.GetFps()
        cloth_fps = cloth.GetFps()
        source_offset_seconds = args.source_frame_offset / body_fps

        recovery_matrix = proxy.GetMg()
        recovery_matrix.off += c4d.Vector(*args.proxy_world_offset)
        recovery_root = c4d.BaseObject(c4d.Onull)
        recovery_root.SetName(RECOVERY_ROOT_NAME)
        recovery_root.SetMg(recovery_matrix)
        target.InsertObject(recovery_root)

        body_clone, body_materials = clone_materials_and_root(
            body, target, body_root
        )
        body_clone.SetName(BODY_RECOVERY_NAME)
        body_clone.SetMl(body_root.GetMl())
        body_clone.InsertUnder(recovery_root)
        shifted_tracks, shifted_keys = shift_tracks(
            body_clone, -source_offset_seconds
        )

        cloth_alias = c4d.AliasTrans()
        if not cloth_alias.Init(cloth):
            raise RuntimeError("Could not initialize cloth alias translator")
        cloth_clone = cloth_root.GetClone(c4d.COPYFLAGS_NONE, cloth_alias)
        cloth_alias.Translate(True)
        cloth_clone.SetName(CLOTH_RECOVERY_NAME)
        cloth_clone.SetMl(cloth_root.GetMl())
        cloth_clone.InsertUnder(recovery_root)
        try:
            cloth_clone[c4d.ALEMBIC_PATH] = c4d.Filename(str(cloth_path))
        except Exception:
            cloth_clone[c4d.ALEMBIC_PATH] = str(cloth_path)
        cloth_clone[c4d.ALEMBIC_USE_ANIMATION] = True
        # A negative offset advances the cache, so target frame zero evaluates
        # the source sequence's frame 16.
        cloth_clone[c4d.ALEMBIC_ANIMATION_OFFSET] = c4d.BaseTime(
            -args.source_frame_offset, cloth_fps
        )
        cloth_clone[c4d.ALEMBIC_ANIMATION_SPEED] = 1.0
        cloth_clone.Message(c4d.MSG_UPDATE)

        hair_alias = c4d.AliasTrans()
        if not hair_alias.Init(target):
            raise RuntimeError("Could not initialize hair alias translator")
        hair_clone = source_hair_root.GetClone(
            c4d.COPYFLAGS_NONE, hair_alias
        )
        hair_alias.Translate(True)
        hair_clone.SetName(HAIR_RECOVERY_NAME)
        hair_matrix = source_hair_root.GetMg()
        hair_matrix.off += c4d.Vector(*args.hair_world_offset)
        hair_clone.SetMg(hair_matrix)
        target.InsertObject(hair_clone)
        hair_clone.SetRenderMode(c4d.MODE_ON)
        hair_clone.SetEditorMode(c4d.MODE_ON)
        hair_meshes_enabled = []
        for op in walk_objects(hair_clone.GetDown()):
            if not isinstance(op, c4d.PolygonObject):
                continue
            if op.GetName().casefold() == "hair":
                op.SetRenderMode(c4d.MODE_ON)
                op.SetEditorMode(c4d.MODE_ON)
                hair_meshes_enabled.append(object_path(op))
            else:
                op.SetRenderMode(c4d.MODE_OFF)
                op.SetEditorMode(c4d.MODE_OFF)

        proxy.SetRenderMode(c4d.MODE_OFF)
        proxy.SetEditorMode(c4d.MODE_OFF)
        proxy.SetName(PROXY_NAME + "__offline_original")

        verification_time = c4d.BaseTime(
            args.verification_frame, target_fps
        )
        target.SetTime(verification_time)
        target.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        body_geometry = geometry_summary(body_clone)
        cloth_geometry = geometry_summary(cloth_clone)
        hair_geometry = geometry_summary(hair_clone)
        if body_geometry["polygonCount"] <= 0:
            raise RuntimeError("Recovered body produced no evaluated polygons")
        if cloth_geometry["polygonCount"] <= 0:
            raise RuntimeError("Recovered cloth produced no evaluated polygons")
        if hair_geometry["polygonCount"] <= 0:
            raise RuntimeError("Recovered hair produced no evaluated polygons")

        report.update(
            {
                "targetFps": target_fps,
                "bodyFps": body_fps,
                "clothFps": cloth_fps,
                "sourceFrameOffset": args.source_frame_offset,
                "sourceOffsetSeconds": source_offset_seconds,
                "proxyWorldOffset": list(args.proxy_world_offset),
                "hairWorldOffset": list(args.hair_world_offset),
                "recoveryRootMatrix": matrix_record(recovery_root.GetMg()),
                "verificationFrame": args.verification_frame,
                "clonedBodyMaterials": len(body_materials),
                "shiftedBodyTracks": shifted_tracks,
                "shiftedBodyKeys": shifted_keys,
                "bodyGeometry": body_geometry,
                "clothGeometry": cloth_geometry,
                "hairGeometry": hair_geometry,
                "hairMeshesEnabled": hair_meshes_enabled,
                "offlineProxyDisabled": True,
            }
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            target,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report["saved"] = bool(saved)
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
        print(
            "PARACOSM_NTH_RUNNING_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_NTH_RUNNING_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(target)
        c4d.documents.KillDocument(body)
        c4d.documents.KillDocument(cloth)
        os._exit(0)


if __name__ == "__main__":
    main()
