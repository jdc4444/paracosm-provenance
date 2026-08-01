"""Read-only topology inventory for one indexed C4D node material."""

from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path

import c4d
import maxon


NODE_SPACE = maxon.Id(
    "com.redshift3d.redshift4c4d.class.nodespace"
)


def safe(callable_value):
    stage = "load"
    try:
        value = callable_value()
        return str(value)
    except Exception as error:
        return f"<{type(error).__name__}: {error}>"


def walk_graph(parent):
    for child in parent.GetChildren():
        yield child
        yield from walk_graph(child)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--material-index", type=int, required=True)
    parser.add_argument("--frame", type=int, default=0)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    doc = c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        stage = "select_material"
        material = doc.GetFirstMaterial()
        for _ in range(args.material_index):
            if material is None:
                break
            material = material.GetNext()
        if material is None:
            raise RuntimeError(
                f"Material index not found: {args.material_index}"
            )
        stage = "open_graph"
        reference = material.GetNodeMaterialReference()
        if not reference.HasSpace(NODE_SPACE):
            raise RuntimeError("Material does not have a Redshift node graph")
        graph = reference.GetGraph(NODE_SPACE)
        root = graph.GetRoot()
        records = []
        first_methods = []
        stage = "iterate_graph"
        for item in walk_graph(root):
            stage = "inspect_graph_item"
            path = safe(item.GetPath)
            kind = safe(item.GetKind)
            connections = []
            if kind in {"8", "16"}:
                for direction_name, direction in (
                    ("input", maxon.PORT_DIR.INPUT),
                    ("output", maxon.PORT_DIR.OUTPUT),
                ):
                    try:
                        for target, wires in item.GetConnections(direction):
                            wires_text = str(wires)
                            if "Value:0" in wires_text:
                                continue
                            connections.append(
                                {
                                    "direction": direction_name,
                                    "targetPath": safe(target.GetPath),
                                    "wires": wires_text,
                                }
                            )
                    except Exception as error:
                        connections.append(
                            {
                                "direction": direction_name,
                                "error": (
                                    f"{type(error).__name__}: {error}"
                                ),
                            }
                        )
            records.append(
                {
                    "path": path,
                    "kind": kind,
                    "connections": connections,
                }
            )
        stage = "serialize"
        print(
            "PARACOSM_MATERIAL_GRAPH_TOPOLOGY_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "materialIndex": args.material_index,
                    "material": material.GetName(),
                    "graphMethods": sorted(
                        name
                        for name in dir(graph)
                        if "connect" in name.casefold()
                        or "wire" in name.casefold()
                    ),
                    "graphNodeMethods": first_methods,
                    "items": records,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_MATERIAL_GRAPH_TOPOLOGY_ERROR="
            + f"{stage} · {type(error).__name__}: {error}\n"
            + traceback.format_exc(),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
