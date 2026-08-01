#!/usr/bin/env python3
"""Upload the browser-ready Paracosm archive to the hosted R2 binding."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import mimetypes
import os
from pathlib import Path
import threading
import time
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PART_SIZE = 16 * 1024 * 1024
SIMPLE_UPLOAD_LIMIT = 64 * 1024 * 1024
STATE_LOCK = threading.Lock()
WEB_SUFFIXES = {
    ".csv",
    ".gif",
    ".glb",
    ".gltf",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".mid",
    ".mov",
    ".mp4",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webm",
    ".webp",
}


def session(token: str, access_token: str) -> requests.Session:
    client = requests.Session()
    client.headers["x-paracosm-upload-key"] = token
    client.headers["OAI-Sites-Authorization"] = f"Bearer {access_token}"
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[408, 425, 429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "PUT", "POST", "DELETE"],
    )
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client


def media_url(base_url: str, relative_path: str) -> str:
    encoded = "/".join(quote(part, safe="") for part in relative_path.split("/"))
    return f"{base_url.rstrip('/')}/api/media/{encoded}"


def content_type(path: Path) -> str:
    value, _ = mimetypes.guess_type(path.name)
    return value or "application/octet-stream"


def remote_size(
    client: requests.Session,
    url: str,
) -> int | None:
    response = client.head(url, params={"action": "head"}, timeout=120)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    value = response.headers.get("content-length")
    return int(value) if value else None


def simple_upload(
    client: requests.Session,
    url: str,
    path: Path,
) -> None:
    with path.open("rb") as body:
        response = client.put(
            url,
            params={"action": "put", "contentType": content_type(path)},
            data=body,
            timeout=600,
        )
    response.raise_for_status()


def multipart_upload(
    client: requests.Session,
    url: str,
    path: Path,
) -> None:
    create = client.post(
        url,
        params={"action": "mpu-create", "contentType": content_type(path)},
        timeout=120,
    )
    create.raise_for_status()
    upload_id = create.json()["uploadId"]
    parts: list[dict[str, object]] = []

    try:
        with path.open("rb") as source:
            part_number = 1
            while True:
                block = source.read(PART_SIZE)
                if not block:
                    break
                response = client.put(
                    url,
                    params={
                        "action": "mpu-uploadpart",
                        "uploadId": upload_id,
                        "partNumber": part_number,
                    },
                    data=block,
                    timeout=600,
                )
                response.raise_for_status()
                parts.append(response.json())
                part_number += 1

        complete = client.post(
            url,
            params={"action": "mpu-complete", "uploadId": upload_id},
            json={"parts": parts},
            timeout=600,
        )
        complete.raise_for_status()
    except Exception:
        client.delete(
            url,
            params={"action": "mpu-abort", "uploadId": upload_id},
            timeout=120,
        )
        raise


def write_state(path: Path, state: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def upload_one(
    base_url: str,
    token: str,
    access_token: str,
    archive_root: Path,
    path: Path,
    state_path: Path,
    state: dict[str, object],
) -> tuple[str, int, str]:
    relative = path.relative_to(archive_root).as_posix()
    remote_path = f"archive/{relative}"
    size = path.stat().st_size
    client = session(token, access_token)
    url = media_url(base_url, relative)

    if remote_size(client, url) == size:
        result = (remote_path, size, "present")
    else:
        if size < SIMPLE_UPLOAD_LIMIT:
            simple_upload(client, url, path)
        else:
            multipart_upload(client, url, path)
        if remote_size(client, url) != size:
            raise RuntimeError(f"Hosted size verification failed for {remote_path}")
        result = (remote_path, size, "uploaded")

    with STATE_LOCK:
        completed = state.setdefault("completed", {})
        assert isinstance(completed, dict)
        completed[remote_path] = {"size": size, "status": result[2]}
        write_state(state_path, state)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--token-env",
        default="PARACOSM_MEDIA_UPLOAD_TOKEN",
    )
    parser.add_argument(
        "--access-token-env",
        default="PARACOSM_SITES_ACCESS_TOKEN",
    )
    args = parser.parse_args()

    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit(f"Missing environment variable {args.token_env}")
    access_token = os.environ.get(args.access_token_env)
    if not access_token:
        raise SystemExit(
            f"Missing environment variable {args.access_token_env}"
        )
    archive_root = args.archive_root.resolve()
    files = sorted(
        path
        for path in archive_root.rglob("*")
        if path.is_file() and path.suffix.lower() in WEB_SUFFIXES
    )

    state: dict[str, object]
    if args.state.exists():
        state = json.loads(args.state.read_text())
    else:
        state = {
            "baseUrl": args.base_url,
            "archiveRoot": str(archive_root),
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "completed": {},
        }
    write_state(args.state, state)

    total_bytes = sum(path.stat().st_size for path in files)
    uploaded_bytes = 0
    with concurrent.futures.ThreadPoolExecutor(args.workers) as executor:
        futures = [
            executor.submit(
                upload_one,
                args.base_url,
                token,
                access_token,
                archive_root,
                path,
                args.state,
                state,
            )
            for path in files
        ]
        for index, future in enumerate(
            concurrent.futures.as_completed(futures),
            start=1,
        ):
            remote_path, size, status = future.result()
            uploaded_bytes += size
            print(
                f"[{index}/{len(files)}] {status:8s} "
                f"{uploaded_bytes / total_bytes:7.2%} {remote_path}",
                flush=True,
            )

    state["completedAt"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(),
    )
    state["fileCount"] = len(files)
    state["totalBytes"] = total_bytes
    write_state(args.state, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
