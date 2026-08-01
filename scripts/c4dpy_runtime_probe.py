"""Print the exact Cinema 4D and Redshift runtime loaded by c4dpy."""

from __future__ import annotations

import json

import c4d


def main() -> None:
    payload: dict[str, object] = {
        "cinema4dVersion": c4d.GetC4DVersion(),
        "cinema4dPrefsPath": c4d.storage.GeGetC4DPath(c4d.C4D_PATH_PREFS),
    }
    try:
        import redshift

        payload["redshiftModuleAttributes"] = sorted(
            name
            for name in dir(redshift)
            if "version" in name.casefold()
        )
        for name in payload["redshiftModuleAttributes"]:
            value = getattr(redshift, name)
            if callable(value):
                try:
                    value = value()
                except Exception as error:
                    value = f"{type(error).__name__}: {error}"
            payload[f"redshift.{name}"] = str(value)
    except Exception as error:
        payload["redshiftImportError"] = f"{type(error).__name__}: {error}"
    print("PARACOSM_C4DPY_RUNTIME_JSON=" + json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
