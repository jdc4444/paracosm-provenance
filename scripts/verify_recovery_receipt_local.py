#!/usr/bin/env python3
"""Verify a Windows recovery receipt against its hydrated macOS mirror."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(record: dict[str, Any]) -> str:
    value = record.get("destinationRelativePath") or record.get(
        "relativePath"
    )
    if not value:
        raise ValueError("receipt record has no relative destination path")
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--hash", action="store_true")
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()

    receipt_path = args.receipt.expanduser().resolve()
    local_root = args.local_root.expanduser().resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    records = list(receipt.get("records") or receipt.get("files") or [])
    missing: list[dict[str, Any]] = []
    size_mismatches: list[dict[str, Any]] = []
    hash_mismatches: list[dict[str, Any]] = []
    verified_files = 0
    verified_bytes = 0
    hashed_files = 0

    for record in records:
        relative = relative_path(record)
        target = local_root.joinpath(*relative.replace("/", "\\").split("\\"))
        source = record.get("source") or {}
        expected_bytes = int(
            source.get("bytes")
            if source.get("bytes") is not None
            else record.get("destinationBytes")
            or 0
        )
        expected_hash = str(
            source.get("sha256")
            or record.get("destinationSha256")
            or ""
        ).casefold()
        if not target.is_file():
            missing.append(
                {
                    "relativePath": relative,
                    "expectedBytes": expected_bytes,
                }
            )
            continue
        actual_bytes = target.stat().st_size
        if actual_bytes != expected_bytes:
            size_mismatches.append(
                {
                    "relativePath": relative,
                    "expectedBytes": expected_bytes,
                    "actualBytes": actual_bytes,
                }
            )
            continue
        if args.hash and expected_hash:
            actual_hash = sha256(target)
            hashed_files += 1
            if actual_hash.casefold() != expected_hash:
                hash_mismatches.append(
                    {
                        "relativePath": relative,
                        "expectedSha256": expected_hash,
                        "actualSha256": actual_hash,
                    }
                )
                continue
        verified_files += 1
        verified_bytes += actual_bytes

    payload = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "receipt": str(receipt_path),
        "receiptSha256": sha256(receipt_path),
        "localRoot": str(local_root),
        "hashVerificationRequested": args.hash,
        "summary": {
            "receiptFiles": len(records),
            "receiptBytes": sum(
                int((item.get("source") or {}).get("bytes") or 0)
                for item in records
            ),
            "verifiedFiles": verified_files,
            "verifiedBytes": verified_bytes,
            "hashedFiles": hashed_files,
            "missingFiles": len(missing),
            "missingBytes": sum(item["expectedBytes"] for item in missing),
            "sizeMismatches": len(size_mismatches),
            "hashMismatches": len(hash_mismatches),
            "complete": bool(
                verified_files == len(records)
                and not missing
                and not size_mismatches
                and not hash_mismatches
            ),
        },
        "missing": missing,
        "sizeMismatches": size_mismatches,
        "hashMismatches": hash_mismatches,
    }
    rendered = json.dumps(payload, indent=2) + "\n"
    if args.result_json is not None:
        output = args.result_json.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
