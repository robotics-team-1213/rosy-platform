import { HeadlessState, NAVIGATION_LABEL, DOCK_STATE_LABEL, POWER_MODE_LABEL, enumLabel, operatorModeLabel, EVIDENCE_LABEL, evidenceAgeText } from "/common/core_ui_logic.js";
import { createNode } from "/assets/dom.js";

function readout(state, channel, label, freshValue) {
  const evidence = new HeadlessState(state).evidenceOf(channel);
  if (evidence === "fresh") return {evidence, text: freshValue ?? `${label} 값 없음`};
  if (evidence === "disconnected") return {evidence, text: EVIDENCE_LABEL.disconnected};
  if (evidence === "unavailable") return {evidence, text: EVIDENCE_LABEL.unavailable};

  const stamp = Date.parse(state.evidence?.[channel]?.received_at || "");
  const age = Number.isFinite(stamp) ? Math.max(0, Math.floor((Date.now() - stamp) / 1000)) : null;
  return {evidence, text: `${EVIDENCE_LABEL.delayed}${evidenceAgeText(age)}`};
}

export function mount(el, ctx) {
  const head = createNode("ui-head", "", "로봇 상태");
  const status = createNode("ui-status", "", "로봇 상태를 확인하는 중입니다.");
  status.setAttribute("state", "pending");
  const summary = createNode("dl", "ui-readout");
  summary.hidden = true;
  // D-321 부록: 보정 세션이 살아 있는 동안 로봇 카드 맨 위에 경고 칩을 단다.
  const calibration = document.createElement("ui-tag");
  calibration.setAttribute("status", "warn");
  calibration.dataset.calibrationChip = "";
  const fields = ["mode", "power", "dock", "charging", "navigation", "pose", "battery"];
  function renderCalibration(activity) {
    const active = activity?.kind === "CALIBRATING";
    // ui-tag 은 display 를 스스로 정하므로 hidden 대신 붙였다 뗀다.
    if (active && !calibration.isConnected) summary.before(calibration);
    if (!active) calibration.remove();
    calibration.textContent = active ? `보정 중 — ${activity.label || "보정"}` : "";
    const owner = activity?.owner;
    calibration.title = active ? `보정 주체: ${owner?.label || owner?.role || owner?.id || "알 수 없음"}` : "";
  }
  function render(state) {
    status.hidden = true;
    summary.hidden = false;
    renderCalibration(state.activity);
    summary.replaceChildren();
    const pose = state.pose;
    const battery = state.battery;
    const mapPoseTrusted = new HeadlessState(state).isFresh("pose")
      && (state.localization == null || (state.localization.state === "LOCALIZED"
        && state.localization.pose_frame === "map"));
    const percent = Number.isFinite(battery?.percent) ? `${Math.round(battery.percent)}%` : null;
    const volts = Number.isFinite(battery?.voltage) ? `${battery.voltage.toFixed(2)} V` : null;
    const charging = state.battery_status?.charging;
    // D-359 US-009 — 모드는 CORE 자신의 값이라 채널이 없다: 이 응답이 곧 증거(부모 증거)다.
    // 전원 모드도 같은 스냅샷의 값이다. 도크·충전·배터리는 자기 채널이 있다.
    const values = {
      mode: state.mode ? {evidence: "fresh", text: operatorModeLabel(state.mode), title: state.mode} : null,
      power: state.power?.mode
        ? {evidence: "fresh", text: enumLabel(POWER_MODE_LABEL, state.power.mode), title: state.power.mode} : null,
      dock: {...readout(state, "docking", "도크",
        state.docking?.state ? enumLabel(DOCK_STATE_LABEL, state.docking.state) : null),
        title: state.docking?.state},
      charging: readout(state, "battery", "충전",
        charging === true ? "충전 확인" : charging === false ? "충전 미확인" : null),
      navigation: {...readout(state, "navigation", "내비게이션",
        state.mode === "SAFE_STOP" ? "안전 정지 적용" : state.navigation ? `${enumLabel(NAVIGATION_LABEL, state.navigation)}${["PLANNING", "NAVIGATING"].includes(state.navigation) && !mapPoseTrusted ? " · 위치 확인 필요" : ""}` : null), title: state.navigation},
      pose: readout(state, "pose", "위치",
        !mapPoseTrusted ? "지도 위치 확인 불가" : Number.isFinite(pose?.x) && Number.isFinite(pose?.y)
          ? `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}` : null),
      battery: readout(state, "battery", "배터리",
        [percent, volts].filter(Boolean).join(" · ") || null),
    };
    for (const field of fields) {
      const label = createNode("dt", "", ({
        mode: "운전 모드", power: "전원", dock: "도크", charging: "충전",
        navigation: "내비게이션", pose: "현재 위치", battery: "배터리",
      })[field]);
      const value = createNode("dd", "", values[field]?.text ?? "수신 대기");
      if (values[field]?.evidence) value.dataset.evidence = values[field].evidence;
      if (values[field]?.title) value.title = values[field].title;
      summary.append(label, value);
    }
  }
  function fail(error) {
    calibration.remove();
    summary.replaceChildren();
    summary.hidden = true;
    status.textContent = `상태를 불러오지 못했습니다: ${error.message}`;
    status.setAttribute("state", "error");
    status.hidden = false;
  }
  el.append(head, status, summary);
  return ctx.store.state(render, fail);
}
