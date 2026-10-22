// One read-only presentation for Fleet and the robot console. Receipt time never replaces sample age.
const EVIDENCE = {fresh: "실시간", delayed: "지연", disconnected: "연결 끊김", unavailable: "확인 불가"};
const JOINT = {shoulder_pan: "어깨 회전", shoulder_lift: "어깨 올림", elbow_flex: "팔꿈치",
  wrist_flex: "손목 굽힘", wrist_roll: "손목 회전", gripper: "그리퍼",
  joint1: "어깨 회전", joint2: "어깨 올림", joint3: "팔꿈치", joint4: "손목 굽힘",
  joint5: "손목 회전", gripper_joint_1: "그리퍼"};
const WARNING = {high_pwm: "PWM 사용률 높음", near_temperature_limit: "온도 한계 근접"};
const GROUP = {arm_a: "A 팔", arm_b: "B 팔", follower: "팔로워"};
const validAge = value => Number.isFinite(value) && value >= 0;
const hardwareFault = motor => Number.isInteger(motor.hardware_error) && motor.hardware_error > 0;
const number = (value, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : "—";
const ageText = age => validAge(age) ? `${age.toFixed(1)}초 전` : "관측 시각 없음";

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
          `${GROUP[motor.group] || motor.group || "팔로워"} ID ${motor.id ?? "—"} 하드웨어 오류 ${motor.hardware_error}`);
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
  root.classList.add("motor-health-summary");
  root.dataset.evidence = health.evidence;
  root.dataset.severity = health.severity;
  const warned = health.motors.filter(motor => motor.warnings.length);
  const failed = health.motors.filter(hardwareFault);
  const first = warned[0];
  const warning = first ? `${GROUP[first.group] || first.group || "팔로워"} ID ${first.id ?? "—"}: ${first.warnings[0]}` : "";
  const fresh = health.evidence === "fresh" && health.status === "active";
  const count = warned.length || (fresh && health.motors.length && !failed.length)
    ? `${fresh ? "" : "마지막 관측 · "}주의 모터 ${warned.length}개` : "";
  const faults = failed.length ? `고장 모터 ${failed.length}개 · ${failed.map(motor =>
    `${GROUP[motor.group] || motor.group || "팔로워"} ID ${motor.id ?? "—"} 오류 ${motor.hardware_error}`).join(" / ")}` : "";
  const cause = health.status === "fault" ? health.stopReasons[0] || health.lastFault
    : warning || (health.lastFault ? `마지막 중단: ${health.lastFault}` : "");
  root.textContent = [health.label, health.evidenceLabel, faults, count, cause].filter(Boolean).join(" · ");
  root.title = `${health.ageText}${health.lastFault ? ` · 마지막 중단: ${health.lastFault}` : ""}`;
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
    parts = {status, evidence, age, fault, warnings, empty, scroll, body}; views.set(root, parts);
  }
  root.dataset.evidence = health.evidence;
  parts.status.textContent = health.label;
  parts.status.dataset.severity = health.severity;
  parts.evidence.setAttribute("state", health.evidence);
  parts.evidence.textContent = health.evidenceLabel;
  parts.age.textContent = health.ageText;
  parts.fault.hidden = !health.lastFault;
  parts.fault.textContent = health.lastFault ? `마지막 중단: ${health.lastFault}` : "";
  const warnings = health.motors.filter(motor => motor.warnings.length).map(motor =>
    `${GROUP[motor.group] || motor.group || "팔로워"} ID ${motor.id ?? "—"}: ${motor.warnings.join(" · ")}`);
  parts.warnings.hidden = !warnings.length;
  parts.warnings.textContent = warnings.length ? `${health.evidence === "fresh" ? "주의" : "마지막 관측 주의"} · ${warnings.join(" / ")}` : "";
  parts.empty.hidden = health.motors.length > 0;
  parts.empty.textContent = health.supportReason;
  parts.scroll.hidden = health.motors.length === 0;
  const rows = health.motors.map(motor => {
    const row = node("tr"); row.dataset.evidence = motor.evidence;
    row.dataset.severity = motor.warnings.length ? "warn" : "neutral";
    const identity = node("th"); identity.scope = "row";
    identity.append(node("b", `${GROUP[motor.group] || motor.group || "팔로워"} · ID ${motor.id ?? "—"}`),
      node("span", JOINT[motor.joint] || motor.joint || "모터", "motor-health-sub"));
    const error = node("td");
    error.append(node("b", `${number(motor.error_deg, 2)}°`, "motor-health-reading"),
      node("span", `목표 ${number(motor.command_raw, 0)} / 현재 ${number(motor.present_raw, 0)} tick`, "motor-health-sub"));
    const pwm = node("td");
    pwm.append(node("b", `${number(motor.pwm, 0)} / ${number(motor.pwm_limit, 0)}`, "motor-health-reading"),
      node("span", `${number(Number.isFinite(motor.pwm_utilization) ? motor.pwm_utilization * 100 : null, 0)}% 사용`, "motor-health-sub"));
    const temperature = node("td", `${number(motor.temperature_c, 0)} / ${number(motor.temperature_limit_c, 0)} °C`, "motor-health-reading");
    const voltage = node("td");
    voltage.append(node("b", `${number(motor.voltage_v)} V`, "motor-health-reading"),
      node("span", `${number(motor.min_voltage_v)}–${number(motor.max_voltage_v)} V`, "motor-health-sub"));
    const observation = node("td");
    observation.append(node("span", `${EVIDENCE[motor.evidence]} · ${ageText(motor.age)}`),
      node("span", motor.warnings.join(" · "), "motor-health-sub motor-health-warning"));
    if (hardwareFault(motor)) {
      const fault = node("ui-tag", `하드웨어 오류 ${motor.hardware_error}`);
      fault.setAttribute("status", "crit"); observation.append(fault);
    }
    row.append(identity, error, pwm, temperature, voltage, observation);
    return row;
  });
  parts.body.replaceChildren(...rows);
}
