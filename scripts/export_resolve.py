#!/usr/bin/env python3
"""Read-only export of the live Resolve Paracosm project."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
MODULES = Path(
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
    "Developer/Scripting/Modules"
)
sys.path.insert(0, str(MODULES))

import DaVinciResolveScript as dvr_script  # type: ignore  # noqa: E402


def safe_call(obj, name, default=None, *args):
    try:
        value = getattr(obj, name)(*args)
        return default if value is None else value
    except Exception:
        return default


def export() -> dict:
    resolve = dvr_script.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("DaVinci Resolve is not running or scripting is unavailable")
    manager = resolve.GetProjectManager()
    project = manager.GetCurrentProject()
    if not project:
        raise RuntimeError("Resolve has no current project")

    result = {
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "project": safe_call(project, "GetName", ""),
        "frameRate": safe_call(project, "GetSetting", "", "timelineFrameRate"),
        "timelines": [],
        "renderJobs": safe_call(project, "GetRenderJobList", []) or [],
    }

    timeline_count = int(safe_call(project, "GetTimelineCount", 0) or 0)
    for index in range(1, timeline_count + 1):
        timeline = safe_call(project, "GetTimelineByIndex", None, index)
        if not timeline:
            continue
        timeline_data = {
            "index": index,
            "name": safe_call(timeline, "GetName", f"Timeline {index}"),
            "startFrame": safe_call(timeline, "GetStartFrame", 0),
            "endFrame": safe_call(timeline, "GetEndFrame", 0),
            "startTimecode": safe_call(timeline, "GetStartTimecode", ""),
            "tracks": [],
        }
        track_count = int(safe_call(timeline, "GetTrackCount", 0, "video") or 0)
        for track_index in range(1, track_count + 1):
            items = safe_call(timeline, "GetItemListInTrack", [], "video", track_index) or []
            track_data = {
                "index": track_index,
                "name": safe_call(timeline, "GetTrackName", f"V{track_index}", "video", track_index),
                "items": [],
            }
            for item in items:
                media = safe_call(item, "GetMediaPoolItem")
                props = safe_call(media, "GetClipProperty", {}) if media else {}
                if not isinstance(props, dict):
                    props = {}
                track_data["items"].append(
                    {
                        "name": safe_call(item, "GetName", ""),
                        "start": safe_call(item, "GetStart", 0),
                        "end": safe_call(item, "GetEnd", 0),
                        "duration": safe_call(item, "GetDuration", 0),
                        "sourceStartFrame": safe_call(
                            item, "GetSourceStartFrame", None
                        ),
                        "sourceEndFrame": safe_call(
                            item, "GetSourceEndFrame", None
                        ),
                        "sourceStartTime": safe_call(
                            item, "GetSourceStartTime", None
                        ),
                        "sourceEndTime": safe_call(
                            item, "GetSourceEndTime", None
                        ),
                        "leftOffset": safe_call(item, "GetLeftOffset", 0, False),
                        "rightOffset": safe_call(item, "GetRightOffset", 0, False),
                        "mediaId": safe_call(media, "GetMediaId", "") if media else "",
                        "filePath": props.get("File Path") or props.get("FilePath") or "",
                        "clipProperties": props,
                    }
                )
            timeline_data["tracks"].append(track_data)
        result["timelines"].append(timeline_data)
    return result


if __name__ == "__main__":
    target = APP_ROOT / "data" / "resolve-export.json"
    data = export()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(
        f"Exported {len(data['timelines'])} timelines and "
        f"{len(data['renderJobs'])} render jobs to {target}"
    )
