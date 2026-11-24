// Cell camera frames through Vision preview leases (D-136: Fleet은 영상 바이트를 중계하지 않는다).
// A view is {source} for a registered Vision camera or {roiTarget} for the ceiling ROI zoom
// on one target. Views whose source is not in Vision's source list show the honest
// "영상 원본 미등록" state instead of a placeholder stream.
import {createCameraFrameHold, decodeImageUrl, paintCameraFrameHold} from '/common/camera-frame-hold.js';
import {frameBadge} from './vision-view.js';

const CEILING_SOURCE = 'ceiling_north';
const UNREGISTERED_TEXT = '영상 원본 미등록';
const LIST_REFRESH_MS = 30000;
const LEASE_MARGIN_MS = 8000;
const REQUEST_TIMEOUT_MS = 1500;
const MAX_IN_FLIGHT = 4;

// what stopped the arm, as cell_why names it, and how the person knows it
export const INCIDENT_CAUSES = [
  ['unknown', '원인: 판단 불가'], ['blocked', '막힘 (닿음)'], ['wrong_position', '위치가 어긋나 닿음'], ['snagged', '걸림'],
  ['too_fast', '속도 초과'], ['no_room', '공간 부족으로 거부'], ['software_or_config', '코드·설정'], ['camera_or_map', '카메라·지도'], ['other', '기타'],
];
export const INCIDENT_BASES = [
  ['unknown', '근거: 없음'], ['repeat', '같은 동작을 다시 해 봄'], ['measured', '측정값'], ['seen', '사진·눈으로'],
];

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

export async function issueVisionLease(callFn, source, {
  signal,
  timeoutMs = REQUEST_TIMEOUT_MS,
  strictFramePath = false,
  now = Date.now,
} = {}) {
  const issued = await callFn('/api/fleet/vision/lease', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({source_id: source}), signal, timeoutMs,
  });
  const target = new URL(issued?.frame_path || '', location.origin);
  if (target.origin !== location.origin || target.username || target.password
      || (strictFramePath && target.pathname !== `/api/vision/sources/${encodeURIComponent(source)}/frame`)) {
    throw Error(strictFramePath ? '영상 주소 확인 필요' : '영상 주소를 확인하세요.');
  }
  return {
    token: issued?.lease || '',
    lease: issued?.lease || '',
    framePath: target.href,
    frame_path: target.href,
    expiresAt: now() + Math.max(1, (issued?.expires_in_s || 60)) * 1000 - LEASE_MARGIN_MS,
    expires: now() + 45000,
  };
}

export function bindFocusZoom(target, { trigger = target, onToggle = null } = {}) {
  const setZoom = (on) => {
    if (!target?.classList) return;
    target.classList.toggle('focused', Boolean(on));
    onToggle?.(Boolean(on));
  };
  trigger?.addEventListener('click', (ev) => {
    ev.stopPropagation?.();
    setZoom(!target.classList.contains('focused'));
  });
  trigger?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      setZoom(!target.classList.contains('focused'));
    } else if (ev.key === 'Escape') {
      setZoom(false);
    }
  });
  return setZoom;
}

export function createCellFrameFeed({
  call, scope = null, intervalMs = 2000, now = Date.now, onStateChange = null, onSourcesSample = null,
}) {
  const watchers = new Map();
  const seen = new WeakSet();  // nodes painted while connected
  let sources = null, sourcesAt = -Infinity, sourcesError = '', listing = null;
  let running = true, paused = false, disposed = false, active = null, timer = null, disconnectTimer = null, tickQueued = false, rerun = false;

  const patchField = (obj, prop, val) => { if (obj && obj[prop] !== val) obj[prop] = val; };
  const isCurrent = (watcher, signal) => !signal.aborted && watchers.get(watcher.key) === watcher;
  const keyOf = view => (view.roiTarget ? `roi:${view.roiTarget}` : `source:${view.source}`);

  function notifyState(watcher, snap) {
    onStateChange?.(watcher.key, {
      source: watcher.view.roiTarget ? CEILING_SOURCE : watcher.view.source,
      roiTarget: watcher.view.roiTarget || null,
      live: snap.phase === 'live',
      hasFrame: snap.hasFrame,
      phase: snap.phase,
      kind: snap.kind,
      label: snap.label,
      text: snap.text,
    });
  }

  function watcherOf(view) {
    const key = keyOf(view);
    let watcher = watchers.get(key);
    if (!watcher) {
      watcher = {key, view, imgs: new Set(), badges: new Set(), badgeLabel: '', lease: null,
        hold: createCameraFrameHold({now})};
      watchers.set(key, watcher);
    }
    return watcher;
  }

  function stopDisconnectTimer() {
    if (disconnectTimer !== null && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
      window.clearInterval(disconnectTimer);
    }
    disconnectTimer = null;
  }

  function syncDisconnectTimer() {
    const at = now();
    const hasDisconnected = running && !paused && !disposed
      && [...watchers.values()].some(w => w.hold.snapshot(at).phase === 'disconnected');
    if (!hasDisconnected) {
      stopDisconnectTimer();
      return;
    }
    if (disconnectTimer !== null || typeof window === 'undefined' || typeof window.setInterval !== 'function') return;
    disconnectTimer = window.setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return;
      for (const watcher of watchers.values()) {
        if (watcher.hold.snapshot(now()).phase === 'disconnected') paint(watcher, {notify: false});
      }
    }, 1000);
  }

  function paint(watcher, {notify = true} = {}) {
    const snap = watcher.hold.snapshot(now());
    for (const img of watcher.imgs) {
      // A node bound before it is attached stays until it has been seen connected once.
      if (!img.isConnected) { if (seen.has(img)) watcher.imgs.delete(img); continue; }
      seen.add(img);
      const sibling = img.nextElementSibling?.classList?.contains('omx-inspector-cam-standby') ? img.nextElementSibling : null;
      paintCameraFrameHold(img.parentElement, img, sibling, snap);
      if (img.dataset && img.dataset.frameStateText !== snap.text) img.dataset.frameStateText = snap.text;
    }
    const badgeText = [watcher.badgeLabel, snap.text].filter(Boolean).join(' · ');
    for (const badge of watcher.badges) {
      if (!badge.isConnected) { if (seen.has(badge)) watcher.badges.delete(badge); continue; }
      seen.add(badge);
      patchField(badge, 'textContent', badgeText);
    }
    if (!watcher.imgs.size && !watcher.badges.size) {
      watcher.hold.dispose();
      watchers.delete(watcher.key);
      syncDisconnectTimer();
      return;
    }
    if (notify) notifyState(watcher, snap);
  }

  function unavailable(watcher, kind, label, detail = '', {dropFrame = false} = {}) {
    watcher.hold.disconnect({kind, label, detail, dropFrame});
    paint(watcher);
    syncDisconnectTimer();
  }

  async function ensureSources(signal) {
    if (sources !== null && now() - sourcesAt < LIST_REFRESH_MS) return sources;
    listing ??= call('/api/fleet/vision/sources', {signal, timeoutMs: REQUEST_TIMEOUT_MS})
      .then(res => {
        if (signal.aborted) return;
        const names = (res?.sources || []).filter(item => typeof item === 'string');
        sources = new Set(names);
        sourcesError = '';
        sourcesAt = now();
        onSourcesSample?.({finished: true, status: 200, names});
      })
      .catch(error => {
        if (signal.aborted) return;
        if (error?.status === 401 || error?.status === 403) sourcesError = 'unauthorized';
        else if (typeof error?.status === 'number') sourcesError = 'http';
        onSourcesSample?.(typeof error?.status === 'number'
          ? {finished: true, status: error.status}
          : {finished: false});
      })
      .finally(() => { listing = null; });
    return listing;
  }

  async function leaseFor(source, signal) {
    return issueVisionLease(call, source, {signal, timeoutMs: REQUEST_TIMEOUT_MS, now});
  }

  async function refreshOne(watcher, signal) {
    const source = watcher.view.roiTarget ? CEILING_SOURCE : watcher.view.source;
    if (!watcher.view.roiTarget) {
      await ensureSources(signal);
      if (!isCurrent(watcher, signal)) return;
      if (sources !== null && !sources.has(source)) {
        return unavailable(watcher, 'unregistered', UNREGISTERED_TEXT, `Vision 카메라 목록에 ${source} 없음 — 등록 확인`);
      }
      if (sources === null) {
        if (sourcesError === 'unauthorized') {
          return unavailable(watcher, 'warn', '영상 권한 확인 필요', '접속 후 다시 확인하세요', {dropFrame: true});
        }
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
    if (response.status === 404 && response.headers.get('X-Frame-State') !== 'stale') {
      return unavailable(watcher, 'warn', '카메라 송신기 미연결', 'Vision 404 — 현장 카메라 전송 확인');
    }
    const seq = response.headers.get('X-Frame-Seq');
    const badge = frameBadge({ok: response.ok, status: response.status,
      ageMs: frameAge(response.headers, Boolean(watcher.view.roiTarget)),
      frameState: response.headers.get('X-Frame-State'), rectified: false});
    if (!response.ok || badge.state !== 'live') {
      return unavailable(watcher, badge.kind, badge.label, badge.detail, {dropFrame: badge.state === 'unauthorized'});
    }
    const label = watcher.view.roiTarget ? '천장 Cam 확대 추적' : '원본 최신 프레임';
    const detail = watcher.view.roiTarget ? CEILING_SOURCE : seq && `#${seq}`;
    const currentSnap = watcher.hold.snapshot(now());
    if (seq && currentSnap.hasFrame && currentSnap.seq === seq) {
      watcher.hold.markLive({label, detail});
      paint(watcher);
      syncDisconnectTimer();
      return;
    }
    const blob = await response.blob();
    if (!isCurrent(watcher, signal)) return;
    if (!blob.size) return unavailable(watcher, 'warn', '첫 프레임 대기', '스트림 연결 확인');
    const next = URL.createObjectURL(blob);
    const decoded = await decodeImageUrl(next);
    if (!isCurrent(watcher, signal) || !decoded) {
      URL.revokeObjectURL(next);
      if (isCurrent(watcher, signal) && !decoded) unavailable(watcher, 'warn', '영상 디코딩 실패');
      return;
    }
    watcher.hold.acceptFrame({url: next, seq, label, detail});
    paint(watcher);
    syncDisconnectTimer();
  }

  async function tick() {
    if (disposed || !running || paused || !watchers.size) return;
    if (active) { rerun = true; return; }
    if (typeof document !== 'undefined' && document.hidden) return;
    do {
      rerun = false;
      const queue = [...watchers.values()];
      if (!queue.length) break;
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
            const isAuth = error?.status === 401 || error?.status === 403;
            const label = isAuth ? '영상 권한 없음' : '영상 연결 끊김 — Vision 확인';
            unavailable(watcher, 'warn', label, '', {dropFrame: isAuth});
          }
        }
      }
      try {
        await Promise.all(Array.from({length: Math.min(queue.length, MAX_IN_FLIGHT)}, drain));
      } finally {
        active = null;
        if (!watchers.size) stopTimer();
      }
    } while (rerun && running && !paused && !disposed && watchers.size && !(typeof document !== 'undefined' && document.hidden));
  }

  function scheduleTick() {
    if (tickQueued || disposed || !running || paused) return;
    tickQueued = true;
    queueMicrotask(() => {
      tickQueued = false;
      void tick();
    });
  }

  function stopTimer() {
    if (timer !== null && typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
      window.clearInterval(timer);
    }
    timer = null;
  }

  function startTimer() {
    if (!watchers.size || paused || timer !== null || typeof window === 'undefined' || typeof window.setInterval !== 'function') return;
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
        other.hold.dispose();
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
    syncDisconnectTimer();
    scheduleTick();
  }

  function repaint(view) {
    if (disposed || !view) return;
    const watcher = watchers.get(keyOf(view));
    if (watcher) paint(watcher);
  }

  function setRunning(next) {
    if (disposed) return;
    running = Boolean(next);
    if (running && !paused) { startTimer(); syncDisconnectTimer(); scheduleTick(); }
    else { stopTimer(); stopDisconnectTimer(); active?.abort(); }
  }

  function setPaused(next) {
    if (disposed) return;
    const value = Boolean(next);
    if (paused === value) return;
    paused = value;
    for (const watcher of watchers.values()) {
      watcher.hold.setPaused(value);
      paint(watcher);
    }
    if (!paused && running) { startTimer(); syncDisconnectTimer(); scheduleTick(); }
    else if (paused) { stopTimer(); stopDisconnectTimer(); active?.abort(); }
  }

  function checkSources(signal) {
    if (disposed) return Promise.resolve();
    const sig = signal || AbortSignal.timeout(REQUEST_TIMEOUT_MS);
    return ensureSources(sig);
  }

  function dispose() {
    setRunning(false);
    disposed = true;
    for (const watcher of watchers.values()) {
      watcher.hold.disconnect({kind: 'neutral', label: '영상 수신 대기', dropFrame: true});
      paint(watcher);
      watcher.hold.dispose();
    }
    watchers.clear();
    stopDisconnectTimer();
  }

  scope?.onDispose?.(dispose);
  return {bind, setRunning, setPaused, repaint, checkSources, dispose};
}
