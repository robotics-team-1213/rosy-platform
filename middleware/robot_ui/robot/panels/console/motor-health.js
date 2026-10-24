import {createMotorHealthState, renderMotorHealth} from "/common/motor-health.js";

export function mount(el, ctx) {
  const state = createMotorHealthState();
  const draw = () => renderMotorHealth(el, state.read());
  draw();
  const stop = ctx.store.poll("/api/v1/motors/health", 1000,
    (data, timing) => { state.accept(data, timing); draw(); },
    () => { state.disconnect(); draw(); });
  // Local age keeps advancing while an in-flight read is slow; it is not a second API poll.
  const timer = setInterval(draw, 1000);
  return () => { stop(); clearInterval(timer); };
}
