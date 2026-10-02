// D-425 screen/panel lifetime. Domain polling and recovery policies stay with owners.
export function createScope() {
  const controller = new AbortController();
  const cleanups = new Set();
  let disposed = false;
  let generation = 0;

  return {
    signal: controller.signal,
    capture: () => generation,
    isCurrent: value => !disposed && value === generation,
    advance() {
      if (disposed) throw new Error('scope is disposed');
      return ++generation;
    },
    guard(callback) {
      return function (...args) {
        if (!disposed) return callback.apply(this, args);
      };
    },
    onDispose(cleanup) {
      if (disposed) {
        cleanup();
        return () => {};
      }
      cleanups.add(cleanup);
      return () => cleanups.delete(cleanup);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      generation++;
      controller.abort();
      const pending = [...cleanups];
      cleanups.clear();
      const errors = [];
      for (const cleanup of pending) {
        try { cleanup(); } catch (error) { errors.push(error); }
      }
      if (errors.length) throw new AggregateError(errors, 'scope cleanup failed');
    },
  };
}
