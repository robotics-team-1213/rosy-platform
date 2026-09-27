import { HeadlessState } from "/common/core_ui_logic.js";

function readout(state, channel, label, freshValue) {
  const evidence = new HeadlessState(state).evidenceOf(channel);
  if (evidence === "fresh") return {evidence, text: freshValue ?? `${label} 값 없음`};
  if (evidence === "disconnected") return {evidence, text: "연결 끊김"};
  if (evidence === "unavailable") return {evidence, text: "정보 없음"};

  const stamp = Date.parse(state.evidence?.[channel]?.received_at || "");
  const age = Number.isFinite(stamp) ? Math.max(0, Math.floor((Date.now() - stamp) / 1000)) : null;
  return {evidence, text: `지연${age === null ? "" : ` · ${age}초 전`}`};
}

export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.textContent = "로봇 상태";
  const summary = document.createElement("dl");
  summary.className = "ui-readout";
  const fields = ["mode", "navigation", "pose", "battery"];
  function render(state) {
    summary.replaceChildren();
    const pose = state.pose;
    const battery = state.battery;
    const values = {
      mode: state.mode,
      navigation: state.navigation,
      pose: readout(state, "pose", "위치",
        Number.isFinite(pose?.x) && Number.isFinite(pose?.y)
          ? `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}` : null),
      battery: readout(state, "battery", "배터리",
        Number.isFinite(battery?.percent) ? `${Math.round(battery.percent)}%` : null),
    };
    for (const field of fields) {
      const label = document.createElement("dt");
      label.textContent = ({mode:"운전 모드", navigation:"내비게이션", pose:"현재 위치", battery:"배터리"})[field];
      const value = document.createElement("dd");
      value.textContent = values[field]?.text ?? values[field] ?? "수신 대기";
      if (values[field]?.evidence) value.dataset.evidence = values[field].evidence;
      summary.append(label, value);
    }
  }
  function fail(error) {
    summary.replaceChildren();
    const note = document.createElement("ui-empty");
    note.textContent = `상태를 불러오지 못했습니다: ${error.message}`;
    summary.append(note);
  }
  el.append(head, summary);
  return ctx.store.poll("/api/v1/robot/state", 1_000, render, fail);
}
