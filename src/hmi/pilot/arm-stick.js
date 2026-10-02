// D-411 B: arm joystick — sequential bounded goals (D-390 §2). No DOM, no fetch, no clock.
// Release stops issuing; a goal already sent (<= max step, duration_s) finishes: OMX cancel
// latches the owner in HOLD and the SIM API has no recover path (D-411 구현 부록).
export const DEADZONE = 0.15;
const TERMINAL_OK = "SUCCEEDED";

const clamp = (v) => Math.max(-1, Math.min(1, v));
const round4 = (v) => Math.round(v * 1e4) / 1e4;

// Pointer offset from the pad centre (screen px, y down) → axes in [-1, 1], y up.
export function axesFromOffset(dx, dy, radius) {
  const r = radius > 0 ? radius : 1;
  return {x: round4(clamp(dx / r)), y: round4(clamp(-dy / r)) || 0};
}

// One goal moves one joint (OmxSimJog.joint), so only the dominant axis is sent.
export function stepFor(axes, mapping, maxStep, deadzone = DEADZONE) {
  const ax = Math.abs(axes?.x ?? 0), ay = Math.abs(axes?.y ?? 0);
  const [axis, value] = ax >= ay ? ["x", axes?.x ?? 0] : ["y", axes?.y ?? 0];
  const magnitude = Math.abs(value);
  if (magnitude <= deadzone || !mapping?.[axis] || !(maxStep > 0)) return null;
  const delta = round4(Math.sign(value) * maxStep * Math.min(1, (magnitude - deadzone) / (1 - deadzone)));
  return delta === 0 ? null : {joint: mapping[axis], delta};
}

// `submit(step)` resolves to the accepted command id (truthy) or a falsy value / throws when
// the goal was not accepted. `settled(state, commandId)` reports the goal's terminal state;
// a settle naming another command (e.g. a button goal) is ignored.
export function createArmJogger({submit, mapping, maxStep, deadzone = DEADZONE}) {
  let pressed = false, inFlight = false, pending = null, axes = {x: 0, y: 0};
  async function pump() {
    if (!pressed || inFlight) return;
    const step = stepFor(axes, mapping, maxStep, deadzone);
    if (!step) return;
    inFlight = true;
    pending = null;
    let accepted = null;
    try { accepted = await submit(step); } catch { accepted = null; }
    if (!accepted) { inFlight = false; pressed = false; return; }
    pending = typeof accepted === "string" ? accepted : null;
  }
  return {
    press(next) { pressed = true; axes = next; pump(); },
    move(next) { axes = next; pump(); },
    release() { const was = inFlight; pressed = false; axes = {x: 0, y: 0}; return {inFlight: was}; },
    settled(state, commandId) {
      if (!inFlight || (commandId && pending && commandId !== pending)) return;
      inFlight = false;
      pending = null;
      if (state !== TERMINAL_OK) pressed = false;
      pump();
    },
    state: () => ({pressed, inFlight}),
  };
}
