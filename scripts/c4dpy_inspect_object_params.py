"""Dump named parameters and raw values for one C4D object or material."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d

# Importing Redshift registers its private custom datatypes with the Python
# bridge.  Without this, legacy RSFILE parameters can appear as an unknown
# type even though the installed Redshift plugin can read them.
try:
    import redshift  # noqa: F401
except Exception:
    redshift = None


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


def safe_value(value, fps=None):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, c4d.Vector):
        return {"x": value.x, "y": value.y, "z": value.z}
    if isinstance(value, c4d.BaseTime):
        result = {
            "type": "BaseTime",
            "seconds": value.Get(),
        }
        if fps:
            result["frame"] = value.GetFrame(fps)
        return result
    result = {"type": type(value).__name__}
    try:
        result["repr"] = repr(value)
    except Exception as error:
        result["reprError"] = f"{type(error).__name__}: {error}"
    try:
        result["str"] = str(value)
    except Exception as error:
        result["strError"] = f"{type(error).__name__}: {error}"
    for method_name in ("GetString", "GetSystemPath", "GetUrl", "GetName"):
        method = getattr(value, method_name, None)
        if not callable(method):
            continue
        try:
            result[method_name] = str(method())
        except Exception as error:
            result[method_name + "Error"] = (
                f"{type(error).__name__}: {error}"
            )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--compact", action="store_true")
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--object")
    target_group.add_argument("--material")
    target_group.add_argument("--scene-hook-id", type=int)
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
        if args.scene_hook_id is not None:
            target = doc.FindSceneHook(args.scene_hook_id)
        elif args.material is not None:
            target = next(
                (
                    material
                    for material in doc.GetMaterials()
                    if material.GetName() == args.material
                ),
                None,
            )
        else:
            target = next(
                (
                    op
                    for op in walk_objects(doc.GetFirstObject())
                    if object_path(op) == args.object
                    or op.GetName() == args.object
                ),
                None,
            )
        if target is None:
            raise RuntimeError(
                "Target "
                f"{args.object or args.material or args.scene_hook_id!r} "
                "not found"
            )
        parameters = []
        description = target.GetDescription(
            getattr(c4d, "DESCFLAGS_DESC_0", 0)
        )
        for container, desc_id, _ in description:
            try:
                value = target[desc_id]
            except Exception:
                continue
            name = container.GetString(c4d.DESC_NAME)
            if value in ("", None, 0, 0.0, False) and not name:
                continue
            levels = [
                {
                    "id": level.id,
                    "dtype": level.dtype,
                    "creator": level.creator,
                }
                for level in (
                    desc_id[index] for index in range(desc_id.GetDepth())
                )
            ]
            parameters.append(
                {
                    "name": name,
                    "levels": levels,
                    "value": safe_value(value, doc.GetFps()),
                }
            )
        raw_values = []
        data = target.GetDataInstance()
        for parameter_id, value in data:
            raw_values.append(
                {
                    "id": parameter_id,
                    "value": safe_value(value, doc.GetFps()),
                }
            )
        report = {
            "project": str(project),
            "fps": doc.GetFps(),
            "name": target.GetName(),
            "path": (
                object_path(target)
                if isinstance(target, c4d.BaseObject)
                else None
            ),
            "typeId": target.GetType(),
            "pythonMethods": sorted(
                name
                for name in dir(target)
                if "sim" in name.casefold()
                or "mode" in name.casefold()
                or "cache" in name.casefold()
            ),
            "parameters": parameters,
            "rawValues": raw_values,
            "specialParameterAccess": [],
            "customDataAccess": [],
        }
        if args.compact:
            report["parameters"] = [
                item
                for item in parameters
                if any(
                    level["id"]
                    in (
                        500,
                        1000,
                        1001,
                        1005,
                        1020,
                        1027,
                        1028,
                        1031,
                        1032,
                        1220,
                        7002,
                        7003,
                    )
                    for level in item["levels"]
                )
            ]
            report["rawValues"] = [
                item
                for item in raw_values
                if item["id"]
                in (
                    500,
                    1000,
                    1001,
                    1005,
                    1020,
                    1027,
                    1028,
                    1031,
                    1032,
                    1220,
                    7002,
                    7003,
                )
            ]
        for parameter_id in (10000,):
            try:
                value = data.GetCustomDataType(parameter_id)
                report["customDataAccess"].append(
                    {
                        "id": parameter_id,
                        "value": safe_value(value, doc.GetFps()),
                    }
                )
            except Exception as error:
                report["customDataAccess"].append(
                    {
                        "id": parameter_id,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
        # Do not probe arbitrary BaseContainer getters here. Redshift's private
        # RSFILE value (dtype 1036765) can crash c4dpy when it is coerced through
        # a mismatched public getter. The description/raw-value evidence above
        # is the safe read-only boundary for unknown plugin datatypes.
        report["containerAccess"] = [
            {
                "status": "skipped_private_plugin_datatype_coercion",
                "parameterId": 10000,
            }
        ]
        for parameter_id in (
            500,
            1220,
            7002,
            7003,
            10000,
            12001,
            12002,
            12003,
            14000,
            14001,
            14002,
        ):
            try:
                value = target.GetParameter(
                    c4d.DescID(parameter_id),
                    getattr(c4d, "DESCFLAGS_GET_0", 0),
                )
                report["specialParameterAccess"].append(
                    {
                        "id": parameter_id,
                        "value": safe_value(value, doc.GetFps()),
                    }
                )
            except Exception as error:
                report["specialParameterAccess"].append(
                    {
                        "id": parameter_id,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
        # The plugin's Python convenience module is not exposed in every
        # c4dpy launch even though Redshift itself is loaded. The nested
        # DescID is still a safe read boundary in an isolated helper process,
        # so attempt it with Redshift's stable numeric custom-datatype ID.
        # A failure is captured per attempt and the source document is never
        # saved.
        if True:
            rsfile_type = (
                getattr(redshift, "CUSTOMDATATYPE_RSFILE", 1036765)
                if redshift is not None
                else 1036765
            )
            nested_attempts = (
                (
                    "typed_custom_then_filename",
                    c4d.DescID(
                        c4d.DescLevel(10000, rsfile_type, target.GetType()),
                        c4d.DescLevel(
                            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                            c4d.DTYPE_FILENAME,
                            0,
                        ),
                    ),
                ),
                (
                    "typed_custom_then_string",
                    c4d.DescID(
                        c4d.DescLevel(10000, rsfile_type, target.GetType()),
                        c4d.DescLevel(
                            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                            c4d.DTYPE_STRING,
                            0,
                        ),
                    ),
                ),
                (
                    "untyped_custom_then_filename",
                    c4d.DescID(
                        c4d.DescLevel(10000),
                        c4d.DescLevel(
                            getattr(c4d, "REDSHIFT_FILE_PATH", 1000),
                            c4d.DTYPE_FILENAME,
                            0,
                        ),
                    ),
                ),
            )
            for label, desc_id in nested_attempts:
                try:
                    value = target.GetParameter(
                        desc_id,
                        getattr(c4d, "DESCFLAGS_GET_0", 0),
                    )
                    report["specialParameterAccess"].append(
                        {
                            "label": label,
                            "levels": [
                                {
                                    "id": desc_id[index].id,
                                    "dtype": desc_id[index].dtype,
                                    "creator": desc_id[index].creator,
                                }
                                for index in range(desc_id.GetDepth())
                            ],
                            "value": safe_value(value, doc.GetFps()),
                        }
                    )
                except Exception as error:
                    report["specialParameterAccess"].append(
                        {
                            "label": label,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
            rsfile_fields = (
                ("animation_mode", 1001, c4d.DTYPE_LONG),
                ("timing_mode", 1002, c4d.DTYPE_LONG),
                ("frame_start", 1003, c4d.DTYPE_LONG),
                ("frame_end", 1004, c4d.DTYPE_LONG),
                ("frame_rate", 1005, c4d.DTYPE_LONG),
                ("range_start", 1006, c4d.DTYPE_TIME),
                ("range_end", 1007, c4d.DTYPE_TIME),
                ("frame_offset", 1008, c4d.DTYPE_LONG),
                ("loop_count", 1009, c4d.DTYPE_LONG),
            )
            for label, parameter_id, dtype in rsfile_fields:
                desc_id = c4d.DescID(
                    c4d.DescLevel(10000, rsfile_type, target.GetType()),
                    c4d.DescLevel(parameter_id, dtype, 0),
                )
                try:
                    value = target.GetParameter(
                        desc_id,
                        getattr(c4d, "DESCFLAGS_GET_0", 0),
                    )
                    report["specialParameterAccess"].append(
                        {
                            "label": label,
                            "levels": [
                                {
                                    "id": desc_id[index].id,
                                    "dtype": desc_id[index].dtype,
                                    "creator": desc_id[index].creator,
                                }
                                for index in range(desc_id.GetDepth())
                            ],
                            "value": safe_value(value, doc.GetFps()),
                        }
                    )
                except Exception as error:
                    report["specialParameterAccess"].append(
                        {
                            "label": label,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
        print(
            "PARACOSM_OBJECT_PARAMS_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        print(
            "PARACOSM_OBJECT_PARAMS_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "object": args.object,
                    "error": f"{type(error).__name__}: {error}",
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
