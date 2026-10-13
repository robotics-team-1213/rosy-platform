"""D-368 — vision.js 운전자 MJPEG 스트림 클라이언트의 순수 부분. Node 서브프로세스 패턴.

vision.js는 상단에서 /common/evidence.js를 import한다(폴링 경로). 스트림 클라이언트와
multipart 파서는 그 import를 쓰지 않으므로 시험은 import 줄만 걷어내고 data: URL로 적재한다.
여기가 검증하는 것: 파서의 분할·경계·Content-Length 처리, 종료 폴백 신호, fps 통계.
브라우저 종단(실제 화면·폴링 복귀)은 test_pilot_browser.py가 가진다.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[1] / "vision.js"


def _run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
let source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
source = source.replace(/^import .*$/gm, "");
const vision = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def _part_bytes(seq: int) -> bytes:
    jpeg = b"\xff\xd8" + bytes([48 + seq]) * 8 + b"\xff\xd9"
    head = (b"--frame\r\nContent-Type: image/jpeg\r\n"
            + f"Content-Length: {len(jpeg)}\r\n".encode()
            + f"X-Rosy-Camera-Sequence: {seq}\r\n".encode()
            + b"X-Rosy-Camera-Source: STREAMTEST\r\n"
            + b"X-Rosy-Camera-Captured-At: 12.5\r\n"
            + b"\r\n")
    return head + jpeg + b"\r\n"


def _js_bytes(data: bytes) -> str:
    return json.dumps(list(data))


def test_parser_reassembles_split_chunks():
    result = _run_js(f"""
    const parts = [];
    const parser = vision.createMultipartParser({{onPart: (p) => parts.push(p)}});
    const bytes = {_js_bytes(_part_bytes(1) + _part_bytes(2))};
    for (let i = 0; i < bytes.length; i += 3) parser.push(new Uint8Array(bytes.slice(i, i + 3)));
    console.log(JSON.stringify(parts.map((p) => ({{
      seq: Number(p.headers["x-rosy-camera-sequence"]),
      source: p.headers["x-rosy-camera-source"],
      length: Number(p.headers["content-length"]),
      bodyLen: p.body.length,
      jpegStart: Array.from(p.body).slice(0, 2),
    }}))));
    """)
    assert result == [
        {"seq": 1, "source": "STREAMTEST", "length": 12, "bodyLen": 12, "jpegStart": [255, 216]},
        {"seq": 2, "source": "STREAMTEST", "length": 12, "bodyLen": 12, "jpegStart": [255, 216]},
    ]


def test_parser_waits_for_a_split_body():
    result = _run_js(f"""
    const parts = [];
    const parser = vision.createMultipartParser({{onPart: (p) => parts.push(p)}});
    const bytes = {_js_bytes(_part_bytes(7))};
    const cut = bytes.length - 3;
    for (let i = 0; i < cut; i += 4) parser.push(new Uint8Array(bytes.slice(i, Math.min(i + 4, cut))));
    const before = parts.length;   // 몸통이 덜 왔다 — 내보내지 않는다
    parser.push(new Uint8Array(bytes.slice(cut)));
    console.log(JSON.stringify({{before, after: parts.length,
      seq: Number(parts[0].headers["x-rosy-camera-sequence"])}}));
    """)
    assert result["before"] == 0
    assert result["after"] == 1
    assert result["seq"] == 7


def test_stream_reports_frames_stats_and_falls_back_when_ended():
    result = _run_js("""
    const events = [];
    let queue = [];
    let ended = false;
    const encoder = new TextEncoder();
    const part = (seq) => encoder.encode(
      "--frame\\r\\nContent-Type: image/jpeg\\r\\nContent-Length: 4\\r\\n" +
      "X-Rosy-Camera-Sequence: " + seq + "\\r\\nX-Rosy-Camera-Source: S\\r\\n" +
      "X-Rosy-Camera-Captured-At: 1.0\\r\\n\\r\\n" +
      "\\xff\\xd8\\xff\\xd9" + "\\r\\n");
    const reader = {read: async () => (ended || queue.length === 0
      ? {done: true} : {done: false, value: queue.shift()})};
    const stream = vision.createDriverStream({
      fetchImpl: async () => ({ok: true, status: 200, body: {getReader: () => reader}}),
      headers: () => ({Authorization: "Bearer x"}),
      onFrame: (_url, meta) => events.push(["frame", meta.seq, meta.source, meta.blob?.type]),
      onStats: (s) => events.push(["stats", s.fps]),
      onLost: (d) => events.push(["lost", d.reason]),
      schedule: (fn) => { const id = setInterval(fn, 20); return () => clearInterval(id); },
    });
    queue.push(part(1), part(2));
    stream.start(false);
    await new Promise((resolve) => setTimeout(resolve, 50));
    ended = true;
    await new Promise((resolve) => setTimeout(resolve, 50));
    console.log(JSON.stringify({
      frames: events.filter((e) => e[0] === "frame").map((e) => [e[1], e[2], e[3]]),
      statsSawFps: events.some((e) => e[0] === "stats" && e[1] >= 1),
      lastStatsFps: events.filter((e) => e[0] === "stats").slice(-1)[0]?.[1],
      lost: events.filter((e) => e[0] === "lost").map((e) => e[1]),
    }));
    """)
    assert [f[:2] for f in result["frames"]] == [[1, "S"], [2, "S"]]
    assert all(f[2] == "image/jpeg" for f in result["frames"])
    assert result["statsSawFps"] is True
    assert result["lastStatsFps"] == 0      # 종료 후 통계는 0fps — HUD가 즉시 반영한다
    assert result["lost"] == ["ended"]      # 폴링 복귀 신호(D-368 §5)
