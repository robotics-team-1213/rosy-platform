import {createMotorHealthState, renderMotorHealth, renderMotorHealthSummary} from "/common/motor-health.js";

// 진단은 접힘이다: 한 줄 요약(근거 없음·주의·고장)만 보이고, 표는 펼칠 때 본다. 주의·고장이면 한 번 저절로 펼친다.
export function mount(el, ctx) {
  const state = createMotorHealthState();
  const details = document.createElement("details");
  details.className = "surface-disclosure motor-health-disclosure";
  const summary = document.createElement("summary");
  const body = document.createElement("div");
  details.append(summary, body);
  el.append(details);
  let autoOpened = false;
  const draw = () => {
    const health = state.read();
    renderMotorHealthSummary(summary, health);
    renderMotorHealth(body, health);
    el.dataset.evidence = health.evidence;
    if (!autoOpened && ["warn", "crit"].includes(health.severity)) { autoOpened = true; details.open = true; }
  };
  draw();
  const stop = ctx.store.poll("/api/v1/motors/health", 1000,
    (data, timing) => { state.accept(data, timing); draw(); },
    () => { state.disconnect(); draw(); });
  // Local age keeps advancing while an in-flight read is slow; it is not a second API poll.
  const timer = setInterval(draw, 1000);
  return () => { stop(); clearInterval(timer); };
}
