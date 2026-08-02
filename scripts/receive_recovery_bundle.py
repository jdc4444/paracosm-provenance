#!/usr/bin/env python3
"""Receive one exact recovery bundle through a bearer-authenticated endpoint."""

from __future__ import annotations

import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import urllib.parse


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-bytes", type=int, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--token-env", default="PARACOSM_RECOVERY_BUNDLE_TOKEN"
    )
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    expected_bytes = args.expected_bytes
    expected_sha256 = args.expected_sha256.lower()
    if expected_bytes < 1:
        raise ValueError("--expected-bytes must be positive")
    if len(expected_sha256) != 64 or any(
        character not in "0123456789abcdef"
        for character in expected_sha256
    ):
        raise ValueError("--expected-sha256 must be a lowercase SHA-256")
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    if partial.exists():
        raise FileExistsError(partial)

    token = os.environ.get(args.token_env, "")
    if len(token) < 32:
        raise RuntimeError(
            f"{args.token_env} must contain at least 32 characters"
        )

    state = {"complete": False}
    state_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ParacosmRecoveryReceiver/1"
        sys_version = ""

        def log_message(self, format: str, *values: object) -> None:
            return

        def authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            return hmac.compare_digest(supplied, "Bearer " + token)

        def send_json(self, status: int, payload: dict[str, object]) -> None:
            data = json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return
            route = urllib.parse.urlsplit(self.path).path
            if route != "/health":
                self.send_json(404, {"error": "not found"})
                return
            self.send_json(
                200,
                {
                    "ok": True,
                    "complete": state["complete"],
                    "receivedBytes": (
                        output.stat().st_size
                        if state["complete"] and output.exists()
                        else partial.stat().st_size
                        if partial.exists()
                        else 0
                    ),
                    "filename": output.name,
                    "expectedBytes": expected_bytes,
                    "expectedSha256": expected_sha256,
                },
            )

        def do_PUT(self) -> None:
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return
            route = urllib.parse.urlsplit(self.path).path
            if route == "/chunk":
                self.receive_chunk()
                return
            if route != "/bundle":
                self.send_json(404, {"error": "not found"})
                return
            if state["complete"] or output.exists():
                self.send_json(409, {"error": "bundle already received"})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            supplied_sha256 = self.headers.get("X-Content-SHA256", "").lower()
            if length != expected_bytes:
                self.send_json(400, {"error": "Content-Length mismatch"})
                return
            if not hmac.compare_digest(supplied_sha256, expected_sha256):
                self.send_json(400, {"error": "X-Content-SHA256 mismatch"})
                return

            file_descriptor, temp_name = tempfile.mkstemp(
                prefix=output.name + ".", suffix=".partial", dir=output.parent
            )
            temp = Path(temp_name)
            digest = hashlib.sha256()
            remaining = expected_bytes
            try:
                with os.fdopen(file_descriptor, "wb") as handle:
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise EOFError("request ended before Content-Length")
                        handle.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                actual_sha256 = digest.hexdigest()
                if not hmac.compare_digest(actual_sha256, expected_sha256):
                    raise ValueError("uploaded bundle SHA-256 mismatch")
                os.replace(temp, output)
                state["complete"] = True
                self.send_json(
                    201,
                    {
                        "received": True,
                        "filename": output.name,
                        "bytes": expected_bytes,
                        "sha256": actual_sha256,
                    },
                )
            except Exception as exc:
                temp.unlink(missing_ok=True)
                self.send_json(400, {"error": str(exc)})

        def receive_chunk(self) -> None:
            if state["complete"] or output.exists():
                self.send_json(409, {"error": "bundle already received"})
                return
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            try:
                offset = int(query.get("offset", ["-1"])[0])
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                self.send_json(400, {"error": "invalid chunk metadata"})
                return
            supplied_sha256 = self.headers.get("X-Content-SHA256", "").lower()
            if offset < 0 or length < 1 or length > 64 * 1024 * 1024:
                self.send_json(400, {"error": "invalid chunk range"})
                return
            if offset + length > expected_bytes:
                self.send_json(400, {"error": "chunk exceeds expected bundle"})
                return
            if len(supplied_sha256) != 64 or any(
                character not in "0123456789abcdef"
                for character in supplied_sha256
            ):
                self.send_json(400, {"error": "invalid X-Content-SHA256"})
                return

            with state_lock:
                received = partial.stat().st_size if partial.exists() else 0
                if offset != received:
                    self.send_json(
                        409,
                        {"error": "offset mismatch", "expectedOffset": received},
                    )
                    return
                digest = hashlib.sha256()
                remaining = length
                try:
                    with partial.open("ab") as handle:
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise EOFError(
                                    "request ended before Content-Length"
                                )
                            handle.write(chunk)
                            digest.update(chunk)
                            remaining -= len(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
                    actual_chunk_sha256 = digest.hexdigest()
                    if not hmac.compare_digest(
                        actual_chunk_sha256, supplied_sha256
                    ):
                        with partial.open("r+b") as handle:
                            handle.truncate(offset)
                        raise ValueError("uploaded chunk SHA-256 mismatch")
                    received = partial.stat().st_size
                    complete = received == expected_bytes
                    if complete:
                        actual_sha256 = sha256_file(partial)
                        if not hmac.compare_digest(
                            actual_sha256, expected_sha256
                        ):
                            raise ValueError("assembled bundle SHA-256 mismatch")
                        os.replace(partial, output)
                        state["complete"] = True
                    self.send_json(
                        201 if complete else 200,
                        {
                            "received": True,
                            "complete": complete,
                            "receivedBytes": received,
                            "nextOffset": received,
                            "chunkSha256": actual_chunk_sha256,
                            "sha256": expected_sha256 if complete else None,
                        },
                    )
                except Exception as exc:
                    self.send_json(400, {"error": str(exc)})

    print(
        json.dumps(
            {
                "status": "receiving",
                "bind": "127.0.0.1",
                "port": args.port,
                "filename": output.name,
                "expectedBytes": expected_bytes,
                "expectedSha256": expected_sha256,
            }
        ),
        flush=True,
    )
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
