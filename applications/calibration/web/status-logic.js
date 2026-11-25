// Fail-closed status helpers for Rosy Calibration (never claim clear/pass on missing evidence).

export function mergeIncident(profileInc, liveInc) {
  const isHeld = (inc) =>
    inc?.local_held === true || inc?.fleet_held === true || Number(inc?.unsent_outbox) > 0;
  if (!liveInc) return profileInc || null;
  if (!profileInc) return liveInc;
  if (!isHeld(profileInc) && !isHeld(liveInc)) {
    if (liveInc.error || liveInc.local_held !== undefined || liveInc.fleet_held !== undefined) {
      return liveInc;
    }
    return profileInc;
  }
  const ids = [...new Set([...(profileInc.incident_ids || []), ...(liveInc.incident_ids || [])])];
  const pickHeld = (a, b) => (a === true || b === true ? true : b ?? a ?? null);
  return {
    ...profileInc,
    ...liveInc,
    local_held: pickHeld(profileInc.local_held, liveInc.local_held),
    fleet_held: pickHeld(profileInc.fleet_held, liveInc.fleet_held),
    unsent_outbox: Math.max(Number(profileInc.unsent_outbox) || 0, Number(liveInc.unsent_outbox) || 0),
    incident_ids: ids,
    local_reason: liveInc.local_reason || profileInc.local_reason,
    fleet_reason: liveInc.fleet_reason || profileInc.fleet_reason,
  };
}

export function classifyHold(inc) {
  const outbox = Number(inc?.unsent_outbox) || 0;
  const ids = (inc?.incident_ids || []).filter(Boolean).join(",");
  if (inc?.local_held === true || inc?.fleet_held === true || outbox > 0) {
    const badge = `HELD (${ids || (outbox > 0 ? `outbox:${outbox}` : "hold")})`;
    const reasons = [inc?.local_reason, inc?.fleet_reason].filter(Boolean).join(" / ");
    const detail = `${badge}${outbox > 0 && ids ? ` · outbox ${outbox}` : ""}${reasons ? ` · ${reasons}` : ""}`;
    return { state: "held", status: "crit", badge, detail };
  }
  if (inc?.error) {
    return { state: "error", status: "warn", badge: "HOLD 조회 오류", detail: `조회 오류 (${inc.error})` };
  }
  if (inc?.local_held === false && inc?.fleet_held !== false) {
    const why = inc?.fleet_reason ? ` (${inc.fleet_reason})` : "";
    return {
      state: "partial",
      status: inc?.fleet_reason ? "warn" : "neutral",
      badge: "HOLD 미확인 (Fleet)",
      detail: `local clear · Fleet 미확인${why}`,
    };
  }
  if (!inc || inc.local_held !== false || inc.fleet_held !== false) {
    return { state: "unknown", status: "neutral", badge: "HOLD 미확인", detail: "미확인 (보류 정보 없음)" };
  }
  return { state: "clear", status: "neutral", badge: "HOLD CLEAR", detail: "clear (local·Fleet 확인)" };
}

export function classifyFrameBinding(profile) {
  const hygiene = profile?.hygiene || [];
  const shiftErr = hygiene.find((h) => h.code === "camera_shifted")?.message;
  const bindErr = hygiene.find((h) => h.code === "map_binding")?.message;
  const shift = profile?.camera_top?.shift;
  const shiftText = shift?.ok
    ? `shift max ${shift.max_px}px`
    : shift
      ? `카메라 이동 미확인 (${shift.why || "비교 실패"})`
      : "카메라 이동 미확인";
  if (shiftErr) {
    return { status: "crit", badge: "CAMERA SHIFTED", title: shiftErr, shiftText };
  }
  if (bindErr) {
    const note = shift?.ok ? bindErr : `${bindErr} (카메라가 실제로 움직였는지는 아직 확인되지 않았습니다)`;
    return { status: "warn", badge: "MAP UNBOUND", title: note, shiftText };
  }
  if (profile?.camera_top?.has_reference === false) {
    return { status: "warn", badge: "NO REFERENCE", title: "기준 이미지 없음 · 카메라 이동 미확인", shiftText };
  }
  const okNote = shift?.ok
    ? `지도 결속 일치 (${shiftText})`
    : "지도 결속은 일치하나 카메라가 움직였는지는 아직 확인되지 않았습니다";
  return { status: "active", badge: "MAP BOUND", title: okNote, shiftText };
}

export function classifyDrift(profile) {
  const drift = profile?.cross_verify?.drift || profile?.drift || {};
  const alarmed = drift.alarmed_sites || [];
  const sites = Object.values(drift.sites || {});
  if (alarmed.length > 0) {
    return { verdict: "advisory", alarmed, detail: ` (${drift.pattern || "drift"}: ${alarmed.length})`, drift };
  }
  if (sites.some((s) => s?.status === "pass")) {
    return { verdict: "pass", alarmed, detail: "", drift };
  }
  return { verdict: "unknown", alarmed, detail: "", drift };
}
export function linkedArm(search) {
  const arms = new URLSearchParams(search).getAll("arm");
  return arms.length === 1 && ["arm_a", "arm_b", "arm_s"].includes(arms[0]) ? arms[0] : null;
}

export function profileForArm(profiles, arm, selected) {
  if (arm) return profiles.find(p => (p.arm_id || p.id) === arm) || null;
  return profiles.find(p => p.id === selected) || profiles[0] || null;
}

export function defaultSiteForProfile(profile) {
  if (!profile?.sites) return null;
  for (const s of profile.map_sites || []) {
    if (profile.sites[s]?.map) return s;
  }
  for (const [k, v] of Object.entries(profile.sites)) {
    if (!v.extra && v.map) return k;
  }
  return Object.keys(profile.sites)[0] || null;
}
