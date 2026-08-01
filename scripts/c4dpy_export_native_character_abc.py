"""Export body/face geometry from a C4D-native same-action FBX import.

The source document is loaded read-only. Only the first root that contains the
two exact character mesh names is selected for Alembic export. Hair, wardrobe,
shoes, and all cross-shot assets are excluded.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


TARGET_NAMES = (
    "SKM_AbbyV2Character_BodyMesh",
    "SKM_NewMetaHumanCharacter_FaceMesh",
)


def walk_objects(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk_objects(op.GetDown())
        op = op.GetNext()


def object_path(op) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def descendants(root):
    prefix = object_path(root) + "/"
    for item in walk_objects(root.GetDown()):
        if not object_path(item).startswith(prefix):
            break
        yield item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument(
        "--full-root",
        action="store_true",
        help=(
            "Prune the in-memory document to one same-action rig root and "
            "export that root so Skin deformers are included."
        ),
    )
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if args.end < args.start:
        raise ValueError("--end must be greater than or equal to --start")
    if "_codex_" not in str(output).casefold():
        raise RuntimeError("Output must live in a dated _codex_ path")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite output: {output}")

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(source), flags)
    if doc is None:
        raise RuntimeError(f"Could not load source: {source}")
    report = {
        "source": str(source),
        "output": str(output),
        "frameRange": [args.start, args.end],
        "targets": [],
        "saved": False,
        "hairTouched": False,
        "fullRootExport": args.full_root,
        "inMemoryRemoved": [],
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        roots = list(walk_objects(doc.GetFirstObject()))
        root = next(
            (
                item
                for item in roots
                if item.GetUp() is None
                and TARGET_NAMES
                == tuple(
                    name
                    for name in TARGET_NAMES
                    if any(
                        child.GetName() == name
                        for child in descendants(item)
                    )
                )
            ),
            None,
        )
        if root is None:
            raise RuntimeError("No root contains both exact character meshes")
        root_descendants = list(descendants(root))
        targets = [
            next(
                (
                    item
                    for item in root_descendants
                    if item.GetName() == name
                ),
                None,
            )
            for name in TARGET_NAMES
        ]
        if any(item is None for item in targets):
            raise RuntimeError("Could not resolve both character targets")

        if args.full_root:
            for top_level in [
                item for item in roots if item.GetUp() is None and item is not root
            ]:
                report["inMemoryRemoved"].append(object_path(top_level))
                top_level.Remove()
            shoes = next(
                (
                    item
                    for item in descendants(root)
                    if item.GetUp() is root and item.GetName() == "Shoes"
                ),
                None,
            )
            if shoes is not None:
                report["inMemoryRemoved"].append(object_path(shoes))
                shoes.Remove()
        else:
            for index, item in enumerate(targets):
                doc.SetActiveObject(
                    item,
                    c4d.SELECTION_NEW if index == 0 else c4d.SELECTION_ADD,
                )
        doc.SetMinTime(c4d.BaseTime(args.start, doc.GetFps()))
        doc.SetMaxTime(c4d.BaseTime(args.end, doc.GetFps()))
        doc.SetTime(c4d.BaseTime(args.start, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            c4d.BUILDFLAGS_EXTERNALRENDERER,
        )

        plugin = c4d.plugins.FindPlugin(
            c4d.FORMAT_ABCEXPORT, c4d.PLUGINTYPE_SCENESAVER
        )
        if plugin is None:
            raise RuntimeError("Cinema 4D Alembic scene saver is unavailable")
        private_data = {}
        if not plugin.Message(c4d.MSG_RETRIEVEPRIVATEDATA, private_data):
            raise RuntimeError("Could not retrieve Alembic exporter settings")
        exporter = private_data.get("imexporter")
        if exporter is None:
            raise RuntimeError("Alembic exporter settings container is absent")
        exporter[c4d.ABCEXPORT_FRAME_START] = args.start
        exporter[c4d.ABCEXPORT_FRAME_END] = args.end
        exporter[c4d.ABCEXPORT_FRAME_STEP] = 1
        exporter[c4d.ABCEXPORT_SUBFRAMES] = 1
        exporter[c4d.ABCEXPORT_SELECTION_ONLY] = not args.full_root
        exporter[c4d.ABCEXPORT_VISIBILITY] = True
        exporter[c4d.ABCEXPORT_NORMALS] = True
        exporter[c4d.ABCEXPORT_UVS] = True
        exporter[c4d.ABCEXPORT_POLYGONSELECTIONS] = True
        exporter[c4d.ABCEXPORT_HYPERNURBS] = False
        exporter[c4d.ABCEXPORT_SPLINES] = False
        exporter[c4d.ABCEXPORT_HAIR] = False
        exporter[c4d.ABCEXPORT_PARTICLES] = False
        exporter[c4d.ABCEXPORT_MERGE_CACHE] = True
        exporter[c4d.ABCEXPORT_GLOBAL_MATRIX] = False

        output.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_ABCEXPORT,
        )
        report["saved"] = bool(saved)
        report["sourceRoot"] = object_path(root)
        report["targets"] = [
            {
                "path": object_path(item),
                "pointCount": item.GetPointCount(),
                "polygonCount": item.GetPolygonCount(),
            }
            for item in targets
        ]
        report["outputBytes"] = (
            output.stat().st_size if output.is_file() else None
        )
        print(
            "PARACOSM_NATIVE_CHARACTER_ABC_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
        if not saved or not output.is_file():
            raise RuntimeError("Cinema 4D Alembic export failed")
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_NATIVE_CHARACTER_ABC_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
