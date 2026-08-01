"""Attach the dated NTH recovery to the offline proxy's surviving motion.

The Redshift proxy mesh is unavailable, but its animated child Null and Target
remain evaluable in the render-time project. This helper clones that motion
hierarchy into the dated recovery, parents the recovered body/cloth and hair
branches beneath it while preserving their calibrated frame-60 world state,
and saves a new v002 file. The input project is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import c4d


PROXY_NAME = "02NTHI2_slow_walk_into_run_v2_Proxy_01_0016__offline_original"
RECOVERY_ROOT_NAME = "NTH_RUNNING_PROXY_RECOVERY_codex_072526"
HAIR_ROOT_NAME = "NTH_RUNNING_HAIR_codex_072526"
DRIVER_PARENT_NAME = "NTH_RUNNING_PROXY_PARENT_DRIVER_codex_072526"
DRIVER_NAME = "NTH_RUNNING_PROXY_MOTION_DRIVER_codex_072526"


def walk_objects(op):
    while op:
        yield op
        child = op.GetDown()
        if child:
            yield from walk_objects(child)
        op = op.GetNext()


def object_path(op) -> str:
    result = []
    while op:
        result.insert(0, op.GetName())
        op = op.GetUp()
    return "/".join(result)


def find_object(doc, name: str):
    return next(
        (
            op
            for op in walk_objects(doc.GetFirstObject())
            if op.GetName() == name or object_path(op) == name
        ),
        None,
    )


def matrix_record(value: c4d.Matrix) -> dict:
    def vector(item):
        return {"x": item.x, "y": item.y, "z": item.z}

    return {
        "off": vector(value.off),
        "v1": vector(value.v1),
        "v2": vector(value.v2),
        "v3": vector(value.v3),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-frame", type=int, default=60)
    parser.add_argument(
        "--calibration-offset",
        nargs=3,
        type=float,
        default=(-0.772, 0.0, 1.046),
    )
    args = parser.parse_args()

    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    report = {
        "input": str(input_path),
        "output": str(output_path),
        "saved": False,
    }
    if output_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing recovery: {output_path}"
        )

    flags = (
        c4d.SCENEFILTER_OBJECTS
        | c4d.SCENEFILTER_MATERIALS
        | c4d.SCENEFILTER_DONTCORRECTOUTPUTFORMAT
    )
    doc = c4d.documents.LoadDocument(str(input_path), flags)
    if doc is None:
        raise RuntimeError(f"Could not load {input_path}")
    try:
        c4d.documents.SetActiveDocument(doc)
        proxy = find_object(doc, PROXY_NAME)
        recovery_root = find_object(doc, RECOVERY_ROOT_NAME)
        hair_root = find_object(doc, HAIR_ROOT_NAME)
        if proxy is None or recovery_root is None or hair_root is None:
            raise RuntimeError(
                "Recovery project is missing the offline proxy, recovered "
                "body/cloth root, or recovered hair root"
            )
        motion_null = proxy.GetDown()
        if motion_null is None or motion_null.GetName() != "Null":
            raise RuntimeError(
                "Offline proxy no longer contains its animated child Null"
            )

        fps = doc.GetFps()
        doc.SetTime(c4d.BaseTime(args.reference_frame, fps))
        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        source_driver_at_reference = motion_null.GetMg()

        driver_parent = c4d.BaseObject(c4d.Onull)
        driver_parent.SetName(DRIVER_PARENT_NAME)
        driver_parent.SetMg(proxy.GetMg())
        driver_parent.SetEditorMode(c4d.MODE_ON)
        driver_parent.SetRenderMode(c4d.MODE_ON)
        doc.InsertObject(driver_parent)

        driver = motion_null.GetClone(c4d.COPYFLAGS_NONE)
        if driver is None:
            raise RuntimeError("Could not clone the surviving proxy motion")
        driver.SetName(DRIVER_NAME)
        driver.SetEditorMode(c4d.MODE_ON)
        driver.SetRenderMode(c4d.MODE_ON)
        driver.InsertUnder(driver_parent)

        calibration = c4d.Vector(*args.calibration_offset)
        attached = []
        for root in (recovery_root, hair_root):
            world = root.GetMg()
            world.off += calibration
            root.InsertUnder(driver)
            root.SetMg(world)
            root.SetEditorMode(c4d.MODE_ON)
            root.SetRenderMode(c4d.MODE_ON)
            attached.append(
                {
                    "path": object_path(root),
                    "referenceWorldMatrix": matrix_record(root.GetMg()),
                }
            )

        doc.ExecutePasses(
            None,
            True,
            True,
            True,
            getattr(c4d, "BUILDFLAGS_NONE", 0),
        )
        cloned_driver_at_reference = driver.GetMg()
        driver_error = (
            cloned_driver_at_reference.off - source_driver_at_reference.off
        ).GetLength()
        if driver_error > 1e-5:
            raise RuntimeError(
                f"Cloned motion driver differs by {driver_error} world units"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        saved = c4d.documents.SaveDocument(
            doc,
            str(output_path),
            c4d.SAVEDOCUMENTFLAGS_DONTADDTORECENTLIST,
            c4d.FORMAT_C4DEXPORT,
        )
        report.update(
            {
                "saved": bool(saved),
                "fps": fps,
                "referenceFrame": args.reference_frame,
                "calibrationOffset": list(args.calibration_offset),
                "sourceDriverAtReference": matrix_record(
                    source_driver_at_reference
                ),
                "clonedDriverAtReference": matrix_record(
                    cloned_driver_at_reference
                ),
                "driverWorldError": driver_error,
                "attachedRoots": attached,
            }
        )
        if not saved:
            raise RuntimeError("Cinema 4D SaveDocument returned false")
        print(
            "PARACOSM_NTH_PROXY_MOTION_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(
            "PARACOSM_NTH_PROXY_MOTION_JSON="
            + json.dumps(report, separators=(",", ":")),
            flush=True,
        )
    finally:
        c4d.documents.KillDocument(doc)
        os._exit(0)


if __name__ == "__main__":
    main()
