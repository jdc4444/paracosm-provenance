"""Print the bitmap API exposed by the installed Cinema 4D Python runtime."""

from __future__ import annotations

import json
import os

import c4d


def main() -> None:
    bitmap = c4d.bitmaps.MultipassBitmap(8, 8, c4d.COLORMODE_RGB)
    layer = bitmap.AddChannel(True, True)
    payload = {
        "multipassBitmap": [
            name
            for name in dir(bitmap)
            if "layer" in name.casefold()
            or "pixel" in name.casefold()
            or "color" in name.casefold()
            or "save" in name.casefold()
        ],
        "channel": [
            name
            for name in dir(layer)
            if "layer" in name.casefold()
            or "pixel" in name.casefold()
            or "color" in name.casefold()
            or "save" in name.casefold()
        ],
    }
    print(json.dumps(payload, indent=2), flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
