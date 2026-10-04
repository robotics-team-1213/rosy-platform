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

// Browser lifetime mechanics. Owners supply resume reads; no operation is replayed here.
export function createPageScope({events = globalThis, clock = globalThis} = {}) {
  let epoch = createScope();
  let active = true;
  let disposed = false;
  const resources = new Set();
  const resumes = new Set();

  function invoke(callback, receiver, args = []) {
    const result = callback.apply(receiver, args);
    return result?.then ? result.catch(error => {
      if (error.name !== 'AbortError') throw error;
    }) : result;
  }

  function capture() {
    const held = epoch;
    const current = () => active && !disposed && held === epoch && !held.signal.aborted;
    return {
      signal: held.signal,
      current,
      check() {
        if (!current()) throw new DOMException('Page operation is no longer current', 'AbortError');
      },
    };
  }

  function arm(resource) {
    const cleanup = resource.start();
    let stopped = false;
    resource.stop = () => {
      if (stopped) return;
      stopped = true;
      cleanup();
    };
    resource.detach = epoch.onDispose(resource.stop);
  }

  function register(start, stopOnUnregister = true) {
    if (disposed) throw new Error('page scope is disposed');
    const resource = {start};
    resources.add(resource);
    if (active) arm(resource);
    return () => {
      if (!resources.delete(resource)) return;
      resource.detach?.();
      if (stopOnUnregister) resource.stop?.();
    };
  }

  function renew() {
    epoch = createScope();
    for (const resource of resources) arm(resource);
  }

  function hide() {
    if (!active) return;
    active = false;
    epoch.dispose();
  }

  function show(event) {
    if (!event.persisted || active || disposed) return;
    active = true;
    renew();
    for (const callback of resumes) callback();
  }

  events.addEventListener('pagehide', hide);
  events.addEventListener('pageshow', show);
  return {
    capture,
    get signal() { return epoch.signal; },
    guard(callback) {
      const ticket = capture();
      return function (...args) {
        if (ticket.current()) return invoke(callback, this, args);
      };
    },
    listen(target, type, callback, options) {
      if (!target) return () => {};
      return register(() => {
        const ticket = capture();
        const wrapped = function (...args) {
          if (ticket.current()) return invoke(callback, this, args);
        };
        target.addEventListener(type, wrapped, options);
        return () => target.removeEventListener(type, wrapped, options);
      });
    },
    interval(callback, ms) {
      return register(() => {
        const ticket = capture();
        const id = clock.setInterval(() => { if (ticket.current()) invoke(callback); }, ms);
        return () => clock.clearInterval(id);
      });
    },
    timeout(callback, ms) {
      const task = capture();
      task.check();
      const id = clock.setTimeout(() => { detach(); if (task.current()) invoke(callback); }, ms);
      const detach = epoch.onDispose(() => clock.clearTimeout(id));
      return () => { detach(); clock.clearTimeout(id); };
    },
    sleep(ms) {
      const task = capture();
      return new Promise((resolve, reject) => {
        if (!task.current()) { reject(new DOMException('Page wait cancelled', 'AbortError')); return; }
        const cancel = () => {
          clock.clearTimeout(id);
          task.signal.removeEventListener('abort', cancel);
          reject(new DOMException('Page wait cancelled', 'AbortError'));
        };
        const id = clock.setTimeout(() => {
          task.signal.removeEventListener('abort', cancel);
          if (task.current()) resolve();
          else reject(new DOMException('Page wait cancelled', 'AbortError'));
        }, ms);
        task.signal.addEventListener('abort', cancel, {once: true});
      });
    },
    subscribe: start => register(start),
    onDispose: callback => register(() => callback, false),
    onResume(callback) { resumes.add(callback); return () => resumes.delete(callback); },
    invalidate() {
      if (disposed) throw new Error('page scope is disposed');
      try { epoch.dispose(); } finally { if (active) renew(); }
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      active = false;
      events.removeEventListener('pagehide', hide);
      events.removeEventListener('pageshow', show);
      try { epoch.dispose(); } finally { resources.clear(); resumes.clear(); }
    },
  };
}
