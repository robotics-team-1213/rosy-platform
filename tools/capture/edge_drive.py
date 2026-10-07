"""Supervised edge-capture drives over the CORE API (operator at the robot, Fleet watching).

    edge_drive.py --robot <robot-ip> --token-file FILE (--ca-file CA | --insecure) COMMAND
      nudge LIN ANG SECS OUT.jpg [--device NAME] [--lidar-forward-deg D]
            short MANUAL teleop (|lin| <= 0.08 m/s, |ang| <= 0.6 rad/s, <= 4 s), then IDLE
            and save the front frame (OUT.jpg) and the raw driver frame (OUT_raw.jpg);
            SECS 0 only saves the frames
      drive [--max-s 45] [--rearm 3]
            start a recording, CAMERA_LINE under a 1 s hold deadman until a stop reason,
            3 s without motion or --max-s, then line-follow OFF and stop the recording;
            a deadman release (link stall) re-arms up to --rearm times in the same recording
      rec start|stop
      cam-watch SECONDS EVERY OUT_DIR
            raw driver frame every EVERY s with road-band clipping in OUT_DIR/exposure.jsonl

Body check (D-422/D-424): before a nudge the shared RobotBody judges one GET
/api/v1/sensors/lidar scan. It is ADVISORY (user decision 2026-10-07): a blocked path
prints a WARN and the robot moves anyway; CORE's own stop stays authoritative. The
LiDAR forward angle is the URDF nominal, refined by the device's accepted lidar_mount
record in the PC calibration store (--device), overridden by --lidar-forward-deg.

The Operator token is read from --token-file or ROSY_CORE_OPERATOR_TOKEN_FILE, never
argv. TLS: --ca-file pins the device CA (the robot name must match the certificate);
--insecure skips verification for a robot's self-signed certificate on a bench LAN.
If this tool dies mid-move, CORE's teleop watchdog (500 ms) or the missing line-follow
hold stops the wheels.
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import ssl
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "contracts" / "foundation"))

from core_common.robot_body import PINKY_PRO  # noqa: E402

TOKEN_ENV = "ROSY_CORE_OPERATOR_TOKEN_FILE"
STORE = REPO / "data" / "calibration"
LIMITS = (0.08, 0.6, 4.0)           # |linear| m/s, |angular| rad/s, seconds
STOP_REASONS = ("obstacle", "departure", "stale", "driver_released", "limit", "angular_limit", "wall", "lost")
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


class Core:
    """One kept-alive HTTPS connection (a loaded Pi times out repeated TLS handshakes);
    reconnect once on a broken one. A network failure is (0, None), never an exception."""

    def __init__(self, host, token, port, context):
        self.host, self.token, self.port, self.context = host, token, port, context
        self.conn = None

    def _headers(self):
        return {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}

    def call(self, method, path, body=None, raw=False, timeout=3.0):
        data = None if body is None else json.dumps(body).encode()
        for _ in range(2):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPSConnection(self.host, self.port, timeout=timeout,
                                                            context=self.context)
                self.conn.timeout = timeout
                if self.conn.sock:
                    self.conn.sock.settimeout(timeout)
                self.conn.request(method, "/api/v1" + path, body=data, headers=self._headers())
                r = self.conn.getresponse()
                payload = r.read()
                if raw:
                    return r.status, payload
                try:
                    return r.status, json.loads(payload) if payload else None
                except ValueError:
                    return r.status, payload[:300]
            except (OSError, http.client.HTTPException):
                if self.conn is not None:
                    self.conn.close()
                self.conn = None
        return 0, None

    def clone(self):
        """A second client on its own connection (one HTTPSConnection is not thread-safe)."""
        return Core(self.host, self.token, self.port, self.context)

    def raw_frame(self, timeout=5.0):
        """First JPEG of the driver MJPEG stream (no overlay); None when not available."""
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=self.context)
        try:
            conn.request("GET", "/api/v1/vision/front/stream?overlay=false", headers=self._headers())
            r = conn.getresponse()
            if r.status != 200:
                return None
            buf = b""
            while True:
                a = buf.find(SOI)
                b = buf.find(EOI, a + 2) if a >= 0 else -1
                if b >= 0:
                    return buf[a:b + 2]
                chunk = r.read1(4096) if hasattr(r, "read1") else r.read(4096)
                if not chunk:
                    return None
                buf += chunk
        except (OSError, http.client.HTTPException):
            return None
        finally:
            conn.close()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# --- body advisory (pure) ------------------------------------------------------------------

def lidar_forward_deg(device=None, explicit=None, store_root=STORE):
    """(degrees, source): URDF nominal < device's accepted lidar_mount record < explicit."""
    nominal = PINKY_PRO.lidar_forward_deg
    if device is None and explicit is None:
        return nominal, "URDF nominal (geometry.yaml); pass --device for the accepted record"
    from core_common.calibration_store import resolve
    override = None if explicit is None else {"lidar_yaw_offset": math.radians(explicit)}
    values, source = resolve("lidar_mount", {"lidar_yaw_offset": math.radians(nominal)},
                             fallback_source="URDF nominal (geometry.yaml)", robot=device or "none",
                             root=store_root, nominal={"lidar_forward_deg": nominal}, override=override)
    return math.degrees(values["lidar_yaw_offset"]) % 360.0, source


def advisory(view, lin, secs, body=PINKY_PRO):
    """(report, warning or None) for a nudge on one ScanView. Advisory only: the caller
    prints the warning and moves anyway (user decision 2026-10-07)."""
    if lin:
        reverse = lin < 0
        need = abs(lin) * secs + body.stop_gap_m(abs(lin))      # travel + D-422 stop gap
        gap = body.translation_gap(view.points, reverse=reverse)
        unknown = body.unknown_blocks(view, reverse=reverse)
        report = (f"body gap {'rear' if reverse else 'front'}: {gap} m, need {need:.3f} m, "
                  f"unknown band blocks: {unknown}, points {len(view.points)}")
        if (gap is not None and gap < need) or unknown:
            return report, f"body path blocked (gap {gap}, need {need:.3f}, unknown {unknown})"
        return report, None
    kind, why = body.rotation_check(view)
    return f"rotation check: {kind or 'clear'} {why or ''}".rstrip(), (
        f"in-place turn not clear: {why}" if kind else None)


# --- commands ------------------------------------------------------------------------------

def cmd_nudge(core, args):
    lin, ang, secs = args.linear, args.angular, args.seconds
    if abs(lin) > LIMITS[0] or abs(ang) > LIMITS[1] or not 0 <= secs <= LIMITS[2]:
        sys.exit(f"nudge limits: |linear| <= {LIMITS[0]}, |angular| <= {LIMITS[1]}, 0 <= seconds <= {LIMITS[2]}")
    moved = False
    if secs > 0:
        deg, source = lidar_forward_deg(args.device, args.lidar_forward_deg)
        print(f"LiDAR forward {deg:.1f} deg from {source}")
        s, scan = core.call("GET", "/sensors/lidar")
        if s != 200 or not isinstance(scan, dict):
            print(f"WARN (advisory only, Fleet watching): no LiDAR scan ({s}); body not checked")
        else:
            report, warn = advisory(PINKY_PRO.scan_view(scan, forward_deg=deg), lin, secs)
            print(report)
            if warn:
                print(f"WARN (advisory only, Fleet watching): {warn}")
    code = None
    try:
        if secs > 0:
            s, b = core.call("POST", "/mode", {"mode": "MANUAL"})
            if s != 200:
                sys.exit(f"MANUAL refused {s} {b}")
            t0 = time.time()
            while time.time() - t0 < secs:
                s, b = core.call("POST", "/teleop", {"linear": lin, "angular": ang})
                if s != 200:
                    print("teleop refused", s, b)
                    break
                moved = True
                time.sleep(0.1)
    finally:
        if secs > 0:
            core.call("POST", "/teleop", {"linear": 0.0, "angular": 0.0})
            for _ in range(3):  # the watchdog stops the wheels anyway; IDLE ends the MANUAL seat
                code = core.call("POST", "/mode", {"mode": "IDLE"})[0]
                if code == 200:
                    break
                time.sleep(0.5)
            print("mode IDLE", code)
    time.sleep(0.8)
    _, st = core.call("GET", "/vision/front/status")
    seq = st.get("sequence") if isinstance(st, dict) else None
    s, img = 0, None
    for _ in range(6):  # the frame advances every ~0.1 s; a 409 names the current sequence
        s, img = core.call("GET", f"/vision/front/frame?sequence={seq}", raw=True)
        if s != 409:
            break
        seq = img.decode(errors="ignore").split("sequence ")[-1].split('"')[0]
    out = Path(args.out)
    if s == 200:
        out.write_bytes(img)
    raw = core.raw_frame(timeout=3.0)   # needs this token to be the driver (last accepted teleop)
    if raw:
        out.with_name(out.stem + "_raw" + out.suffix).write_bytes(raw)
        print("raw frame saved")
    else:
        print("raw frame unavailable")
    _, state = core.call("GET", "/robot/state")
    print("moved", moved, "frame", s, "pose", state.get("pose") if isinstance(state, dict) else None)


def _recording_state(core):
    _, b = core.call("GET", "/recordings/active")
    return ((b if isinstance(b, dict) else {}).get("active") or {})


def rec_start(core):
    s, b = core.call("POST", "/recordings", {})
    log("recording start", s, b if s != 201 else (b or {}).get("id"))
    if s != 201:
        sys.exit(f"recording refused: {s} {b}")
    for _ in range(40):
        st = _recording_state(core)
        if st.get("state") == "recording":
            log("recording", st.get("id"))
            return st.get("id")
        time.sleep(0.5)
    sys.exit("recorder never reached 'recording'")


def rec_stop(core):
    s, b = core.call("POST", "/recordings/active/stop")
    log("recording stop", s, b.get("state") if isinstance(b, dict) else b)
    for _ in range(40):
        if _recording_state(core).get("state") in ("idle", None):
            break
        time.sleep(0.5)
    _, b = core.call("GET", "/recordings")
    log("latest recording", json.dumps((b if isinstance(b, dict) else {}).get("items", [])[:1],
                                       ensure_ascii=False)[:400])


def cmd_rec(core, args):
    rec_start(core) if args.action == "start" else rec_stop(core)


class HoldLoop(threading.Thread):
    """Line-follow hold every PERIOD s on its own connection, so a slow status read on a
    loaded Pi never stretches the gap past CORE's 1 s deadman. A daemon: if the tool dies,
    the holds stop and CORE releases line-follow by itself."""

    PERIOD = 0.3

    def __init__(self, core):
        super().__init__(daemon=True)
        self.core, self.status, self.done = core, 200, threading.Event()

    def run(self):
        while not self.done.is_set():
            self.status, _ = self.core.call("POST", "/line-follow/hold", timeout=0.8)
            if self.status != 200:
                return
            self.done.wait(self.PERIOD)


def _arm(core):
    """CAMERA_LINE under a fresh 1 s deadman, holds from their own thread; None if refused."""
    s, b = core.call("PUT", "/line-follow/mode", {"mode": "CAMERA_LINE", "hold_s": 1.0})
    log("line-follow mode", s, {k: b.get(k) for k in ("mode", "state", "reason")} if s == 200 else b)
    if s != 200:
        return None
    holds = HoldLoop(core.clone())
    holds.start()
    return holds


def _disarm(holds):
    if holds is not None:
        holds.done.set()
        holds.join(timeout=2.0)


def cmd_drive(core, args):
    """A link stall longer than the 1 s deadman releases line-follow (driver_released); that
    stop stands, and the drive re-arms at most --rearm times inside the same recording."""
    started, holds, rearms = False, None, 0
    try:
        rec_start(core)
        holds = _arm(core)
        if holds is None:
            raise SystemExit("line-follow refused")
        started = True
        t0, still_since = time.time(), None
        while time.time() - t0 < args.max_s:
            _, lf = core.call("GET", "/line-follow", timeout=0.8)
            hs = holds.status
            lf = lf if isinstance(lf, dict) else {}
            lin, ang = lf.get("linear") or 0.0, lf.get("angular") or 0.0
            reason = str(lf.get("reason"))
            log(f"t={time.time() - t0:4.1f} hold={hs} state={lf.get('state')} reason={reason} v={lin:.3f} "
                f"w={ang:.3f} conf={lf.get('confidence') or 0:.2f} gap={lf.get('body_gap_m')} stuck={bool(lf.get('stuck'))}")
            released = hs != 200 or "driver_released" in reason
            if released and rearms < getattr(args, "rearm", 0):
                rearms += 1
                _disarm(holds)
                log(f"deadman released (link stall) -> re-arm {rearms}/{args.rearm}")
                holds = _arm(core)
                if holds is None:
                    log("re-arm refused -> stop")
                    break
                still_since = None
                continue
            if released:
                log("hold refused -> stop")
                break
            if lf.get("stuck") or any(k in reason for k in STOP_REASONS):
                log("stop reason -> stop")
                break
            if abs(lin) < 1e-3 and abs(ang) < 1e-3:
                still_since = still_since or time.time()
                if time.time() - still_since > 3.0 and time.time() - t0 > 3.0:
                    log("not moving for 3 s -> stop")
                    break
            else:
                still_since = None
            time.sleep(0.3)
    finally:
        _disarm(holds)
        if started:
            log("line-follow OFF", core.call("PUT", "/line-follow/mode", {"mode": "OFF"})[0])
        rec_stop(core)


def cmd_cam_watch(core, args):
    import cv2
    import numpy as np
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0, n = time.time(), 0
    with open(out / "exposure.jsonl", "a", encoding="utf-8") as fh:
        while time.time() - t0 < args.total_s:
            jpg = core.raw_frame()
            g = None if jpg is None else cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
            if g is None:
                print("grab failed", flush=True)
                time.sleep(args.every_s)
                continue
            h, w = g.shape
            road = g[int(h * .35):int(h * .95), int(w * .10):int(w * .90)]  # camera_visibility.py road band
            row = {"t": round(time.time(), 1), "road_clip": round(float(np.mean(road > 247)), 3),
                   "road_median": int(np.median(road)), "full_clip": round(float(np.mean(g > 247)), 3)}
            (out / f"{n:04d}.jpg").write_bytes(jpg)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(row, flush=True)
            n += 1
            time.sleep(args.every_s)


def tls_context(ca_file, insecure):
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE     # explicit --insecure only: a bench robot's self-signed cert
    return ctx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", required=True, help="robot address, e.g. <robot-ip>")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--token-file", help=f"Operator token file (env {TOKEN_ENV})")
    tls = ap.add_mutually_exclusive_group(required=True)
    tls.add_argument("--ca-file", help="device CA; the robot name must match its certificate")
    tls.add_argument("--insecure", action="store_true", help="do not verify the robot's TLS certificate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("nudge")
    p.add_argument("linear", type=float)
    p.add_argument("angular", type=float)
    p.add_argument("seconds", type=float)
    p.add_argument("out")
    p.add_argument("--device", help="robot name in the PC calibration store (session.json device)")
    p.add_argument("--lidar-forward-deg", type=float, help="operator override of the LiDAR forward angle")
    p.set_defaults(fn=cmd_nudge)
    p = sub.add_parser("drive")
    p.add_argument("--max-s", type=float, default=45.0)
    p.add_argument("--rearm", type=int, default=3,
                   help="re-arm CAMERA_LINE this many times after a deadman release (link stall)")
    p.set_defaults(fn=cmd_drive)
    p = sub.add_parser("rec")
    p.add_argument("action", choices=("start", "stop"))
    p.set_defaults(fn=cmd_rec)
    p = sub.add_parser("cam-watch")
    p.add_argument("total_s", type=float)
    p.add_argument("every_s", type=float)
    p.add_argument("out_dir")
    p.set_defaults(fn=cmd_cam_watch)
    args = ap.parse_args(argv)
    token_file = args.token_file or os.environ.get(TOKEN_ENV)
    if not token_file:
        ap.error(f"pass --token-file or set {TOKEN_ENV}")
    if args.insecure:
        print("WARNING: --insecure: the robot's TLS certificate is not verified", file=sys.stderr)
    core = Core(args.robot, Path(token_file).read_text(encoding="utf-8").strip(), args.port,
                tls_context(args.ca_file, args.insecure))
    args.fn(core, args)


if __name__ == "__main__":
    main()
