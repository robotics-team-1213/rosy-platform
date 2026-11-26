// World-only SIM rule; the 2D map rules shared with Fleet are in /common/map-rules.js (shared/web).

// Server-judged SIM freshness (serve.py age_ms / fresh_for_ms); no browser clock math. Callers charge the
// request time to fresh_for_ms (active-site-map.js way).
export function simFreshness(sample) {
  if (!Number.isSafeInteger(sample?.age_ms) || !Number.isSafeInteger(sample?.fresh_for_ms) || sample.fresh_for_ms < 0) {
    return null;
  }
  return { state: sample.fresh_for_ms > 0 ? "fresh" : "delayed", ageS: Math.round(Math.abs(sample.age_ms) / 1000) };
}
