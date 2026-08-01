"""List top-level C4D object identities without loading project materials.

Run with Maxon's bundled c4dpy.  The source document is read-only and is
destroyed without saving.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def vector(value):
    return {"x": value.x, "y": value.y, "z": value.z}


def count_descendants(root) -> int:
    count = 0
    stack = []
    child = root.GetDown()
    while child:
        stack.append(child)
        child = child.GetNext()
    while stack:
        item = stack.pop()
        count += 1
        child = item.GetDown()
        while child:
            stack.append(child)
            child = child.GetNext()
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--name-contains")
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        records = []
        occurrence_by_name = {}
        root = doc.GetFirstObject()
        while root:
            name = root.GetName()
            occurrence = occurrence_by_name.get(name, 0)
            occurrence_by_name[name] = occurrence + 1
            if (
                not args.name_contains
                or args.name_contains.casefold() in name.casefold()
            ):
                matrix = root.GetMg()
                records.append(
                    {
                        "name": name,
                        "occurrence": occurrence,
                        "guid": str(root.GetGUID()),
                        "typeId": root.GetType(),
                        "editorMode": root.GetEditorMode(),
                        "renderMode": root.GetRenderMode(),
                        "position": vector(matrix.off),
                        "scale": vector(root.GetAbsScale()),
                        "descendantCount": count_descendants(root),
                        "trackCount": len(root.GetCTracks()),
                    }
                )
            root = root.GetNext()
        print(
            "PARACOSM_TOP_LEVEL_STATE_JSON="
            + json.dumps(
                {"project": str(project), "records": records},
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
