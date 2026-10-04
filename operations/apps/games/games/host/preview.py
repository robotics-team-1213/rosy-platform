"""Laptop match board. stdlib HTTP only. No cv2, no CORE dashboard."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from games.field import Field
from games.game import MatchState, Observation

WEB = Path(__file__).resolve().parents[1] / "web"


def web_common_dir() -> Path:
    """Installed web_common share first, then the source tree (host runs).

    A web_common directory is one that ships ``shared-assets.json``."""
    try:
        from ament_index_python.packages import get_package_share_directory

        share = Path(get_package_share_directory("web_common"))
        if (share / "shared-assets.json").is_file():
            return share
    except (ImportError, LookupError):
        pass
    return Path(__file__).resolve().parents[5] / "shared" / "web"


COMMON = web_common_dir()
#: name -> media type. web_common's manifest is the one /common allowlist.
COMMON_ASSETS = json.loads((COMMON / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
#: The board is same-origin only: its script, sheets, overlay and frame.
PAGE_CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; "
    "script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
)
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg",
}


def overlay_payload(
    field: Field,
    obs: Observation,
    state: MatchState,
    markers: tuple[int, ...] | list[int] = (),
    *,
    has_frame: bool = False,
    visibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ball = None if obs.ball is None else {"x": obs.ball.x, "y": obs.ball.y}
    robots = {
        robot_id: {"x": pose.x, "y": pose.y, "yaw": pose.yaw}
        for robot_id, pose in obs.robots.items()
    }
    return {
        "phase": state.phase.value if hasattr(state.phase, "value") else str(state.phase),
        "score": dict(state.score),
        "reason": state.reason,
        "ball": ball,
        "robots": robots,
        "lost_ball": obs.lost_ball,
        "lost_robots": sorted(obs.lost_robots),
        "home_goal": None if obs.home_goal is None else [list(p) for p in obs.home_goal],
        "away_goal": None if obs.away_goal is None else [list(p) for p in obs.away_goal],
        "markers": [int(v) for v in markers],
        "has_frame": has_frame,
        "visibility": visibility
        if visibility is not None
        else {
            "corners": [],
            "robots": [],
            "goals": [],
            "ball": False,
            "ready": False,
            "note": "not FIELD GO",
        },
        "field": {
            "length_m": field.length_m,
            "width_m": field.width_m,
            "goal_width_m": field.goal_width_m,
            "home_id": field.home_id,
            "away_id": field.away_id,
        },
    }


BOARD_STALE_AFTER_S = 2.0


class PreviewBoard:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._utcnow = utcnow
        self._published_at: float | None = None
        self.overlay: dict[str, Any] = {}
        self.jpeg: bytes | None = None
        self.stop = False

    def request_stop(self) -> None:
        with self._lock:
            self.stop = True

    def publish(self, payload: dict[str, Any], jpeg: bytes | None = None) -> None:
        with self._lock:
            self.overlay = {**payload, "generated_at": self._utcnow().isoformat().replace("+00:00", "Z")}
            self._published_at = self._clock()
            self.jpeg = jpeg

    def snapshot(self) -> tuple[dict[str, Any], bytes | None]:
        with self._lock:
            age_s = None if self._published_at is None else max(0.0, self._clock() - self._published_at)
            evidence = "unavailable" if age_s is None else (
                "delayed" if age_s > BOARD_STALE_AFTER_S else "fresh")
            return {**self.overlay, "age_s": age_s, "stale_after_s": BOARD_STALE_AFTER_S,
                    "evidence": evidence}, self.jpeg


class PreviewServer:
    def __init__(self, board: PreviewBoard, *, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.board = board
        handler = partial(_Handler, board=board)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self) -> str:
        self._thread.start()
        return self.url

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, board: PreviewBoard, **kwargs) -> None:
        self.board = board
        super().__init__(*args, **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/overlay.json":
            payload, _ = self.board.snapshot()
            body = json.dumps(payload).encode("utf-8")
            self._send(200, MIME[".json"], body)
            return
        if path == "/frame.jpg":
            _, jpeg = self.board.snapshot()
            if not jpeg:
                self._send(404, "text/plain; charset=utf-8", b"no frame")
                return
            self._send(200, MIME[".jpg"], jpeg)
            return
        if path.startswith("/common/"):
            asset = path.removeprefix("/common/")
            media = COMMON_ASSETS.get(asset)
            file = COMMON / asset
            if media is None or "/" in asset or not file.is_file():
                self._send(404, "text/plain; charset=utf-8", b"not found")
                return
            self._send(200, f"{media}; charset=utf-8", file.read_bytes())
            return
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        if "/" in name or name.startswith("."):
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        file = WEB / name
        if not file.is_file() or file.suffix not in MIME:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        self._send(200, MIME[file.suffix], file.read_bytes())

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/stop":
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{self.headers.get('Host', '')}":
            # Only the board itself may stop the match; another page open in
            # the same browser may not (a POST without Origin is not a page).
            self._send(403, MIME[".json"], b'{"ok":false,"error":"foreign origin"}')
            return
        self.board.request_stop()
        self._send(200, MIME[".json"], b'{"ok":true}')

    def _send(self, code: int, media: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", media)
        self.send_header("Cache-Control", "no-cache")
        if media.startswith("text/html"):
            self.send_header("Content-Security-Policy", PAGE_CSP)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
