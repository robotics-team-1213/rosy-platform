// One read-only presentation for Fleet and the robot console. Receipt time never replaces sample age.
import { evidenceAgeText } from "./core_ui_logic.js";
const EVIDENCE = {fresh: "실시간", delayed: "지연", disconnected: "연결 끊김", unavailable: "확인 불가"};
const JOINT = {shoulder_pan: "어깨 회전", shoulder_lift: "어깨 올림", elbow_flex: "팔꿈치",
  wrist_flex: "손목 굽힘", wrist_roll: "손목 회전", gripper: "그리퍼",
  joint1: "어깨 회전", joint2: "어깨 올림", joint3: "팔꿈치", joint4: "손목 굽힘",
  joint5: "손목 회전", gripper_joint_1: "그리퍼"};
export const jointLabel = joint => JOINT[joint] || joint || "모터";
const WARNING = {high_pwm: "PWM 사용률 높음", near_temperature_limit: "온도 한계 근접"};
const GROUP = {arm_a: "A 팔", arm_b: "B 팔", follower: "팔로워"};
const validAge = value => Number.isFinite(value) && value >= 0;
const hardwareFault = motor => Number.isInteger(motor.hardware_error) && motor.hardware_error > 0;
// The joint the guard stopped on: the stop reason itself never names it.
const stopped = motor => motor.fault === true && !hardwareFault(motor);
const stoppedText = motor => `${GROUP[motor.group] || motor.group || "팔로워"} ${JOINT[motor.joint] || motor.joint || "모터"}(ID ${motor.id ?? "—"}) 정지`;
const number = (value, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : "—";
const ageText = age => validAge(age) ? evidenceAgeText(Math.round(age * 10) / 10).slice(3) : "관측 시각 없음";
const calmAge = (age, evidence) => evidence === "fresh" ? ""
  : validAge(age) ? evidenceAgeText(Math.floor(age)).slice(3) : "관측 시각 없음";
const putText = (element, text) => {
  const next = String(text ?? "");
  if (element.textContent !== next) element.textContent = next;
};
const putAttr = (element, name, value) => {
  const next = String(value);
  if (element.getAttribute(name) !== next) element.setAttribute(name, next);
};

export function createMotorHealthState() {
  let snapshot = null, receivedAtMs = null, cacheAgeS = 0, disconnected = false, lastFault = "";
  return {
    accept(value, options = {}) {
      snapshot = value?.schema_version === "rosy.motor-health.v1" ? value : null;
      receivedAtMs = options.receivedAtMs ?? Date.now();
      if (Number.isFinite(options.requestedAtMs)) receivedAtMs = Math.min(receivedAtMs, options.requestedAtMs);
      cacheAgeS = options.cacheAgeS === undefined ? 0 : options.cacheAgeS;
      disconnected = options.disconnected === true;
      if (snapshot?.status === "fault") {
        const faults = (snapshot.motors || []).filter(hardwareFault).map(motor =>
          `${GROUP[motor.group] || motor.group || "팔로워"} ID ${motor.id ?? "—"} 하드웨어 오류 ${motor.hardware_error}`)
          .concat((snapshot.motors || []).filter(stopped).map(stoppedText));
        lastFault = [...faults, ...(snapshot.stop_reasons || []).filter(reason => typeof reason === "string")].join(" · ")
          || "세션이 중단되었습니다.";
      }
    },
    disconnect() { disconnected = true; },
    read(nowMs = Date.now()) {
      const elapsed = Number.isFinite(receivedAtMs) && nowMs >= receivedAtMs ? (nowMs - receivedAtMs) / 1000 : null;
      const extra = validAge(elapsed) && validAge(cacheAgeS) ? elapsed + cacheAgeS : null;
      const age = validAge(snapshot?.sample_age_s) && validAge(extra) ? snapshot.sample_age_s + extra : null;
      const limit = Number.isFinite(snapshot?.stale_after_s) && snapshot.stale_after_s > 0 ? snapshot.stale_after_s : 2;
      let evidence = snapshot && Object.hasOwn(EVIDENCE, snapshot.evidence) ? snapshot.evidence : "unavailable";
      if (disconnected) evidence = "disconnected";
      else if (!validAge(age)) evidence = "unavailable";
      else if (evidence === "fresh" && (age > limit || snapshot.status !== "active")) evidence = "delayed";
      const motors = (Array.isArray(snapshot?.motors) ? snapshot.motors : []).map(motor => {
        const ownAge = validAge(motor.sample_age_s) && validAge(extra) ? motor.sample_age_s + extra : null;
        const rowAge = validAge(ownAge) && validAge(age) ? Math.max(age, ownAge) : null;
        const rowEvidence = evidence === "fresh" && (!validAge(rowAge) || rowAge > limit) ? "delayed" : evidence;
        return {...motor, age: rowAge, evidence: rowEvidence,
          warnings: (Array.isArray(motor.warnings) ? motor.warnings : []).map(warning => WARNING[warning] || String(warning))};
      });
      if (!motors.length && evidence === "fresh") evidence = "unavailable";
      const status = snapshot?.status || "unavailable";
      const severity = status === "fault" || motors.some(hardwareFault) ? "crit" : motors.some(motor => motor.warnings.length) ? "warn" : "neutral";
      const label = status === "fault" ? "모터 중단 기록" : status === "ended" ? "모터 세션 종료"
        : motors.some(hardwareFault) ? "모터 고장 관측"
          : evidence === "fresh" ? severity === "warn" ? "모터 주의" : "모터 관측 중" : `모터 ${EVIDENCE[evidence]}`;
      return {evidence, evidenceLabel: EVIDENCE[evidence], age, ageText: ageText(age), status, label, severity,
        motors, lastFault, supportReason: snapshot?.support_reason || "모터별 관측을 제공하는 실행 세션이 없습니다.",
        stopReasons: snapshot?.stop_reasons || [], sessionId: snapshot?.session_id || null};
    },
  };
}

const views = new WeakMap();
function node(tag, text, className = "") {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

export function renderMotorHealthSummary(root, health) {
  if (!root.classList.contains?.("motor-health-summary")) root.classList.add("motor-health-summary");
  if (root.dataset.evidence !== health.evidence) root.dataset.evidence = health.evidence;
  if (root.dataset.severity !== health.severity) root.dataset.severity = health.severity;
  const warned = health.motors.filter(motor => motor.warnings.length);
  const failed = health.motors.filter(hardwareFault);
  const first = warned[0];
  const warning = first ? `${GROUP[first.group] || first.group || "팔로워"} ID ${first.id ?? "—"}: ${first.warnings[0]}` : "";
  const fresh = health.evidence === "fresh" && health.status === "active";
  const count = warned.length || (fresh && health.motors.length && !failed.length)
    ? `${fresh ? "" : "마지막 관측 · "}주의 모터 ${warned.length}개` : "";
  const faults = failed.length ? `고장 모터 ${failed.length}개 · ${failed.map(motor =>
    `${GROUP[motor.group] || motor.group || "팔로워"} ID ${motor.id ?? "—"} 오류 ${motor.hardware_error}`).join(" / ")}` : "";
  const cause = health.status === "fault"
    ? [...health.motors.filter(stopped).map(stoppedText), health.stopReasons[0]].filter(Boolean).join(" · ") || health.lastFault
    : warning || (health.lastFault ? `마지막 중단: ${health.lastFault}` : "");
  const evidenceLabel = health.label && health.evidenceLabel && health.label.endsWith(health.evidenceLabel)
    ? ""
    : health.evidenceLabel;
  const nextText = [health.label, evidenceLabel, faults, count, cause].filter(Boolean).join(" · ");
  if (root.textContent !== nextText) root.textContent = nextText;
  const shownAge = health.evidence === "fresh" ? "실시간" : calmAge(health.age, health.evidence);
  const nextTitle = `${shownAge}${health.lastFault ? ` · 마지막 중단: ${health.lastFault}` : ""}`;
  if (root.title !== nextTitle) root.title = nextTitle;
}

function makeMotorRow() {
  const row = node("tr");
  const identity = node("th"); identity.scope = "row";
  const idEl = node("b"), jointEl = node("span", undefined, "motor-health-sub");
  identity.append(idEl, jointEl);
  const error = node("td"), errVal = node("b", undefined, "motor-health-reading"), errSub = node("span", undefined, "motor-health-sub");
  error.append(errVal, errSub);
  const pwm = node("td"), pwmVal = node("b", undefined, "motor-health-reading"), pwmSub = node("span", undefined, "motor-health-sub");
  pwm.append(pwmVal, pwmSub);
  const tempTd = node("td", undefined, "motor-health-reading");
  const voltage = node("td"), voltVal = node("b", undefined, "motor-health-reading"), voltSub = node("span", undefined, "motor-health-sub");
  voltage.append(voltVal, voltSub);
  const obs = node("td"), obsMain = node("span"), obsWarn = node("span", undefined, "motor-health-sub motor-health-warning");
  obs.append(obsMain, obsWarn);
  const stopTag = node("ui-tag", "이 관절에서 정지");
  stopTag.setAttribute("status", "crit");
  const faultTag = node("ui-tag");
  faultTag.setAttribute("status", "crit");
  row.append(identity, error, pwm, tempTd, voltage, obs);
  return {row, idEl, jointEl, errVal, errSub, pwmVal, pwmSub, tempTd, voltVal, voltSub, obs, obsMain, obsWarn, stopTag, faultTag};
}

export function renderMotorHealth(root, health) {
  let parts = views.get(root);
  if (!parts) {
    root.classList.add("motor-health");
    root.setAttribute("aria-label", "모터 상태");
    const heading = node("ui-head", "모터 상태");
    const line = node("div", undefined, "motor-health-status");
    const status = node("strong");
    status.setAttribute("role", "status");
    const evidence = node("ui-evidence"), age = node("span", undefined, "motor-health-age");
    evidence.setAttribute("state", health.evidence);
    line.append(status, evidence, age);
    const fault = node("p", undefined, "motor-health-fault");
    const warnings = node("p", undefined, "motor-health-warnings");
    const empty = node("p", undefined, "motor-health-empty");
    const scroll = node("div", undefined, "motor-health-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", "모터별 상태 표, 가로로 스크롤");
    const table = node("table", undefined, "motor-health-table");
    const caption = node("caption", "명령을 받는 팔로워 모터 · PWM은 설정 한도에 대한 사용률이며 토크 값이 아닙니다.");
    const head = node("thead"), header = node("tr");
    for (const title of ["모터", "추종 오차", "PWM / 설정 한도", "온도 / 설정 한계", "입력 전압 / 설정 범위", "관측"]) {
      const cell = node("th", title); cell.scope = "col"; header.append(cell);
    }
    head.append(header);
    const body = node("tbody");
    table.append(caption, head, body); scroll.append(table);
    const note = node("p", "보기 전용 · 이 화면은 모터를 켜거나 오류를 해제하지 않습니다.", "motor-health-note");
    root.replaceChildren(heading, line, fault, warnings, empty, scroll, note);
    parts = {status, evidence, age, fault, warnings, empty, scroll, body, rows: new Map()};
    views.set(root, parts);
  }
  if (root.dataset.evidence !== health.evidence) root.dataset.evidence = health.evidence;
  putText(parts.status, health.label);
  if (parts.status.dataset.severity !== health.severity) parts.status.dataset.severity = health.severity;
  putAttr(parts.evidence, "state", health.evidence);
  putText(parts.evidence, health.evidenceLabel);
  const ageHidden = health.evidence === "fresh";
  if (parts.age.hidden !== ageHidden) parts.age.hidden = ageHidden;
  putText(parts.age, calmAge(health.age, health.evidence));
  const faultHidden = !health.lastFault;
  if (parts.fault.hidden !== faultHidden) parts.fault.hidden = faultHidden;
  putText(parts.fault, health.lastFault ? `마지막 중단: ${health.lastFault}` : "");
  const warnings = health.motors.filter(motor => motor.warnings.length).map(motor =>
    `${GROUP[motor.group] || motor.group || "팔로워"} ID ${motor.id ?? "—"}: ${motor.warnings.join(" · ")}`);
  const warnHidden = !warnings.length;
  if (parts.warnings.hidden !== warnHidden) parts.warnings.hidden = warnHidden;
  putText(parts.warnings, warnings.length ? `${health.evidence === "fresh" ? "주의" : "마지막 관측 주의"} · ${warnings.join(" / ")}` : "");
  const emptyHidden = health.motors.length > 0;
  if (parts.empty.hidden !== emptyHidden) parts.empty.hidden = emptyHidden;
  putText(parts.empty, health.supportReason);
  const scrollHidden = health.motors.length === 0;
  if (parts.scroll.hidden !== scrollHidden) parts.scroll.hidden = scrollHidden;
  const used = new Map();
  const desired = [];
  const nextKeys = new Set();
  health.motors.forEach((motor, idx) => {
    const base = `${motor.group || "follower"}:${motor.id ?? idx}`;
    const nth = (used.get(base) || 0) + 1;
    used.set(base, nth);
    const key = nth === 1 ? base : `${base}#${nth}`;
    nextKeys.add(key);
    let rec = parts.rows.get(key);
    if (!rec) { rec = makeMotorRow(); parts.rows.set(key, rec); }
    const sev = stopped(motor) ? "crit" : motor.warnings.length ? "warn" : "neutral";
    if (rec.row.dataset.evidence !== motor.evidence) rec.row.dataset.evidence = motor.evidence;
    if (rec.row.dataset.severity !== sev) rec.row.dataset.severity = sev;
    putText(rec.idEl, `${GROUP[motor.group] || motor.group || "팔로워"} · ID ${motor.id ?? "—"}`);
    putText(rec.jointEl, JOINT[motor.joint] || motor.joint || "모터");
    putText(rec.errVal, `${number(motor.error_deg, 2)}°`);
    putText(rec.errSub, `목표 ${number(motor.command_raw, 0)} / 현재 ${number(motor.present_raw, 0)} tick`);
    putText(rec.pwmVal, `${number(motor.pwm, 0)} / ${number(motor.pwm_limit, 0)}`);
    putText(rec.pwmSub, `${number(Number.isFinite(motor.pwm_utilization) ? motor.pwm_utilization * 100 : null, 0)}% 사용`);
    putText(rec.tempTd, `${number(motor.temperature_c, 0)} / ${number(motor.temperature_limit_c, 0)} °C`);
    putText(rec.voltVal, `${number(motor.voltage_v)} V`);
    putText(rec.voltSub, `${number(motor.min_voltage_v)}–${number(motor.max_voltage_v)} V`);
    putText(rec.obsMain, motor.evidence === "fresh"
      ? EVIDENCE[motor.evidence]
      : `${EVIDENCE[motor.evidence]} · ${calmAge(motor.age, motor.evidence)}`);
    putText(rec.obsWarn, motor.warnings.join(" · "));
    if (stopped(motor)) { if (rec.stopTag.parentNode !== rec.obs) rec.obs.append(rec.stopTag); }
    else if (rec.stopTag.parentNode) rec.stopTag.remove();
    if (hardwareFault(motor)) {
      putText(rec.faultTag, `하드웨어 오류 ${motor.hardware_error}`);
      if (rec.faultTag.parentNode !== rec.obs) rec.obs.append(rec.faultTag);
    } else if (rec.faultTag.parentNode) {
      rec.faultTag.remove();
    }
    desired.push(rec.row);
  });
  for (const key of parts.rows.keys()) if (!nextKeys.has(key)) parts.rows.delete(key);
  if (desired.length !== parts.body.children.length || desired.some((row, i) => parts.body.children[i] !== row)) {
    parts.body.replaceChildren(...desired);
  }
}
