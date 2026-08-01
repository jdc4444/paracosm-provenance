"""Retired cross-shot hair experiment retained only for forensic provenance.

Hair is authored per shot. Importing or cloning a hair hierarchy from another
project cannot establish canonical linkage, even when timing and root
transforms match. This script is deliberately non-runnable.
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


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def walk_subtree(op):
    """Yield one hierarchy only; never cross into root-level siblings."""
    yield op
    child = op.GetDown()
    while child:
        yield from walk_subtree(child)
        child = child.GetNext()


def walk_tags(op):
    for item in walk_subtree(op):
        tag = item.GetFirstTag()
        while tag:
            yield tag
            tag = tag.GetNext()


def child_named(parent, name: str):
    child = parent.GetDown()
    while child:
        if child.GetName() == name:
            return child
        child = child.GetNext()
    return None


def top_named(doc, name: str):
    op = doc.GetFirstObject()
    while op:
        if op.GetName() == name:
            return op
        op = op.GetNext()
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
    records = []
    for op in walk_subtree(root):
        cache = op.GetDeformCache() or op.GetCache()
        points = (
            op.GetPointCount() if isinstance(op, c4d.PointObject) else None
        )
        polygons = (
            op.GetPolygonCount() if isinstance(op, c4d.PolygonObject) else None
        )
        cache_points = (
            cache.GetPointCount()
            if isinstance(cache, c4d.PointObject)
            else None
        )
        cache_polygons = (
            cache.GetPolygonCount()
            if isinstance(cache, c4d.PolygonObject)
            else None
        )
        if any(
            value not in (None, 0)
            for value in (points, polygons, cache_points, cache_polygons)
        ):
            records.append(
                {
                    "name": op.GetName(),
                    "typeId": op.GetType(),
                    "pointCount": points,
                    "polygonCount": polygons,
                    "cachePointCount": cache_points,
                    "cachePolygonCount": cache_polygons,
                }
            )
    return records


def main() -> None:
    raise RuntimeError(RETIRED_REASON)
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--hair-source", type=Path, required=True)
    parser.add_argument("--wardrobe-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-frame", type=int, default=490)
    parser.add_argument("--source-frame", type=int, default=392)
    args = parser.parse_args()

    target_path = args.target.expanduser().resolve()
    source_path = args.hair_source.expanduser().resolve()
    wardrobe_path = args.wardrobe_cache.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output in (target_path, source_path):
        raise RuntimeError("Output must not overwrite either source project")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite recovery copy: {output}")
    if "_codex_072526" not in output.name or output.parent.name != "_codex_072526":
        raise RuntimeError("Recovery output must use the _codex_072526 convention")
    if not wardrobe_path.is_file():
        raise RuntimeError(f"Wardrobe cache missing: {wardrobe_path}")

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
        "wardrobeCache": str(wardrobe_path),
        "outputProject": str(output),
        "saved": False,
    }
    try:
        target_fps = target.GetFps()
        source_fps = source.GetFps()
        target_seconds = args.target_frame / target_fps
        source_seconds = args.source_frame / source_fps
        if abs(target_seconds - source_seconds) > 1e-9:
            raise RuntimeError("Source and target frames do not represent equal time")

        target.SetTime(c4d.BaseTime(args.target_frame, target_fps))
        source.SetTime(c4d.BaseTime(args.source_frame, source_fps))
        target.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        source.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )
        target_character = top_named(
            target, "walks in snow while shivering in wind v2"
        )
        source_character = top_named(
            source, "walks in snow while shivering in wind v2"
        )
        if target_character is None or source_character is None:
            raise RuntimeError("Matching character roots were not found")
        old_hair = child_named(target_character, "Hair")
        source_hair = child_named(source_character, "HAIR")
        target_cloth = child_named(target_character, "cloth_parent")
        if old_hair is None or source_hair is None or target_cloth is None:
            raise RuntimeError("Required Hair/HAIR/cloth_parent objects missing")

        deltas = [
            abs(a - b)
            for a, b in zip(
                matrix_values(old_hair.GetMg()),
                matrix_values(source_hair.GetMg()),
            )
        ]
        transform_delta = max(deltas)
        source_geometry = geometry_summary(source_hair)
        if transform_delta > 1e-6:
            raise RuntimeError(
                f"Hair root transform mismatch ({transform_delta:.8f})"
            )
        if not any(
            (item.get("cachePolygonCount") or item.get("polygonCount") or 0)
            > 0
            for item in source_geometry
        ):
            raise RuntimeError("Source hair hierarchy has no evaluated polygons")

        alias = c4d.AliasTrans()
        if not alias.Init(source):
            raise RuntimeError("Could not initialize the C4D alias translator")
        material_clones = []
        material = source.GetFirstMaterial()
        while material:
            clone = material.GetClone(c4d.COPYFLAGS_NONE, alias)
            clone.SetName(f"{material.GetName()} [CUT-033 CODEX HAIR]")
            material_clones.append(clone)
            material = material.GetNext()

        recovered_hair = source_hair.GetClone(c4d.COPYFLAGS_NONE, alias)
        alias.Translate(True)
        for clone in material_clones:
            target.InsertMaterial(clone)
        recovered_hair.SetName("HAIR_codex_recovery_072526")
        recovered_hair.InsertUnder(target_character)
        linked_material_tags = 0
        for tag in walk_tags(recovered_hair):
            if not tag.CheckType(c4d.Ttexture):
                continue
            linked_material_tags += int(tag.GetMaterial() is not None)

        old_hair.SetName("Hair__offline_original")
        old_hair.SetRenderMode(c4d.MODE_OFF)
        old_hair.SetEditorMode(c4d.MODE_OFF)
        try:
            target_cloth[c4d.DescID(1000)] = c4d.Filename(
                str(wardrobe_path)
            )
        except Exception:
            target_cloth[c4d.DescID(1000)] = str(wardrobe_path)
        target_cloth.Message(c4d.MSG_UPDATE)
        c4d.EventAdd()
        target.ExecutePasses(
            None, True, True, True, getattr(c4d, "BUILDFLAGS_NONE", 0)
        )

        recovered_delta = max(
            abs(a - b)
            for a, b in zip(
                matrix_values(recovered_hair.GetMg()),
                matrix_values(old_hair.GetMg()),
            )
        )
        recovered_geometry = geometry_summary(recovered_hair)
        cloth_cache = target_cloth.GetDeformCache() or target_cloth.GetCache()
        report.update(
            {
                "targetFps": target_fps,
                "sourceFps": source_fps,
                "targetFrame": args.target_frame,
                "sourceFrame": args.source_frame,
                "matchedTimeSeconds": target_seconds,
                "preflightRootTransformDelta": transform_delta,
                "postCloneRootTransformDelta": recovered_delta,
                "sourceHairGeometry": source_geometry,
                "recoveredHairGeometry": recovered_geometry,
                "clonedSourceMaterials": len(material_clones),
                "linkedMaterialTags": linked_material_tags,
                "wardrobeCacheTypeId": (
                    cloth_cache.GetType() if cloth_cache is not None else None
                ),
            }
        )
        if recovered_delta > 1e-6:
            raise RuntimeError(
                f"Recovered hair transform drifted ({recovered_delta:.8f})"
            )
        if not any(
            (item.get("cachePolygonCount") or item.get("polygonCount") or 0)
            > 0
            for item in recovered_geometry
        ):
            raise RuntimeError("Recovered hair produced no evaluated polygons")

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
            "PARACOSM_CUT033_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_CUT033_RECOVERY_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        if target is not None:
            c4d.documents.KillDocument(target)
        if source is not None:
            c4d.documents.KillDocument(source)
        os._exit(0)


if __name__ == "__main__":
    main()
