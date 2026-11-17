// Pinky 앞 카메라 타일(Vision 저주파 JPEG 리스 경로, WebRTC 미사용).
// `keepFrame`·`staleStamp`는 map/camera-backdrop.js에서 그대로 가져와 중복하지 않는다.
import { keepFrame, staleStamp } from "/console/assets/camera-backdrop.js";

const LEASE_MARGIN_MS = 8000;
const STALE_AFTER_MS = 3000;
const LIST_REFRESH_MS = 30000;

/** Derive `pinky_<N>_front` from a robot id (e.g. `rosy_45` -> `pinky_45_front`). */
export function robotCameraSourceId(robotId) {
  const match = String(robotId ?? "").match(/(\d+)$/);
  return match ? `pinky_${match[1]}_front` : null;
}

/** Resolve first registered front camera source id among `pinky_<N>_front`, `pinky_<N>`, `${robotId}_front`, `${robotId}`. */
export function resolveRobotCameraSourceId(robotId, sources) {
  const id = String(robotId ?? "");
  if (!id || !sources?.size) return null;
  const match = id.match(/(\d+)$/);
  const candidates = [
    robotCameraSourceId(id),
    match ? `pinky_${match[1]}` : null,
    `${id}_front`,
    id,
  ].filter(Boolean);
  return candidates.find((candidate) => sources.has(candidate)) || null;
}

/** Pure view model for the front camera tile: unregistered / kept-frame / waiting. */
export function cameraTileViewModel({ registered, keptFrame, lastFrame }, nowMs = Date.now()) {
  if (registered === false) return { state: "unregistered", text: "카메라 등록 안 됨", hasImage: false, url: null };
  if (keptFrame) {
    const stale = !lastFrame || lastFrame.state !== "live" || !(lastFrame.ageMs >= 0 && lastFrame.ageMs <= STALE_AFTER_MS);
    const stamp = staleStamp(keptFrame.capturedAtMs, nowMs, true);
    const agePart = stamp.includes(" · ") ? stamp.split(" · ")[1] : "0초 전";
    return { state: stale ? "stale" : "live", text: `최신 사진 · ${agePart}`, hasImage: true, url: keptFrame.url };
  }
  return { state: "waiting", text: "사진 수신 대기", hasImage: false, url: null };
}

/**
 * Poll one robot's front camera via Vision lease (`POST /api/fleet/vision/lease` -> `/api/vision/sources/<id>/frame`).
 * Keeps the last good frame via `keepFrame` when the feed turns stale or fails.
 */
export function createRobotCameraPoller({
  robotId,
  call,
  signal = null,
  fetchImpl = globalThis.fetch,
  now = Date.now,
  createObjectURL = (blob) => URL.createObjectURL(blob),
  revokeObjectURL = (url) => URL.revokeObjectURL(url),
  onChange = () => {},
}) {
  const fallbackSourceId = robotCameraSourceId(robotId);
  const displaySourceId = fallbackSourceId || (robotId ? `${robotId}_front` : null);
  let activeSourceId = fallbackSourceId;
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  let lease = null;
  let keptFrame = null;
  let stopped = false;
  let inFlight = false;
  let cachedSources = null;
  let cachedSourcesAt = -Infinity;

  function activeSignals() {
    return [controller?.signal, signal].filter(Boolean);
  }
  function isAborted() {
    return stopped || Boolean(signal?.aborted) || Boolean(controller?.signal?.aborted);
  }
  function clearSourcesCache() {
    cachedSources = null;
    cachedSourcesAt = -Infinity;
  }
  async function getSources(callOpts, force = false) {
    if (!force && cachedSources !== null && now() - cachedSourcesAt < LIST_REFRESH_MS) {
      return cachedSources;
    }
    const list = await call("/api/fleet/vision/sources", callOpts);
    cachedSources = new Set(list?.sources || []);
    cachedSourcesAt = now();
    return cachedSources;
  }

  async function step({ force = false } = {}) {
    if (inFlight || isAborted()) return;
    inFlight = true;
    try {
      if (!robotId) {
        activeSourceId = null;
        onChange(cameraTileViewModel({ registered: false, keptFrame: null, lastFrame: null }, now()));
        return;
      }
      const signals = activeSignals();
      const callOpts = signals.length ? { signals } : undefined;
      const sources = await getSources(callOpts, force);
      if (isAborted()) return;
      const resolvedSourceId = resolveRobotCameraSourceId(robotId, sources);
      if (!resolvedSourceId) {
        activeSourceId = displaySourceId;
        lease = null;
        clearSourcesCache();
        onChange(cameraTileViewModel({ registered: false, keptFrame: null, lastFrame: null }, now()));
        return;
      }
      if (resolvedSourceId !== activeSourceId) {
        activeSourceId = resolvedSourceId;
        lease = null;
      }
      if (!lease || now() >= lease.expiresAt) {
        const issued = await call("/api/fleet/vision/lease", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: activeSourceId }),
          ...(signals.length ? { signals } : {}),
        });
        if (isAborted()) return;
        const origin = typeof location !== "undefined" ? location.origin : "http://localhost";
        const target = new URL(issued?.frame_path || `/api/vision/sources/${encodeURIComponent(activeSourceId)}/frame`, origin);
        if (target.origin !== origin || target.username || target.password) throw new Error("영상 주소를 확인하세요.");
        lease = {
          token: issued?.lease || "",
          framePath: target.pathname + target.search,
          expiresAt: now() + Math.max(1, Number(issued?.expires_in_s) || 60) * 1000 - LEASE_MARGIN_MS,
        };
      }
      const fetchSignal = controller?.signal || signal || undefined;
      const response = await fetchImpl(lease.framePath, {
        headers: { Authorization: `Bearer ${lease.token}` },
        credentials: "omit",
        cache: "no-store",
        ...(fetchSignal ? { signal: fetchSignal } : {}),
      });
      if (isAborted()) return;
      if (response.status === 401) { lease = null; clearSourcesCache(); return; }
      if (response.status === 404) { lease = null; clearSourcesCache(); }
      const rawAge = response.headers.get("X-Frame-Age-Ms");
      const ageMs = rawAge === null || rawAge === "" ? NaN : Number(rawAge);
      const frameState = response.headers.get("X-Frame-State");
      const live = response.ok && frameState !== "stale" && Number.isFinite(ageMs) && ageMs >= 0;
      let incoming = { state: live ? "live" : "stale", ageMs, capturedAtMs: now() - (Number.isFinite(ageMs) ? ageMs : 0), url: null };
      if (live) {
        const blob = await response.blob();
        if (isAborted()) return;
        if (blob && blob.size > 0) incoming.url = createObjectURL(blob);
        else incoming = { ...incoming, state: "stale" };
      }
      const nextKept = keepFrame(keptFrame, incoming);
      if (nextKept !== keptFrame) {
        if (keptFrame?.url) revokeObjectURL(keptFrame.url);
        keptFrame = nextKept;
      } else if (incoming.url && incoming !== keptFrame) {
        revokeObjectURL(incoming.url);
      }
      onChange(cameraTileViewModel({ registered: true, keptFrame, lastFrame: incoming }, now()));
    } catch (err) {
      if (err?.status === 401 || err?.status === 404) {
        lease = null;
        clearSourcesCache();
      }
      if (isAborted() || err?.name === "AbortError") return;
      onChange(cameraTileViewModel({ registered: true, keptFrame, lastFrame: null }, now()));
    } finally {
      inFlight = false;
    }
  }

  function stop() {
    stopped = true;
    clearSourcesCache();
    controller?.abort?.();
    if (keptFrame?.url) revokeObjectURL(keptFrame.url);
    keptFrame = null;
  }

  return { get sourceId() { return activeSourceId; }, step, stop };
}

/** Mount a Pinky front camera picture tile into `host` (secondary detail or video fallback). */
export function mountRobotCameraTile({ host, robotId, call, scope = null, intervalMs = 2000, now = Date.now, doc = document }) {
  const figure = doc.createElement("figure");
  figure.className = "robot-camera-tile";
  figure.setAttribute("data-robot-camera-tile", robotId);
  figure.setAttribute("data-state", "waiting");
  const img = doc.createElement("img");
  img.className = "robot-camera-img";
  img.alt = `${robotId} 앞 카메라`;
  img.hidden = true;
  const caption = doc.createElement("figcaption");
  caption.className = "robot-camera-caption";
  caption.textContent = "사진 수신 대기";
  const setupLink = doc.createElement("a");
  setupLink.className = "ui-action-link robot-camera-setup-link";
  setupLink.dataset.kind = "quiet";
  setupLink.href = `/console/install?robot=${encodeURIComponent(robotId)}#install-heading`;
  setupLink.textContent = "설치에서 카메라 등록";
  setupLink.hidden = true;
  figure.append(img, caption, setupLink);
  host.append(figure);

  const poller = createRobotCameraPoller({
    robotId,
    call,
    signal: scope?.signal || null,
    now,
    onChange(vm) {
      figure.setAttribute("data-state", vm.state);
      const labelSource = poller.sourceId || (robotId ? `${robotId}_front` : "");
      caption.textContent = vm.state === "unregistered" && labelSource ? `${vm.text} (${labelSource})` : vm.text;
      setupLink.hidden = vm.state !== "unregistered";
      img.hidden = !vm.hasImage;
      if (vm.hasImage && vm.url && img.src !== vm.url) img.src = vm.url;
    },
  });

  void poller.step();
  let timer = null;
  if (typeof window !== "undefined" && typeof window.setInterval === "function") {
    timer = window.setInterval(() => {
      if (figure.isConnected === false) { stop(); return; }
      if (doc?.hidden || (typeof document !== "undefined" && document.hidden)) return;
      void poller.step();
    }, intervalMs);
  }
  function stop() {
    if (timer !== null && typeof window !== "undefined" && typeof window.clearInterval === "function") {
      window.clearInterval(timer);
    }
    timer = null;
    poller.stop();
  }
  scope?.onDispose?.(stop);
  return { figure, poller, stop };
}
