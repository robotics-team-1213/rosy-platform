"""Local read-only OMX observation viewer. No device access or command publisher.

Run on the camera host; access remotely through an SSH localhost forward.
With ``--record-root`` it also shows each arm's D-858 S3 commissioning gate (read only:
which measurements are missing or failing, and the record revision). It never saves.
Source stamps describe host capture/read time, not synchronized exposure time.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import signal
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _parse_topics(entries, *, cameras=False):
    topics = {}
    for entry in entries:
        label, separator, topic = entry.partition("=")
        if (not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label)
                or label in {"joints", "arms", "cameras", "connection"}
                or label in topics or topic in topics.values()):
            raise ValueError("invalid or duplicate observation label/topic")
        pattern = (r"/(?:[A-Za-z_][A-Za-z0-9_]*/)*image_raw" if cameras else
                   r"/omx_commissioning/(?:[A-Za-z_][A-Za-z0-9_]*/)?joint_states")
        if (not re.fullmatch(pattern, topic)
                or any(part.lower() in {"command", "commands", "control", "cmd", "cmd_vel"}
                       for part in topic.split("/"))):
            raise ValueError("only observation topics are allowed")
        topics[label] = topic
    return topics


def parse_arm_topics(entries):
    return _parse_topics(entries)


def parse_camera_topics(entries):
    return _parse_topics(entries, cameras=True)


class ObservationStore:
    """Retain only the newest advancing sample for each fixed source."""

    def __init__(self, *, arms=None, cameras=None, gates=None):
        self.gates = gates  # () -> {label: commissioning_record.gate_status(...)}, read only
        self.arms = parse_arm_topics([f"{key}={topic}" for key, topic in (arms or {}).items()])
        self.cameras = parse_camera_topics([f"{key}={topic}" for key, topic in
                                           (cameras if cameras is not None else {
                                               "top": "/top_camera/image_raw",
                                               "front": "/front_camera/image_raw"}).items()])
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
            self._samples[source] = (stamp, time.monotonic() if received is None else received,
                                     value, sequence, copy.deepcopy(quality))
        return True

    @staticmethod
    def _metadata(sample, now, wall):
        if sample is None:
            return {"fresh": False, "source_stamp": None, "sequence": 0}
        stamp, receipt, _, sequence, quality = sample
        age = now - receipt
        source_age = wall - stamp
        return {"fresh": 0 <= age <= 2 and -0.25 <= source_age <= 2,
                "source_stamp": stamp, "receipt_age_s": age,
                "source_age_s": source_age, "sequence": sequence,
                "quality": copy.deepcopy(quality) if 0 <= age <= 2 and -0.25 <= source_age <= 2 else None}

    def snapshot(self, *, now=None, wall=None):
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        with self._lock:
            result = {key: self._metadata(self._samples.get(key), now, wall)
                      for key in ("top", "front", "joints")}
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
                for label, topic in self.cameras.items()}
        try:
            result["gates"] = self.gates() if self.gates else {}
        except Exception as exc:  # a broken record must not take the observation view down
            result["gates"] = {"error": type(exc).__name__}
        result.update(read_only=True, physical_acceptance=False,
                      joint_topic=None if self.arms else "/omx_commissioning/joint_states",
                      clock_semantics="host_source_stamp_not_exposure_sync")
        return result

    def image(self, source, *, now=None, wall=None):
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        with self._lock:
            sample = self._samples.get(source)
            return sample[2] if self._metadata(sample, now, wall)["fresh"] else None


PAGE = '''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OMX 수집 관측</title><link rel="stylesheet" href="/viewer.css">
<h1>OMX 수집 관측</h1><p id="connection" role="status">연결 확인 중</p>
<main>__CAMERA_PANELS__</main>
__ARM_PANELS__
<section><h2>커미셔닝 관문 (읽기 전용)</h2><pre id="gates">수신 대기</pre></section>
<p>읽기 전용 · 영상은 호스트 수신 시각 기준 · 물리 보정·정지 수용은 별도 확인</p>
<script src="/viewer.js"></script></html>'''

SCRIPT = '''const cameras = [...document.querySelectorAll("img[data-camera]")].map(item => item.id);
const arms = [...document.querySelectorAll("pre[data-arm]")].map(item => item.dataset.arm);
const conditions = {NORMAL:"밝기·대비 조건 충족", UNDEREXPOSED:"어두움",
  OVEREXPOSED:"과다 노출", MIXED_LIGHTING:"명암 불균형", LOW_CONTRAST:"낮은 대비",
  LOW_SPATIAL_SIGNAL:"장면 구조 부족"};
const displayed = new Map();
const jointExpires = new Map();
const jointElement = key => document.getElementById(key === "joints" ? key : "arm-"+key);
const jointKeys = arms.length ? arms : ["joints"];
const expiresAt = (item, observedAt) => observedAt +
  (2 - Math.max(0, item.source_age_s, item.receipt_age_s))*1000;
setInterval(() => {
  for (const key of cameras) {
    const frame = displayed.get(key);
    if (!frame || performance.now() >= frame.expires) {
      document.getElementById(key).hidden = true;
    }
  }
  for (const key of jointKeys) {
    if (performance.now() >= (jointExpires.get(key) || 0)) {
      jointElement(key).textContent = "최신 피드백 없음";
    }
  }
}, 100);
async function picture(key, item, observedAt) {
  const element = document.getElementById(key);
  if (!item.fresh) { element.hidden = true; return; }
  const previous = displayed.get(key);
  if (previous && previous.sequence === item.sequence) return;
  let url;
  try {
    const response = await fetch(`/frame/${key}.jpg?seq=${item.sequence}`,
      {cache:"no-store", signal:AbortSignal.timeout(1500)});
    if (!response.ok) throw Error("영상 없음");
    url = URL.createObjectURL(await response.blob());
    const next = new Image();
    next.src = url;
    await next.decode();
    const expires = expiresAt(item, observedAt);
    if (performance.now() >= expires) throw Error("영상 만료");
    element.src = url;
    element.hidden = false;
    displayed.set(key, {sequence:item.sequence, expires, url});
    if (previous) URL.revokeObjectURL(previous.url);
    url = null;
  } catch (error) { element.hidden = true; }
  finally { if (url) URL.revokeObjectURL(url); }
}
const itemNames = {joint_limits:"관절 한계", gripper:"그리퍼 열림·닫힘", workspace:"작업 공간 상자",
  stop_test:"정지 시험"};
function gateText(gates) {
  const labels = Object.keys(gates || {});
  if (!labels.length) return "기록 경로 없음 (--record-root)";
  const NL = "\\n";
  return labels.map(label => {
    const gate = gates[label];
    if (!gate.items) return `${label}: 읽기 실패`;
    const items = Object.entries(gate.items).map(([name, item]) =>
      `  ${itemNames[name] || name}: ${item ? `${item.measured_by} · ${item.measured_at} · ${item.config_revision}` : "비어 있음"}`);
    const verdict = gate.blockers.length
      ? "닫힘" + NL + gate.blockers.map(b => "  - " + b).join(NL)
      : "열림 (port 설정 revision은 port가 확인)";
    return [`${label} · revision ${(gate.revision || "없음").slice(0, 12)}`, ...items,
            `관문: ${verdict}`].join(NL);
  }).join(NL + NL);
}
async function refresh() {
  try {
    const observedAt = performance.now();
    const response = await fetch("/state.json", {cache:"no-store", signal:AbortSignal.timeout(2500)});
    if (!response.ok) throw Error("연결 실패");
    const state = await response.json();
    document.getElementById("connection").textContent = "관측 연결됨 · " + new Date().toLocaleTimeString();
    for (const key of cameras) {
      const item = state.cameras[key];
      document.getElementById(key+"-status").textContent = item.fresh
        ? `수신 ${item.receipt_age_s.toFixed(2)}초 전 · ${new Date(item.source_stamp*1000).toLocaleTimeString()} · #${item.sequence} · ${conditions[item.quality?.condition] || "영상 품질 미확인"}`
        : "최신 영상 없음";
    }
    for (const key of jointKeys) {
      const item = arms.length ? state.arms[key] : state.joints;
      const expires = item.fresh ? expiresAt(item, observedAt) : 0;
      jointExpires.set(key, expires);
      jointElement(key).textContent = item.fresh && performance.now() < expires
        ? JSON.stringify(item.values, null, 2) : "실제 피드백 없음 · 관측기 연결 확인 필요";
    }
    document.getElementById("gates").textContent = gateText(state.gates);
    await Promise.all(cameras.map(key => picture(key, state.cameras[key], observedAt)));
  } catch (error) {
    document.getElementById("connection").textContent = "연결 끊김";
    for (const key of cameras) document.getElementById(key).hidden = true;
    for (const key of jointKeys) jointElement(key).textContent = "최신 피드백 없음";
  } finally { setTimeout(refresh, 500); }
}
for (const key of cameras) document.getElementById(key).onerror = () => {
  document.getElementById(key).hidden = true;
};
refresh();'''

CSS = '''body{font:1rem system-ui,sans-serif;margin:1.5rem;line-height:1.5}
main{display:flex;flex-wrap:wrap;gap:1rem}section{flex:1 1 320px;min-width:0}
img{width:100%;max-width:640px}pre{white-space:pre-wrap;overflow-wrap:anywhere}'''


def gate_reader(root, entries):
    """``LABEL=WORKCELL/INSTANCE`` entries -> a callable of per-arm gate status, or None."""
    if root is None:
        return None
    import sys
    adapter = Path(__file__).resolve().parents[3] / "middleware" / "devices" / "omx" / "adapter"
    if str(adapter) not in sys.path:
        sys.path.append(str(adapter))
    from omx_adapter.real.commissioning_record import CommissioningStore, gate_status
    stores = {}
    for entry in entries:
        label, _, arm = entry.partition("=")
        workcell, _, instance = arm.partition("/")
        if not label or label in stores:
            raise ValueError("invalid or duplicate gate arm label")
        stores[label] = CommissioningStore(root, workcell_id=workcell, instance_id=instance)
    if not stores:
        raise ValueError("--record-root needs at least one --gate-arm LABEL=WORKCELL/INSTANCE")
    return lambda: {label: gate_status(record) for label, record in stores.items()}


def make_server(store, *, port=8766):
    titles = {"top": "상단 카메라", "front": "그리퍼 카메라"}
    panels = "".join(
        f'<section><h2>{titles.get(label, label)}</h2><p id="{label}-status"></p>'
        f'<img id="{label}" data-camera alt="{label} 현재 영상" hidden></section>'
        for label in store.cameras)
    feedback = ("".join(f'<section><h2>{label} 실제 피드백 관측</h2>'
                         f'<pre id="arm-{label}" data-arm="{label}">수신 대기</pre></section>'
                         for label in store.arms) if store.arms else
                '<h2>실제 피드백 관측</h2><pre id="joints">수신 대기</pre>')
    page = PAGE.replace("__CAMERA_PANELS__", panels).replace("__ARM_PANELS__", feedback)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body=b"", content_type="text/plain"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; object-src 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.reply(405)

        def do_GET(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.reply(403)
                return
            path = self.path.split("?", 1)[0]
            static = {"/": (page, "text/html; charset=utf-8"),
                      "/viewer.js": (SCRIPT, "text/javascript; charset=utf-8"),
                      "/viewer.css": (CSS, "text/css; charset=utf-8")}
            if path in static:
                body, kind = static[path]
                self.reply(200, body.encode(), kind)
            elif path == "/state.json":
                self.reply(200, json.dumps(store.snapshot(), allow_nan=False).encode(), "application/json")
            elif path in {f"/frame/{label}.jpg" for label in store.cameras}:
                body = store.image(path.split("/")[2].split(".")[0])
                self.reply(200 if body else 503, body or b"no fresh frame", "image/jpeg" if body else "text/plain")
            else:
                self.reply(404)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def consume_native(store):
    """Read only selected local channels without making repeated reads fresh."""
    from core_common.observation_snapshot import SnapshotChannel
    channels = [(label, key, 'jpeg') for label, key in store.cameras.items()]
    channels += [(f'arm:{label}', key, 'joints') for label, key in store.arms.items()]
    if not store.arms:
        channels.append(('joints', '/omx_commissioning/joint_states', 'joints'))
    for label, key, kind in channels:
        sample = SnapshotChannel(key).read()
        if sample is None or sample['kind'] != kind:
            continue
        try:
            value = sample['payload'] if kind == 'jpeg' else json.loads(sample['payload'])
            if kind == 'joints' and (not isinstance(value, dict) or len(value) != 6
                    or not all(type(v) in (int, float) and math.isfinite(v) for v in value.values())):
                continue
            store.put(label, sample['captured_at'], value, received=sample['monotonic'],
                      quality=sample.get('quality'))
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
        store = ObservationStore(arms=parse_arm_topics(args.arm_topic),
                                 cameras=parse_camera_topics(args.camera_topic) if args.camera_topic else None,
                                 gates=gate_reader(args.record_root, args.gate_arm))
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
            time.sleep(.05)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        server.shutdown()
        server.server_close()
        worker.join()


if __name__ == "__main__":
    main()
