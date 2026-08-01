"""Create a dated C4D copy with one exact Redshift proxy sequence relinked.

The source document is never saved. The requested proxy sequence must exist
contiguously across the frame range already recorded on the proxy object.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import c4d
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


def desc_id(op: c4d.BaseObject, sub_id: int, dtype: int) -> c4d.DescID:
    return c4d.DescID(
        c4d.DescLevel(
            getattr(c4d, "REDSHIFT_PROXY_FILE", 10000),
            redshift.CUSTOMDATATYPE_RSFILE,
            op.GetType(),
        ),
        c4d.DescLevel(sub_id, dtype, 0),
    )


def get_nested(op: c4d.BaseObject, sub_id: int, dtype: int):
    return op.GetParameter(
        desc_id(op, sub_id, dtype),
        getattr(c4d, "DESCFLAGS_GET_0", 0),
    )


def contiguous_sequence(
    first_file: Path,
    first_frame: int,
    last_frame: int,
) -> tuple[list[Path], str]:
    match = re.match(r"^(.*?)(\d{4})(\.rs)$", first_file.name, re.IGNORECASE)
    if not match:
        raise RuntimeError(
            "Proxy filename must end in a four-digit frame before .rs: "
            f"{first_file}"
        )
    prefix, digits, suffix = match.groups()
    seed_frame = int(digits)
    if seed_frame != first_frame:
        raise RuntimeError(
            f"Proxy seed frame {seed_frame} does not match saved start "
            f"frame {first_frame}"
        )
    paths = [
        first_file.with_name(f"{prefix}{frame:04d}{suffix}")
        for frame in range(first_frame, last_frame + 1)
    ]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        sample = " | ".join(str(path) for path in missing[:10])
        raise RuntimeError(
            f"Proxy sequence is missing {len(missing)} frames: {sample}"
        )
    return paths, prefix


def normalized_file_path(value: object) -> Path:
    text = str(value)
    if text.startswith("file:"):
        text = unquote(urlparse(text).path)
    return Path(text).expanduser().resolve()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object", required=True)
    parser.add_argument("--proxy-file", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    output = args.output.expanduser().resolve()
    proxy_file = args.proxy_file.expanduser().resolve()
    if project == output:
        raise RuntimeError("Output must differ from the source project")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {output}")
    if "_codex_" not in output.name.casefold() or not any(
        "_codex_" in parent.name.casefold() for parent in output.parents
    ):
        raise RuntimeError(
            "Output filename and an ancestor folder must contain _codex_"
        )
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
        "requestedObject": args.object,
        "proxyFile": str(proxy_file),
        "saved": False,
    }
    try:
        proxy = find_object(doc, args.object)
        if proxy is None:
            raise RuntimeError(f"Proxy object not found: {args.object}")
        if proxy.GetType() != redshift.Orsproxy:
            raise RuntimeError(
                f"Target is not a Redshift proxy: {object_path(proxy)}"
            )
        path_desc = desc_id(
            proxy,
            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
            c4d.DTYPE_FILENAME,
        )
        original_path = get_nested(
            proxy,
            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
            c4d.DTYPE_FILENAME,
        )
        frame_start = int(
            get_nested(
                proxy,
                getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_START", 1003),
                c4d.DTYPE_REAL,
            )
        )
        frame_end = int(
            get_nested(
                proxy,
                getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_END", 1004),
                c4d.DTYPE_REAL,
            )
        )
        frame_rate = float(
            get_nested(
                proxy,
                getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_RATE", 1005),
                c4d.DTYPE_REAL,
            )
        )
        frame_offset = float(
            get_nested(
                proxy,
                getattr(c4d, "REDSHIFT_FILE_ANIMATION_FRAME_OFFSET", 1008),
                c4d.DTYPE_REAL,
            )
        )
        sequence, prefix = contiguous_sequence(
            proxy_file, frame_start, frame_end
        )
        changed = proxy.SetParameter(
            path_desc,
            str(proxy_file),
            getattr(c4d, "DESCFLAGS_SET_0", 0),
        )
        proxy.Message(c4d.MSG_UPDATE)
        c4d.EventAdd()
        verified_path = get_nested(
            proxy,
            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
            c4d.DTYPE_FILENAME,
        )
        if normalized_file_path(verified_path) != proxy_file:
            raise RuntimeError(
                "RSFILE path did not verify after SetParameter: "
                f"{verified_path}"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report.update(
            {
                "objectPath": object_path(proxy),
                "originalProxyPath": str(original_path),
                "changed": bool(changed),
                "verifiedProxyPath": str(verified_path),
                "sequencePrefix": prefix,
                "frameStart": frame_start,
                "frameEnd": frame_end,
                "frameRate": frame_rate,
                "frameOffset": frame_offset,
                "sequenceFiles": len(sequence),
                "sequenceBytes": sum(path.stat().st_size for path in sequence),
                "saved": bool(saved),
            }
        )
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
        print(
            "PARACOSM_RS_PROXY_RELINK_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_RS_PROXY_RELINK_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
