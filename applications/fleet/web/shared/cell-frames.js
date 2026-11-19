// Cell camera frames through Vision preview leases (D-136: Fleet은 영상 바이트를 중계하지 않는다).
// A view is {source} for a registered Vision camera or {roiTarget} for the ceiling ROI zoom
// on one target. Views whose source is not in Vision's source list show the honest
// "영상 원본 미등록" state instead of a placeholder stream.
import {FRAME_LATE_MS, frameBadge} from './vision-view.js';

const CEILING_SOURCE = 'ceiling_north';
const UNREGISTERED_TEXT = '영상 원본 미등록';
// Cell camera name -> its Vision source id in the workcell observation manifest (the cell PC
// observation bridge publishes these). side and arm_s_* are listed once the manifest carries them.
const VISION_SOURCE = {top: 'omx_overhead', arm_a_wrist: 'omx_wrist_a', arm_b_wrist: 'omx_wrist_b',
  side: 'omx_side', arm_s_top: 'omx_arm_s_top', arm_s_wrist: 'omx_arm_s_wrist'};
const LIST_REFRESH_MS = 30000;
const LEASE_MARGIN_MS = 8000;
const REQUEST_TIMEOUT_MS = 2000;
const CONCURRENCY = 4;
const STALE_TEXT = '최신 영상 없음';  // same words as the cell observation tile (cell-observation.js staleCamera)

// An img's own hidden flag is ours (no fresh frame yet), so only a hidden container pauses its feed.
function isNodeHidden(node) {
  const parent = node?.parentElement;
  if (!parent || typeof parent.closest !== 'function') return false;
  return Boolean(parent.closest('[hidden], details:not([open])'));
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
  let running = true, disposed = false, busy = false, timer = null, tickQueued = false, generation = 0;
  const newController = () => (typeof AbortController === 'function' ? new AbortController() : null);
  let controller = newController();

  const stateText = (label, detail) => [label, detail].filter(Boolean).join(' · ');

  function watcherOf(view) {
    const key = view.roiTarget ? `roi:${view.roiTarget}` : `source:${view.source}`;
    let watcher = watchers.get(key);
    if (!watcher) {
      watcher = {key, view, imgs: new Set(), badges: new Set(), badgeLabel: '', lease: null,
        url: null, lastSeq: null, capturedAtMs: null, captured_epoch_s: null, ageMs: null, fresh: false, expiry: null,
        state: {kind: 'neutral', label: '영상 수신 대기', text: '영상 수신 대기'}};
      watchers.set(key, watcher);
    }
    return watcher;
  }

  function dropWatcherIfEmpty(watcher) {
    if (watcher.imgs.size || watcher.badges.size) return false;
    forget(watcher);
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
      // A node bound before it is attached stays (and is painted now, so a fresh mount never shows
      // as a live empty frame while 429s skip paints) until it has been seen connected once.
      if (!img.isConnected && seen.has(img)) { watcher.imgs.delete(img); continue; }
      if (img.isConnected) seen.add(img);
      // Only a frame younger than FRAME_LATE_MS is shown; an expired or failed one must not pass for live.
      img.hidden = !(watcher.fresh && watcher.url);
      if (!watcher.url) img.removeAttribute?.('src');
      else if (img.src !== watcher.url) img.src = watcher.url;
    }
    const badgeText = [watcher.badgeLabel, watcher.state.text].filter(Boolean).join(' · ');
    for (const badge of watcher.badges) {
      if (!badge.isConnected && seen.has(badge)) { watcher.badges.delete(badge); continue; }
      if (badge.isConnected) seen.add(badge);
      if (badge.textContent !== badgeText) badge.textContent = badgeText;
    }
    dropWatcherIfEmpty(watcher);
  }

  async function ensureSources() {
    if (sources !== null && now() - sourcesAt < LIST_REFRESH_MS) return sources;
    const gen = generation;
    listing ??= call('/api/fleet/vision/sources', controller ? {signals: [controller.signal]} : undefined)
      .then(res => { if (gen === generation) { sources = new Set(res?.sources || []); sourcesAt = now(); } })
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

  function cancelExpiry(watcher) {
    if (watcher.expiry !== null) clearTimeout(watcher.expiry);
    watcher.expiry = null;
  }

  // Drop the frame bytes and timing; the next session starts from 영상 수신 대기.
  function forget(watcher) {
    cancelExpiry(watcher);
    if (watcher.url) URL.revokeObjectURL(watcher.url);
    Object.assign(watcher, {url: null, blob: null, lastSeq: null, lease: null, fresh: false,
      capturedAtMs: null, captured_epoch_s: null, ageMs: null});
  }

  function markStale(watcher, state = {kind: 'warn', label: STALE_TEXT, text: STALE_TEXT}) {
    cancelExpiry(watcher);
    watcher.fresh = false;
    watcher.state = state;
    paint(watcher);
  }

  // A frame is live until FRAME_LATE_MS after capture; a 429 keeps it, the timer still ages it out.
  function showFresh(watcher, observedAt, state) {
    cancelExpiry(watcher);
    const ageMs = watcher.ageMs ?? 0;
    const remaining = observedAt + FRAME_LATE_MS - ageMs - now();
    if (!(remaining > 0)) return markStale(watcher);
    watcher.fresh = true;
    watcher.state = state;
    watcher.expiry = setTimeout(() => { watcher.expiry = null; markStale(watcher); }, remaining);
    paint(watcher);
  }

  async function refreshOne(watcher) {
    const gen = generation;
    const gone = () => disposed || !running || gen !== generation;
    if (gone()) return;
    const source = watcher.view.roiTarget ? CEILING_SOURCE : (VISION_SOURCE[watcher.view.source] || watcher.view.source);
    if (!watcher.view.roiTarget) {
      await ensureSources();
      if (gone()) return;
      if (sources !== null && !sources.has(source)) {
        return markStale(watcher, {kind: 'unregistered', label: UNREGISTERED_TEXT,
          text: `${UNREGISTERED_TEXT} · Vision 카메라 목록에 ${source}가 없습니다`});
      }
      if (sources === null) {
        return markStale(watcher, {kind: 'warn', label: '영상 연결 확인 중', text: 'Vision 카메라 목록을 확인하는 중입니다'});
      }
    }
    if (!watcher.lease || now() >= watcher.lease.expiresAt) {
      const lease = await leaseFor(source);
      if (gone()) return;
      watcher.lease = lease;
    }
    const url = watcher.view.roiTarget
      ? `/api/vision/sources/${CEILING_SOURCE}/roi/${encodeURIComponent(watcher.view.roiTarget)}`
      : watcher.lease.framePath;
    const {signal, cleanup} = createFetchSignal(controller?.signal, REQUEST_TIMEOUT_MS);
    const observedAt = now();
    try {
      const response = await fetch(url, {
        headers: {Authorization: `Bearer ${watcher.lease.token}`},
        credentials: 'omit', cache: 'no-store',
        ...(signal ? {signal} : {}),
      });
      if (gone()) return;
      if (response.status === 401) { watcher.lease = null; return markStale(watcher); }
      if (response.status === 429) return;  // one frame budget per viewer and source
      const seq = response.headers?.get?.('X-Frame-Seq');
      const live = watcher.view.roiTarget
        ? {kind: 'good', label: '천장 Cam 확대 추적', text: `천장 Cam 확대 추적 (${CEILING_SOURCE})`}
        : {kind: 'good', label: '원본 최신 프레임', text: `원본 최신 프레임${seq ? ` · #${seq}` : ''}`};
      if (watcher.view.roiTarget) {
        if (!response.ok) return markStale(watcher);
      } else {
        const badge = frameBadge({ok: response.ok, status: response.status,
          ageMs: response.headers?.get?.('X-Frame-Age-Ms'), frameState: response.headers?.get?.('X-Frame-State'), rectified: false});
        if (!response.ok || badge.state !== 'live') {
          return markStale(watcher, {kind: badge.kind, label: badge.label, text: stateText(badge.label, badge.detail)});
        }
      }
      if (!(seq && seq === watcher.lastSeq && watcher.url)) {
        const blob = await response.blob();
        if (gone()) return;
        if (!blob || !blob.size) return markStale(watcher);
        const next = URL.createObjectURL(blob);
        if (watcher.url) URL.revokeObjectURL(watcher.url);
        watcher.url = next;
        watcher.blob = blob;  // kept for snapshot(): the page CSP refuses fetch() of a blob: URL
        watcher.lastSeq = seq || null;
      }
      updateTimingFromHeaders(watcher, response.headers);
      showFresh(watcher, observedAt, live);
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
          const watcher = queue[cursor++], gen = generation;
          try {
            await refreshOne(watcher);
          } catch (error) {
            if (disposed || !running || gen !== generation) break;
            const label = error?.status === 401 || error?.status === 403 ? '영상 권한 없음' : '영상 연결 확인 중';
            markStale(watcher, {kind: 'warn', label, text: `${STALE_TEXT} · ${label}`});
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

  // Logout: stop, abort what is in flight, ignore late answers and wipe the previous session's frames.
  function clear() {
    generation++;
    setRunning(false);
    controller?.abort();
    controller = newController();
    sources = null; sourcesAt = -Infinity;
    for (const watcher of watchers.values()) {
      forget(watcher);
      watcher.state = {kind: 'neutral', label: '영상 수신 대기', text: '영상 수신 대기'};
      paint(watcher);
    }
  }

  function dispose() {
    clear();
    disposed = true;
    watchers.clear();
  }

  // The live camera frames on screen now ({label, blob}), for a fault that must keep what the operator saw.
  function snapshot() {
    return [...watchers.values()].filter(watcher => watcher.fresh && watcher.blob && !watcher.view.roiTarget
      && !isWatcherHidden(watcher)).map(watcher => ({label: watcher.badgeLabel || watcher.view.source, blob: watcher.blob}));
  }

  scope?.onDispose?.(dispose);
  return {bind, setRunning, clear, dispose, snapshot};
}
