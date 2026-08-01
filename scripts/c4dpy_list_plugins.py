"""List installed Cinema 4D plugins whose names match search terms."""

from __future__ import annotations

import argparse
import json
import os

import c4d


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("terms", nargs="+", help="case-insensitive name fragments")
    args = parser.parse_args()
    terms = tuple(term.casefold() for term in args.terms)
    records = []
    for plugin_type in (
        c4d.PLUGINTYPE_OBJECT,
        c4d.PLUGINTYPE_TAG,
        c4d.PLUGINTYPE_TOOL,
        c4d.PLUGINTYPE_COMMAND,
    ):
        for plugin in c4d.plugins.FilterPluginList(plugin_type, True):
            name = str(plugin.GetName() or "")
            if any(term in name.casefold() for term in terms):
                records.append(
                    {
                        "id": int(plugin.GetID()),
                        "name": name,
                        "type": int(plugin_type),
                    }
                )
    print(
        "C4D_PLUGIN_MATCHES="
        + json.dumps(sorted(records, key=lambda item: (item["name"], item["id"]))),
        flush=True,
    )


if __name__ == "__main__":
    main()
    os._exit(0)
