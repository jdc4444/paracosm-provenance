#!/usr/bin/env python3
"""Report render-related constants exposed by the installed Cinema 4D Python API."""

from __future__ import annotations

import json

import c4d


def main() -> None:
    names = sorted(
        name
        for name in dir(c4d)
        if name.startswith("RENDERFLAGS_")
        or name.startswith("RDATA_BAKE_OCIO")
    )
    print(
        json.dumps(
            {
                name: getattr(c4d, name)
                for name in names
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
