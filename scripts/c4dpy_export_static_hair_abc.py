"""Export a dated, static Alembic recovery from a confirmed hair mesh.

This creates only a dependency file in a Codex-dated folder. It never edits
the source C4D/FBX document. The result is deliberately identified as a static
fallback: it can restore the canonical hair silhouette and shared material
inputs, but it does not claim to reproduce a missing shot-specific rope cache.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


ALEMBIC_SCENE_SAVER_ID = 1028082


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-object", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-name", default="Subdivision Surface")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if "_codex_" not in str(output).casefold():
        raise RuntimeError("Output must live in a Codex-dated recovery path")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    source_doc = c4d.documents.LoadDocument(
        str(source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if source_doc is None:
        raise RuntimeError(f"Could not load source: {source}")
    export_doc = c4d.documents.BaseDocument()
    try:
        source_object = next(
            (
                op
                for op in walk_objects(source_doc.GetFirstObject())
                if op.GetName() == args.source_object
                or object_path(op) == args.source_object
            ),
            None,
        )
        if source_object is None:
            raise RuntimeError(
                f"Source object not found: {args.source_object}"
            )
        clone = source_object.GetClone(c4d.COPYFLAGS_NONE)
        clone.SetName(args.object_name)
        clone.SetMg(source_object.GetMg())
        export_doc.InsertObject(clone)
        export_doc.SetFps(source_doc.GetFps())
        export_doc.SetMinTime(source_doc.GetMinTime())
        export_doc.SetMaxTime(source_doc.GetMaxTime())
        saved = c4d.documents.SaveDocument(
            export_doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            ALEMBIC_SCENE_SAVER_ID,
        )
        payload = {
            "source": str(source),
            "sourceObject": object_path(source_object),
            "output": str(output),
            "objectName": args.object_name,
            "saved": bool(saved),
            "staticFallback": True,
            "shotSpecificDynamicsRecovered": False,
        }
        print(
            "PARACOSM_STATIC_HAIR_ABC_JSON="
            + json.dumps(payload, separators=(",", ":")),
            flush=True,
        )
        if not saved:
            raise RuntimeError("Alembic SaveDocument returned false")
    finally:
        c4d.documents.KillDocument(source_doc)
        c4d.documents.KillDocument(export_doc)
        os._exit(0)


if __name__ == "__main__":
    main()
