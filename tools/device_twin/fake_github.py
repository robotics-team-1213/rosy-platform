#!/usr/bin/env python3
"""The device twin's fake GitHub REST API (twin only).

    GET /repos/<owner>/<repo>/releases[?per_page=N]   list, newest first, ETag / If-None-Match -> 304
    GET /download/<owner>/<repo>/<tag>/<name>         asset bytes (browser_download_url)

Every request is appended to <store>/requests.jsonl (path, status, If-None-Match)
so a scenario can show the conditional requests the updater made.

    python3 fake_github.py --store /store --port 8080 --public-base http://rosy-twin-github:8080
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
from pathlib import Path
import sys
import threading
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_github_store import Store, StoreError  # noqa: E402


def make_handler(store: Store, public_base: str):
    log_lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _log(self, status: int) -> None:
            with log_lock, (store.root / "requests.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"path": self.path, "status": status,
                                         "if_none_match": self.headers.get("If-None-Match"),
                                         "user_agent": self.headers.get("User-Agent")}) + "\n")

        def _send(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)
            self._log(status)

        def do_GET(self) -> None:  # noqa: N802
            parts = urllib.parse.urlsplit(self.path)
            segments = [urllib.parse.unquote(item) for item in parts.path.strip("/").split("/")]
            try:
                if len(segments) == 4 and segments[0] == "repos" and segments[3] == "releases":
                    return self._list(f"{segments[1]}/{segments[2]}")
                if len(segments) == 5 and segments[0] == "download":
                    path = store.asset_path(f"{segments[1]}/{segments[2]}", segments[3], segments[4])
                    if path.is_file():
                        return self._send(200, path.read_bytes(), {"Content-Type": "application/octet-stream"})
            except StoreError:
                pass
            self._send(404, b'{"message": "Not Found"}', {"Content-Type": "application/json"})

        def _list(self, repo: str) -> None:
            listed = []
            for item in reversed(store.releases(repo)):
                tag = item["tag_name"]
                listed.append({**item, "assets": [
                    {"name": name, "size": size,
                     "browser_download_url": f"{public_base}/download/{repo}/{tag}/{name}"}
                    for name, size in store.assets(repo, tag)]})
            body = (json.dumps(listed, sort_keys=True) + "\n").encode()
            etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, b"", {"ETag": etag})
            self._send(200, body, {"ETag": etag, "Content-Type": "application/json"})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--public-base", required=True)
    args = parser.parse_args()
    store = Store(args.store)
    args.store.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(store, args.public_base.rstrip("/")))
    print(f"fake GitHub on :{args.port} store={args.store}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
