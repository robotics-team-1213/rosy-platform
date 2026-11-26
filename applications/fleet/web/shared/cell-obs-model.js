// Shared pure (DOM-free) workcell observation & camera utilities for Console and Cell.

export const OBS_BASE = "/api/fleet/workcell-observations";
const JOINT_ORDER = ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"];
export const JOINT_SHORT = ["J1", "J2", "J3", "J4", "J5", "G"];
const RAD_TO_DEG = 180 / Math.PI;
const CAMERA_RANK = { overhead: 0, side: 1, wrist: 2 };

export function canonicalArmId(raw) {
  return String(raw || "").trim().toLowerCase().replace(/^omx_/, "").replace(/_follower$/, "");
}

function cameraRank(cam) {
  return (CAMERA_RANK[cam?.role] ?? 2) + (cam?.stream === "depth" ? 0.5 : 0);
}

export function compareCameras(a, b) {
  return cameraRank(a) - cameraRank(b);
}

export const isHomeRecovery = (incident) => incident?.event_kind === "home_recovery";

export function partitionIncidents(incidents) {
  const list = Array.isArray(incidents) ? incidents : [];
  const pending = list.filter((inc) => inc?.state !== "cleared");
  const open = pending.filter((inc) => !isHomeRecovery(inc));
  const homeRecoveries = pending.filter(isHomeRecovery);
  const held = open.filter((inc) => inc?.decision?.hold !== false);
  const cleared = list.filter((inc) => inc?.state === "cleared");
  const armHeld = pending.some((inc) => inc?.decision?.hold !== false);
  return { open, held, cleared, homeRecoveries, armHeld, namingCount: open.length - held.length };
}

export function formatIncidentCountSummary(totalCount, heldCount, namingCount) {
  if (!totalCount) return "팔 사건 없음";
  const status = heldCount ? `보류 중 ${heldCount}건 (세션 시작 불가)` : namingCount ? "보류 없음" : "모두 해제됨";
  return `팔 사건 ${totalCount}건 · ${status}${namingCount ? ` · 원인 기록 대기 ${namingCount}건` : ""}`;
}

export function isArmAttentionOrLive(arm, selectedId = null) {
  if (!arm) return false;
  return Boolean(
    arm.held
    || (arm.openIncidents && arm.openIncidents.length > 0)
    || arm.hwFaultMotors > 0
    || arm.warnMotors > 0
    || arm.motorHealth?.status === "fault"
    || arm.motorHealth?.status === "warn"
    || arm.fresh
    || (selectedId && arm.id === selectedId),
  );
}

function readArmMetrics(arm, fresh, positions) {
  const health = arm?.motor_health?.schema_version === "rosy.motor-health.v1" ? arm.motor_health : null;
  const motors = Array.isArray(health?.motors) ? health.motors : [];
  let maxTempC = null;
  let maxPwmPct = null;
  let maxCurrentMa = null;
  let hwFaultMotors = 0;
  let warnMotors = 0;
  for (const m of motors) {
    if (Number.isInteger(m?.hardware_error) && m.hardware_error > 0) hwFaultMotors += 1;
    if (Array.isArray(m?.warnings) && m.warnings.length > 0) warnMotors += 1;
    if (typeof m?.temperature_c === "number" && Number.isFinite(m.temperature_c)) {
      maxTempC = maxTempC === null ? m.temperature_c : Math.max(maxTempC, m.temperature_c);
    }
    const util = typeof m?.pwm_utilization === "number" && Number.isFinite(m.pwm_utilization)
      ? Math.round(m.pwm_utilization * 100)
      : (typeof m?.pwm === "number" && Number.isFinite(m.pwm) && typeof m?.pwm_limit === "number" && m.pwm_limit > 0
          ? Math.round((Math.abs(m.pwm) / m.pwm_limit) * 100)
          : null);
    if (util !== null) maxPwmPct = maxPwmPct === null ? util : Math.max(maxPwmPct, util);
    if (typeof m?.current_ma === "number" && Number.isFinite(m.current_ma)) {
      const ma = Math.round(Math.abs(m.current_ma));
      maxCurrentMa = maxCurrentMa === null ? ma : Math.max(maxCurrentMa, ma);
    }
  }
  const jointsDeg = positions
    ? JOINT_ORDER.map((k) => (typeof positions[k] === "number" && Number.isFinite(positions[k]) ? positions[k] * RAD_TO_DEG : null))
    : null;
  const jointsText = jointsDeg && jointsDeg.some((v) => v !== null)
    ? jointsDeg.map((deg, idx) => (deg === null ? `${JOINT_SHORT[idx]}:—` : `${JOINT_SHORT[idx]}:${deg.toFixed(1)}°`)).join(" ")
    : null;
  return { health, motors, maxTempC, maxPwmPct, maxCurrentMa, hwFaultMotors, warnMotors, jointsDeg, jointsText, fresh };
}

export function normalizeWorkcellObservations(payload, receivedAtMs = Date.now()) {
  const workcells = Array.isArray(payload?.workcells) ? payload.workcells : [];
  const arms = [];
  const cameras = [];

  for (const cell of workcells) {
    for (const arm of Array.isArray(cell?.arms) ? cell.arms : []) {
      const id = canonicalArmId(arm?.arm_id || arm?.source_id);
      if (!id) continue;
      const rawPos = arm?.positions && typeof arm.positions === "object" ? arm.positions : null;
      const cleanEntries = rawPos
        ? Object.entries(rawPos).filter(([, v]) => typeof v === "number" && Number.isFinite(v))
        : [];
      const fresh = Boolean(arm?.fresh) && cleanEntries.length > 0;
      const positions = fresh ? Object.fromEntries(cleanEntries) : null;
      const metrics = readArmMetrics(arm, fresh, positions);
      const incidents = Array.isArray(arm?.incidents) ? arm.incidents : [];
      const { open: openIncidents, held: heldIncidents, homeRecoveries, armHeld } = partitionIncidents(incidents);
      const ageS = typeof arm?.source_age_s === "number" && Number.isFinite(arm.source_age_s)
        ? arm.source_age_s
        : (typeof arm?.receipt_age_s === "number" && Number.isFinite(arm.receipt_age_s) ? arm.receipt_age_s : null);
      arms.push({
        id,
        sourceId: String(arm?.source_id || id),
        armId: String(arm?.arm_id || id),
        label: String(arm?.label || id),
        fresh,
        positions,
        jointsDeg: metrics.jointsDeg,
        jointsText: metrics.jointsText,
        motorHealth: metrics.health,
        maxTempC: metrics.maxTempC,
        maxPwmPct: metrics.maxPwmPct,
        maxCurrentMa: metrics.maxCurrentMa,
        hwFaultMotors: metrics.hwFaultMotors,
        warnMotors: metrics.warnMotors,
        incidents,
        openIncidents,
        heldIncidents,
        homeRecoveries,
        held: armHeld,
        faults: Array.isArray(arm?.faults) ? arm.faults : [],
        ageS,
        sequence: typeof arm?.sequence === "number" ? arm.sequence : 0,
      });
    }
    for (const cam of Array.isArray(cell?.cameras) ? cell.cameras : []) {
      if (!cam?.source_id) continue;
      cameras.push({
        source_id: String(cam.source_id),
        label: String(cam.label || cam.source_id),
        role: String(cam.role || "wrist"),
        stream: cam.stream ? String(cam.stream) : "color",
        arm_id: cam.arm_id ? canonicalArmId(cam.arm_id) : null,
        fresh: Boolean(cam.fresh),
        frame_seq: typeof cam.frame_seq === "number" ? cam.frame_seq : null,
        age_s: typeof cam.age_s === "number" && Number.isFinite(cam.age_s) ? cam.age_s : null,
      });
    }
  }

  cameras.sort(compareCameras);

  const summary = {
    armsTotal: arms.length,
    armsFresh: arms.filter((a) => a.fresh).length,
    camsTotal: cameras.length,
    camsLive: cameras.filter((c) => c.fresh).length,
    heldCount: arms.filter((a) => a.held).length,
    incidentHeldCount: arms.filter((a) => a.heldIncidents.length > 0).length,
    homeRecoveryCount: arms.reduce((n, a) => n + a.homeRecoveries.length, 0),
    openIncidentCount: arms.reduce((n, a) => n + a.openIncidents.length, 0),
    faultArmCount: arms.filter((a) => a.hwFaultMotors > 0 || a.motorHealth?.status === "fault").length,
    warnArmCount: arms.filter((a) => a.warnMotors > 0).length,
    receivedAtMs,
  };
  return { receivedAtMs, arms, cameras, summary };
}

export function obsSignature(obs) {
  if (!obs) return "";
  return JSON.stringify({
    arms: (obs.arms || []).map((a) => ({
      id: a.id,
      label: a.label,
      fresh: a.fresh,
      held: a.heldIncidents.length,
      recovery: a.homeRecoveries?.length || 0,
      armHeld: a.held,
      open: a.openIncidents.length,
      faults: a.faults,
      hw: a.hwFaultMotors,
      warn: a.warnMotors,
      temp: a.maxTempC,
      pwm: a.maxPwmPct,
      ma: a.maxCurrentMa,
      mhStatus: a.motorHealth?.status || "",
      mhEv: a.motorHealth?.evidence || "",
      joints: a.jointsDeg ? a.jointsDeg.map((d) => (d === null ? null : d.toFixed(1))) : null,
    })),
    cams: (obs.cameras || []).map((c) => [c.source_id, c.label, c.role, c.stream, c.arm_id, c.fresh]),
  });
}
