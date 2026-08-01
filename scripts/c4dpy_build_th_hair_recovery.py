"""Retired cross-shot hair experiment retained only for forensic provenance.

The missing TH hair must be recovered through the target shot's own authored
hair hierarchy and exact driver caches. This script is deliberately
non-runnable because cloning hair from another project is not canonical.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


RETIRED_REASON = (
    "Rejected cross-shot hair recovery: repair the target shot's authored "
    "Hair hierarchy and exact caches in place; never clone hair from another "
    "C4D project."
)


def walk_subtree(op):
    yield op
    child = op.GetDown()
    while child:
        yield from walk_subtree(child)
        child = child.GetNext()


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def walk_tags(op):
    for item in walk_subtree(op):
        tag = item.GetFirstTag()
        while tag:
            yield tag
            tag = tag.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def find_path(doc, path: str):
    for op in walk_objects(doc.GetFirstObject()):
        if object_path(op) == path:
            return op
    return None


def matrix_values(value):
    return [
        value.off.x,
        value.off.y,
        value.off.z,
        value.v1.x,
        value.v1.y,
        value.v1.z,
        value.v2.x,
        value.v2.y,
        value.v2.z,
        value.v3.x,
        value.v3.y,
        value.v3.z,
    ]


def geometry_summary(root):
    result = {
        "objectCount": 0,
        "pointCount": 0,
        "polygonCount": 0,
        "cachePointCount": 0,
        "cachePolygonCount": 0,
    }
    for op in walk_subtree(root):
        result["objectCount"] += 1
        cache = op.GetDeformCache() or op.GetCache()
        if isinstance(op, c4d.PointObject):
            result["pointCount"] += op.GetPointCount()
        if isinstance(op, c4d.PolygonObject):
            result["polygonCount"] += op.GetPolygonCount()
        if isinstance(cache, c4d.PointObject):
            result["cachePointCount"] += cache.GetPointCount()
        if isinstance(cache, c4d.PolygonObject):
            result["cachePolygonCount"] += cache.GetPolygonCount()
    return result


def main() -> None:
    raise RuntimeError(RETIRED_REASON)
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--hair-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame", type=int, default=244)
    parser.add_argument(
        "--target-hair-root",
        default="th until end of scene v3/Hair",
    )
    parser.add_argument(
        "--source-hair",
        default="Hair/Subdivision Surface",
    )
    parser.add_argument(
        "--disable-target-path",
        action="append",
        default=[
            "th until end of scene v3/Hair/Subdivision Surface_2",
            "th until end of scene v3/Hair/Null/Subdivision Surface_1",
        ],
    )
    args = parser.parse_args()

    target_path = args.target.expanduser().resolve()
    source_path = args.hair_source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output in (target_path, source_path):
        raise RuntimeError("Output must not overwrite either input project")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite recovery copy: {output}")
    if (
        "_codex_072526" not in output.name
        or output.parent.name != "_codex_072526"
    ):
        raise RuntimeError("Output must use the _codex_072526 convention")

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    target = c4d.documents.LoadDocument(str(target_path), flags)
    source = c4d.documents.LoadDocument(str(source_path), flags)
    if target is None or source is None:
        raise RuntimeError("Could not load target and source C4D documents")

    report = {
        "sourceTarget": str(target_path),
        "sourceHairProject": str(source_path),
        "outputProject": str(output),
        "targetHairRoot": args.target_hair_root,
        "sourceHair": args.source_hair,
        "frame": args.frame,
        "saved": False,
    }
    try:
        target.SetTime(c4d.BaseTime(args.frame, target.GetFps()))
        source.SetTime(c4d.BaseTime(0, source.GetFps()))
        target.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        source.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        target_root = find_path(target, args.target_hair_root)
        source_hair = find_path(source, args.source_hair)
        if target_root is None or source_hair is None:
            raise RuntimeError("Target hair root or source hair object missing")

        source_geometry = geometry_summary(source_hair)
        if source_geometry["cachePolygonCount"] < 5000:
            raise RuntimeError(
                "Source procedural hair did not evaluate enough polygons"
            )

        alias = c4d.AliasTrans()
        if not alias.Init(source):
            raise RuntimeError("Could not initialize C4D alias translation")
        material_clones = []
        material = source.GetFirstMaterial()
        while material:
            clone = material.GetClone(c4d.COPYFLAGS_NONE, alias)
            clone.SetName(f"{material.GetName()} [TH CODEX HAIR]")
            material_clones.append(clone)
            material = material.GetNext()
        recovered = source_hair.GetClone(c4d.COPYFLAGS_NONE, alias)
        alias.Translate(True)
        for clone in material_clones:
            target.InsertMaterial(clone)

        source_local = source_hair.GetMl()
        recovered.SetName(
            "Subdivision Surface_codex_recovered_dreadlocks_072526"
        )
        recovered.InsertUnder(target_root)
        recovered.SetMl(source_local)

        disabled = []
        for path in args.disable_target_path:
            op = find_path(target, path)
            if op is None:
                disabled.append({"path": path, "found": False})
                continue
            op.SetRenderMode(c4d.MODE_OFF)
            op.SetEditorMode(c4d.MODE_OFF)
            op.SetName(op.GetName() + "__offline_original")
            disabled.append({"path": path, "found": True})

        target.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        recovered_geometry = geometry_summary(recovered)
        local_delta = max(
            abs(left - right)
            for left, right in zip(
                matrix_values(source_local),
                matrix_values(recovered.GetMl()),
            )
        )
        linked_material_tags = sum(
            1
            for tag in walk_tags(recovered)
            if tag.CheckType(c4d.Ttexture) and tag.GetMaterial() is not None
        )
        report.update(
            {
                "targetFps": target.GetFps(),
                "sourceFps": source.GetFps(),
                "sourceGeometry": source_geometry,
                "recoveredGeometry": recovered_geometry,
                "localTransformDelta": local_delta,
                "clonedSourceMaterials": len(material_clones),
                "linkedMaterialTags": linked_material_tags,
                "disabledOfflineBranches": disabled,
            }
        )
        if local_delta > 1e-6:
            raise RuntimeError(
                f"Recovered hair local transform drifted ({local_delta})"
            )
        if recovered_geometry["cachePolygonCount"] < 5000:
            raise RuntimeError(
                "Recovered procedural hair did not evaluate enough polygons"
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
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        print(
            "PARACOSM_TH_HAIR_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        c4d.documents.KillDocument(target)
        c4d.documents.KillDocument(source)
        os._exit(0)


if __name__ == "__main__":
    main()
