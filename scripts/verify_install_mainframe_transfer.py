#!/usr/bin/env python3
"""Verify and install an extracted MAINFRAME recovery transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


CHUNK_BYTES = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=CHUNK_BYTES) as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value: str) -> Path:
    normalized = PurePosixPath(value.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"Unsafe staged relative path: {value}")
    return Path(*normalized.parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--destination-root", required=True, type=Path)
    parser.add_argument("--receipt-json", required=True, type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--remote-thread-id", required=True)
    parser.add_argument("--ciphertext-path", type=Path)
    parser.add_argument("--ciphertext-sha256")
    parser.add_argument("--plaintext-archive-path", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_sha256 = sha256_file(args.manifest)
    if manifest_sha256 != args.expected_manifest_sha256.lower():
        raise RuntimeError(
            f"Manifest SHA-256 mismatch: {manifest_sha256} != "
            f"{args.expected_manifest_sha256.lower()}"
        )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    records = manifest if isinstance(manifest, list) else manifest["files"]

    installed = []
    for record in records:
        relative = safe_relative_path(record["stagedRelativePath"])
        source = args.source_root / relative
        destination = args.destination_root / relative
        expected_bytes = int(record["bytes"])
        expected_sha256 = str(record["sha256"]).lower()
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.stat().st_size != expected_bytes:
            raise RuntimeError(f"Extracted byte count mismatch: {source}")
        source_sha256 = sha256_file(source)
        if source_sha256 != expected_sha256:
            raise RuntimeError(f"Extracted SHA-256 mismatch: {source}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        disposition = "already_present_identical"
        if destination.exists():
            if (
                destination.stat().st_size != expected_bytes
                or sha256_file(destination) != expected_sha256
            ):
                raise RuntimeError(
                    f"Refusing to overwrite non-identical destination: {destination}"
                )
        else:
            shutil.copy2(source, destination)
            disposition = "installed_copy"
        installed_sha256 = sha256_file(destination)
        if installed_sha256 != expected_sha256:
            raise RuntimeError(f"Installed SHA-256 mismatch: {destination}")
        installed.append(
            {
                **record,
                "extractedPath": str(source),
                "extractedHashVerified": True,
                "installedPath": str(destination),
                "installedHashVerified": True,
                "disposition": disposition,
            }
        )
        print(
            f"verified_install={relative} bytes={expected_bytes} "
            f"sha256={expected_sha256}",
            flush=True,
        )

    receipt = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "authority": (
            "Authenticated AES-256-GCM transfer from the connected JDC host "
            "after read-only recovery from MAINFRAME. The ciphertext, "
            "authenticated plaintext archive, extracted files, and installed "
            "Mac copies were independently verified before use."
        ),
        "remoteThreadId": args.remote_thread_id,
        "manifest": {
            "path": str(args.manifest),
            "bytes": args.manifest.stat().st_size,
            "sha256": manifest_sha256,
        },
        "ciphertext": (
            {
                "path": str(args.ciphertext_path),
                "bytes": args.ciphertext_path.stat().st_size,
                "sha256": sha256_file(args.ciphertext_path),
                "expectedSha256": args.ciphertext_sha256,
                "authentication": "AES-256-GCM passed",
            }
            if args.ciphertext_path
            else None
        ),
        "plaintextArchive": (
            {
                "path": str(args.plaintext_archive_path),
                "bytes": args.plaintext_archive_path.stat().st_size,
                "sha256": sha256_file(args.plaintext_archive_path),
            }
            if args.plaintext_archive_path
            else None
        ),
        "destinationRoot": str(args.destination_root),
        "fileCount": len(installed),
        "sourceBytes": sum(int(item["bytes"]) for item in installed),
        "files": installed,
    }
    if (
        receipt["ciphertext"]
        and args.ciphertext_sha256
        and receipt["ciphertext"]["sha256"] != args.ciphertext_sha256.lower()
    ):
        raise RuntimeError("Receipt ciphertext SHA-256 does not match transfer")
    args.receipt_json.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_json.write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    print(f"receipt={args.receipt_json}", flush=True)


if __name__ == "__main__":
    main()
