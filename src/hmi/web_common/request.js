// D-425 HTTP mechanics. Credential storage, service errors and replay belong to callers.
export function createRequest({origin = globalThis.location?.origin, credential = () => '', fetchImpl} = {}) {
  const base = new URL(origin);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password) {
    throw new Error('request origin must be an HTTP origin without credentials');
  }
  const send = fetchImpl ?? ((...args) => globalThis.fetch(...args));

  return async function request(path, options = {}) {
    const target = new URL(path, base.origin);
    if (target.origin !== base.origin || target.username || target.password) {
      throw new Error('request destination must match its origin and omit URL credentials');
    }
    const {timeoutMs = 0, signal: parent, signals = [], headers: supplied, ...init} = options;
    if (!Number.isFinite(timeoutMs) || timeoutMs < 0) {
      throw new RangeError('request timeout must be a finite nonnegative number');
    }
    const parents = [...new Set([parent, ...signals].filter(Boolean))];
    for (const signal of parents) signal.throwIfAborted();
    const controller = new AbortController();
    const subscriptions = parents.map(signal => {
      const abort = () => controller.abort(signal.reason);
      signal.addEventListener('abort', abort, {once: true});
      return () => signal.removeEventListener('abort', abort);
    });
    const timer = timeoutMs > 0
      ? setTimeout(() => controller.abort(new DOMException('Request timed out', 'AbortError')), timeoutMs)
      : undefined;
    try {
      const headers = new Headers(supplied);
      const value = credential();
      headers.delete('Authorization');
      if (value) headers.set('Authorization', `Bearer ${value}`);
      controller.signal.throwIfAborted();
      const response = await send(target.href, {
        cache: 'no-store', ...init, headers, signal: controller.signal,
        credentials: 'omit', redirect: 'error',
      });
      controller.signal.throwIfAborted();
      const body = response.status === 204 ? null : await response.json().catch(() => null);
      controller.signal.throwIfAborted();
      return {status: response.status, ok: response.ok, body};
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      for (const unsubscribe of subscriptions) unsubscribe();
    }
  };
}
