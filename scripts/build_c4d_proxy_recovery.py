#!/usr/bin/env python3
"""Map active Redshift proxies to proxy files or reconstructable sources."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ABSOLUTELY = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
SCENE_AUDIT = ROOT / "data" / "c4d-scene-state-audit.json"
PROXY_AUDIT_DIR = ROOT / "data" / "redshift-proxy-audits"
OUTPUT = ROOT / "data" / "c4d-proxy-recovery.json"

EXPLICIT_PROXY_FILES = {
    "001ndi1_teacup_v1": ABSOLUTELY / "SG/C4D/Teacup_V1_Proxy_01_0414.rs",
    "cut-062": (
        ABSOLUTELY
        / "SG/CHARACTER_MODEL/Abby_Metahuman_Greece_Flying_v001/"
        "Abby_Metahuman_Greece_Flying_v001_0066.rs"
    ),
}

MOTION_PATTERNS = (
    re.compile(r"(?i)(02NTHI2_slow_walk_into_run_v2)"),
    re.compile(r"(?i)(02NTHI4_scales_cliff_v3)"),
    re.compile(r"(?i)(02NTHI5_tosses_garment)(?:_SIM)?(?:_v\d+)?"),
    re.compile(r"(?i)(001NDI1[_ ]Teacup[_ ]v1)"),
    re.compile(r"(?i)(01NDI1[_ ]Teacup[_ ]v2)"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_inventory(root: Path) -> list[Path]:
    result = subprocess.run(
        ["rg", "--files", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(value) for value in result.stdout.splitlines() if value]


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def motion_token(proxy_name: str) -> str | None:
    for pattern in MOTION_PATTERNS:
        match = pattern.search(proxy_name)
        if match:
            return re.sub(r"[_ ]+", "_", match.group(1))
    return None


def source_components(token: str | None, files: list[Path]) -> list[dict]:
    if not token:
        return []
    key = normalized(token)
    candidates = []
    for path in files:
        if path.suffix.casefold() not in {".fbx", ".abc", ".c4d", ".rs"}:
            continue
        if key not in normalized(str(path)):
            continue
        category = "other"
        folded = path.name.casefold()
        if "body" in folded or "fbx-fixed" in folded or "iclone" in folded:
            category = "body"
        elif "face" in folded:
            category = "face"
        elif "boot" in folded:
            category = "boots"
        elif "cloth" in folded or "garment" in folded:
            category = "cloth"
        elif path.suffix.casefold() == ".rs":
            category = "proxy"
        candidates.append(
            {
                "path": str(path),
                "category": category,
                "sizeBytes": path.stat().st_size,
                "modifiedAt": datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat(),
            }
        )
    candidates.sort(
        key=lambda item: (
            item["category"],
            -(item["sizeBytes"] or 0),
            item["path"].casefold(),
        )
    )
    return candidates


def explicit_proxy(cuts: list[str], name: str) -> Path | None:
    if "CUT-062" in cuts:
        return EXPLICIT_PROXY_FILES["cut-062"]
    folded = normalized(name)
    if "001ndi1teacupv1" in folded:
        return EXPLICIT_PROXY_FILES["001ndi1_teacup_v1"]
    return None


def audit_for_proxy(proxy: Path) -> dict | None:
    for path in PROXY_AUDIT_DIR.glob("*.json"):
        try:
            audit = json.loads(path.read_text())
        except Exception:
            continue
        if audit.get("proxyPath") == str(proxy):
            return {"path": str(path), "audit": audit}
    return None


def main() -> None:
    scene = json.loads(SCENE_AUDIT.read_text())
    files = file_inventory(ABSOLUTELY)
    records = []
    for project in scene.get("projects", []):
        active_proxies = [
            item
            for item in project.get("redshiftProxies", [])
            if item.get("effectiveRenderEnabled")
        ]
        if not active_proxies:
            continue
        for proxy_object in active_proxies:
            name = proxy_object["name"]
            token = motion_token(name)
            proxy_file = explicit_proxy(project["cuts"], name)
            if proxy_file is not None and not proxy_file.exists():
                proxy_file = None
            components = source_components(token, files)
            proxy_audit = audit_for_proxy(proxy_file) if proxy_file else None
            categories = {item["category"] for item in components}
            source_complete = (
                {"body", "face", "boots", "cloth"}.issubset(categories)
                if token
                else False
            )
            runtime_compatible_sequence_missing = (
                proxy_file is not None and "CUT-008" in project["cuts"]
            )
            if runtime_compatible_sequence_missing:
                status = "proxy_sequence_missing_runtime_compatible"
            elif proxy_file:
                status = "proxy_present_renderer_blocked"
            elif source_complete:
                status = "proxy_missing_source_components_complete"
            elif components:
                status = "proxy_missing_source_components_partial"
            else:
                status = "proxy_missing_sources_unresolved"
            records.append(
                {
                    "projectPath": project["projectPath"],
                    "cuts": project["cuts"],
                    "proxyObjectName": name,
                    "proxyObjectPath": proxy_object["path"],
                    "proxyObjectRenderEnabled": True,
                    "editableCharacterDiagnosis": project["diagnosis"],
                    "motionToken": token,
                    "status": status,
                    "proxyFile": str(proxy_file) if proxy_file else None,
                    "proxyAuditPath": (
                        proxy_audit["path"] if proxy_audit else None
                    ),
                    "proxyAuditSummary": (
                        proxy_audit["audit"].get("summary")
                        if proxy_audit
                        else None
                    ),
                    "producerVersion": (
                        proxy_audit["audit"]
                        .get("container", {})
                        .get("producerVersion")
                        if proxy_audit
                        else None
                    ),
                    "rendererCompatibility": (
                        {
                            "installed": "Cinema 4D 2026.3 embedded Redshift",
                            "requiredMinimum": "Redshift 2026.2.1 / mesh 49",
                            "status": "compatible_static_proxy_rendered",
                            "evidence": (
                                "CUT-008-c4d2026p3-newer-runtime-visual-audit.json"
                            ),
                            "remainingBlocker": (
                                "Exact authored animated proxy sequence "
                                "01NDI1_Teacup_v2_JosCup_01_0080-2160.rs"
                            ),
                        }
                        if runtime_compatible_sequence_missing
                        else {
                            "installed": "Redshift 2026.1.1 / mesh 47",
                            "requiredMinimum": "Redshift 2026.2.1 / mesh 49",
                            "currentOfficial": "Redshift 2026.8.0",
                            "status": "incompatible_update_required",
                        }
                        if proxy_file
                        else None
                    ),
                    "sourceComponentsComplete": source_complete,
                    "sourceComponents": components,
                }
            )

    cut_records = {}
    for record in records:
        for cut in record["cuts"]:
            cut_records.setdefault(cut, []).append(record)
    status_counts = {}
    for record in records:
        status_counts[record["status"]] = (
            status_counts.get(record["status"], 0) + 1
        )
    payload = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "authority": (
            "Active Redshift proxy objects from read-only C4D inspection, "
            "matched to exact proxy files or the body/face/boots/cloth source "
            "components needed to regenerate missing proxies."
        ),
        "summary": {
            "activeProxyObjects": len(records),
            "affectedCuts": len(cut_records),
            "byStatus": dict(sorted(status_counts.items())),
            "proxyFilesPresent": sum(bool(item["proxyFile"]) for item in records),
            "missingProxiesWithCompleteSourceComponents": sum(
                item["status"] == "proxy_missing_source_components_complete"
                for item in records
            ),
        },
        "records": records,
        "cuts": cut_records,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        "PARACOSM_C4D_PROXY_RECOVERY_JSON="
        + json.dumps(
            {"output": str(OUTPUT), "summary": payload["summary"]},
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
