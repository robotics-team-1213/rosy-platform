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

// Below this a step is "at the limit": the owner would refuse a target outside the range.
export const LIMIT_EPS_RAD = 0.001;

// Clamp a step to the room left in the joint range ([lower - position, upper - position]).
// Unknown range or position → unchanged (the owner still judges). Nothing left → null.
export function limitStep(step, range, position) {
  if (!step) return null;
  const known = (v) => typeof v === "number" && Number.isFinite(v);
  if (!range || !known(range.lower) || !known(range.upper) || !known(position)) return step;
  const up = step.delta > 0;
  const room = up ? range.upper - position : range.lower - position;
  const allowed = up ? Math.min(step.delta, room) : Math.max(step.delta, room);
  const delta = up ? Math.floor(allowed * 1e4) / 1e4 : Math.ceil(allowed * 1e4) / 1e4;
  return Math.abs(delta) >= LIMIT_EPS_RAD && Math.sign(delta) === Math.sign(step.delta)
    ? {...step, delta} : null;
}

// `submit(step)` resolves to the accepted command id (truthy); `null` = "not now" (a goal is
// still running or the readback is not ready yet — `poke()` retries while pressed); any other
// falsy value or a throw = refused, which stops the stick until it is pressed again.
// `settled(state, commandId)` reports the goal's terminal state; a settle naming another
// command (e.g. a button goal) is ignored. `limits`/`positionOf` clamp each step to the range.
export function createArmJogger({submit, mapping, maxStep, deadzone = DEADZONE, limits = {}, positionOf = () => undefined}) {
  let pressed = false, inFlight = false, pending = null, atLimit = false, axes = {x: 0, y: 0};
  async function pump() {
    if (!pressed || inFlight) return;
    const raw = stepFor(axes, mapping, maxStep, deadzone);
    const step = raw && limitStep(raw, limits[raw.joint], positionOf(raw.joint));
    atLimit = Boolean(raw) && !step;
    if (!step) return;
    inFlight = true;
    pending = null;
    let accepted = false;
    try { accepted = await submit(step); } catch { accepted = false; }
    if (accepted === null) { inFlight = false; return; }
    if (!accepted) { inFlight = false; pressed = false; return; }
    pending = typeof accepted === "string" ? accepted : null;
  }
  return {
    press(next) { pressed = true; axes = next; pump(); },
    move(next) { axes = next; pump(); },
    poke() { pump(); },
    release() { const was = inFlight; pressed = false; atLimit = false; axes = {x: 0, y: 0}; return {inFlight: was}; },
    settled(state, commandId) {
      if (!inFlight || (commandId && pending && commandId !== pending)) return;
      inFlight = false;
      pending = null;
      if (state !== TERMINAL_OK) pressed = false;
      pump();
    },
    atLimit: () => atLimit,
    state: () => ({pressed, inFlight}),
  };
}
