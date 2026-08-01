"""Apply native facial FBX curves to Abby's 1:1 C4D rig and repair weights."""

from __future__ import annotations

import argparse
import collections
import gzip
import importlib.util
import json
import os
from pathlib import Path

import c4d


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


def desc_id(payload: list[list[int]]) -> c4d.DescID:
    return c4d.DescID(
        *[
            c4d.DescLevel(int(item[0]), int(item[1]), int(item[2]))
            for item in payload
        ]
    )


def load_weight_repair():
    source = Path(__file__).with_name(
        "create-abby-slide7-facial-animation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "abby_face_weight_repair", source
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import weight repair from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.repair_facial_weights


def remove_tracks(doc) -> int:
    removed = 0
    for item in walk_objects(doc.GetFirstObject()):
        for track in list(item.GetCTracks()):
            track.Remove()
            removed += 1
    return removed


def choose_targets(name: str, candidates, targets):
    if name == "root":
        return [
            item
            for root_name in ("root.002", "root.003")
            for item in targets.get(root_name, [])
            if object_path(item) == root_name
        ]
    if len(candidates) == 1:
        return candidates
    shared = [
        item
        for item in candidates
        if object_path(item).startswith(("root.002/", "root.003/"))
    ]
    return shared


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--motion-cache", type=Path, required=True)
    parser.add_argument("--blender-weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    cache_path = args.motion_cache.expanduser().resolve()
    weights_path = args.blender_weights.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if source == output:
        raise RuntimeError("Retarget output cannot overwrite the C4D master")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite derived scene: {output}")

    with gzip.open(cache_path, "rt", encoding="utf-8") as handle:
        cache = json.load(handle)
    fps = int(cache["fps"])
    start_frame = int(cache["startFrame"])
    end_frame = int(cache["endFrame"])

    doc = c4d.documents.LoadDocument(
        str(source),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )
    if doc is None:
        raise RuntimeError(f"Could not load {source}")

    report = {
        "source": str(source),
        "mocapSource": cache["source"],
        "motionCache": str(cache_path),
        "output": str(output),
        "masterUntouched": True,
        "fps": fps,
        "frames": end_frame - start_frame + 1,
        "scope": "FACIAL_* hierarchy only",
        "matchedSourceObjects": 0,
        "targetAssignments": 0,
        "missingObjects": [],
        "tracksRemoved": 0,
        "curvesApplied": 0,
        "keysApplied": 0,
        "weightRepair": None,
    }
    try:
        c4d.documents.SetActiveDocument(doc)
        take_data = doc.GetTakeData()
        main_take = take_data.GetMainTake() if take_data else None
        if take_data and main_take:
            take_data.SetCurrentTake(main_take)

        targets = collections.defaultdict(list)
        for item in walk_objects(doc.GetFirstObject()):
            targets[item.GetName()].append(item)
        report["tracksRemoved"] = remove_tracks(doc)
        report["weightRepair"] = load_weight_repair()(
            doc, weights_path
        )

        for record in cache["objects"]:
            if not record["name"].startswith("FACIAL_"):
                continue
            selected_targets = choose_targets(
                record["name"],
                targets.get(record["name"], []),
                targets,
            )
            if not selected_targets:
                report["missingObjects"].append(record["path"])
                continue
            report["matchedSourceObjects"] += 1
            report["targetAssignments"] += len(selected_targets)
            for target in selected_targets:
                for track_record in record["tracks"]:
                    parameter_id = desc_id(track_record["desc"])
                    target_base = float(
                        target.GetParameter(
                            parameter_id, c4d.DESCFLAGS_GET_0
                        )
                    )
                    source_base = float(track_record["base"])
                    target.SetParameter(
                        parameter_id,
                        target_base,
                        c4d.DESCFLAGS_SET_0,
                    )
                    values = track_record["values"]
                    if values is None:
                        continue
                    parameter_root = int(track_record["desc"][0][0])
                    if (
                        parameter_root == c4d.ID_BASEOBJECT_REL_SCALE
                        and abs(source_base) > 1.0e-9
                    ):
                        retargeted_values = [
                            target_base * (float(value) / source_base)
                            for value in values
                        ]
                    else:
                        retargeted_values = [
                            target_base + (float(value) - source_base)
                            for value in values
                        ]
                    track = c4d.CTrack(target, parameter_id)
                    track[c4d.ID_CTRACK_ANIMOFF] = True
                    target.InsertTrackSorted(track)
                    curve = track.GetCurve()
                    if curve is None:
                        raise RuntimeError(
                            f"Could not create curve on {target.GetName()}"
                        )
                    for index, value in enumerate(retargeted_values):
                        frame = start_frame + index
                        added = curve.AddKey(c4d.BaseTime(frame, fps))
                        key = added["key"]
                        key.SetValue(curve, float(value))
                        key.SetInterpolation(
                            curve, c4d.CINTERPOLATION_LINEAR
                        )
                    report["curvesApplied"] += 1
                    report["keysApplied"] += len(retargeted_values)

        doc.SetFps(fps)
        doc.SetMinTime(c4d.BaseTime(start_frame, fps))
        doc.SetMaxTime(c4d.BaseTime(end_frame, fps))
        doc.SetLoopMinTime(c4d.BaseTime(start_frame, fps))
        doc.SetLoopMaxTime(c4d.BaseTime(end_frame, fps))
        doc.SetTime(c4d.BaseTime(start_frame, fps))
        doc.ExecutePasses(None, True, True, True, 0)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        if not saved:
            raise RuntimeError(f"Could not save {output}")
        print(
            "ABBY_FBX_MOCAP_RETARGET="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)


if __name__ == "__main__":
    main()
    os._exit(0)
