import { HeadlessState } from "/common/core_ui_logic.js";

export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.textContent = "로봇 상태";
  const summary = document.createElement("dl");
  summary.className = "ui-readout";
  const fields = ["mode", "navigation", "pose", "battery"];
  function render(state) {
    summary.replaceChildren();
    const evidence = new HeadlessState(state);
    const values = {
      mode: state.mode,
      navigation: state.navigation,
      pose: evidence.isFresh("pose") ? `${Number(state.pose.x).toFixed(2)}, ${Number(state.pose.y).toFixed(2)}` : "위치 수신 대기",
      battery: evidence.isFresh("battery") && state.battery?.percent != null ? `${Math.round(state.battery.percent)}%` : "배터리 수신 대기",
    };
    for (const field of fields) {
      const label = document.createElement("dt");
      label.textContent = ({mode:"운전 모드", navigation:"내비게이션", pose:"현재 위치", battery:"배터리"})[field];
      const value = document.createElement("dd");
      value.textContent = values[field] ?? "수신 대기";
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
