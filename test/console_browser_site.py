"""Shared Console HTTP fixture using the production asset registry."""

import json
import os
import runpy
import socket
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "applications/fleet/web"
_registry = runpy.run_path(str(WEB / "asset_registry.py"))["load_registry"](WEB)
CONSOLE_ASSETS = {name: (entry["path"], entry["media_type"]) for name, entry in _registry["assets"].items()}
WEB_COMMON = ROOT / "shared" / "web"


@pytest.fixture()
def console_url():
    # index.html 의 절대 경로(/common/tokens.css, /console/assets/*)를 풀어 준다.
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB), **kwargs)

        def translate_path(self, path: str) -> str:
            if path.startswith("/common/"):
                name = path.removeprefix("/common/")
                if name in json.loads((WEB_COMMON / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]:
                    return str(WEB_COMMON / name)
            name = path.split("?", 1)[0]  # D-518/D-798: flat URLs, files in web/<document>/ folders
            if name.startswith("/console/assets/"):
                asset = CONSOLE_ASSETS.get(name.removeprefix("/console/assets/"))
                if asset is not None:
                    return str(WEB / asset[0])
            if name.count("/") == 1 and name.endswith(".html"):
                name = name.rsplit("/", 1)[1]
                moved = next(iter(sorted(WEB.glob(f"*/{name}"))), None)
                path = "/" + (moved.relative_to(WEB).as_posix() if moved and not (WEB / name).exists() else name)
            return super().translate_path(path)

        def log_message(self, *args):  # 시험 출력을 조용히
            pass

    class ConsoleServer(ThreadingHTTPServer):
        # Windows SO_REUSEADDR permits concurrent servers on the same endpoint.
        # Each browser must receive this fixture's files, including mutations.
        allow_reuse_address = os.name != "nt"

        def server_bind(self):
            if os.name == "nt":
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    # Windows may assign Chromium-blocked ports (for example 10080) for port 0.
    for port in range(40000, 41000):
        try:
            server = ConsoleServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        else:
            break
    else:
        raise RuntimeError("could not allocate a browser-safe local port")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


