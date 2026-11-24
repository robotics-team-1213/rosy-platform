// Visibility-aware non-overlapping polling helper for Rosy Learning pages.

export function startVisibilityPoll(fn, intervalMs, {
  shouldRun = () => true,
  runOnVisible = true,
  doc = globalThis.document,
} = {}) {
  let inFlight = false;
  let stopped = false;

  const tick = async () => {
    if (stopped || inFlight || doc?.hidden || !shouldRun()) return;
    inFlight = true;
    try {
      await fn();
    } finally {
      inFlight = false;
    }
  };

  const timer = setInterval(() => { void tick(); }, intervalMs);
  const onVisibility = () => {
    if (!doc?.hidden && runOnVisible) void tick();
  };
  doc?.addEventListener?.("visibilitychange", onVisibility);

  return {
    stop() {
      stopped = true;
      clearInterval(timer);
      doc?.removeEventListener?.("visibilitychange", onVisibility);
    },
  };
}
