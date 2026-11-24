// Display grace hold for transient online missing/aged battery polls; preserves strict D-509 charging rules.
import { powerHealthView } from "/console/assets/power-health-view.js";

export function createCalmPowerHealth({ graceMs = 3000, readPower = powerHealthView } = {}) {
  const cache = new Map();

  function read(robot, { receivedAtMs, nowMs = Date.now(), stateUnavailable = false } = {}) {
    const raw = readPower(robot, receivedAtMs, nowMs);
    const id = robot?.robot_id;
    if (!id || stateUnavailable || !robot?.online || raw.problem) {
      if (id) cache.delete(id);
      return raw;
    }
    if (raw.percent !== null) {
      cache.set(id, {
        battery: raw.battery,
        percent: raw.percent,
        voltage: raw.voltage,
        observedAgeS: raw.observedAgeS,
        heldSinceMs: null,
      });
      return raw;
    }
    const entry = cache.get(id);
    if (!entry) return raw;
    if (entry.heldSinceMs === null) entry.heldSinceMs = nowMs;
    const elapsedMs = nowMs - entry.heldSinceMs;
    if (elapsedMs >= graceMs) {
      cache.delete(id);
      return raw;
    }
    return {
      ...raw,
      battery: entry.battery,
      percent: entry.percent,
      voltage: entry.voltage,
      observedAgeS: typeof entry.observedAgeS === "number" ? entry.observedAgeS + Math.round(elapsedMs / 1000) : undefined,
    };
  }

  return { read, reset: () => cache.clear() };
}
