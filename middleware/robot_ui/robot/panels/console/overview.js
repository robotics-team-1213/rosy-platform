import { HeadlessState, NAVIGATION_LABEL, DOCK_STATE_LABEL, POWER_MODE_LABEL, enumLabel, operatorModeLabel, EVIDENCE_LABEL, evidenceAgeText } from "/common/core_ui_logic.js";
import { createNode } from "/assets/dom.js";
import { actionIcon } from "/common/ui.js";
import { statusTag } from "/common/status-tag.js";

function readout(state, channel, label, freshValue) {
  const evidence = new HeadlessState(state).evidenceOf(channel);
  if (evidence === "fresh") return {evidence, text: freshValue ?? EVIDENCE_LABEL.unavailable, empty: freshValue == null};
  if (evidence === "disconnected") return {evidence, text: EVIDENCE_LABEL.disconnected};
  if (evidence === "unavailable") return {evidence, text: EVIDENCE_LABEL.unavailable};

  const stamp = Date.parse(state.evidence?.[channel]?.received_at || "");
  const age = Number.isFinite(stamp) ? Math.max(0, Math.floor((Date.now() - stamp) / 1000)) : null;
  return {evidence, text: `${EVIDENCE_LABEL.delayed}${evidenceAgeText(age)}`};
}

export function mount(el, ctx) {
  // 머리: 로봇 아이콘 + 제목 + 종합 상태 태그. 정상은 조용한 태그, 예외만 아이콘이 붙는다.
  const head = createNode("ui-head", "", "로봇 상태");
  const header = createNode("div", "overview-head");
  const robot = createNode("span", "overview-icon");
  actionIcon(robot, "robot");
  const overall = createNode("span", "overview-overall");
  header.append(robot, head, overall);
  const status = createNode("ui-status", "", "로봇 상태를 확인하는 중입니다.");
  status.setAttribute("state", "pending");
  // 알려진 값만 띠에 둔다. 근거 없는 값은 아래 한 줄로 묶어 펼침으로 본다(D-82 정상은 조용하다).
  const summary = createNode("dl", "ui-readout");
  summary.dataset.form = "strip";
  summary.hidden = true;
  const unknownBox = createNode("details", "surface-disclosure overview-unknown");
  const unknownSummary = createNode("summary", "");
  const unknownList = createNode("dl", "ui-readout");
  unknownBox.append(unknownSummary, unknownList);
  unknownBox.hidden = true;
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
    const batteryStatus = state.battery_status;
    const charging = batteryStatus?.charging;
    const shown = Number.isFinite(batteryStatus?.shown_percent) ? batteryStatus.shown_percent : null;
    const live = Number.isFinite(battery?.percent) ? battery.percent : null;
    // D-688: while charging is confirmed, the row keeps the pre-charge estimate.
    const held = charging === true && shown !== null ? shown : null;
    const displayPercent = held !== null ? held : live;
    const percent = displayPercent === null ? null : `${Math.round(displayPercent)}%`;
    const volts = Number.isFinite(battery?.voltage) ? `${battery.voltage.toFixed(2)} V` : null;
    const levelWord = {warning: "주의", critical: "위험", deep: "심각"}[batteryStatus?.level];
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
        charging === true ? (held !== null ? `충전 중 · ${Math.round(held)}%` : "충전 확인")
          : charging === false ? "충전 미확인" : null),
      navigation: {...readout(state, "navigation", "내비게이션",
        state.mode === "SAFE_STOP" ? "안전 정지 적용" : state.navigation ? `${enumLabel(NAVIGATION_LABEL, state.navigation)}${["PLANNING", "NAVIGATING"].includes(state.navigation) && !mapPoseTrusted ? " · 위치 확인 필요" : ""}` : null), title: state.navigation},
      pose: readout(state, "pose", "위치",
        !mapPoseTrusted ? "지도 위치 확인 불가" : Number.isFinite(pose?.x) && Number.isFinite(pose?.y)
          ? `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}` : null),
      battery: readout(state, "battery", "배터리",
        [percent, volts, levelWord].filter(Boolean).join(" · ") || null),
    };
    const names = {mode: "운전 모드", power: "전원", dock: "도크", charging: "충전",
      navigation: "내비게이션", pose: "현재 위치", battery: "배터리"};
    unknownList.replaceChildren();
    let unknown = 0, worst = "fresh";
    for (const field of fields) {
      const value = values[field];
      // 값이 없거나 근거가 없으면 띠가 아니라 "근거 없음" 묶음으로 간다.
      const known = value && value.evidence !== "unavailable" && !value.empty;
      const target = known ? summary : unknownList;
      const label = createNode("dt", "", names[field]);
      const text = createNode("dd", "", value?.text ?? EVIDENCE_LABEL.unavailable);
      text.dataset.evidence = value?.evidence ?? "unavailable";
      if (value?.title) text.dataset.uiTooltip = value.title;  // rule 9: no title attribute; the label is already visible
      const cell = known ? createNode("div") : target;
      cell.append(label, text);
      if (known) {
        if (value.evidence !== "fresh") cell.dataset.alert = "";
        if (value.evidence === "disconnected") worst = "disconnected";
        else if (value.evidence === "delayed" && worst === "fresh") worst = "delayed";
        summary.append(cell);
      } else unknown += 1;
    }
    // 마지막 관측 시각: 근거 채널 중 가장 늦은 수신.
    const stamps = Object.values(state.evidence || {}).map((item) => Date.parse(item?.received_at || "")).filter(Number.isFinite);
    if (stamps.length) {
      const cell = createNode("div");
      cell.append(createNode("dt", "", "마지막 관측"),
        createNode("dd", "", new Date(Math.max(...stamps)).toTimeString().slice(0, 8)));
      summary.append(cell);
    }
    unknownBox.hidden = unknown === 0;
    const unknownLabel = `근거 없음 ${unknown}개`;
    if (unknown) unknownSummary.replaceChildren(statusTag("unknown", unknownLabel));
    else unknownSummary.textContent = unknownLabel;
    overall.replaceChildren(state.mode === "SAFE_STOP" ? statusTag("caution", "안전 정지")
      : worst !== "fresh" ? statusTag(worst)
      : summary.children.length ? statusTag("fresh") : statusTag("unknown"));
  }
  function fail(error) {
    calibration.remove();
    summary.replaceChildren();
    summary.hidden = true;
    unknownBox.hidden = true;
    overall.replaceChildren();
    status.textContent = `상태를 불러오지 못했습니다: ${error.message}`;
    status.setAttribute("state", "error");
    status.hidden = false;
  }
  // 보조 행동 하나: 직접 운전은 밑줄 링크가 아니라 조용한 행동 링크다.
  const apps = createNode("ui-actions", "overview-actions");
  const pilot = createNode("a", "ui-action-link", "Rosy Pilot · 직접 운전");
  pilot.href = "/pilot";
  pilot.dataset.kind = "quiet";
  apps.append(pilot);
  el.append(header, status, summary, unknownBox, apps);
  return ctx.store.state(render, fail);
}
