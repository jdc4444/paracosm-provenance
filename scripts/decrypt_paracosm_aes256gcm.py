#!/usr/bin/env python3
"""Stream-decrypt authenticated Paracosm transfer payloads."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


HEADER = b"PARACOSM-AES256GCM-v1\n"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=CHUNK_BYTES) as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--key-hex", required=True)
    parser.add_argument("--nonce-hex", required=True)
    parser.add_argument("--aad", required=True)
    parser.add_argument("--expected-ciphertext-sha256")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.expected_ciphertext_sha256:
        actual_sha256 = sha256_file(args.input)
        expected_sha256 = args.expected_ciphertext_sha256.lower()
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"Ciphertext SHA-256 mismatch: {actual_sha256} != {expected_sha256}"
            )
        print(f"ciphertext_sha256={actual_sha256}", flush=True)

    key = bytes.fromhex(args.key_hex)
    expected_nonce = bytes.fromhex(args.nonce_hex)
    if len(key) != 32 or len(expected_nonce) != NONCE_BYTES:
        raise ValueError("Expected a 32-byte key and 12-byte nonce")

    payload_bytes = args.input.stat().st_size
    ciphertext_bytes = payload_bytes - len(HEADER) - NONCE_BYTES - TAG_BYTES
    if ciphertext_bytes < 0:
        raise RuntimeError("Encrypted payload is shorter than its envelope")

    with args.input.open("rb", buffering=CHUNK_BYTES) as encrypted:
        header = encrypted.read(len(HEADER))
        if header != HEADER:
            raise RuntimeError(f"Unexpected transfer header: {header!r}")
        stored_nonce = encrypted.read(NONCE_BYTES)
        if stored_nonce != expected_nonce:
            raise RuntimeError("Stored nonce does not match the transfer record")
        encrypted.seek(payload_bytes - TAG_BYTES)
        tag = encrypted.read(TAG_BYTES)
        encrypted.seek(len(HEADER) + NONCE_BYTES)

        decryptor = Cipher(
            algorithms.AES(key), modes.GCM(stored_nonce, tag)
        ).decryptor()
        decryptor.authenticate_additional_data(args.aad.encode("utf-8"))

        args.output.parent.mkdir(parents=True, exist_ok=True)
        partial = args.output.with_name(args.output.name + ".partial")
        remaining = ciphertext_bytes
        try:
            with partial.open("wb", buffering=CHUNK_BYTES) as plaintext:
                while remaining:
                    chunk = encrypted.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise RuntimeError("Encrypted payload ended unexpectedly")
                    plaintext.write(decryptor.update(chunk))
                    remaining -= len(chunk)
                plaintext.write(decryptor.finalize())
            os.replace(partial, args.output)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    print(f"authentication=AES-256-GCM-passed", flush=True)
    print(f"plaintext_bytes={args.output.stat().st_size}", flush=True)
    print(f"plaintext_sha256={sha256_file(args.output)}", flush=True)


if __name__ == "__main__":
    main()
