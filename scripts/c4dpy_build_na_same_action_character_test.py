"""Build a dated NA test copy using only the exact same-action body/face FBX.

The input C4D document is loaded read-only. The output must live in a dated
``_codex_`` folder and must not already exist. Hair, cloth, wardrobe, and all
other scene branches are left untouched.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d
import maxon


TARGETS = (
    (
        "Ripping Wallpaper ABC/SKM_AbbyV2Character_BodyMesh",
        "/Null/SKM_AbbyV2Character_BodyMesh/Mesh_002",
    ),
    (
        "Ripping Wallpaper ABC/SKM_NewMetaHumanCharacter_FaceMesh",
        "/Null/SKM_NewMetaHumanCharacter_FaceMesh/Mesh_001",
    ),
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--alembic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--swap-yz",
        action="store_true",
        help=(
            "Place both existing character Alembic objects under a recovery "
            "null that swaps their local Y/Z axes. This compensates only for "
            "the verified FBX-to-Blender-to-Alembic basis change."
        ),
    )
    parser.add_argument(
        "--recovery-offset",
        nargs=3,
        type=float,
        default=(0.0, 0.0, 0.0),
        metavar=("X", "Y", "Z"),
    )
    parser.add_argument("--recovery-scale", type=float, default=1.0)
    parser.add_argument(
        "--override-offset-seconds",
        type=float,
        default=None,
        help=(
            "Override only the two replacement body/face Alembic time offsets. "
            "Hair and every other shot branch remain untouched."
        ),
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    alembic = args.alembic.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not project.is_file():
        raise FileNotFoundError(project)
    if not alembic.is_file():
        raise FileNotFoundError(alembic)
    if output == project:
        raise RuntimeError("Output resolves to the source project")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite output: {output}")
    if "_codex_" not in output.name.casefold() or not any(
        "_codex_" in parent.name.casefold() for parent in output.parents
    ):
        raise RuntimeError("Output must use a dated _codex_ name and folder")

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")

    report = {
        "sourceProject": str(project),
        "sameActionAlembic": str(alembic),
        "outputProject": str(output),
        "hairTouched": False,
        "changes": [],
        "saved": False,
        "basisSwapYZ": args.swap_yz,
        "recoveryOffset": list(args.recovery_offset),
        "recoveryScale": args.recovery_scale,
        "overrideOffsetSeconds": args.override_offset_seconds,
    }
    try:
        objects = {
            object_path(item): item
            for item in walk_objects(doc.GetFirstObject())
        }
        for path, identifier in TARGETS:
            item = objects.get(path)
            if item is None:
                raise RuntimeError(f"Required target not found: {path}")
            before_path = str(item[c4d.DescID(1000)])
            before_identifier = str(item[c4d.DescID(1001)])
            before_offset = item[c4d.DescID(1005)]
            item[c4d.DescID(1000)] = str(alembic)
            item[c4d.DescID(1001)] = identifier
            if args.override_offset_seconds is not None:
                item[c4d.DescID(1005)] = c4d.BaseTime(
                    args.override_offset_seconds
                )
            item.Message(c4d.MSG_UPDATE)
            after_offset = item[c4d.DescID(1005)]
            report["changes"].append(
                {
                    "objectPath": path,
                    "beforePath": before_path,
                    "afterPath": str(item[c4d.DescID(1000)]),
                    "beforeIdentifier": before_identifier,
                    "afterIdentifier": str(item[c4d.DescID(1001)]),
                    "offsetSecondsPreserved": before_offset.Get(),
                    "offsetFramesAt24FpsPreserved": before_offset.GetFrame(24),
                    "afterOffsetSeconds": after_offset.Get(),
                    "afterOffsetFramesAt24Fps": after_offset.GetFrame(24),
                }
            )

        if args.swap_yz:
            parent = objects.get("Ripping Wallpaper ABC")
            if parent is None:
                raise RuntimeError("Ripping Wallpaper ABC root not found")
            recovery = c4d.BaseObject(c4d.Onull)
            recovery.SetName(
                "NA_SAME_ACTION_BODY_FACE_BASIS_RECOVERY_codex_072626"
            )
            scale = args.recovery_scale
            recovery.SetMl(
                c4d.Matrix(
                    c4d.Vector(*args.recovery_offset),
                    c4d.Vector(scale, 0.0, 0.0),
                    c4d.Vector(0.0, 0.0, scale),
                    c4d.Vector(0.0, scale, 0.0),
                )
            )
            recovery.InsertUnder(parent)
            for path, _identifier in TARGETS:
                item = objects[path]
                item.Remove()
                item.InsertUnder(recovery)
                item.SetMl(c4d.Matrix())
            report["recoveryObjectPath"] = (
                "Ripping Wallpaper ABC/"
                "NA_SAME_ACTION_BODY_FACE_BASIS_RECOVERY_codex_072626"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        doc.GetDataInstance()[c4d.DOCUMENT_SECONDARYPATH] = maxon.Url(
            str(project.parent)
        )
        c4d.EventAdd()
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report["saved"] = bool(saved)
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
        print(
            "PARACOSM_NA_CHARACTER_TEST_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_NA_CHARACTER_TEST_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
