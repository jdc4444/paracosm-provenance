#!/usr/bin/env python3
"""Inspect a Redshift ``.rs`` proxy without requiring a compatible renderer.

Redshift proxies are chunked zlib containers. This read-only inspector extracts
the producer version, source-document/object evidence, and external texture
references, then resolves those references against the shared Absolutely tree.
"""

from __future__ import annotations

import argparse
import json
import re
import zlib
from datetime import datetime, timezone
from pathlib import Path

from resolve_c4d_dependencies import index_files, ranked_candidates


DEFAULT_ROOT = Path(
    "/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely"
)
PATH_EXTENSION = re.compile(
    r"(?i)\.(?:png|jpe?g|tiff?|exr|tx|hdr|psd|bmp|tga|abc|fbx|obj|usd|usdz|rs)"
    r"$"
)
PRINTABLE = re.compile(rb"[ -~]{4,}")
SOURCE_NAMESPACE = re.compile(r"(?i)^(.+?\.c4d):(.+)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iter_zlib_chunks(data: bytes):
    position = 0
    while position < len(data) - 2:
        found = None
        for index in range(position, len(data) - 2):
            cmf, flag = data[index], data[index + 1]
            if cmf & 15 == 8 and ((cmf << 8) | flag) % 31 == 0:
                found = index
                break
        if found is None:
            return
        try:
            inflater = zlib.decompressobj()
            unpacked = inflater.decompress(data[found:])
            unpacked += inflater.flush()
            if not inflater.eof or not unpacked:
                position = found + 1
                continue
            consumed = len(data[found:]) - len(inflater.unused_data)
            yield found, consumed, unpacked
            position = found + max(consumed, 2)
        except zlib.error:
            position = found + 1


def printable_strings(data: bytes):
    for match in PRINTABLE.finditer(data):
        text = match.group().decode("utf-8", "ignore").strip()
        if text:
            yield text


def dependency_string(value: str) -> bool:
    if len(value) > 1000 or not PATH_EXTENSION.search(value):
        return False
    return (
        "/" in value
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value) is not None
    )


def local_exact_candidate(
    required: str, proxy: Path, root: Path
) -> Path | None:
    normalized = required.replace("\\", "/")
    folded = normalized.casefold()
    marker = "/absolutely/"
    if marker in folded:
        index = folded.index(marker) + len(marker)
        candidate = root / normalized[index:]
        if candidate.exists():
            return candidate
    if re.match(r"^[A-Za-z]:/", normalized):
        marker_without_leading = "absolutely/"
        if marker_without_leading in folded:
            index = folded.index(marker_without_leading) + len(
                marker_without_leading
            )
            candidate = root / normalized[index:]
            if candidate.exists():
                return candidate
    if normalized.startswith("../") or normalized.startswith("./"):
        candidate = (proxy.parent / normalized).resolve()
        if candidate.exists():
            return candidate
    direct = Path(normalized).expanduser()
    if direct.is_absolute() and direct.exists():
        return direct
    return None


def category_for(path: str) -> str:
    value = path.casefold()
    if "hair" in value:
        return "hair"
    if any(
        token in value
        for token in ("outfit", "fabric", "garment", "cloth", "shoe")
    ):
        return "wardrobe"
    if any(
        token in value
        for token in (
            "skin",
            "face",
            "eye",
            "lash",
            "metahuman",
            "abby_merged",
        )
    ):
        return "character"
    return "environment_or_other"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proxy", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    proxy = args.proxy.expanduser().resolve()
    root = args.root.expanduser().resolve()
    if not proxy.exists():
        raise FileNotFoundError(proxy)

    raw = proxy.read_bytes()
    chunks = list(iter_zlib_chunks(raw))
    all_strings = set()
    for _, _, unpacked in chunks:
        all_strings.update(printable_strings(unpacked))

    producer_version = None
    if chunks:
        header_strings = list(printable_strings(chunks[0][2]))
        producer_version = next(
            (
                value
                for value in header_strings
                if re.fullmatch(r"\d{4}\.\d+\.\d+", value)
            ),
            None,
        )

    source_documents = set()
    source_members = set()
    for value in all_strings:
        match = SOURCE_NAMESPACE.match(value)
        if not match:
            continue
        source_documents.add(match.group(1))
        source_members.add(match.group(2))

    dependencies = sorted(
        {value for value in all_strings if dependency_string(value)},
        key=str.casefold,
    )
    _, by_basename, by_stem = index_files(root)
    dependency_records = []
    for required in dependencies:
        exact = local_exact_candidate(required, proxy, root)
        if exact:
            status = "recovered_exact_path"
            candidates = [{"path": str(exact), "exactRelativeSuffix": True}]
        else:
            status, candidates = ranked_candidates(
                required, by_basename, by_stem
            )
        dependency_records.append(
            {
                "requiredPath": required,
                "basename": Path(required.replace("\\", "/")).name,
                "category": category_for(required),
                "status": status,
                "candidates": candidates,
            }
        )

    status_counts = {}
    category_counts = {}
    for record in dependency_records:
        status_counts[record["status"]] = (
            status_counts.get(record["status"], 0) + 1
        )
        category = record["category"]
        category_counts.setdefault(category, {})
        category_counts[category][record["status"]] = (
            category_counts[category].get(record["status"], 0) + 1
        )

    member_values = sorted(source_members, key=str.casefold)
    evidence = {
        "bodyMesh": [
            value for value in member_values if "bodymesh" in value.casefold()
        ][:30],
        "faceMesh": [
            value for value in member_values if "facemesh" in value.casefold()
        ][:30],
        "hair": [
            value for value in member_values if "hair" in value.casefold()
        ][:60],
        "wardrobe": [
            value
            for value in member_values
            if any(
                token in value.casefold()
                for token in (
                    "cloth",
                    "garment",
                    "outfit",
                    "shoe",
                    "dress",
                    "jacket",
                    "pants",
                )
            )
        ][:60],
        "camera": [
            value for value in member_values if "camera" in value.casefold()
        ][:30],
    }
    payload = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "proxyPath": str(proxy),
        "sizeBytes": proxy.stat().st_size,
        "modifiedAt": datetime.fromtimestamp(
            proxy.stat().st_mtime, timezone.utc
        ).isoformat(),
        "container": {
            "magic": raw[:12].decode("ascii", "replace"),
            "zlibChunks": len(chunks),
            "compressedBytesParsed": sum(item[1] for item in chunks),
            "uncompressedBytesParsed": sum(len(item[2]) for item in chunks),
            "producerVersion": producer_version,
        },
        "sourceDocuments": sorted(source_documents, key=str.casefold),
        "sourceMemberCount": len(source_members),
        "embeddedEvidence": evidence,
        "summary": {
            "dependencyCount": len(dependency_records),
            "dependencyByStatus": dict(sorted(status_counts.items())),
            "dependencyByCategoryAndStatus": {
                key: dict(sorted(value.items()))
                for key, value in sorted(category_counts.items())
            },
            "bodyMeshPresent": bool(evidence["bodyMesh"]),
            "faceMeshPresent": bool(evidence["faceMesh"]),
            "hairPresent": bool(evidence["hair"]),
            "wardrobePresent": bool(evidence["wardrobe"]),
            "cameraPresent": bool(evidence["camera"]),
        },
        "dependencies": dependency_records,
    }
    output = args.output
    if output:
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        "PARACOSM_RS_PROXY_AUDIT_JSON="
        + json.dumps(
            {
                "output": str(output) if output else None,
                "proxyPath": str(proxy),
                "producerVersion": producer_version,
                "summary": payload["summary"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
