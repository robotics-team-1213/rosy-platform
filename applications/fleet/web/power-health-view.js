// D-509: only CORE power evidence can confirm charging. Fleet cache age and
// browser elapsed time both count; a stale percentage is not a live reading.
function agoText(sec) {
  return sec >= 3600 ? `${(sec / 3600).toFixed(1)}시간 전` : `${Math.max(1, Math.round(sec / 60))}분 전`;
}

export function powerHealthView(robot, receivedAtMs, nowMs) {
  const unknown = { battery: "확인 불가", voltage: null, charging: "확인 불가",
    problem: "배터리 값 없음 — 배터리 센서 서비스 확인", note: "" };
  const safetyRelease = robot.online && robot.state?.safety?.estop === true
    ? "로봇 안전 확인 후: 로봇 등록 목록 → 비상정지 해제… → 그 로봇 정지 화면의 Release code" : "";
  const age = robot.power_health_age_s;
  const health = robot.power_health;
  const battery = health?.battery;
  const elapsed = Math.max(0, nowMs - (receivedAtMs ?? nowMs)) / 1000;
  if (!robot.online || !Number.isFinite(age) || age < 0 || age + elapsed > 5 || !battery) {
    // No Fleet read, or one too old (a slow or timed-out fetch): unknown, but the robot said
    // nothing wrong, so it is not an attention item (field check 2026-10-10).
    return { ...unknown, problem: "", safetyRelease };
  }
  if (battery.evidence !== "fresh"
      || !Number.isFinite(battery.sample_age_s) || battery.sample_age_s < 0
      || !Number.isFinite(battery.stale_after_s) || battery.stale_after_s <= 0) {
    // missing: no reading ever arrived (rosy-io off); anything else: a value that froze or is unusable.
    if (battery.evidence === "missing") return { ...unknown, safetyRelease };
    const frozen = battery.evidence === "stale" && Number.isFinite(battery.sample_age_s) && battery.sample_age_s >= 0
      ? battery.sample_age_s + age + elapsed : null;
    // The age stays out of `problem`: queue rows group by identical text, a varying age would split them.
    return { ...unknown, problem: "배터리 값 멈춤 — 센서 연결 확인", safetyRelease,
      note: frozen === null ? "값 멈춤" : `값 멈춤 (${agoText(frozen)})` };
  }
  if (battery.sample_age_s + age + elapsed > battery.stale_after_s) {
    return { ...unknown, problem: "", safetyRelease };
  }
  const held = battery.charging_state === "confirmed"
    && Number.isFinite(battery.shown_percent)
    && battery.shown_percent >= 0 && battery.shown_percent <= 100
    ? battery.shown_percent : null;
  const reading = held !== null ? held : battery.percent;
  const percent = Number.isFinite(reading) && reading >= 0 && reading <= 100
    ? `${Math.round(reading)}%` : "확인 불가";
  const chargeAge = battery.charging_evidence_age_s;
  const chargingLabel = held !== null ? `충전 확인 · ${Math.round(held)}%` : "충전 확인";
  const charging = battery.charging_state !== "confirmed" ? "충전 미확인"
    : Number.isFinite(chargeAge) && chargeAge >= 0 && chargeAge + age + elapsed <= 5
      ? chargingLabel : "확인 불가";
  let problem = "";
  if (battery.level !== "ok") problem = "배터리 경고 — 충전·절전 확인";
  else if (charging !== "충전 확인" && ["DOCKED", "CHARGING"].includes(robot.state?.docking?.state))
    problem = "도킹 후 충전 미확인 — 도크·전압 근거 확인";
  const voltage = Number.isFinite(battery.filtered_voltage) ? battery.filtered_voltage : null;
  return { battery: percent, voltage, charging, problem, safetyRelease,
    observedAgeS: Math.round(battery.sample_age_s + age + elapsed) };
}
