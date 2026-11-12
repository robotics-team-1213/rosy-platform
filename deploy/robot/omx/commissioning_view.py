"""Local read-only OMX observation viewer. No device access or command publisher.

Single Responsibility:
  - `ObservationStore`: Retain newest advancing sample per camera and 5/6/7-DOF arm source.
  - Read-only localhost HTTP server (`make_server`) and native channel consumer (`consume_native`).
  - Topic/gate parsers and static UI assets live in `commissioning_view_assets.py` and are re-exported.
"""
from __future__ import annotations

import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import signal
import sys
import threading
import time

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from commissioning_view_assets import (  # noqa: E402,F401  (re-exported)
    CSS,
    PAGE,
    SCRIPT,
    _parse_topics,
    gate_reader,
    parse_arm_topics,
    parse_camera_topics,
)


class ObservationStore:
    """Retain only the newest advancing sample for each fixed source."""

    def __init__(self, *, arms=None, cameras=None, gates=None):
        self.gates = gates  # () -> {label: commissioning_record.gate_status(...)}, read only
        self.arms = parse_arm_topics([f"{key}={topic}" for key, topic in (arms or {}).items()])
        self.cameras = parse_camera_topics(
            [
                f"{key}={topic}"
                for key, topic in (
                    cameras
                    if cameras is not None
                    else {
                        "top": "/top_camera/image_raw",
                        "front": "/front_camera/image_raw",
                    }
                ).items()
            ]
        )
        self._sources = set(self.cameras) | {f"arm:{key}" for key in self.arms}
        if not self.arms:
            self._sources.add("joints")
        self._lock = threading.Lock()
        self._samples = {}

    def put(self, source, stamp, value, *, received=None, wall=None, quality=None):
        if source not in self._sources:
            raise ValueError("unknown source")
        if not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("invalid source stamp")
        if stamp > (time.time() if wall is None else wall) + 0.25:
            raise ValueError("future source stamp")
        with self._lock:
            previous = self._samples.get(source)
            if previous and stamp <= previous[0]:
                return False
            sequence = previous[3] + 1 if previous else 1
            self._samples[source] = (
                stamp,
                time.monotonic() if received is None else received,
                value,
                sequence,
                copy.deepcopy(quality),
            )
        return True

    @staticmethod
    def _metadata(sample, now, wall):
        if sample is None:
            return {"fresh": False, "source_stamp": None, "sequence": 0}
        stamp, receipt, _, sequence, quality = sample
        age = now - receipt
        source_age = wall - stamp
        return {
            "fresh": 0 <= age <= 2 and -0.25 <= source_age <= 2,
            "source_stamp": stamp,
            "receipt_age_s": age,
            "source_age_s": source_age,
            "sequence": sequence,
            "quality": copy.deepcopy(quality) if 0 <= age <= 2 and -0.25 <= source_age <= 2 else None,
        }

    def snapshot(self, *, now=None, wall=None):
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        with self._lock:
            result = {key: self._metadata(self._samples.get(key), now, wall) for key in (*self.cameras, "joints")}
            joints = self._samples.get("joints")
            result["joints"]["values"] = joints[2] if joints and result["joints"]["fresh"] else None
            result["arms"] = {}
            for label, topic in self.arms.items():
                sample = self._samples.get(f"arm:{label}")
                item = self._metadata(sample, now, wall)
                item.update(topic=topic, values=copy.deepcopy(sample[2]) if sample and item["fresh"] else None)
                result["arms"][label] = item
            result["cameras"] = {
                label: dict(self._metadata(self._samples.get(label), now, wall), topic=topic)
                for label, topic in self.cameras.items()
            }
        try:
            result["gates"] = self.gates() if self.gates else {}
        except Exception as exc:
            result["gates"] = {"error": type(exc).__name__}
        result.update(
            read_only=True,
            physical_acceptance=False,
            joint_topic=None if self.arms else "/omx_commissioning/joint_states",
            clock_semantics="host_source_stamp_not_exposure_sync",
        )
        return result

    def image(self, source, *, now=None, wall=None):
        return self.image_with_meta(source, now=now, wall=wall)[0]

    def image_with_meta(self, source, *, now=None, wall=None):
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        with self._lock:
            sample = self._samples.get(source)
            meta = self._metadata(sample, now, wall)
            return (sample[2] if meta["fresh"] else None), meta


def make_server(store, *, port=8766):
    titles = {
        "top": "상단 카메라",
        "side": "옆 카메라",
        "arm_a_wrist": "arm_a 손목 카메라",
        "arm_b_wrist": "arm_b 손목 카메라",
        "front": "그리퍼 카메라",
    }
    panels = "".join(
        f'<section><h2>{titles.get(label, label)}</h2><p id="{label}-status"></p>'
        f'<img id="{label}" data-camera alt="{label} 현재 영상" hidden></section>'
        for label in store.cameras
    )
    feedback = (
        "".join(
            f'<section><h2>{label} 실제 피드백 관측</h2>'
            f'<pre id="arm-{label}" data-arm="{label}">수신 대기</pre></section>'
            for label in store.arms
        )
        if store.arms
        else '<h2>실제 피드백 관측</h2><pre id="joints">수신 대기</pre>'
    )
    page = PAGE.replace("__CAMERA_PANELS__", panels).replace("__ARM_PANELS__", feedback)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def reply(self, code, body=b"", content_type="text/plain", *, extra_headers=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; object-src 'none'",
            )
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self):
            self.reply(405)

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.reply(403)
                return
            path = self.path.split("?", 1)[0]
            static = {
                "/": (page, "text/html; charset=utf-8"),
                "/viewer.js": (SCRIPT, "text/javascript; charset=utf-8"),
                "/viewer.css": (CSS, "text/css; charset=utf-8"),
            }
            if path in static:
                body, kind = static[path]
                self.reply(200, body.encode(), kind)
            elif path == "/inventory.json":
                from device_inventory import local_inventory

                self.reply(200, json.dumps(local_inventory(), ensure_ascii=False).encode(), "application/json")
            elif path == "/state.json":
                self.reply(200, json.dumps(store.snapshot(), allow_nan=False).encode(), "application/json")
            elif path in {f"/frame/{label}.jpg" for label in store.cameras}:
                label = path.split("/")[2].split(".")[0]
                body, meta = store.image_with_meta(label)
                if not body:
                    self.reply(503, b"no fresh frame", "text/plain")
                    return
                etag = f'"{meta["sequence"]}"'
                headers = {
                    "X-Frame-Seq": str(meta["sequence"]),
                    "X-Source-Stamp": f"{meta['source_stamp']:.6f}",
                    "ETag": etag,
                }
                if self.headers.get("If-None-Match") == etag:
                    self.reply(304, b"", "image/jpeg", extra_headers=headers)
                else:
                    self.reply(200, body, "image/jpeg", extra_headers=headers)
            elif path in {f"/stream/{label}.mjpg" for label in store.cameras}:
                label = path.split("/")[2].split(".")[0]
                body = store.image(label)
                if not body:
                    self.reply(503, b"no fresh frame", "text/plain")
                    return
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Connection", "close")
                self.end_headers()
                last_seq = None
                while True:
                    snap = store.snapshot()
                    cam = snap["cameras"].get(label, {})
                    frame = store.image(label)
                    if not frame or not cam.get("fresh"):
                        break
                    if cam.get("sequence") != last_seq:
                        last_seq = cam.get("sequence")
                        part = (
                            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(frame)).encode()
                            + b"\r\n\r\n"
                            + frame
                            + b"\r\n"
                        )
                        try:
                            self.wfile.write(part)
                            self.wfile.flush()
                        except OSError:
                            break
                    if self.headers.get("X-Max-Frames") == "1":
                        break
                    time.sleep(0.05)
            else:
                self.reply(404)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def consume_native(store):
    """Read only selected local channels without making repeated reads fresh."""
    from core_common.observation_snapshot import SnapshotChannel

    channels = [(label, key, "jpeg") for label, key in store.cameras.items()]
    channels += [(f"arm:{label}", key, "joints") for label, key in store.arms.items()]
    if not store.arms:
        channels.append(("joints", "/omx_commissioning/joint_states", "joints"))
    for label, key, kind in channels:
        sample = SnapshotChannel(key).read()
        if sample is None or sample["kind"] != kind:
            continue
        try:
            value = sample["payload"] if kind == "jpeg" else json.loads(sample["payload"])
            if kind == "joints" and (
                not isinstance(value, dict)
                or len(value) not in (6, 7, 8)
                or not all(type(v) in (int, float) and math.isfinite(v) for v in value.values())
            ):
                continue
            store.put(
                label, sample["captured_at"], value, received=sample["monotonic"], quality=sample.get("quality")
            )
        except (ValueError, TypeError):
            continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--arm-topic", action="append", default=[], metavar="LABEL=TOPIC")
    parser.add_argument("--camera-topic", action="append", default=[], metavar="LABEL=TOPIC")
    parser.add_argument("--record-root", type=Path, help="commissioning record root (read only)")
    parser.add_argument("--gate-arm", action="append", default=[], metavar="LABEL=WORKCELL/INSTANCE")
    args = parser.parse_args()
    try:
        store = ObservationStore(
            arms=parse_arm_topics(args.arm_topic),
            cameras=parse_camera_topics(args.camera_topic) if args.camera_topic else None,
            gates=gate_reader(args.record_root, args.gate_arm),
        )
    except ValueError as exc:
        parser.error(str(exc))
    server = make_server(store, port=args.port)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    from core_common.observation_snapshot import interrupt_on_termination

    previous = signal.signal(signal.SIGTERM, interrupt_on_termination)
    try:
        while True:
            consume_native(store)
            time.sleep(0.025)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        server.shutdown()
        server.server_close()
        worker.join()


if __name__ == "__main__":
    main()
