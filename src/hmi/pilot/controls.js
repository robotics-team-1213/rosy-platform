// D-411 B: rosy.controls/1 on the Pilot side. Drivers only transport; one widget per kind.
// Forward compatible (API Ref §9.1): unknown kinds are shown as unsupported, unknown fields
// are ignored. A missing descriptor (old server) falls back to the legacy profile; an
// EMPTY `items` means "no controls right now" and is not a fallback.
export const CONTROLS_SCHEMA = "rosy.controls/1";
const KNOWN_AUTONOMY = new Set(["line"]);

export function readControls(descriptor) {
  if (!descriptor || descriptor.schema !== CONTROLS_SCHEMA || !Array.isArray(descriptor.items)) return null;
  return descriptor.items.filter((item) => item && typeof item.kind === "string" && typeof item.id === "string");
}

export function widgetPlan(items, kinds) {
  const known = new Set(kinds);
  return (items ?? []).map((control) => ({control, supported: known.has(control.kind)}));
}

export function fallbackPinkyControls(profile) {
  return [{id: "base", kind: "base_velocity", label: "주행", max_linear: null, max_angular: null,
           pivot: profile?.pivot !== false, fine: profile?.fine !== false,
           autonomy: [...(profile?.autonomy ?? [])]}];
}

// max_linear / max_angular are the live manual limits (0 = held at standstill); null when the
// device did not announce them (legacy fallback).
export function profileFromBaseVelocity(control) {
  const autonomy = Array.isArray(control?.autonomy) ? control.autonomy : [];
  const cap = (value) => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null);
  return {kind: "base", command: "velocity", pivot: control?.pivot !== false,
          fine: control?.fine !== false, autonomy: autonomy.filter((mode) => KNOWN_AUTONOMY.has(mode)),
          max_linear: cap(control?.max_linear), max_angular: cap(control?.max_angular)};
}

// SIM servers before v1.76 have no `controls`: the legacy screen jogged every joint and the
// gripper by 0.02 rad, so that is the fallback (limits unknown → null).
export function fallbackOmxControls(target) {
  const names = [...new Set([...(target?.joints ?? []), ...(target?.gripper ? [target.gripper] : [])])];
  return [{id: "arm", kind: "joint_jog", label: "팔", max_step_rad: 0.02, duration_s: 0.4,
           command: "bounded_goal", joints: names.map((name) => ({name, lower: null, upper: null}))}];
}

// D-411 C: gripper. 0 % = closed, 100 % = open, whichever way the joint turns.
// A full stroke takes the longest goal (2.0 s, OmxSimGripperGoal), a shorter move
// proportionally less, never under the 0.2 s goal minimum.
export const GRIPPER_GOAL_MIN_S = 0.2;
export const GRIPPER_GOAL_MAX_S = 2.0;
export const GRIPPER_STATE_LABEL = Object.freeze({
  open: "열림", closed: "닫힘", holding: "쥐고 있음", moving: "이동 중", unknown: "알 수 없음",
});

const clamp = (value, low, high) => Math.max(low, Math.min(high, value));

export function gripperPercent(position, g) {
  if (!Number.isFinite(position)) return null;
  return Math.round(clamp((position - g.closed) / (g.open - g.closed), 0, 1) * 100);
}

export function gripperPosition(percent, g) {
  const p = clamp(Number(percent) || 0, 0, 100) / 100;
  return Math.round((g.closed + (g.open - g.closed) * p) * 1e4) / 1e4;
}

export function gripperDuration(from, to, g) {
  const fraction = Number.isFinite(from) ? Math.abs(to - from) / Math.abs(g.open - g.closed) : 1;
  return Math.round(clamp(fraction * GRIPPER_GOAL_MAX_S, GRIPPER_GOAL_MIN_S, GRIPPER_GOAL_MAX_S) * 100) / 100;
}

export function gripperStateLabel(state) {
  return GRIPPER_STATE_LABEL[state] ?? GRIPPER_STATE_LABEL.unknown;
}
