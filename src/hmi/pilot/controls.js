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

export function profileFromBaseVelocity(control) {
  const autonomy = Array.isArray(control?.autonomy) ? control.autonomy : [];
  return {kind: "base", command: "velocity", pivot: control?.pivot !== false,
          fine: control?.fine !== false, autonomy: autonomy.filter((mode) => KNOWN_AUTONOMY.has(mode))};
}

// SIM servers before v1.76 have no `controls`: the legacy screen jogged every joint and the
// gripper by 0.02 rad, so that is the fallback (limits unknown → null).
export function fallbackOmxControls(target) {
  const names = [...new Set([...(target?.joints ?? []), ...(target?.gripper ? [target.gripper] : [])])];
  return [{id: "arm", kind: "joint_jog", label: "팔", max_step_rad: 0.02, duration_s: 0.4,
           command: "bounded_goal", joints: names.map((name) => ({name, lower: null, upper: null}))}];
}
