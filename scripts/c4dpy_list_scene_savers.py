"""List Cinema 4D scene-saver plugins for reproducible interchange exports."""

from __future__ import annotations

import json
import os

import c4d


def main() -> None:
    records = []
    for item in c4d.plugins.FilterPluginList(
        c4d.PLUGINTYPE_SCENESAVER, True
    ):
        plugin = (
            item
            if isinstance(item, c4d.plugins.BasePlugin)
            else c4d.plugins.FindPlugin(
                item, c4d.PLUGINTYPE_SCENESAVER
            )
        )
        records.append(
            {
                "id": int(plugin.GetID()) if plugin is not None else int(item),
                "name": plugin.GetName() if plugin is not None else None,
            }
        )
    print(
        "PARACOSM_SCENE_SAVERS_JSON="
        + json.dumps(records, separators=(",", ":")),
        flush=True,
    )
    os._exit(0)


if __name__ == "__main__":
    main()
