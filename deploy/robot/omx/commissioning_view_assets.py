"""Web UI Assets & Topic/Gate Parsers for Local Read-Only OMX Observation Viewer (`commissioning_view_assets.py`).

Single Responsibility:
  - Validate read-only arm and camera observation topics (`_parse_topics`, `parse_arm_topics`, `parse_camera_topics`).
  - Read-only D-858 S3 commissioning gate reader (`gate_reader`).
  - Static HTML/JS/CSS viewer templates (`PAGE`, `SCRIPT`, `CSS`).
"""
from __future__ import annotations

from pathlib import Path
import re
import sys


def _parse_topics(entries, *, cameras=False):
    topics = {}
    for entry in entries:
        label, separator, topic = entry.partition("=")
        if (
            not separator
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label)
            or label in {"joints", "arms", "cameras", "connection"}
            or label in topics
            or topic in topics.values()
        ):
            raise ValueError("invalid or duplicate observation label/topic")
        pattern = (
            r"/(?:[A-Za-z_][A-Za-z0-9_]*/)*image_raw"
            if cameras
            else r"/omx_commissioning/(?:[A-Za-z_][A-Za-z0-9_]*/)?joint_states"
        )
        if not re.fullmatch(pattern, topic) or any(
            part.lower() in {"command", "commands", "control", "cmd", "cmd_vel"} for part in topic.split("/")
        ):
            raise ValueError("only observation topics are allowed")
        topics[label] = topic
    return topics


def parse_arm_topics(entries):
    return _parse_topics(entries)


def parse_camera_topics(entries):
    return _parse_topics(entries, cameras=True)


def gate_reader(root, entries):
    """``LABEL=WORKCELL/INSTANCE`` entries -> a callable of per-arm gate status, or None."""
    if root is None:
        return None
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


PAGE = '''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OMX 수집 관측</title><link rel="stylesheet" href="/viewer.css">
<h1>OMX 수집 관측</h1><p id="connection" role="status">연결 확인 중</p><p><a href="/inventory.json" download="inventory.json">장치 목록 내려받기 (Learning 프로필 초안용)</a></p>
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
  } finally { setTimeout(refresh, 120); }
}
for (const key of cameras) document.getElementById(key).onerror = () => {
  document.getElementById(key).hidden = true;
};
refresh();'''

CSS = '''body{font:1rem system-ui,sans-serif;margin:1.5rem;line-height:1.5}
main{display:flex;flex-wrap:wrap;gap:1rem}section{flex:1 1 320px;min-width:0}
img{width:100%;max-width:640px}pre{white-space:pre-wrap;overflow-wrap:anywhere}'''
