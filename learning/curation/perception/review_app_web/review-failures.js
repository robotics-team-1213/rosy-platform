// Per-endpoint failure book for review-alerts.js: the common alert stays up until every endpoint that failed has answered again,
// so one healthy endpoint cannot close it while others still fail. Keys are paths without the query.
// An endpoint that failed once and is never called again (a one-shot load) would pin the alert forever, so a failure that has not
// repeated for `ttlMs` is dropped as soon as any other endpoint answers; polled endpoints repeat their failure and stay.
export function createFailureTracker(show, clear, {ttlMs = 60000, now = Date.now} = {}) {
  const failing = new Map();  // key -> {message, at}
  let shown = '';
  const sync = () => {
    const next = failing.values().next().value?.message || '';
    if (next === shown) return;
    shown = next;
    if (next) show(next); else clear();
  };
  return {
    fail(key, message) { failing.set(key, {message, at: now()}); sync(); },
    recover(key) {
      const cutoff = now() - ttlMs;
      let changed = failing.delete(key);
      for (const [other, entry] of failing) if (entry.at < cutoff) { failing.delete(other); changed = true; }
      if (changed) sync();
    },
    down: () => failing.size > 0,
  };
}
