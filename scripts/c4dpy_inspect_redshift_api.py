"""Inspect the Redshift Python surface and one proxy dependency graph.

Run with Maxon's bundled c4dpy. This script is read-only.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
from pathlib import Path

import c4d


def safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): safe(item) for key, item in value.items()}
    if isinstance(value, c4d.BaseContainer):
        return {
            "type": "BaseContainer",
            "entries": [
                {"id": parameter_id, "value": safe(item)}
                for parameter_id, item in value
            ],
        }
    result = {"type": type(value).__name__}
    try:
        result["repr"] = repr(value)
    except Exception as error:
        result["reprError"] = f"{type(error).__name__}: {error}"
    try:
        result["str"] = str(value)
    except Exception as error:
        result["strError"] = f"{type(error).__name__}: {error}"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", type=Path)
    args = parser.parse_args()
    import_attempts = {}
    redshift = getattr(c4d, "redshift", None)
    for module_name in (
        "redshift",
        "c4d.redshift",
        "c4d.modules.redshift",
        "c4d.modules",
    ):
        try:
            module = importlib.import_module(module_name)
            import_attempts[module_name] = {
                "type": type(module).__name__,
                "names": sorted(
                    name for name in dir(module) if not name.startswith("_")
                ),
            }
            if module_name.endswith("redshift"):
                redshift = module
        except Exception as error:
            import_attempts[module_name] = {
                "error": f"{type(error).__name__}: {error}"
            }
    report = {
        "c4dVersion": c4d.GetC4DVersion(),
        "redshiftType": type(redshift).__name__ if redshift else None,
        "redshiftNames": sorted(name for name in dir(redshift) if not name.startswith("_"))
        if redshift
        else [],
        "importAttempts": import_attempts,
        "geDataNames": sorted(
            name for name in dir(c4d) if "GeData" in name or "CustomData" in name
        ),
        "maxonNames": [],
        "proxy": str(args.proxy.expanduser().resolve()) if args.proxy else None,
    }
    custom_type_attempts = {}
    custom_type_ids = []
    for owner_name, owner in (("redshift", redshift), ("c4d", c4d)):
        if owner is None:
            continue
        type_id = getattr(owner, "CUSTOMDATATYPE_RSFILE", None)
        if isinstance(type_id, int):
            custom_type_ids.append((owner_name, type_id))
    for function_name in (
        "GetCustomDataTypeDefault",
        "GetCustomDatatypeDefault",
    ):
        function = getattr(c4d, function_name, None)
        if not callable(function):
            continue
        for owner_name, type_id in custom_type_ids:
            key = f"{function_name}:{owner_name}:{type_id}"
            try:
                value = function(type_id)
                value_report = {
                    "value": safe(value),
                    "type": type(value).__name__,
                }
                value_report["names"] = sorted(
                    name for name in dir(value) if not name.startswith("_")
                )
                custom_type_attempts[key] = value_report
            except Exception as error:
                custom_type_attempts[key] = {
                    "error": f"{type(error).__name__}: {error}"
                }
    report["customTypeAttempts"] = custom_type_attempts
    report["redshiftCallableDocs"] = {}
    if redshift:
        for name in sorted(
            name
            for name in dir(redshift)
            if any(token in name.casefold() for token in ("file", "proxy"))
        ):
            value = getattr(redshift, name)
            entry = {"type": type(value).__name__}
            if callable(value):
                try:
                    entry["signature"] = str(inspect.signature(value))
                except Exception as error:
                    entry["signatureError"] = f"{type(error).__name__}: {error}"
                doc = inspect.getdoc(value)
                if doc:
                    entry["doc"] = doc
            else:
                entry["value"] = safe(value)
            report["redshiftCallableDocs"][name] = entry
    try:
        import maxon

        report["maxonNames"] = sorted(
            name
            for name in dir(maxon)
            if any(token in name.lower() for token in ("url", "file", "data"))
        )
    except Exception as error:
        report["maxonError"] = f"{type(error).__name__}: {error}"
    if args.proxy and redshift and hasattr(redshift, "GetProxyDependencies"):
        path = str(args.proxy.expanduser().resolve())
        attempts = {}
        values = [path, c4d.storage.FilenameConvert(path)]
        try:
            import maxon

            values.append(maxon.Url(path))
        except Exception:
            pass
        for value in values:
            label = type(value).__name__
            try:
                attempts[label] = safe(redshift.GetProxyDependencies(value))
            except Exception as error:
                attempts[label] = {
                    "error": f"{type(error).__name__}: {error}",
                    "value": safe(value),
                }
        report["getProxyDependencies"] = attempts
    print(
        "PARACOSM_REDSHIFT_API_JSON="
        + json.dumps(report, separators=(",", ":")),
        flush=True,
    )
    os._exit(0)


if __name__ == "__main__":
    main()
