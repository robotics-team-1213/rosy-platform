// CORE reports a Nav2 send with no answer as an unknown result but its state stays PLANNING,
// so a plan that never ends is the only sign the console gets.
// shortcut: first-seen time lives in this tab, so a reload restarts the count; a state field would fix it.
export const PLANNING_SLOW_S = 15;

export function planningStalled(since, robotId, nav, nowMs) {
  if (nav !== "PLANNING") {
    since.delete(robotId);
    return false;
  }
  if (!since.has(robotId)) since.set(robotId, nowMs);
  return nowMs - since.get(robotId) >= PLANNING_SLOW_S * 1000;
}
