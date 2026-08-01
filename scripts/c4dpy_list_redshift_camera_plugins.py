"""List installed Cinema 4D plugins whose names mention Redshift or cameras."""

from __future__ import annotations

import json
import os

import c4d


def main() -> None:
    records = []
    for type_name in (
        "PLUGINTYPE_OBJECT",
        "PLUGINTYPE_TAG",
        "PLUGINTYPE_SCENEHOOK",
        "PLUGINTYPE_VIDEOPOST",
        "PLUGINTYPE_COMMAND",
    ):
        plugin_type = getattr(c4d, type_name, None)
        if plugin_type is None:
            continue
        for item in c4d.plugins.FilterPluginList(plugin_type, True):
            plugin = (
                item
                if isinstance(item, c4d.plugins.BasePlugin)
                else c4d.plugins.FindPlugin(item, plugin_type)
            )
            plugin_id = (
                int(plugin.GetID()) if plugin is not None else int(item)
            )
            name = plugin.GetName() if plugin is not None else None
            normalized = str(name or "").casefold()
            if "redshift" not in normalized and "camera" not in normalized:
                continue
            records.append(
                {
                    "pluginTypeName": type_name,
                    "pluginType": int(plugin_type),
                    "id": plugin_id,
                    "name": name,
                }
            )
    print(
        "PARACOSM_REDSHIFT_CAMERA_PLUGINS_JSON="
        + json.dumps(records, separators=(",", ":")),
        flush=True,
    )
    os._exit(0)


if __name__ == "__main__":
    main()
