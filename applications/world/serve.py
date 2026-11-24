"""Serve a built ROSY World application, live observations, and SSE factory stream."""

import argparse
from functools import partial
import hmac
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from world_state import (  # noqa: E402
    ADAPTER_LABELS,
    BACKENDS,
    CANONICAL_FLEET_ROBOTS,
    LIVE_FRESH_MS,
    SHA256_RE,
    WORLD_ID_RE,
    _atomic_write_json,
    _canonical_reference,
    _clamp,
    _lerp_arms,
    _lerp_pinkys,
    _lerp_vec,
    _lerp_yaw,
    _live_state,
    _read_fresh_json,
    _read_json_strict,
    _reject_constant,
    _safe_world_path,
    discover_worlds,
    sample_timeline,
    verify_world_parity,
)

DEFAULT_PORT = 8140
MAX_INGEST_BYTES = 262_144
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
LIVE_PATHS = {
    "/data/pinky-sim.json", "/data/pinky-camera.jpg", "/data/isaac-live.json",
    "/data/mujoco-top.jpg", "/data/field-live.jpg", "/data/isaac-view.json",
    "/data/factory-live.json",
}


class WorldHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".webmanifest": "application/manifest+json"}

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def json_reply(self, status, value):
        data = json.dumps(value, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return BytesIO(data)

    def _worlds_dir(self) -> Path:
        return getattr(self.server, "worlds_dir", Path(self.directory) / "data" / "worlds")

    def _authorize_ingest(self) -> tuple[bool, int, str]:
        token = getattr(self.server, "ingest_token", None)
        if token:
            header = self.headers.get("Authorization") or ""
            scheme, _, supplied = header.partition(" ")
            if scheme.lower() != "bearer" or not supplied:
                return False, 401, "missing ingest bearer token"
            if not hmac.compare_digest(supplied.strip(), token):
                return False, 403, "invalid ingest bearer token"
            return True, 200, ""
        client_ip = (self.client_address[0] if self.client_address else "")
        if client_ip in LOOPBACK_HOSTS:
            return True, 200, ""
        return False, 403, "remote ingest requires ROSY_WORLD_INGEST_TOKEN"

    def _parse_world_ingest_id(self) -> str | None:
        path = urlsplit(self.path).path
        if not path.startswith("/api/worlds/"):
            return None
        return path.removeprefix("/api/worlds/")

    def send_head(self):
        parts = urlsplit(self.path)
        if parts.path == "/api/mdns":
            port = self.server.server_port
            mdns_host = getattr(self.server, "mdns_host", None)
            fleet_host = getattr(self.server, "fleet_mdns_host", None)
            return self.json_reply(200, {
                "schema": "rosy.world.mdns.v1",
                "service_type": "_rosy-world._tcp",
                "hostname": mdns_host,
                "port": port,
                "fleet_mdns_host": fleet_host,
                "worlds_api": "/api/worlds",
            })
        if parts.path == "/api/worlds":
            query = parse_qs(parts.query)
            adapter_filter = (query.get("adapter") or [None])[0]
            if adapter_filter and adapter_filter not in ("all", *BACKENDS):
                return self.json_reply(400, {"error": f"invalid adapter: {adapter_filter}"})
            now_ms = time.time_ns() // 1_000_000
            return self.json_reply(
                200, discover_worlds(Path(self.directory), now_ms, adapter_filter, worlds_dir=self._worlds_dir()),
            )
        if self.path == "/sim/control":
            controller = getattr(self.server, "sim_control", None)
            if controller is not None:
                return self.json_reply(200, controller.status())
            self.send_error(404)
            return None
        if parts.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self.server.health)))
            self.end_headers()
            return BytesIO(self.server.health)
        return super().send_head()

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/sim/stream":
            return self._stream_factory(parse_qs(parts.query))
        return super().do_GET()

    def _stream_factory(self, query: dict[str, list[str]]) -> None:
        mode = (query.get("mode") or ["auto"])[0]
        if mode not in ("auto", "live", "timeline"):
            mode = "auto"
        world_id = (query.get("world") or [None])[0]
        adapter = (query.get("adapter") or [None])[0]
        if adapter and adapter not in ("all", *BACKENDS):
            with self.json_reply(400, {"error": f"invalid adapter: {adapter}"}) as reply:
                self.copyfile(reply, self.wfile)
            return

        bundle_dir = Path(self.directory)
        data_dir = bundle_dir / "data"
        worlds_dir = self._worlds_dir()
        canonical = _canonical_reference(bundle_dir)
        world_file: Path | None = None
        if world_id is not None:
            if world_id not in ("verified-replay", "real-site"):
                world_file = _safe_world_path(worlds_dir, world_id)
                if world_file is None:
                    with self.json_reply(400, {"error": "invalid world id"}) as reply:
                        self.copyfile(reply, self.wfile)
                    return
                if not world_file.is_file():
                    with self.json_reply(404, {"error": f"unknown world: {world_id}"}) as reply:
                        self.copyfile(reply, self.wfile)
                    return

        speed = _clamp(query.get("speed"), 1.0, 0.25, 8.0)
        hz = _clamp(query.get("hz"), 25.0, 5.0, 30.0)
        start_s = _clamp(query.get("start_s"), 0.0, 0.0, 3600.0)
        max_events = None
        if "max_events" in query:
            try:
                max_events = max(1, int(query["max_events"][0]))
            except ValueError:
                max_events = 1

        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close" if max_events is not None else "keep-alive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        timeline_path = data_dir / "factory-timeline.json"
        cached_timeline: tuple[int, dict] | None = None
        started = time.monotonic()
        stop_event = getattr(self.server, "stop_event", None)
        sent = 0
        period = 1.0 / hz
        try:
            while max_events is None or sent < max_events:
                if stop_event is not None and stop_event.is_set():
                    break
                now_ms = time.time_ns() // 1_000_000
                payload = None
                event_name = "state"

                if world_id == "real-site" or adapter == "real":
                    # Anti-faking guardrail: real mode never falls back to simulation replay.
                    live_real = _read_fresh_json(world_file, now_ms) if world_file else None
                    if live_real is None and worlds_dir.is_dir():
                        for cand_path in sorted(worlds_dir.glob("*.json")):
                            cand = _read_fresh_json(cand_path, now_ms)
                            if cand and cand.get("adapter") == "real":
                                live_real = cand
                                break
                    if live_real is not None:
                        payload = {**live_real, "stream_mode": "live", "adapter": "real", "parity": verify_world_parity(canonical, live_real)}
                    else:
                        event_name = "idle"
                        payload = {
                            "schema": "rosy.world.factory-state.v1",
                            "stream_mode": "waiting",
                            "state": "waiting",
                            "adapter": "real",
                            "world_id": "real-site",
                            "reason": "실물 현장 미연결",
                            "observed_at_ms": now_ms,
                        }
                elif world_file is not None:
                    snap = _read_fresh_json(world_file, now_ms)
                    if snap is not None:
                        snap_adapter = str(snap.get("adapter") or snap.get("simulator") or "mujoco")
                        payload = {
                            **snap,
                            "world_id": world_id,
                            "adapter": snap_adapter,
                            "stream_mode": "live",
                            "parity": verify_world_parity(canonical, snap),
                        }
                    else:
                        event_name = "idle"
                        payload = {
                            "schema": "rosy.world.factory-state.v1",
                            "stream_mode": "waiting",
                            "state": "stalled",
                            "world_id": world_id,
                            "reason": "시뮬레이션 갱신 중단",
                            "observed_at_ms": now_ms,
                        }
                else:
                    if world_id != "verified-replay" and mode in ("auto", "live"):
                        payload = _live_state(data_dir, now_ms)
                    if payload is None and mode in ("auto", "timeline") and timeline_path.is_file():
                        try:
                            mtime = timeline_path.stat().st_mtime_ns
                            if cached_timeline is None or cached_timeline[0] != mtime:
                                cached_timeline = (mtime, json.loads(timeline_path.read_bytes()))
                            payload = sample_timeline(cached_timeline[1], start_s + (time.monotonic() - started) * speed)
                            payload["parity"] = verify_world_parity(canonical, payload)
                        except (OSError, ValueError, KeyError):
                            payload = None
                    if payload is None:
                        event_name = "idle"
                        payload = {"schema": "rosy.world.factory-state.v1", "state": "waiting", "observed_at_ms": now_ms}

                chunk = f"event: {event_name}\ndata: {json.dumps(payload, allow_nan=False)}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
                sent += 1
                if max_events is not None and sent >= max_events:
                    break
                wait_s = 1.0 if event_name == "idle" else period
                if stop_event is not None and stop_event.wait(wait_s):
                    break
                if stop_event is None:
                    time.sleep(wait_s)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def end_headers(self):
        path = urlsplit(self.path).path
        if (
            path in LIVE_PATHS
            or path in ("/", "/healthz", "/api/mdns", "/api/worlds", "/sim/control", "/sim/stream")
            or path.endswith((".html", ".js", ".css", ".json", ".webmanifest"))
        ):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def _reply_json(self, status: int, value: dict) -> None:
        with self.json_reply(status, value) as reply:
            self.copyfile(reply, self.wfile)

    def _ingest_world(self, raw_id: str) -> None:
        allowed, auth_status, auth_err = self._authorize_ingest()
        if not allowed:
            return self._reply_json(auth_status, {"error": auth_err})
        if raw_id == "verified-replay":
            return self._reply_json(400, {"error": "verified-replay cannot be overwritten"})
        target = _safe_world_path(self._worlds_dir(), raw_id)
        if target is None:
            return self._reply_json(400, {"error": "invalid world id"})
        if self.headers.get_content_type() != "application/json":
            return self._reply_json(400, {"error": "expected application/json"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._reply_json(400, {"error": "invalid Content-Length"})
        if size <= 0:
            return self._reply_json(400, {"error": "empty JSON body"})
        if size > MAX_INGEST_BYTES:
            return self._reply_json(413, {"error": f"payload exceeds {MAX_INGEST_BYTES} bytes"})
        try:
            self.connection.settimeout(2)
            body = json.loads(self.rfile.read(size).decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, UnicodeDecodeError, OSError) as error:
            return self._reply_json(400, {"error": str(error)})
        if not isinstance(body, dict) or body.get("schema") != "rosy.world.factory-state.v1":
            return self._reply_json(400, {"error": "expected rosy.world.factory-state.v1 object"})
        adapter = str(
            body.get("adapter")
            or (body.get("env") or {}).get("backend")
            or body.get("simulator")
            or ""
        )
        if adapter not in BACKENDS:
            return self._reply_json(400, {"error": f"unsupported adapter: {adapter!r}"})
        if adapter == "real" or raw_id == "real-site":
            if body.get("stream_mode") not in (None, "live"):
                return self._reply_json(403, {"error": "real world rejects non-live stream_mode"})
            adapter = "real"
            body["stream_mode"] = "live"
        body["world_id"] = raw_id
        body["adapter"] = adapter
        body.setdefault("observed_at_ms", time.time_ns() // 1_000_000)
        canonical = _canonical_reference(Path(self.directory))
        parity = verify_world_parity(canonical, body)
        _atomic_write_json(target, body)
        return self._reply_json(200, {"ok": True, "world_id": raw_id, "adapter": adapter, "parity": parity})

    def do_POST(self):
        raw_id = self._parse_world_ingest_id()
        if raw_id is not None:
            return self._ingest_world(raw_id)
        controller = getattr(self.server, "sim_control", None)
        origin = f"http://127.0.0.1:{self.server.server_port}"
        if controller is None or self.path != "/sim/control":
            self.send_error(404)
            return
        if self.headers.get("Origin") != origin or self.headers.get("Host") != origin.removeprefix("http://"):
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 512 or self.headers.get_content_type() != "application/json":
                raise ValueError("expected a small JSON control message")
            self.connection.settimeout(2)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("expected a control object")
            if body.get("adapter") == "real" or body.get("world_id") == "real-site":
                status, value = 403, {"error": "real hardware control forbidden"}
            else:
                status, value = controller.command(body)
        except (ValueError, OSError) as error:
            status, value = 400, {"error": str(error)}
        self._reply_json(status, value)

    def do_DELETE(self):
        raw_id = self._parse_world_ingest_id()
        if raw_id is None:
            self.send_error(404)
            return
        allowed, auth_status, auth_err = self._authorize_ingest()
        if not allowed:
            return self._reply_json(auth_status, {"error": auth_err})
        if raw_id == "verified-replay":
            return self._reply_json(400, {"error": "verified-replay cannot be deleted"})
        target = _safe_world_path(self._worlds_dir(), raw_id)
        if target is None:
            return self._reply_json(400, {"error": "invalid world id"})
        existed = target.is_file()
        target.unlink(missing_ok=True)
        return self._reply_json(200, {"ok": True, "world_id": raw_id, "deleted": existed})

    def log_message(self, fmt, *args):
        if sys.stderr is not None:
            super().log_message(fmt, *args)


class WorldHTTPServer(ThreadingHTTPServer):
    """HTTP/SSE server sized for concurrent static asset + EventSource loads on Windows and Linux."""

    request_queue_size = 128
    allow_reuse_address = True


def make_server(
    root: Path,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    *,
    worlds_dir: Path | None = None,
    ingest_token: str | None = None,
    mdns_host: str | None = None,
    fleet_mdns_host: str | None = None,
) -> ThreadingHTTPServer:
    handler = partial(WorldHandler, directory=str(root))
    server = WorldHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.stop_event = threading.Event()
    server.worlds_dir = (worlds_dir if worlds_dir is not None else (root / "data" / "worlds")).resolve()
    resolved_token = ingest_token if ingest_token is not None else os.environ.get("ROSY_WORLD_INGEST_TOKEN", "")
    server.ingest_token = resolved_token.strip() or None
    default_mdns = f"{socket.gethostname().split('.')[0].lower()}.local"
    resolved_mdns = (mdns_host if mdns_host is not None else os.environ.get("ROSY_WORLD_MDNS_HOST", "")).strip()
    server.mdns_host = resolved_mdns or default_mdns
    resolved_fleet = (fleet_mdns_host if fleet_mdns_host is not None else os.environ.get("ROSY_FLEET_MDNS_HOST", "")).strip()
    server.fleet_mdns_host = resolved_fleet or None
    server.health = b'{"application":"rosy-world","status":"ready"}\n'
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).parent)
    parser.add_argument("--worlds-dir", type=Path, default=None, help="writable directory for live world JSON snapshots")
    parser.add_argument("--ingest-token-env", default="ROSY_WORLD_INGEST_TOKEN", help="env var holding bearer token for remote POST/DELETE /api/worlds/<id>")
    parser.add_argument("--mdns-host", default=None, help="advertised .local hostname (or $ROSY_WORLD_MDNS_HOST)")
    parser.add_argument("--fleet-mdns-host", default=None, help="paired Fleet .local hostname (or $ROSY_FLEET_MDNS_HOST)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    root = args.bundle.resolve()
    env_worlds = os.environ.get("ROSY_WORLD_WORLDS_DIR", "").strip()
    worlds_dir = args.worlds_dir if args.worlds_dir is not None else (Path(env_worlds) if env_worlds else None)
    ingest_token = os.environ.get(args.ingest_token_env, "").strip() or None
    try:
        for name in ("index.html", "app.js", "SHA256SUMS.txt"):
            if not (root / name).is_file():
                raise ValueError(f"incomplete bundle: {name} is missing")
        manifest = json.loads((root / "manifest.json").read_bytes())
        if not isinstance(manifest.get("inputs"), dict):
            raise ValueError("invalid ROSY World manifest")
        with make_server(
            root,
            args.host,
            args.port,
            worlds_dir=worlds_dir,
            ingest_token=ingest_token,
            mdns_host=args.mdns_host,
            fleet_mdns_host=args.fleet_mdns_host,
        ) as server:
            try:
                server.serve_forever()
            finally:
                server.stop_event.set()
    except KeyboardInterrupt:
        return
    except (OSError, ValueError, AttributeError) as error:
        parser.exit(1, f"rosy-world: {error}\n")


if __name__ == "__main__":
    main()
