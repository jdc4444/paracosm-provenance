#!/usr/bin/env python3
"""Serve one exact recovery bundle through a bearer-authenticated endpoint."""

from __future__ import annotations

import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import urllib.parse


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--token-env", default="PARACOSM_RECOVERY_BUNDLE_TOKEN"
    )
    args = parser.parse_args()

    bundle = args.file.expanduser().resolve()
    if not bundle.is_file():
        raise FileNotFoundError(bundle)
    token = os.environ.get(args.token_env, "")
    if len(token) < 32:
        raise RuntimeError(
            f"{args.token_env} must contain at least 32 characters"
        )
    size = bundle.stat().st_size
    digest = sha256_file(bundle)

    class Handler(BaseHTTPRequestHandler):
        server_version = "ParacosmRecoveryBundle/1"
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
            if route == "/health":
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "filename": bundle.name,
                        "bytes": size,
                        "sha256": digest,
                    },
                )
                return
            if route != "/bundle":
                self.send_json(404, {"error": "not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-SHA256", digest)
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{bundle.name}"',
            )
            self.end_headers()
            with bundle.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    self.wfile.write(chunk)

    print(
        json.dumps(
            {
                "status": "serving",
                "bind": "127.0.0.1",
                "port": args.port,
                "filename": bundle.name,
                "bytes": size,
                "sha256": digest,
            }
        ),
        flush=True,
    )
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
