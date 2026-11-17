// Cell camera frames through Vision preview leases (D-136: Fleet은 영상 바이트를 중계하지 않는다).
// A view is {source} for a registered Vision camera or {roiTarget} for the ceiling ROI zoom
// on one target. Views whose source is not in Vision's source list show the honest
// "영상 원본 미등록" state instead of a placeholder stream.
import {frameBadge} from './vision-view.js';

export const CEILING_SOURCE = 'ceiling_north';
export const UNREGISTERED_TEXT = '영상 원본 미등록';
// Cell camera name -> its Vision source id in the workcell observation manifest (the cell PC
// observation bridge publishes these). side and arm_s_* are listed once the manifest carries them.
export const VISION_SOURCE = {top: 'omx_overhead', arm_a_wrist: 'omx_wrist_a', arm_b_wrist: 'omx_wrist_b',
  side: 'omx_side', arm_s_top: 'omx_arm_s_top', arm_s_wrist: 'omx_arm_s_wrist'};
const LIST_REFRESH_MS = 30000;
const LEASE_MARGIN_MS = 8000;
const REQUEST_TIMEOUT_MS = 2000;
const CONCURRENCY = 4;

function isNodeHidden(node) {
  if (!node || typeof node.closest !== 'function') return false;
  return Boolean(node.closest('[hidden], details:not([open])'));
}

function createFetchSignal(parentSignal, timeoutMs) {
  const timeout = typeof AbortSignal === 'function' ? AbortSignal.timeout?.(timeoutMs) : undefined;
  if (timeout && (!parentSignal || typeof AbortSignal.any === 'function')) {
    return {signal: parentSignal ? AbortSignal.any([parentSignal, timeout]) : timeout, cleanup: () => {}};
  }
  if (typeof AbortController !== 'function') return {signal: parentSignal, cleanup: () => {}};
  const local = new AbortController();
  const onAbort = () => local.abort(parentSignal.reason);
  if (parentSignal) {
    if (parentSignal.aborted) onAbort();
    else parentSignal.addEventListener('abort', onAbort, {once: true});
  }
  const timer = setTimeout(() => local.abort(), timeoutMs);
  return {
    signal: local.signal,
    cleanup() {
      clearTimeout(timer);
      parentSignal?.removeEventListener('abort', onAbort);
    },
  };
}

export function createCellFrameFeed({call, scope = null, intervalMs = 2000, now = Date.now}) {
  const watchers = new Map();
  const seen = new WeakSet();  // nodes painted while connected  // key -> {key, view, imgs:Set, badges:Set, lease, url, state}
  let sources = null, sourcesAt = -Infinity, listing = null;
  let running = true, disposed = false, busy = false, timer = null, tickQueued = false;
  const controller = typeof AbortController === 'function' ? new AbortController() : null;

  const stateText = (label, detail) => [label, detail].filter(Boolean).join(' · ');

  function watcherOf(view) {
    const key = view.roiTarget ? `roi:${view.roiTarget}` : `source:${view.source}`;
    let watcher = watchers.get(key);
    if (!watcher) {
      watcher = {key, view, imgs: new Set(), badges: new Set(), badgeLabel: '', lease: null,
        url: null, lastSeq: null, capturedAtMs: null, captured_epoch_s: null, ageMs: null,
        state: {kind: 'neutral', label: '영상 수신 대기', text: '영상 수신 대기'}};
      watchers.set(key, watcher);
    }
    return watcher;
  }

  function dropWatcherIfEmpty(watcher) {
    if (watcher.imgs.size || watcher.badges.size) return false;
    if (watcher.url) URL.revokeObjectURL(watcher.url);
    watcher.url = null;
    watchers.delete(watcher.key);
    return true;
  }

  function pruneWatchers() {
    for (const watcher of [...watchers.values()]) {
      for (const img of watcher.imgs) {
        if (img.isConnected) seen.add(img);
        else if (seen.has(img)) watcher.imgs.delete(img);
      }
      for (const badge of watcher.badges) {
        if (badge.isConnected) seen.add(badge);
        else if (seen.has(badge)) watcher.badges.delete(badge);
      }
      dropWatcherIfEmpty(watcher);
    }
  }

  function isWatcherHidden(watcher) {
    return [...watcher.imgs].every(isNodeHidden) && [...watcher.badges].every(isNodeHidden);
  }

  function paint(watcher) {
    for (const img of watcher.imgs) {
      // A node bound before it is attached stays until it has been seen connected once.
      if (!img.isConnected) { if (seen.has(img)) watcher.imgs.delete(img); continue; }
      seen.add(img);
      img.hidden = watcher.state.kind === 'unregistered';
      if (watcher.url && img.src !== watcher.url) img.src = watcher.url;
    }
    const badgeText = [watcher.badgeLabel, watcher.state.text].filter(Boolean).join(' · ');
    for (const badge of watcher.badges) {
      if (!badge.isConnected) { if (seen.has(badge)) watcher.badges.delete(badge); continue; }
      seen.add(badge);
      if (badge.textContent !== badgeText) badge.textContent = badgeText;
    }
    dropWatcherIfEmpty(watcher);
  }

  async function ensureSources() {
    if (sources !== null && now() - sourcesAt < LIST_REFRESH_MS) return sources;
    listing ??= call('/api/fleet/vision/sources', controller ? {signals: [controller.signal]} : undefined)
      .then(res => { sources = new Set(res?.sources || []); sourcesAt = now(); })
      .catch(() => {})
      .finally(() => { listing = null; });
    return listing;
  }

  async function leaseFor(source) {
    const issued = await call('/api/fleet/vision/lease', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source_id: source}),
      timeoutMs: REQUEST_TIMEOUT_MS,
      ...(controller ? {signals: [controller.signal]} : {}),
    });
    const target = new URL(issued?.frame_path || '', location.origin);
    if (target.origin !== location.origin || target.username || target.password) {
      throw Error('영상 주소를 확인하세요.');
    }
    return {token: issued?.lease || '', framePath: target.href,
      expiresAt: now() + Math.max(1, (issued?.expires_in_s || 60)) * 1000 - LEASE_MARGIN_MS};
  }

  function updateTimingFromHeaders(watcher, headers) {
    const rawAge = headers?.get?.('X-Frame-Age-Ms');
    const ageMs = rawAge !== null && rawAge !== undefined && rawAge !== '' ? Number(rawAge) : NaN;
    const rawCapturedAt = headers?.get?.('X-Frame-Captured-At');
    const capturedEpochS = rawCapturedAt !== null && rawCapturedAt !== undefined && rawCapturedAt !== ''
      ? Number(rawCapturedAt) : NaN;
    watcher.ageMs = Number.isFinite(ageMs) ? ageMs : null;
    watcher.captured_epoch_s = Number.isFinite(capturedEpochS) ? capturedEpochS : null;
    watcher.capturedAtMs = Number.isFinite(capturedEpochS)
      ? capturedEpochS * 1000
      : (Number.isFinite(ageMs) ? now() - ageMs : now());
  }

  async function refreshOne(watcher) {
    if (disposed || !running) return;
    const source = watcher.view.roiTarget ? CEILING_SOURCE : (VISION_SOURCE[watcher.view.source] || watcher.view.source);
    if (!watcher.view.roiTarget) {
      await ensureSources();
      if (disposed || !running) return;
      if (sources !== null && !sources.has(source)) {
        watcher.state = {kind: 'unregistered', label: UNREGISTERED_TEXT,
          text: `${UNREGISTERED_TEXT} · Vision 카메라 목록에 ${source}가 없습니다`};
        return paint(watcher);
      }
      if (sources === null) {
        watcher.state = {kind: 'warn', label: '영상 연결 확인 중', text: 'Vision 카메라 목록을 확인하는 중입니다'};
        return paint(watcher);
      }
    }
    if (!watcher.lease || now() >= watcher.lease.expiresAt) watcher.lease = await leaseFor(source);
    if (disposed || !running) return;
    const url = watcher.view.roiTarget
      ? `/api/vision/sources/${CEILING_SOURCE}/roi/${encodeURIComponent(watcher.view.roiTarget)}`
      : watcher.lease.framePath;
    const {signal, cleanup} = createFetchSignal(controller?.signal, REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        headers: {Authorization: `Bearer ${watcher.lease.token}`},
        credentials: 'omit', cache: 'no-store',
        ...(signal ? {signal} : {}),
      });
      if (disposed || !running) return;
      if (response.status === 401) { watcher.lease = null; return; }
      if (response.status === 429) return;  // one frame budget per viewer and source
      const seq = response.headers?.get?.('X-Frame-Seq');
      if (watcher.view.roiTarget) {
        if (!response.ok) return;
        if (seq && seq === watcher.lastSeq && watcher.url) {
          updateTimingFromHeaders(watcher, response.headers);
          watcher.state = {kind: 'good', label: '천장 Cam 확대 추적', text: `천장 Cam 확대 추적 (${CEILING_SOURCE})`};
          return paint(watcher);
        }
        const blob = await response.blob();
        if (disposed || !running || !blob || !blob.size) return;
        const next = URL.createObjectURL(blob);
        if (watcher.url) URL.revokeObjectURL(watcher.url);
        watcher.url = next;
        watcher.lastSeq = seq || null;
        updateTimingFromHeaders(watcher, response.headers);
        watcher.state = {kind: 'good', label: '천장 Cam 확대 추적', text: `천장 Cam 확대 추적 (${CEILING_SOURCE})`};
        return paint(watcher);
      }
      const badge = frameBadge({ok: response.ok, status: response.status,
        ageMs: response.headers?.get?.('X-Frame-Age-Ms'), frameState: response.headers?.get?.('X-Frame-State'), rectified: false});
      if (!response.ok || badge.state !== 'live') {
        watcher.state = {kind: badge.kind, label: badge.label, text: stateText(badge.label, badge.detail)};
        return paint(watcher);
      }
      if (seq && seq === watcher.lastSeq && watcher.url) {
        updateTimingFromHeaders(watcher, response.headers);
        watcher.state = {kind: 'good', label: '원본 최신 프레임',
          text: `원본 최신 프레임${seq ? ` · #${seq}` : ''}`};
        return paint(watcher);
      }
      const blob = await response.blob();
      if (disposed || !running) return;
      const next = URL.createObjectURL(blob);
      if (watcher.url) URL.revokeObjectURL(watcher.url);
      watcher.url = next;
      watcher.lastSeq = seq || null;
      updateTimingFromHeaders(watcher, response.headers);
      watcher.state = {kind: 'good', label: '원본 최신 프레임',
        text: `원본 최신 프레임${seq ? ` · #${seq}` : ''}`};
      paint(watcher);
    } finally {
      cleanup();
    }
  }

  async function tick() {
    if (busy || !running || disposed) return;
    if (typeof document !== 'undefined' && document.hidden) return;
    busy = true;
    try {
      pruneWatchers();
      const queue = [...watchers.values()].filter(watcher => !isWatcherHidden(watcher));
      let cursor = 0;
      const workerCount = Math.min(CONCURRENCY, queue.length);
      await Promise.all(Array.from({length: workerCount}, async () => {
        while (cursor < queue.length && !disposed && running) {
          const watcher = queue[cursor++];
          try {
            await refreshOne(watcher);
          } catch (error) {
            if (disposed || !running) break;
            const label = error?.status === 401 || error?.status === 403 ? '영상 권한 없음' : '영상 연결 확인 중';
            watcher.state = {kind: 'warn', label, text: label};
            paint(watcher);
          }
        }
      }));
    } finally {
      busy = false;
      if (!watchers.size || disposed || !running) stopTimer();
    }
  }

  function scheduleTick() {
    if (!tickQueued) {
      tickQueued = true;
      queueMicrotask(() => {
        tickQueued = false;
        void tick();
      });
    }
  }

  function stopTimer() {
    if (timer !== null && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
      window.clearInterval(timer);
    }
    timer = null;
  }

  function startTimer() {
    if (timer !== null || typeof window === 'undefined' || typeof window.setInterval !== 'function') return;
    timer = window.setInterval(() => { void tick(); }, intervalMs);
  }

  // Bind an <img> (and an optional badge element prefixed with label) to a view. Re-renders
  // re-bind; disconnected nodes are dropped on the next paint.
  function bind(img, view, badge = null, label = '') {
    const watcher = watcherOf(view);
    for (const other of [...watchers.values()]) {  // a re-bound node leaves its previous view
      if (other === watcher) continue;
      if (img) other.imgs.delete(img);
      if (badge) other.badges.delete(badge);
      dropWatcherIfEmpty(other);
    }
    if (img) watcher.imgs.add(img);
    if (badge) {
      watcher.badgeLabel = label;
      watcher.badges.add(badge);
    }
    paint(watcher);
    startTimer();
    scheduleTick();
  }

  function setRunning(next) {
    running = Boolean(next);
    if (running) { startTimer(); scheduleTick(); }
    else stopTimer();
  }

  function dispose() {
    disposed = true;
    running = false;
    stopTimer();
    controller?.abort();
    for (const watcher of watchers.values()) if (watcher.url) URL.revokeObjectURL(watcher.url);
    watchers.clear();
  }

  scope?.onDispose?.(dispose);
  return {bind, setRunning, dispose};
}
