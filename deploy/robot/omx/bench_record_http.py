#!/usr/bin/env python3
"""HTTP server and CLI entrypoint for bench_record.py."""
from __future__ import annotations

import argparse, json, re, socket, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "bench_record.html").read_text(encoding="utf-8")


def make_server(bench, port, *, bind="127.0.0.1", mdns_hosts=(), allow_mdns_control=False):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, value, kind="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code); self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY"); self.end_headers(); self.wfile.write(body)

        def local(self):
            return self.client_address[0] == "127.0.0.1" and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def readonly_allowed(self):
            if self.local():
                return True
            return self.headers.get("Host") in {f"{h.lower()}:{self.server.server_port}" for h in mdns_hosts if h}

        def do_GET(self):
            if not self.readonly_allowed():
                return self.reply(403, {"error": "local bench or allowed mDNS host only"})
            path = self.path.split("?", 1)[0]
            if path == "/cameras.json":
                try:
                    raw = json.loads(urllib.request.urlopen("http://127.0.0.1:8767/state.json", timeout=1.5).read())
                    cams = {k: v for k, v in raw.items() if isinstance(v, dict) and "quality" in v}
                    return self.reply(200, cams)
                except Exception:
                    return self.reply(200, {})
            if path.startswith("/camera/") and path.endswith(".jpg"):
                label = path[8:-4]
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", label):
                    return self.reply(400, {"error": "invalid camera label"})
                try:
                    jpg = urllib.request.urlopen(f"http://127.0.0.1:8767/frame/{label}.jpg", timeout=1.5).read()
                    return self.reply(200, jpg, "image/jpeg")
                except Exception:
                    return self.reply(503, {"error": "camera frame unavailable"})
            if path == "/api/arms":
                return self.reply(200, bench.arms_status())
            if path == "/api/telemetry":
                return self.reply(200, bench.telemetry())
            if path == "/api/camera_check":
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                return self.reply(200, bench.check_camera_drift((qs.get("arm") or [""])[0]))
            routes = {"/": lambda: (PAGE.encode(), "text/html; charset=utf-8"),
                      "/bench_record_ui.js": lambda: ((HERE / "bench_record_ui.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_app.js": lambda: ((HERE / "bench_record_app.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_cam.js": lambda: ((HERE / "bench_record_cam.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/choices.json": lambda: (bench.choices(), "application/json"),
                      "/status.json": lambda: (bench.status(), "application/json")}
            if path not in routes:
                return self.reply(404, {"error": "not found"})
            body, kind = routes[path]()
            self.reply(200, body, kind)

        def do_POST(self):
            allowed = self.readonly_allowed() if allow_mdns_control else self.local()
            if not allowed or self.headers.get("X-Bench") != "1":
                return self.reply(403, {"error": "local bench only"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 <= length <= 65536:
                    raise ValueError("bounded JSON body required")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                if self.path == "/start":
                    return self.reply(200, bench.start(body))
                if self.path == "/stop":
                    return self.reply(200, bench.stop())
                if self.path == "/save_caps":
                    return self.reply(200, bench.save_caps(body))
                if self.path == "/release_lock":
                    return self.reply(200, bench.release_lock(body))
                if self.path == "/home":
                    return self.reply(200, bench.go_home(body))
                if self.path == "/save_initial_pose":
                    return self.reply(200, bench.save_initial_pose(body))
                if self.path == "/save_leader_pose":
                    return self.reply(200, bench.save_leader_pose(body))
                if self.path == "/api/camera_baseline":
                    return self.reply(200, bench.save_camera_baseline(body))
                m_arm = re.fullmatch(r"/api/arms/(arm_[abs]+)/(start|stop|home|initial_pose|leader_pose)", self.path)
                if m_arm:
                    arm_id, act = m_arm.group(1), m_arm.group(2)
                    if act == "start":
                        return self.reply(200, bench.start(dict(body, arm=arm_id)))
                    if act == "stop":
                        return self.reply(200, bench.stop())
                    if act == "home":
                        return self.reply(200, bench.go_home(dict(body, arm=arm_id)))
                    if act == "initial_pose":
                        return self.reply(200, bench.save_initial_pose(dict(body, arm=arm_id)))
                    if act == "leader_pose":
                        return self.reply(200, bench.save_leader_pose(dict(body, arm=arm_id)))
                self.reply(404, {"error": "not found"})
            except (ValueError, OSError) as exc:
                self.reply(400, {"error": str(exc)})

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((bind, port), Handler)


def main(argv=None, *, bench_cls=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, default=Path("~/.config/rosy/omx-bench-record.json").expanduser())
    parser.add_argument("--port", type=int, default=8771)
    parser.add_argument("--allow-mdns", action="store_true")
    parser.add_argument("--allow-mdns-control", action="store_true")
    args = parser.parse_args(argv)
    cfg = json.loads(args.config.read_text())
    if bench_cls is None:
        from bench_record import Bench as bench_cls
    bench = bench_cls(cfg); bench.restore_leftovers()
    allow_ctrl = args.allow_mdns_control or bool(cfg.get("allow_mdns_control"))
    allow_mdns = args.allow_mdns or allow_ctrl or bool(cfg.get("allow_mdns"))
    host_local = f"{socket.gethostname().split('.')[0].lower()}.local"
    mdns_hosts = tuple(cfg.get("mdns_hosts") or ((host_local,) if allow_mdns else ()))
    make_server(bench, args.port, bind="0.0.0.0" if allow_mdns else "127.0.0.1",
                mdns_hosts=mdns_hosts, allow_mdns_control=allow_ctrl).serve_forever()


if __name__ == "__main__":
    main()
