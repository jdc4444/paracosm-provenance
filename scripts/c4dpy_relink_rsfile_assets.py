"""Create a dated C4D copy with exact Redshift RSFILE assets relinked."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import c4d
import maxon
import redshift


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op: c4d.BaseObject) -> str:
    names = []
    while op:
        names.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(names)


def find_object(doc, target: str) -> c4d.BaseObject | None:
    return next(
        (
            op
            for op in walk_objects(doc.GetFirstObject())
            if object_path(op) == target or op.GetName() == target
        ),
        None,
    )


def normalized_file_path(value: object) -> Path:
    text = str(value)
    if text.startswith("file:"):
        text = unquote(urlparse(text).path)
    return Path(text).expanduser().resolve()


def path_desc_id(op: c4d.BaseObject, parameter_id: int) -> c4d.DescID:
    return c4d.DescID(
        c4d.DescLevel(
            parameter_id,
            redshift.CUSTOMDATATYPE_RSFILE,
            op.GetType(),
        ),
        c4d.DescLevel(
            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
            c4d.DTYPE_FILENAME,
            0,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--update-existing-dated-copy",
        action="store_true",
        help=(
            "Save back to an existing Codex-dated recovery copy. Originals "
            "cannot pass the filename/folder guard."
        ),
    )
    parser.add_argument(
        "--asset",
        action="append",
        required=True,
        metavar="OBJECT_PATH|PARAMETER_ID|FILE_PATH",
    )
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if project == output and not args.update_existing_dated_copy:
        raise RuntimeError("Output must differ from the source project")
    if output.exists() and not args.update_existing_dated_copy:
        raise RuntimeError(f"Refusing to overwrite existing output: {output}")
    if "_codex_" not in output.name.casefold() or not any(
        "_codex_" in parent.name.casefold() for parent in output.parents
    ):
        raise RuntimeError(
            "Output filename and an ancestor folder must contain _codex_"
        )
    specifications = []
    for raw in args.asset:
        try:
            target, raw_parameter_id, raw_path = raw.split("|", 2)
            parameter_id = int(raw_parameter_id)
            file_path = Path(raw_path).expanduser().resolve()
        except Exception as error:
            raise RuntimeError(
                "--asset must be OBJECT_PATH|PARAMETER_ID|FILE_PATH; "
                f"received {raw!r}"
            ) from error
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        specifications.append((target, parameter_id, file_path))
    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(project), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {project}")
    report: dict[str, object] = {
        "c4dVersion": c4d.GetC4DVersion(),
        "sourceProject": str(project),
        "outputProject": str(output),
        "changes": [],
        "saved": False,
    }
    try:
        for target, parameter_id, file_path in specifications:
            op = find_object(doc, target)
            if op is None:
                raise RuntimeError(f"Object not found: {target}")
            desc_id = path_desc_id(op, parameter_id)
            original_value = op.GetParameter(
                desc_id, getattr(c4d, "DESCFLAGS_GET_0", 0)
            )
            changed = op.SetParameter(
                desc_id,
                str(file_path),
                getattr(c4d, "DESCFLAGS_SET_0", 0),
            )
            op.Message(c4d.MSG_UPDATE)
            verified_value = op.GetParameter(
                desc_id, getattr(c4d, "DESCFLAGS_GET_0", 0)
            )
            if normalized_file_path(verified_value) != file_path:
                raise RuntimeError(
                    f"RSFILE path did not verify for {object_path(op)} "
                    f"parameter {parameter_id}: {verified_value}"
                )
            report["changes"].append(
                {
                    "objectPath": object_path(op),
                    "parameterId": parameter_id,
                    "originalPath": str(original_value),
                    "targetPath": str(file_path),
                    "verifiedPath": str(verified_value),
                    "changed": bool(changed),
                    "bytes": file_path.stat().st_size,
                }
            )
        c4d.EventAdd()
        output.parent.mkdir(parents=True, exist_ok=True)
        doc.GetDataInstance()[c4d.DOCUMENT_SECONDARYPATH] = maxon.Url(
            str(output.parent)
        )
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
            "PARACOSM_RSFILE_RELINK_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_RSFILE_RELINK_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
