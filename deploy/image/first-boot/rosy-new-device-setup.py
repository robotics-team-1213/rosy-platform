#!/usr/bin/env python3
"""Read-only LAN landing page while a moved SD card awaits new registration."""

from __future__ import annotations

import argparse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


STATUS = Path("/run/rosy-boot/boot-status.json")
DEVICE_NAME = re.compile(r"^rosy-pinky-[a-hj-km-np-z2-9]{4}$")


def response(path: str, status_path: Path) -> tuple[int, dict[str, str], bytes]:
    """Expose setup status, never the previous device's CORE or credentials."""
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        status = {}
    if not isinstance(status, dict) or status.get("stage") != "SETUP":
        return 503, {"Content-Type": "text/plain; charset=utf-8"}, b"Setup status unavailable\n"

    route = urlsplit(path).path
    if route.startswith("/api/"):
        body = json.dumps({"state": "NEW_DEVICE_SETUP", "ready": False}).encode("ascii")
        return 503, {"Content-Type": "application/json; charset=utf-8"}, body
    if route not in {"/", "/dashboard"}:
        return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not found\n"

    candidate = status.get("device_name")
    name = candidate if isinstance(candidate, str) and DEVICE_NAME.fullmatch(candidate) else "New Rosy device"
    page = f"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ROSY new device setup</title>
<style>body{{font:16px system-ui,sans-serif;max-width:40rem;margin:8vh auto;padding:1.5rem;
background:#f8fafc;color:#172033}}main{{background:white;padding:2rem;border:1px solid #d8e0e8;
border-radius:1rem}}h1{{font-size:1.7rem}}code{{font-weight:700}}</style>
<main><h1>New device registration pending</h1>
<p><code>{escape(name)}</code> was staged after this SD card was moved to another Raspberry Pi.</p>
<p>The previous device's robot number, CORE API credential, Fleet pairing and motion runtime are unavailable.
The site Wi-Fi stays connected for operator access.</p>
<p>Keep the old SD card as the previous device's data archive. Register this board on a verified ROSY OS
card with a new robot number and credential before starting CORE. See the Pinky Pro first-device runbook.</p>
</main></html>"""
    return 200, {"Content-Type": "text/html; charset=utf-8"}, page.encode("utf-8")


def handler(status_path: Path):
    class SetupHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib interface
            code, headers, body = response(self.path, status_path)
            self.send_response(code)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 - stdlib interface
            self.send_error(405, "Registration changes are not accepted here")

        def log_message(self, _format, *_args):
            return

    return SetupHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler(STATUS)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
