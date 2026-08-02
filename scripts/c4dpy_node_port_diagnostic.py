"""Inspect exact Redshift graph ports without modifying or saving a project."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d
import maxon


def walk_takes(take, result: dict[str, object]) -> None:
    current = take
    while current:
        result[current.GetName()] = current
        child = current.GetDown()
        if child:
            walk_takes(child, result)
        current = current.GetNext()


def safe_value(callable_value) -> dict[str, object]:
    try:
        value = callable_value()
        return {
            "ok": True,
            "type": type(value).__name__,
            "string": str(value),
            "repr": repr(value),
        }
    except Exception as error:
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--take", default="Main")
    parser.add_argument("--material-term", action="append", default=[])
    parser.add_argument(
        "--material-index", action="append", type=int, default=[]
    )
    parser.add_argument("--path-term", action="append", default=[])
    parser.add_argument("--result-json", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    try:
        take_data = doc.GetTakeData()
        takes: dict[str, object] = {}
        if take_data:
            walk_takes(take_data.GetMainTake(), takes)
            selected_take = takes.get(args.take)
            if selected_take is None:
                raise RuntimeError(f"Take not found: {args.take}")
            take_data.SetCurrentTake(selected_take)
        doc.SetTime(c4d.BaseTime(args.frame, doc.GetFps()))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        node_space = maxon.Id(
            "com.redshift3d.redshift4c4d.class.nodespace"
        )
        terms = tuple(args.path_term)
        material_terms = tuple(
            item.casefold() for item in args.material_term if item
        )
        material_indexes = set(args.material_index)
        records: list[dict[str, object]] = []
        material = doc.GetFirstMaterial()
        material_index = 0
        while material:
            if material_indexes and material_index not in material_indexes:
                material = material.GetNext()
                material_index += 1
                continue
            if material_terms and not any(
                term in material.GetName().casefold()
                for term in material_terms
            ):
                material = material.GetNext()
                material_index += 1
                continue
            reference = material.GetNodeMaterialReference()
            if not reference.HasSpace(node_space):
                material = material.GetNext()
                material_index += 1
                continue
            graph = reference.GetGraph(node_space)
            root = graph.GetRoot()
            for item in root.GetInnerNodes(maxon.NODE_KIND.ALL_MASK, True):
                path = str(item.GetPath())
                if terms and not any(term in path for term in terms):
                    continue
                values: dict[str, object] = {}
                for method_name in (
                    "GetPortValue",
                    "GetDefaultValue",
                    "GetEffectivePortValue",
                    "GetStoredValue",
                ):
                    method = getattr(item, method_name, None)
                    if method is not None:
                        values[method_name] = safe_value(method)
                records.append(
                    {
                        "material": material.GetName(),
                        "materialIndex": material_index,
                        "path": path,
                        "kind": safe_value(
                            lambda graph_item=item: graph_item.GetKind()
                        ),
                        "values": values,
                    }
                )
            material = material.GetNext()
            material_index += 1
        payload = {
            "project": str(project),
            "frame": args.frame,
            "take": args.take,
            "materialTerms": list(material_terms),
            "materialIndexes": sorted(material_indexes),
            "pathTerms": list(terms),
            "matches": records,
        }
        output = args.result_json.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            "PARACOSM_NODE_PORT_DIAGNOSTIC_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "frame": args.frame,
                    "take": args.take,
                    "materialTerms": list(material_terms),
                    "materialIndexes": sorted(material_indexes),
                    "pathTerms": list(terms),
                    "matchCount": len(records),
                    "resultJson": str(output),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    except Exception as error:
        payload = {
            "project": str(project),
            "frame": args.frame,
            "take": args.take,
            "materialTerms": list(args.material_term),
            "materialIndexes": list(args.material_index),
            "pathTerms": list(args.path_term),
            "error": f"{type(error).__name__}: {error}",
        }
        output = args.result_json.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(
            "PARACOSM_NODE_PORT_DIAGNOSTIC_ERROR="
            + payload["error"],
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
