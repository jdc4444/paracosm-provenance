"""Probe the exact shot hair sweep across source frames, read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

import c4d

from c4dpy_build_th_hanging_hair_recovery import find_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--frame", type=int, action="append", required=True)
    parser.add_argument(
        "--hair-root",
        default="walks in snow while shivering in wind v2/HAIR",
    )
    parser.add_argument(
        "--sweep",
        default=(
            "walks in snow while shivering in wind v2/HAIR/"
            "Subdivision Surface/Sweep"
        ),
    )
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
    records = []
    try:
        root = find_path(doc, args.hair_root)
        sweep = find_path(doc, args.sweep)
        if root is None or sweep is None:
            raise RuntimeError("Exact shot hair root or sweep is missing")
        fps = doc.GetFps()
        for frame in args.frame:
            doc.SetTime(c4d.BaseTime(frame, fps))
            doc.ExecutePasses(
                None,
                True,
                True,
                True,
                getattr(c4d, "BUILDFLAGS_NONE", 0),
            )
            cache = sweep.GetDeformCache() or sweep.GetCache()
            if not isinstance(cache, c4d.PolygonObject):
                raise RuntimeError(f"No polygon sweep cache at frame {frame}")
            transform = ~root.GetMg() * cache.GetMg()
            points = [transform * point for point in cache.GetAllPoints()]
            low = [
                min(point[index] for point in points)
                for index in range(3)
            ]
            high = [
                max(point[index] for point in points)
                for index in range(3)
            ]
            digest = hashlib.sha256()
            for point in points:
                digest.update(
                    struct.pack(
                        "<fff",
                        round(point.x, 4),
                        round(point.y, 4),
                        round(point.z, 4),
                    )
                )
            records.append(
                {
                    "frame": frame,
                    "seconds": frame / fps,
                    "pointCount": cache.GetPointCount(),
                    "polygonCount": cache.GetPolygonCount(),
                    "localBounds": {
                        "low": low,
                        "high": high,
                        "center": [
                            (low[index] + high[index]) * 0.5
                            for index in range(3)
                        ],
                        "extent": [
                            high[index] - low[index]
                            for index in range(3)
                        ],
                    },
                    "pointHash": digest.hexdigest(),
                }
            )
        print(
            "PARACOSM_HAIR_FRAME_PROBE_JSON="
            + json.dumps(
                {
                    "project": str(project),
                    "fps": fps,
                    "hairRoot": args.hair_root,
                    "sweep": args.sweep,
                    "records": records,
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
