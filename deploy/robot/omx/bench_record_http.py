#!/usr/bin/env python3
"""HTTP server and CLI entrypoint for bench_record.py."""
from __future__ import annotations

import argparse, json, re, socket, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "bench_record.html").read_text(encoding="utf-8")
VIEWER = "http://127.0.0.1:8767"


def active_preview(bench):
    with bench.lock:
        return bench.live_preview if bench.state["status"] == "recording" else None


def camera_state(bench):
    preview = active_preview(bench)
    if preview is not None:
        return preview.fresh_cameras()
    try:
        with urllib.request.urlopen(f"{VIEWER}/state.json", timeout=1.5) as stream:
            raw = json.load(stream)
        return {k: v for k, v in raw.items() if isinstance(v, dict) and "quality" in v}
    except Exception:
        return {}


def camera_frame(bench, label):
    preview = active_preview(bench)
    if preview is not None:
        jpg = preview.frame(label)
        if jpg and active_preview(bench) is preview:
            return jpg
    with urllib.request.urlopen(f"{VIEWER}/frame/{label}.jpg", timeout=1.5) as stream:
        return stream.read()


def fleet_clear_target(origin, source_id):
    """Link to Fleet's authenticated operator workflow, without passing credentials."""
    if not isinstance(origin, str) or not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", source_id):
        return None
    try:
        url = urllib.parse.urlsplit(origin)
        host = url.hostname
        port = url.port
    except ValueError:
        return None
    if (url.scheme != "https" or not host or not re.fullmatch(r"[a-zA-Z0-9.-]+", host)
            or url.username is not None or url.password is not None or url.path not in ("", "/")
            or url.query or url.fragment or port == 0 or any(c.isspace() for c in origin)):
        return None
    authority = f"{host}:{port}" if port is not None else host
    return f"https://{authority}/console/cell?focus=arm:{source_id}"


def make_server(bench, port, *, bind="127.0.0.1", mdns_hosts=(), allow_mdns_control=False, fleet_console_origin=None):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, value, kind="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            try:
                self.send_response(code); self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY"); self.end_headers(); self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                self.close_connection = True

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
            if path == "/api/recover/fleet_clear":
                params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
                arms = params.get("arm", [])
                if set(params) != {"arm"} or len(arms) != 1 or arms[0] not in ("arm_a", "arm_b", "arm_s"):
                    return self.reply(400, {"error": "Select one arm for Fleet incident clearance"})
                from omx_incident_fleet import link_for
                link = link_for(arms[0]) if fleet_console_origin else None
                target = fleet_clear_target(fleet_console_origin, link.source_id if link else None)
                if target is None:
                    return self.reply(503, {"error": "Fleet operator console is not configured"})
                self.send_response(303)
                self.send_header("Location", target)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            if path == "/cameras.json":
                return self.reply(200, camera_state(bench))
            if path.startswith("/camera/") and path.endswith(".jpg"):
                label = path[8:-4]
                if not re.fullmatch(r"[a-zA-Z0-9_-]+", label):
                    return self.reply(400, {"error": "invalid camera label"})
                try:
                    jpg = camera_frame(bench, label)
                except Exception:
                    return self.reply(503, {"error": "camera frame unavailable"})
                return self.reply(200, jpg, "image/jpeg")
            if path == "/api/arms":
                return self.reply(200, bench.arms_status())
            if path == "/api/leader_check":
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                try:
                    return self.reply(200, bench.check_leader_home_status((qs.get("arm") or ["all"])[0]))
                except ValueError as exc:
                    return self.reply(400, {"error": str(exc)})
            if path == "/api/grip_map":
                return self.reply(200, bench.grip_maps())
            if path == "/api/telemetry":
                return self.reply(200, bench.telemetry())
            if path == "/api/camera_check":
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                return self.reply(200, bench.check_camera_drift((qs.get("arm") or [""])[0]))
            if path == "/api/pipeline/status":
                return self.reply(200, bench.pipeline_status())
            if path == "/api/hf/status":
                return self.reply(200, bench.hf_upload_status())
            if path == "/api/cell_map":
                return self.reply(200, bench.cell_map())
            if path == "/api/logs":
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                try:
                    lim = int((qs.get("limit") or ["80"])[0])
                except ValueError:
                    lim = 80
                return self.reply(200, bench.live_logs(lim))
            if path == "/api/defaults":
                return self.reply(200, bench.defaults_summary())
            if path == "/api/dataset/episodes":
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                try:
                    return self.reply(200, bench.dataset_episodes((qs.get("dataset") or [""])[0]))
                except (ValueError, OSError) as exc:
                    return self.reply(400, {"error": str(exc)})
            if path == "/api/dataset/video":
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                try:
                    vp = bench.resolve_dataset_video(
                        (qs.get("dataset") or [""])[0], (qs.get("cam") or [""])[0],
                        int((qs.get("chunk") or ["0"])[0]), int((qs.get("file") or ["0"])[0]))
                    sz = vp.stat().st_size
                    rng = self.headers.get("Range") or ""
                    m = re.match(r"bytes=(\d+)-(\d*)$", rng.strip())
                    if m:
                        s_i, e_i = int(m.group(1)), int(m.group(2)) if m.group(2) else sz - 1
                        if s_i >= sz or s_i > e_i:
                            return self.reply(416, b"", "video/mp4")
                        e_i = min(e_i, sz - 1)
                        with vp.open("rb") as fh:
                            fh.seek(s_i)
                            chunk_b = fh.read(e_i - s_i + 1)
                        self.send_response(206)
                        self.send_header("Content-Type", "video/mp4")
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Range", f"bytes {s_i}-{e_i}/{sz}")
                        self.send_header("Content-Length", str(len(chunk_b)))
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        self.wfile.write(chunk_b)
                        return
                    data = vp.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except (ValueError, OSError) as exc:
                    return self.reply(400, {"error": str(exc)})
            routes = {"/": lambda: (PAGE.encode(), "text/html; charset=utf-8"),
                      "/bench_record.css": lambda: ((HERE / "bench_record.css").read_bytes(), "text/css; charset=utf-8"),
                      "/bench_record_ui.js": lambda: ((HERE / "bench_record_ui.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_map.js": lambda: ((HERE / "bench_record_map.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_status.js": lambda: ((HERE / "bench_record_status.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_app.js": lambda: ((HERE / "bench_record_app.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_params.js": lambda: ((HERE / "bench_record_params.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_drawers.js": lambda: ((HERE / "bench_record_drawers.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_cam.js": lambda: ((HERE / "bench_record_cam.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_pipeline.js": lambda: ((HERE / "bench_record_pipeline.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_log_reset.js": lambda: ((HERE / "bench_record_log_reset.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_overlay.js": lambda: ((HERE / "bench_record_overlay.js").read_bytes(), "application/javascript; charset=utf-8"),
                      "/bench_record_review.js": lambda: ((HERE / "bench_record_review.js").read_bytes(), "application/javascript; charset=utf-8"),
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
                if self.path == "/prepare":
                    return self.reply(200, bench.prepare(body))
                if self.path == "/record_episode":
                    return self.reply(200, bench.record_episode(body))
                if self.path == "/finish":
                    return self.reply(200, bench.finish(body))
                if self.path == "/api/episode/next":
                    return self.reply(200, bench.episode_next(body))
                if self.path == "/api/episode/rerecord":
                    return self.reply(200, bench.episode_rerecord(body))
                if self.path == "/stop":
                    return self.reply(200, bench.stop())
                if self.path == "/save_caps":
                    return self.reply(200, bench.save_caps(body))
                if self.path == "/api/teleop_speed":
                    return self.reply(200, bench.set_teleop_speed(body))
                if self.path == "/api/grip_map":
                    return self.reply(200, bench.save_grip_map(body))
                if self.path == "/release_lock":
                    return self.reply(200, bench.release_lock(body))
                if self.path == "/home":
                    return self.reply(200, bench.go_home(body))
                if self.path == "/save_initial_pose":
                    return self.reply(200, bench.save_initial_pose(body))
                if self.path == "/save_leader_pose":
                    return self.reply(200, bench.save_leader_pose(body))
                if self.path == "/api/cameras/restart":
                    return self.reply(200, bench.restart_cameras(body))
                if self.path == "/api/camera_baseline":
                    return self.reply(200, bench.save_camera_baseline(body))
                if self.path == "/api/pipeline/generate_replay":
                    return self.reply(200, bench.pipeline_generate_replay(body))
                if self.path == "/api/pipeline/run":
                    return self.reply(200, bench.pipeline_run(body))
                if self.path == "/api/pipeline/config":
                    return self.reply(200, bench.pipeline_config(body))
                if self.path == "/api/hf/upload":
                    return self.reply(200, bench.hf_upload_start(body))
                if self.path == "/api/hf/config":
                    return self.reply(200, bench.hf_upload_config(body))
                if self.path == "/api/dataset/delete":
                    return self.reply(200, bench.dataset_delete(body))
                if self.path == "/api/dataset/episode/rate":
                    return self.reply(200, bench.rate_episode(body))
                if self.path == "/api/dataset/episode/delete":
                    return self.reply(200, bench.delete_dataset_episodes(body))
                if self.path == "/api/dataset/do_not_train":
                    return self.reply(200, bench.set_dataset_do_not_train(body))
                if self.path == "/api/manual_hold/release_runner":
                    return self.reply(200, bench.release_held_runner(body))
                if self.path == "/api/manual_hold/clear":
                    return self.reply(200, bench.clear_manual_hold(body))
                if self.path == "/api/recover/baseline":
                    return self.reply(200, bench.recover_baseline(body))
                if self.path == "/api/recover/restore_units":
                    return self.reply(200, bench.recover_restore_units(body))
                if self.path == "/api/recover/ack_error":
                    return self.reply(200, bench.ack_bench_error(body))
                if self.path == "/api/recover/sync_incident":
                    return self.reply(200, bench.recover_sync_incident(body))
                if self.path == "/api/recover/auto":
                    return self.reply(200, bench.auto_recover(body))
                if self.path == "/api/defaults/reset":
                    return self.reply(200, bench.reset_defaults(body))
                m_arm = re.fullmatch(r"/api/arms/(arm_[abs]+)/(start|stop|home|initial_pose|leader_pose|release_lease|prepare|record_episode|finish)", self.path)
                if m_arm:
                    arm_id, act = m_arm.group(1), m_arm.group(2)
                    if act == "start":
                        return self.reply(200, bench.start(dict(body, arm=arm_id)))
                    if act == "stop":
                        return self.reply(200, bench.stop())
                    if act in ("prepare", "record_episode", "finish"):
                        return self.reply(200, getattr(bench, act)(dict(body, arm=arm_id)))
                    if act == "home":
                        return self.reply(200, bench.go_home(dict(body, arm=arm_id)))
                    if act == "initial_pose":
                        return self.reply(200, bench.save_initial_pose(dict(body, arm=arm_id)))
                    if act == "leader_pose":
                        return self.reply(200, bench.save_leader_pose(dict(body, arm=arm_id)))
                    if act == "release_lease":
                        return self.reply(200, bench.release_lease(dict(body, arm=arm_id)))
                self.reply(404, {"error": "not found"})
            except (ValueError, OSError) as exc:
                self.reply(400, {"error": str(exc)})

        def log_message(self, *args):
            pass

    class _BenchHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 32
        allow_reuse_address = True

    return _BenchHTTPServer((bind, port), Handler)


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
                mdns_hosts=mdns_hosts, allow_mdns_control=allow_ctrl,
                fleet_console_origin=cfg.get("fleet_console_origin")).serve_forever()


if __name__ == "__main__":
    main()
