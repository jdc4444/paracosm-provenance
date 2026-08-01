"""Clone known-good FBX transform tracks onto one target joint for diagnosis."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


def walk(op):
    while op:
        yield op
        if op.GetDown():
            yield from walk(op.GetDown())
        op = op.GetNext()


def path(op):
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def load(project):
    return c4d.documents.LoadDocument(
        str(project),
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-object", required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--target-object", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")
    source_doc = load(args.source.expanduser().resolve())
    target_doc = load(args.target.expanduser().resolve())
    if source_doc is None or target_doc is None:
        raise RuntimeError("Could not load source/target")
    try:
        source = next(item for item in walk(source_doc.GetFirstObject()) if path(item) == args.source_object)
        target = next(item for item in walk(target_doc.GetFirstObject()) if path(item) == args.target_object)
        take_data = target_doc.GetTakeData()
        if take_data:
            take_data.SetCurrentTake(take_data.GetMainTake())
        for track in list(target.GetCTracks()):
            track.Remove()
        count = 0
        for track in source.GetCTracks():
            clone = track.GetClone(c4d.COPYFLAGS_0)
            target.InsertTrackSorted(clone)
            count += 1
        target_doc.SetFps(source_doc.GetFps())
        target_doc.SetMinTime(source_doc.GetMinTime())
        target_doc.SetMaxTime(source_doc.GetMaxTime())
        target_doc.SetTime(c4d.BaseTime(0, target_doc.GetFps()))
        target_doc.ExecutePasses(None, True, True, True, 0)
        if not c4d.documents.SaveDocument(
            target_doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        ):
            raise RuntimeError("Could not save probe")
        print("C4D_CLONE_TRACK_PROBE=" + json.dumps({"output": str(output), "tracks": count}), flush=True)
    finally:
        c4d.documents.KillDocument(source_doc)
        c4d.documents.KillDocument(target_doc)


if __name__ == "__main__":
    main()
    os._exit(0)
