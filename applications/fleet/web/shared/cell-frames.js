// Cell camera frames through Vision preview leases (D-136: Fleet은 영상 바이트를 중계하지 않는다).
// A view is {source} for a registered Vision camera or {roiTarget} for the ceiling ROI zoom
// on one target. Views whose source is not in Vision's source list show the honest
// "영상 원본 미등록" state instead of a placeholder stream.
import {frameBadge} from './vision-view.js';

const CEILING_SOURCE = 'ceiling_north';
const UNREGISTERED_TEXT = '영상 원본 미등록';
const LIST_REFRESH_MS = 30000;
const LEASE_MARGIN_MS = 8000;
const REQUEST_TIMEOUT_MS = 1500;
const MAX_IN_FLIGHT = 4;

function frameAge(headers, isRoi) {
  const age = headers.get('X-Frame-Age-Ms');
  if (age !== null || !isRoi) return age;
  const date = headers.get('Date');
  const responseAt = Date.parse(date);
  const capturedAt = Number(headers.get('X-Frame-Captured-At')) * 1000;
  if (!Number.isFinite(responseAt) || new Date(responseAt).toUTCString() !== date
      || !Number.isFinite(capturedAt) || capturedAt <= 0) return null;
  // HTTP Date truncates to seconds. Use the upper age bound and reject future seconds.
  const ageUpperBound = responseAt + 1000 - capturedAt;
  return ageUpperBound > 0 ? ageUpperBound : null;
}

export function createCellFrameFeed({call, scope = null, intervalMs = 2000, now = Date.now}) {
  const watchers = new Map();
  const seen = new WeakSet();  // nodes painted while connected
  let sources = null, sourcesAt = -Infinity, listing = null;
  let running = true, disposed = false, active = null, timer = null;

  const stateText = (label, detail) => [label, detail].filter(Boolean).join(' · ');
  const isCurrent = (watcher, signal) => !signal.aborted && watchers.get(watcher.key) === watcher;

  function watcherOf(view) {
    const key = view.roiTarget ? `roi:${view.roiTarget}` : `source:${view.source}`;
    let watcher = watchers.get(key);
    if (!watcher) {
      watcher = {key, view, imgs: new Set(), badges: new Set(), badgeLabel: '', lease: null,
        url: null, state: {kind: 'neutral', label: '영상 수신 대기', text: '영상 수신 대기'}};
      watchers.set(key, watcher);
    }
    return watcher;
  }

  function paint(watcher) {
    for (const img of watcher.imgs) {
      // A node bound before it is attached stays until it has been seen connected once.
      if (!img.isConnected) { if (seen.has(img)) watcher.imgs.delete(img); continue; }
      seen.add(img);
      img.hidden = !watcher.url;
      if (watcher.url) img.src = watcher.url;
      else img.removeAttribute?.('src');
    }
    for (const badge of watcher.badges) {
      if (!badge.isConnected) { if (seen.has(badge)) watcher.badges.delete(badge); continue; }
      seen.add(badge);
      badge.textContent = [watcher.badgeLabel, watcher.state.text].filter(Boolean).join(' · ');
    }
    if (!watcher.imgs.size && !watcher.badges.size) {
      if (watcher.url) URL.revokeObjectURL(watcher.url);
      watchers.delete(watcher.key);
    }
  }

  function unavailable(watcher, kind, label, detail = '') {
    if (watcher.url) URL.revokeObjectURL(watcher.url);
    watcher.url = null;
    watcher.state = {kind, label, text: stateText(label, detail)};
    paint(watcher);
  }

  async function ensureSources(signal) {
    if (sources !== null && now() - sourcesAt < LIST_REFRESH_MS) return sources;
    listing ??= call('/api/fleet/vision/sources', {signal, timeoutMs: REQUEST_TIMEOUT_MS})
      .then(res => {
        if (signal.aborted) return;
        sources = new Set(res?.sources || []);
        sourcesAt = now();
      })
      .catch(() => {})
      .finally(() => { listing = null; });
    return listing;
  }

  async function leaseFor(source, signal) {
    const issued = await call('/api/fleet/vision/lease', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source_id: source}), signal, timeoutMs: REQUEST_TIMEOUT_MS,
    });
    const target = new URL(issued?.frame_path || '', location.origin);
    if (target.origin !== location.origin || target.username || target.password) {
      throw Error('영상 주소를 확인하세요.');
    }
    return {token: issued?.lease || '', framePath: target.href,
      expiresAt: now() + Math.max(1, (issued?.expires_in_s || 60)) * 1000 - LEASE_MARGIN_MS};
  }

  async function refreshOne(watcher, signal) {
    const source = watcher.view.roiTarget ? CEILING_SOURCE : watcher.view.source;
    if (!watcher.view.roiTarget) {
      await ensureSources(signal);
      if (!isCurrent(watcher, signal)) return;
      if (sources !== null && !sources.has(source)) {
        return unavailable(watcher, 'unregistered', UNREGISTERED_TEXT, `Vision 카메라 목록에 ${source}가 없습니다`);
      }
      if (sources === null) {
        return unavailable(watcher, 'warn', '영상 연결 확인 중', 'Vision 카메라 목록을 확인하는 중입니다');
      }
    }
    if (!watcher.lease || now() >= watcher.lease.expiresAt) watcher.lease = await leaseFor(source, signal);
    if (!isCurrent(watcher, signal)) return;
    const url = watcher.view.roiTarget
      ? `/api/vision/sources/${CEILING_SOURCE}/roi/${encodeURIComponent(watcher.view.roiTarget)}`
      : watcher.lease.framePath;
    const response = await fetch(url, {
      headers: {Authorization: `Bearer ${watcher.lease.token}`},
      credentials: 'omit', redirect: 'error', cache: 'no-store',
      signal: AbortSignal.any([signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]),
    });
    if (!isCurrent(watcher, signal)) return;
    if (response.status === 401 || response.status === 403) watcher.lease = null;
    if (response.status === 429) return unavailable(watcher, 'warn', '영상 요청 한도 도달');
    const seq = response.headers.get('X-Frame-Seq');
    const badge = frameBadge({ok: response.ok, status: response.status,
      ageMs: frameAge(response.headers, Boolean(watcher.view.roiTarget)),
      frameState: response.headers.get('X-Frame-State'), rectified: false});
    if (!response.ok || badge.state !== 'live') {
      return unavailable(watcher, badge.kind, badge.label, badge.detail);
    }
    const blob = await response.blob();
    if (!isCurrent(watcher, signal)) return;
    if (!blob.size) return unavailable(watcher, 'warn', '영상 수신 대기');
    const next = URL.createObjectURL(blob);
    if (watcher.url) URL.revokeObjectURL(watcher.url);
    watcher.url = next;
    const label = watcher.view.roiTarget ? '천장 Cam 확대 추적' : '원본 최신 프레임';
    const detail = watcher.view.roiTarget ? CEILING_SOURCE : seq && `#${seq}`;
    watcher.state = {kind: 'good', label, text: stateText(label, detail)};
    paint(watcher);
  }

  async function tick() {
    if (active || !running || !watchers.size) return;
    if (typeof document !== 'undefined' && document.hidden) return;
    const queue = [...watchers.values()];
    const pending = queue.values();
    active = new AbortController();
    const {signal} = active;
    async function drain() {
      for (const watcher of pending) {
        if (!isCurrent(watcher, signal)) continue;
        try {
          await refreshOne(watcher, signal);
        } catch (error) {
          if (!isCurrent(watcher, signal)) continue;
          const label = error?.status === 401 || error?.status === 403 ? '영상 권한 없음' : '영상 연결 확인 중';
          unavailable(watcher, 'warn', label);
        }
      }
    }
    try {
      await Promise.all(Array.from({length: Math.min(queue.length, MAX_IN_FLIGHT)}, drain));
    } finally {
      active = null;
      if (!watchers.size) stopTimer();
    }
  }

  function stopTimer() {
    if (timer !== null && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
      window.clearInterval(timer);
    }
    timer = null;
  }

  function startTimer() {
    if (!watchers.size || timer !== null || typeof window === 'undefined' || typeof window.setInterval !== 'function') return;
    timer = window.setInterval(() => { void tick(); }, intervalMs);
  }

  // Bind an <img> (and an optional badge element prefixed with label) to a view. Re-renders
  // re-bind; disconnected nodes are dropped on the next paint.
  function bind(img, view, badge = null, label = '') {
    if (disposed) return;
    const watcher = watcherOf(view);
    for (const other of [...watchers.values()]) {  // a re-bound node leaves its previous view
      if (other === watcher) continue;
      if (img) other.imgs.delete(img);
      if (badge) other.badges.delete(badge);
      if (!other.imgs.size && !other.badges.size) {
        if (other.url) URL.revokeObjectURL(other.url);
        watchers.delete(other.key);
      }
    }
    if (img) watcher.imgs.add(img);
    if (badge) {
      watcher.badgeLabel = label;
      watcher.badges.add(badge);
    }
    paint(watcher);
    startTimer();
    void tick();
  }

  function setRunning(next) {
    if (disposed) return;
    running = Boolean(next);
    if (running) { startTimer(); void tick(); }
    else { stopTimer(); active?.abort(); }
  }

  function dispose() {
    setRunning(false);
    disposed = true;
    for (const watcher of watchers.values()) unavailable(watcher, 'neutral', '영상 수신 대기');
    watchers.clear();
  }

  scope?.onDispose?.(dispose);
  return {bind, setRunning, dispose};
}
