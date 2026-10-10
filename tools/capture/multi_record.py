#!/usr/bin/env python3
"""Record selected site cameras and robot previews without issuing motion commands.

multi_record.py record --config <private.json> --out <new-session-dir> --duration 60
multi_record.py render --session <session-dir> --out <video.mp4>

The loopback wall, original JPEGs, tracking snapshots and capture.sqlite3 share one
session. CORE previews retain their source clock; a non-UTC clock uses receipt
time for approximate composition. Native high-rate robot bags remain a separate
recording workflow. TLS is always verified; tokens are read from files only.
"""
from __future__ import annotations

import argparse
import bisect
import functools
import hashlib
import http.client
import json
import math
import os
import re
import signal
import sqlite3
import ssl
import subprocess
import tempfile
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from ceiling_record import parse_lens
from edge_drive import Core

MAX_AGE = 2.0


def validate_config(config):
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a nonempty list")
    ids = set()
    for source in sources:
        sid = source.get("id", "")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sid) or sid in ids:
            raise ValueError("source ids must be unique safe file names")
        ids.add(sid)
        if source.get("kind") not in ("robot", "site"):
            raise ValueError("source kind must be robot or site")
        if source["kind"] == "site" and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source.get("source_id", "")):
            raise ValueError("site source_id required")
        endpoint = source if source["kind"] == "robot" else config.get("site", {})
        url = urlsplit(endpoint.get("url", ""))
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in ("", "/")):
            raise ValueError("endpoints require an HTTPS origin without embedded credentials")
        if not endpoint.get("ca_file") or not endpoint.get("token_file"):
            raise ValueError("ca_file and token_file required")
        if "token" in endpoint:
            raise ValueError("use token_file, not inline tokens")
    return config


def client(endpoint):
    url = urlsplit(endpoint["url"])
    token = Path(endpoint["token_file"]).read_text(encoding="utf-8").strip()
    if not token or len(token) > 16384 or "\n" in token or "\r" in token:
        raise ValueError("invalid token file")
    return Core(endpoint.get("connect_host", url.hostname), token, url.port or 443,
                ssl.create_default_context(cafile=endpoint["ca_file"]), tls_host=url.hostname)


class SiteClient:
    """Use CORE's verified TLS connection helper, without the robot API prefix."""
    def __init__(self, endpoint):
        self.core = client(endpoint)

    def request(self, path, body=None, bearer=None):
        if not path.startswith("/") or path.startswith("//") or "#" in path:
            raise ValueError("invalid site relative path")
        core = self.core
        try:
            if core.conn is None:
                core.conn = core._connection(3.)
            headers = core._headers()
            if bearer:
                headers["Authorization"] = "Bearer " + bearer
            core.conn.request("GET" if body is None else "POST", path,
                              body=None if body is None else json.dumps(body).encode(), headers=headers)
            response = core.conn.getresponse()
            data = response.read()
            if response.status != 200:
                raise OSError(f"site HTTP {response.status}")
            return data, response.headers
        except (OSError, http.client.HTTPException):
            if core.conn:
                core.conn.close()
            core.conn = None
            raise


def robot_frame(core, *, now=None):
    status, meta = core.call("GET", "/vision/front/status")
    if status != 200 or not isinstance(meta, dict) or not meta.get("available") or meta.get("stale"):
        raise OSError("robot preview unavailable")
    seq = meta.get("raw_sequence") if meta.get("raw_available") else meta.get("sequence")
    if not isinstance(seq, int):
        raise ValueError("invalid camera sequence")
    # Request raw explicitly: do not substitute annotated pixels if raw is absent.
    code, jpeg = core.call("GET", f"/vision/front/frame?sequence={seq}&overlay=false", raw=True)
    if code != 200 or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise OSError("raw preview unavailable")
    stamp = float(meta["captured_at"])
    received = time.time() if now is None else now
    if not math.isfinite(stamp) or not math.isfinite(received):
        raise ValueError("invalid camera clock")
    # shortcut: ROS clocks can be non-UTC; use labelled receipt time until clock mapping is available.
    utc = math.isfinite(stamp) and stamp > 1_000_000_000 and abs(received - stamp) <= MAX_AGE
    return jpeg, {"seq": seq, "captured_at": stamp, "received_at": received,
                  "timeline_at": stamp if utc else received, "clock": "source_utc" if utc else "receipt",
                  "age_ms": meta.get("age_ms"), "rotation_deg": 0, "variant": "raw"}


class SiteCamera:
    def __init__(self, site, source_id, out):
        self.site, self.source_id, self.out = site, source_id, out
        self.lease, self.until = None, 0.
        records = json.loads(site.request("/api/fleet/calibrations")[0]).get("calibrations", [])
        calibration = next((r for r in records if r.get("source_id") == source_id), None)
        (out / "calibration.json").write_text(json.dumps(calibration), encoding="utf-8")

    def __call__(self):
        if self.lease is None or time.monotonic() >= self.until:
            self.lease = json.loads(self.site.request("/api/fleet/vision/lease", {"source_id": self.source_id})[0])
            self.until = time.monotonic() + max(0., float(self.lease["expires_in_s"]) - 5.)
        try:
            jpeg, headers = self.site.request(self.lease["frame_path"], bearer=self.lease["lease"])
        except (OSError, http.client.HTTPException):
            self.lease = None
            raise
        stamp = float(headers["X-Frame-Captured-At"])
        received = time.time()
        if not math.isfinite(stamp) or received - stamp > MAX_AGE or stamp > received + MAX_AGE:
            raise OSError("site frame clock/staleness mismatch")
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError("invalid JPEG")
        return jpeg, {"seq": int(headers["X-Frame-Seq"]), "captured_at": stamp, "received_at": received,
                      "timeline_at": stamp, "clock": "source_utc", "rotation_deg": int(headers.get("X-Frame-Rotation-Deg", 0)),
                      "lens": parse_lens(headers.get("X-Source-Lens")), "variant": "raw"}


class Session:
    def __init__(self, out, sources, *, clock=time.time):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.clock, self.started, self.ended = clock, clock(), None
        self.lock = threading.RLock()
        self.sources = [{"id": s["id"], "kind": s["kind"], "source_id": s.get("source_id"),
                         "robot_id": s.get("robot_id", s["id"]) if s["kind"] == "robot" else None,
                         "status": "waiting", "frames": 0, "latest": None} for s in sources]
        self.by_id = {s["id"]: s for s in self.sources}
        for sid in self.by_id:
            (self.out / sid / "frames").mkdir(parents=True)
        self.position = None
        self.db = sqlite3.connect(self.out / "capture.sqlite3", check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE frames(source_id TEXT, timeline_at REAL, captured_at REAL,
                received_at REAL, seq INTEGER, file TEXT, sha256 TEXT, metadata TEXT);
            CREATE INDEX frame_time ON frames(source_id,timeline_at);
            CREATE TABLE positions(received_at REAL, metadata TEXT);
            CREATE TABLE events(at REAL, source_id TEXT, kind TEXT, detail TEXT);
        """)
        self.event(None, "session_started", None)
        (self.out / "index.html").write_bytes(Path(__file__).with_name("multi_record.html").read_bytes())
        self.publish()

    def event(self, sid, kind, detail):
        self.db.execute("INSERT INTO events VALUES(?,?,?,?)", (self.clock(), sid, kind, detail))
        self.db.commit()

    def frame(self, sid, jpeg, meta):
        for key in ("captured_at", "received_at", "timeline_at"):
            value = meta[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("invalid frame timestamp")
        if meta["clock"] not in ("source_utc", "receipt") or not isinstance(meta["seq"], int):
            raise ValueError("invalid frame metadata")
        json.dumps(meta, allow_nan=False)
        with self.lock:
            source = self.by_id[sid]
            if source["latest"] and (source["latest"]["seq"], source["latest"]["captured_at"]) == (meta["seq"], meta["captured_at"]):
                source["status"] = "live"
                return
            file = f"{sid}/frames/{source['frames']:08d}.jpg"
            (self.out / file).write_bytes(jpeg)
            row = {**meta, "file": file, "sha256": hashlib.sha256(jpeg).hexdigest()}
            self.db.execute("INSERT INTO frames VALUES(?,?,?,?,?,?,?,?)", (sid, row["timeline_at"], row["captured_at"],
                            row["received_at"], row["seq"], file, row["sha256"], json.dumps(row)))
            self.db.commit()
            source.update(status="live", latest=row, frames=source["frames"] + 1)
            self.publish()

    def error(self, sid, code):
        with self.lock:
            if self.by_id[sid]["status"] == "unavailable":
                return
            self.by_id[sid]["status"] = "unavailable"
            self.event(sid, "source_error", code)
            self.publish()

    def positions(self, tracking):
        if not isinstance(tracking, dict) or not isinstance(tracking.get("robots"), list):
            raise ValueError("invalid tracking snapshot")
        stamp = tracking.get("ts")
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise ValueError("invalid tracking clock")
        for row in tracking["robots"]:
            if not isinstance(row, dict) or not isinstance(row.get("robot_id"), str):
                raise ValueError("invalid tracked robot")
            camera = row.get("camera")
            if camera is not None and (not isinstance(camera, dict) or any(
                    not isinstance(camera.get(k), (int, float)) or not math.isfinite(camera[k]) for k in ("x", "y"))):
                raise ValueError("invalid tracked position")
        json.dumps(tracking, allow_nan=False)
        with self.lock:
            self.position = {"received_at": self.clock(), "tracking": tracking}
            self.db.execute("INSERT INTO positions VALUES(?,?)", (self.clock(), json.dumps(self.position)))
            self.db.commit()
            self.publish()

    def view(self, now=None):
        now = self.clock() if now is None else now
        sources = []
        for s in self.sources:
            row = dict(s)
            if row["status"] == "live" and now - row["latest"]["received_at"] > MAX_AGE:
                row["status"] = "stale"
            sources.append(row)
        p = self.position
        if p and (abs(now - p["received_at"]) > MAX_AGE or abs(now - p["tracking"]["ts"]) > MAX_AGE):
            p = None
        return {"started_at": self.started, "ended_at": self.ended, "updated_at": now,
                "max_age_s": MAX_AGE, "sources": sources, "positions": p,
                "recording_kind": "PC raw preview; no motion commands"}

    def publish(self):
        path = self.out / "session.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.view(), allow_nan=False), encoding="utf-8")
        os.replace(temp, path)

    def finish(self):
        with self.lock:
            self.ended = self.clock()
            self.event(None, "session_stopped", None)
            self.publish()
            self.db.close()


def collect(session, sid, grab, stop, interval):
    while not stop.is_set():
        start = time.monotonic()
        try:
            jpeg, meta = grab()
            session.frame(sid, jpeg, meta)
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            # Exception text can contain credentials or internal addresses.
            session.error(sid, "capture_unavailable")
        stop.wait(max(.01, interval - (time.monotonic() - start)))


def positions_loop(session, endpoint, stop):
    site = None
    while not stop.is_set():
        try:
            if site is None:
                site = SiteClient(endpoint)
            session.positions(json.loads(site.request("/api/fleet/tracking")[0]))
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            pass
        stop.wait(.5)


def position_lines(tracking, robot_ids):
    rows = {r["robot_id"]: r for r in tracking.get("robots", [])}
    lines = []
    for rid in robot_ids:
        row = rows.get(rid, {})
        camera = row.get("camera")
        if camera and row.get("status") in ("MARKER", "OK", "OFFSET"):
            lines.append(f"{rid}: map X {camera['x']:.2f} Y {camera['y']:.2f} m [{row.get('source_id')}]")
        else:
            lines.append(f"{rid}: map position unconfirmed [{row.get('status', 'unavailable')}]")
    return lines


def layout(sources):
    cols = min(4, math.ceil(math.sqrt(len(sources) * 1280 / 600)))
    rows = math.ceil(len(sources) / cols)
    robot_count = sum(s["kind"] == "robot" for s in sources)
    footer = max(80, math.ceil(robot_count / 2) * 22 + 20)
    height = max(720, 40 + rows * 240 + footer)
    height += height % 2  # H.264 yuv420 requires even dimensions.
    return cols, rows, 1280 // cols, (height - 40 - footer) // rows, height


class Renderer:
    def __init__(self, session):
        self.root = Path(session).resolve()
        self.manifest = json.loads((self.root / "session.json").read_text(encoding="utf-8"))
        self.size = (1280, layout(self.manifest["sources"])[4])
        db = sqlite3.connect(f"{(self.root / 'capture.sqlite3').as_uri()}?mode=ro", uri=True)
        self.rows = {}
        for source in self.manifest["sources"]:
            rows = [json.loads(r[0]) for r in db.execute("SELECT metadata FROM frames WHERE source_id=? ORDER BY timeline_at,received_at", (source["id"],))]
            self.rows[source["id"]] = ([r["timeline_at"] for r in rows], rows)
        self.positions = [json.loads(r[0]) for r in db.execute("SELECT metadata FROM positions ORDER BY received_at")]
        self.pt = [p["received_at"] for p in self.positions]
        db.close()

    def frame(self, at):
        from PIL import Image, ImageDraw, ImageOps
        image = Image.new("RGB", self.size, "#101923")
        draw = ImageDraw.Draw(image)
        draw.text((12, 10), datetime.fromtimestamp(at, timezone.utc).isoformat() + " | PC preview recording", fill="white")
        sources = self.manifest["sources"]
        cols, rows, width, height, total_height = layout(sources)
        for i, source in enumerate(sources):
            x, y = (i % cols) * width, 40 + (i // cols) * height
            stamps, frames = self.rows[source["id"]]
            n = bisect.bisect_right(stamps, at) - 1
            row = frames[n] if n >= 0 and at - stamps[n] <= MAX_AGE else None
            draw.text((x + 10, y + 4), source["id"] + (" | " + row["clock"] if row else " | unavailable / stale"), fill="white")
            if row:
                file = self.root / row["file"]
                data = file.read_bytes()
                if hashlib.sha256(data).hexdigest() != row["sha256"]:
                    raise ValueError("frame hash mismatch")
                with Image.open(file) as camera:
                    camera = camera.convert("RGB").rotate(-row.get("rotation_deg", 0), expand=True)
                    camera = ImageOps.contain(camera, (max(1, width - 20), max(1, height - 35)))
                    image.paste(camera, (x + (width - camera.width) // 2, y + 30))
        n = bisect.bisect_right(self.pt, at) - 1
        tracking = self.positions[n]["tracking"] if n >= 0 and at - self.pt[n] <= MAX_AGE and abs(at - self.positions[n]["tracking"]["ts"]) <= MAX_AGE else {}
        robot_ids = [s["robot_id"] for s in sources if s["kind"] == "robot"]
        lines = position_lines(tracking, robot_ids)
        for i, line in enumerate(lines):
            draw.text((12 + (i % 2) * 640, 45 + rows * height + (i // 2) * 22), line, fill="white")
        return image


def render(session, out, fps=2.):
    renderer = Renderer(session)
    manifest = renderer.manifest
    if manifest["ended_at"] is None:
        raise ValueError("stop the session before exporting")
    out = Path(out).resolve()
    sidecar = Path(str(out) + ".json")
    if out.exists() or sidecar.exists():
        raise FileExistsError("output already exists")
    start, end = manifest["started_at"], manifest["ended_at"]
    count = max(1, math.ceil((end - start) * fps))
    fd, name = tempfile.mkstemp(prefix=".multi-record-", suffix=".mp4", dir=out.parent)
    os.close(fd)
    temp = Path(name)
    process = None
    try:
        process = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
                                    "-video_size", f"{renderer.size[0]}x{renderer.size[1]}", "-framerate", str(fps), "-i", "pipe:0", "-an",
                                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(temp)], stdin=subprocess.PIPE)
        for i in range(count):
            process.stdin.write(renderer.frame(start + i / fps).tobytes())
        process.stdin.close()
        if process.wait() != 0:
            raise OSError("video encoder failed")
        with temp.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        os.link(temp, out)  # Publish only complete video, atomically and without overwriting.
        with sidecar.open("x", encoding="utf-8") as stream:
            json.dump({"frames": count, "fps": fps, "sha256": digest, "started_at": start,
                       "ended_at": end, "alignment": "source UTC where available, otherwise labelled receipt time"}, stream)
    except BaseException:
        if process:
            process.kill()
            process.wait()
        raise
    finally:
        temp.unlink(missing_ok=True)


class LocalWall(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403)
            return
        super().do_GET()

    def do_HEAD(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403)
            return
        super().do_HEAD()

    def log_message(self, *args):
        pass


def record(config, out, duration, port, open_browser=True):
    validate_config(config)
    session = Session(out, config["sources"])
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    handler = functools.partial(LocalWall, directory=str(session.out))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    wall = f"http://127.0.0.1:{server.server_port}/"
    print(json.dumps({"wall": wall, "session": str(session.out)}), flush=True)
    if open_browser:
        webbrowser.open(wall)
    threads = []
    try:
        for source in config["sources"]:
            sid = source["id"]
            # Setup is retried inside this worker; another camera is never blocked by it.
            def worker(source=source, sid=sid):
                grab = None
                def fetch():
                    nonlocal grab
                    if grab is None:
                        if source["kind"] == "robot":
                            core = client(source)
                            grab = lambda: robot_frame(core)
                        else:
                            grab = SiteCamera(SiteClient(config["site"]), source["source_id"], session.out / sid)
                    return grab()
                collect(session, sid, fetch, stop, .5)
            thread = threading.Thread(target=worker)
            thread.start()
            threads.append(thread)
        if config.get("site"):
            thread = threading.Thread(target=positions_loop, args=(session, config["site"], stop))
            thread.start()
            threads.append(thread)
        stop.wait(duration)
    finally:
        stop.set()
        for thread in threads:
            thread.join()
        server.shutdown()
        server.server_close()
        session.finish()
    return session


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("record")
    capture.add_argument("--config", type=Path, required=True)
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("--duration", type=float, default=60.)
    capture.add_argument("--port", type=int, default=0)
    capture.add_argument("--no-open", action="store_true")
    export = sub.add_parser("render")
    export.add_argument("--session", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--fps", type=float, default=2.)
    args = parser.parse_args()
    if args.command == "record":
        if not math.isfinite(args.duration) or args.duration <= 0:
            parser.error("duration must be positive and finite")
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))
        record(config, args.out, args.duration, args.port, not args.no_open)
    else:
        if not math.isfinite(args.fps) or args.fps <= 0 or args.fps > 30:
            parser.error("fps must be in (0,30]")
        render(args.session, args.out, args.fps)


if __name__ == "__main__":
    main()
