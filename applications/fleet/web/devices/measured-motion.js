import { staleAgeS } from "/console/assets/state-age.js";

const MOVING_LINEAR_MS = 0.01, MOVING_ANGULAR_RS = 0.02;

/** True/false when CORE's fresh velocity says so; null when not provable (no state, stale, or evidence not fresh). */
export function movingNow(state, stale) {
  const v = state?.velocity;
  if (stale !== null || !Number.isFinite(v?.linear) || !Number.isFinite(v?.angular)
      || state.evidence?.velocity?.evidence !== "fresh") return null;
  return Math.abs(v.linear) > MOVING_LINEAR_MS || Math.abs(v.angular) > MOVING_ANGULAR_RS;
}

export function measuredMotion(robot, view, nowMs = Date.now()) {
  if (view.stateUnavailable || !robot.online) return null;
  const { state } = robot;
  const velocity = state?.evidence?.velocity;
  const elapsed = Math.max(0, nowMs - (view.receivedAtMs ?? nowMs)) / 1000;
  const sourceStamped = velocity && Object.hasOwn(velocity, "sampled_at");
  const sampled = Date.parse(sourceStamped ? velocity.sampled_at : velocity?.received_at) / 1000;
  if (sourceStamped && !Number.isFinite(sampled)) return null;
  const sampleAge = Number.isFinite(sampled) && Number.isFinite(state?.ts) ? Math.max(0, state.ts - sampled) : 0;
  if (Number.isFinite(velocity?.stale_after_s)
      && sampleAge + (robot.state_age_s ?? 0) + elapsed > velocity.stale_after_s) return null;
  return movingNow(state, staleAgeS(robot, view.receivedAtMs, nowMs));
}

export function motionLabel(moving) {
  return moving === null ? "이동 미확인" : moving ? "이동 중" : "정지";
}

export function fleetMotion(robots, view, nowMs) {
  const motions = robots.map(r => measuredMotion(r, view, nowMs));
  const movingCount = motions.filter(moving => moving === true).length;
  const unknownCount = motions.filter(moving => moving === null).length;
  const text = !robots.length ? "—" : unknownCount === robots.length ? `미확인 ${robots.length}대`
    : `${movingCount}대${unknownCount ? ` · 미확인 ${unknownCount}대` : ""}`;
  return { text, tone: movingCount ? "active" : unknownCount ? "warn" : "neutral" };
}
