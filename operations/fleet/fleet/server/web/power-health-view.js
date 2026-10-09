// D-509: only CORE power evidence can confirm charging. Fleet cache age and
// browser elapsed time both count; a stale percentage is not a live reading.
export function powerHealthView(robot, receivedAtMs, nowMs) {
  const unknown = { battery: "확인 불가", voltage: null, charging: "확인 불가",
    problem: "배터리 근거 확인 불가 — 센서/CORE 확인" };
  const safetyRelease = robot.online && robot.state?.safety?.estop === true
    ? "관리자: 로봇 안전 상태 확인 후 명시적으로 해제" : "";
  const age = robot.power_health_age_s;
  const health = robot.power_health;
  const battery = health?.battery;
  const elapsed = Math.max(0, nowMs - (receivedAtMs ?? nowMs)) / 1000;
  if (!robot.online || !Number.isFinite(age) || age < 0 || age + elapsed > 5
      || !battery || battery.evidence !== "fresh"
      || !Number.isFinite(battery.sample_age_s) || battery.sample_age_s < 0
      || !Number.isFinite(battery.stale_after_s) || battery.stale_after_s <= 0
      || battery.sample_age_s + age + elapsed > battery.stale_after_s) {
    return { ...unknown, safetyRelease };
  }
  const percent = Number.isFinite(battery.percent) && battery.percent >= 0 && battery.percent <= 100
    ? `${Math.round(battery.percent)}%` : "확인 불가";
  const chargeAge = battery.charging_evidence_age_s;
  const charging = battery.charging_state !== "confirmed" ? "충전 미확인"
    : Number.isFinite(chargeAge) && chargeAge >= 0 && chargeAge + age + elapsed <= 5
      ? "충전 확인" : "확인 불가";
  let problem = "";
  if (battery.level !== "ok") problem = "배터리 경고 — 충전·절전 확인";
  else if (charging !== "충전 확인" && ["DOCKED", "CHARGING"].includes(robot.state?.docking?.state))
    problem = "도킹 후 충전 미확인 — 도크·전압 근거 확인";
  const voltage = Number.isFinite(battery.filtered_voltage) ? battery.filtered_voltage : null;
  return { battery: percent, voltage, charging, problem, safetyRelease,
    observedAgeS: Math.round(battery.sample_age_s + age + elapsed) };
}
