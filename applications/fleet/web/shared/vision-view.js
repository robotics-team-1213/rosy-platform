const NO_SOURCE = "관제 카메라 인증 후 영상을 불러옵니다.";
const DEFAULT_RECTIFICATION = Object.freeze({ fx: 1, fy: 1, cx: 0.5, cy: 0.5, k1: 0, k2: 0, p1: 0, p2: 0, k3: 0, corners: [[0, 0], [1, 0], [1, 1], [0, 1]], output_aspect: 0 });
const AUTO_RECTIFICATION = Object.freeze({ mode: "auto" }), MAP_RECTIFICATION = Object.freeze({ mode: "map" });
export const FRAME_LATE_MS = 3000;
export function parsePlaneHeader(value) {
  const parts = String(value ?? "").split(",").map((part) => part.trim());
  if (parts.length !== 5 || parts.some((part) => part === "")) return null;
  const [min_x, min_y, max_x, max_y, ppm] = parts.map(Number);
  return [min_x, min_y, max_x, max_y, ppm].every(Number.isFinite) && min_x < max_x && min_y < max_y && ppm > 0 ? { min_x, min_y, max_x, max_y, ppm } : null;
}
export const planeToMap = (plane, u, v) => ({ x: plane.min_x + u / plane.ppm, y: plane.max_y - v / plane.ppm });
export const mapToPlane = (plane, x, y) => ({ u: (x - plane.min_x) * plane.ppm, v: (plane.max_y - y) * plane.ppm });
export const planeFitsImage = (plane, width, height) =>
  Math.abs((plane.max_x - plane.min_x) * plane.ppm - width) <= 1 && Math.abs((plane.max_y - plane.min_y) * plane.ppm - height) <= 1;
export const planeCalibrationsFor = (calibrations, siteMap, source) => (calibrations || []).filter((row) =>
  row?.source_id === source && (siteMap?.maps || []).some((map) => map.map_id === row.map_id));
export function planeCalibration(frame, calibrations, siteMap) {
  if (!frame?.calibrationRevision || !(frame.ageMs >= 0 && frame.ageMs <= FRAME_LATE_MS)) return null;
  return planeCalibrationsFor(calibrations, siteMap, frame.source).find((row) => row.calibration_revision === frame.calibrationRevision) || null;
}
export async function fetchMapPlane(call, source, held, signal) {
  let lease = held?.source === source && Date.now() < held.expiresAt ? held : null;
  if (!lease) {
    try {
      const issued = await call("/api/fleet/vision/lease", {
        method: "POST", signals: [signal], headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: source, rectification: MAP_RECTIFICATION }),
      });
      const life = Number(issued.expires_in_s);
      lease = { ...issued, source, expiresAt: Date.now() + (life > 0 ? Math.max(1, life - 5) : 45) * 1000 };
    } catch (error) {
      if (error.status === 422) return { state: "plane-unavailable", lease: null };
      throw error;
    }
  }
  const path = new URL(lease.frame_path, location.origin);
  if (path.origin !== location.origin || path.username || path.password) throw new Error("영상 주소를 확인하세요.");
  const response = await fetch(path, { signal, credentials: "omit", redirect: "error", cache: "no-store", headers: { Authorization: `Bearer ${lease.lease}` } });
  if (response.status === 409 && response.headers.get("X-Frame-State") === "plane-unavailable") return { state: "plane-unavailable", lease };
  if (!response.ok) return { state: "error", status: response.status, lease: response.status === 401 || response.status === 403 ? null : lease };
  const plane = parsePlaneHeader(response.headers.get("X-Frame-Plane"));
  if (response.headers.get("X-Frame-Rectified") !== "map" || !plane) return { state: "plane-unavailable", lease };
  const age = response.headers.get("X-Frame-Age-Ms");
  return { state: "live", plane, calibrationRevision: response.headers.get("X-Frame-Calibration"),
    observedFraction: parseObservedFraction(response.headers.get("X-Frame-Observed-Fraction")),
    ageMs: age === null ? NaN : Number(age), blob: await response.blob(), lease };
}
export function parseObservedFraction(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const fraction = Number(value);
  return Number.isFinite(fraction) && fraction >= 0 && fraction <= 1 ? fraction : null;
}
export function frameBadge({ ok, status, frameState, ageMs, rectified }) {
  if (ok) {
    const age = ageMs === null || ageMs === undefined || ageMs === "" ? NaN : Number(ageMs);
    if (!Number.isFinite(age) || age < 0) return { state: "stale", label: "영상 시각 미확인", kind: "warn", detail: "촬영 시각을 확인할 수 없어 영상을 지웠습니다." };
    if (frameState === "stale" || age > FRAME_LATE_MS) return { state: "stale", label: "영상 지연", kind: "warn", detail: `최신 프레임이 ${Math.round(age / 100) / 10} s 전 것입니다.` };
    if (frameState === "field-unavailable") return { state: "live", label: "자동 보정 대기", kind: "neutral", detail: "필드 경계를 아직 잡지 못해 원본을 보여 줍니다." };
    return { state: "live", label: rectified === "auto" ? "자동 보정 미리보기" : rectified ? "화면 보정 미리보기" : "원본 최신 프레임", kind: "good", detail: "" };
  }
  if (status === 401 || status === 403) return { state: "unauthorized", label: "영상 권한 없음", kind: "warn", detail: "영상 사용 허가가 만료됐거나 거부됐습니다. 다시 요청합니다." };
  if (frameState === "stale") return { state: "stale", label: "영상 정지", kind: "warn", detail: "최신 프레임이 없어 영상 표시를 지웠습니다." };
  if (status === 422) return { state: "invalid", label: "보정값 확인", kind: "warn", detail: "보정값을 확인하세요. 모서리는 교차하지 않는 사각형이어야 합니다." };
  return { state: "no-frame", label: "영상 수신 대기", kind: "neutral", detail: `Vision 응답 ${status}` };
}
const RECTIFICATION_PREFIX = "rosy-camera-rectification:", LENS_NAMES = { wide: "초광각", standard: "기본 렌즈" };
export function parseLensHeader(value) {
  if (!value) return null;
  const fields = Object.fromEntries(value.split(";").map((part) => part.split("=").map((item) => item.trim())));
  return Object.hasOwn(LENS_NAMES, fields.kind) ? { kind: fields.kind, focal_mm: Number(fields.focal_mm), hfov_deg: Number(fields.hfov_deg) } : null;
}
export const rectificationKey = (source, lensKind) => lensKind ? `${RECTIFICATION_PREFIX}${source}@${lensKind}` : `${RECTIFICATION_PREFIX}${source}`;
export function resolveSavedProfile(storage, source, lensKind) {
  const key = rectificationKey(source, lensKind), legacyKey = rectificationKey(source, null);
  let saved = storage.getItem(key);
  if (lensKind && saved === null) {
    const legacy = storage.getItem(legacyKey);
    if (legacy !== null && lensKind === "standard") { storage.setItem(key, legacy); saved = legacy; }
  }
  if (!lensKind || saved !== null) return { saved, warning: null };
  const others = Object.keys(LENS_NAMES).filter((kind) => kind !== lensKind && storage.getItem(rectificationKey(source, kind)) !== null);
  if (storage.getItem(legacyKey) !== null && !others.includes("standard")) others.push("standard");
  return others.length ? { saved: null, warning: `저장한 화면 보정은 ${LENS_NAMES[others[0]]}용입니다. 지금 카메라는 ${LENS_NAMES[lensKind]}라 기본값으로 보여 줍니다. 이 렌즈에 맞게 다시 맞추세요.` } : { saved: null, warning: null };
}
const PLANE_RETRY_MS = 30000, PLANE_ERROR_MS = 5000;
export function createPlaneFeed({ scope, visionView, onChange, now = Date.now }) {
  let frame = null, busy = false, retryAt = 0, cancelExpiry = () => {}, generation = 0;
  function drop() {
    cancelExpiry(); cancelExpiry = () => {};
    if (frame) URL.revokeObjectURL(frame.url);
    const had = Boolean(frame); frame = null; return had;
  }
  async function refresh(wanted = true) {
    if (!wanted) { generation += 1; if (drop()) onChange(); return; }
    if (busy || now() < retryAt) return;
    busy = true;
    const life = scope.capture(), startedGeneration = generation, requestedAt = now();
    try {
      const got = await visionView.fetchPlane();
      if (got.state === "plane-unavailable") { retryAt = now() + PLANE_RETRY_MS; drop(); return; }
      if (got.state !== "live") { retryAt = now() + PLANE_ERROR_MS; return; }
      const url = URL.createObjectURL(got.blob), image = new Image();
      image.src = url;
      const decoded = await image.decode().then(() => true, () => false);
      if (!life.current() || startedGeneration !== generation || !decoded) {
        URL.revokeObjectURL(url); if (!decoded) retryAt = now() + PLANE_ERROR_MS; return;
      }
      const ageMs = got.ageMs + now() - requestedAt;
      if (!Number.isFinite(ageMs) || ageMs < 0 || ageMs > FRAME_LATE_MS) { URL.revokeObjectURL(url); drop(); return; }
      if (!planeFitsImage(got.plane, image.naturalWidth, image.naturalHeight)) {
        URL.revokeObjectURL(url); retryAt = now() + PLANE_RETRY_MS; drop(); return;
      }
      drop();
      frame = { image, url, source: got.source, plane: got.plane, calibrationRevision: got.calibrationRevision, observedFraction: got.observedFraction, ageMs };
      cancelExpiry = scope.timeout(() => { drop(); onChange(); }, Math.max(0, FRAME_LATE_MS - ageMs) || 0);
    } catch (error) {
      if (error.name !== "AbortError") retryAt = now() + PLANE_ERROR_MS;
    } finally {
      busy = false;
      if (life.current()) onChange();
    }
  }
  scope.onDispose(drop);
  return { refresh, current: () => frame };
}
const absentPanel = () => ({ open: false, hidden: true, textContent: "", querySelectorAll: () => [], addEventListener: () => {}, removeEventListener: () => {}, toggleAttribute: () => {}, setAttribute: () => {} });
export function createVisionView({ scope, el, call, isActive = () => true, rawOnly = false, onSources = () => {} }) {
  const select = el("vision-source"), frame = el("vision-frame"), stage = el("vision-image-stage"), image = el("vision-image");
  const cornerOverlay = el("vision-corner-overlay"), cornerPolygon = el("vision-corner-polygon"), cornerHandles = [...cornerOverlay.querySelectorAll("[data-corner-handle]")];
  const status = el("vision-state"), message = el("vision-message"), adjustments = el("vision-adjustments") || absentPanel();
  const profileFields = [...adjustments.querySelectorAll("[data-rect]")], cornerFields = [...adjustments.querySelectorAll("[data-corner]")];
  const profileFieldsets = [...adjustments.querySelectorAll("fieldset")], cornerModes = el("vision-corner-modes") || absentPanel();
  const cornerHint = el("vision-corner-hint") || absentPanel(), adjustmentState = el("vision-adjustment-state") || absentPanel(), proposalPolygon = el("vision-proposal-polygon");
  let lease = null, leaseExpiresAt = 0, planeLease = null, objectUrl = null, busy = false, previewLifetime = new AbortController(), lastSourcesAt = 0, refreshTimer = null;
  let viewMode = rawOnly ? "raw" : "adjusted", draggingPointerId = null, proposalCorners = null;
  let currentLens = null, currentLensInfo = null, selectedSource = "", sourceAvailable = false, availableSources = [];
  const frameListeners = [];
  let cancelFrameExpiry = () => {};
  function pausePreview() {
    previewLifetime.abort(); previewLifetime = new AbortController();
    if (busy?.kind === "frame") busy = false;
  }
  scope.onDispose(() => {
    cancelFrameExpiry(); pausePreview(); busy = false; refreshTimer?.(); refreshTimer = null;
    lease = null; leaseExpiresAt = 0; draggingPointerId = null;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  });
  function showState(label, kind = "neutral", detail = label) {
    cancelFrameExpiry(); status.textContent = label; status.setAttribute("status", kind); message.textContent = detail;
    image.hidden = true; stage.hidden = true; cornerOverlay.toggleAttribute("hidden", true); frame.dataset.state = kind;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    for (const listener of frameListeners) listener({ state: "stale", source: select.value });
  }
  function readProfile() {
    if (!cornerFields.length || !profileFields.length) return { ...DEFAULT_RECTIFICATION };
    const profile = { ...DEFAULT_RECTIFICATION };
    for (const field of profileFields) profile[field.dataset.rect] = Number(field.value);
    profile.corners = Array.from({ length: 4 }, (_, index) => Array.from({ length: 2 }, (_, axis) =>
      Number(cornerFields.find((item) => Number(item.dataset.corner) === index && Number(item.dataset.axis) === axis).value) / 100));
    return profile;
  }
  function writeProfile(profile) {
    for (const field of profileFields) field.value = String(profile[field.dataset.rect] ?? DEFAULT_RECTIFICATION[field.dataset.rect]);
    for (const field of cornerFields) {
      field.value = formatPercent(100 * (profile.corners?.[Number(field.dataset.corner)]?.[Number(field.dataset.axis)]
        ?? DEFAULT_RECTIFICATION.corners[Number(field.dataset.corner)][Number(field.dataset.axis)]));
    }
    updateCornerOverlay();
  }
  const formatPercent = (value) => { const rounded = Math.round(value * 10) / 10; return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1); };
  scope.subscribe(() => {
    const life = scope.capture();
    const observer = new ResizeObserver(() => {
      if (!life.current()) return;
      const bounds = stage.getBoundingClientRect();
      if (bounds.width > 0 && bounds.height > 0) updateCornerOverlay();
    });
    observer.observe(stage);
    return () => observer.disconnect();
  });
  function updateCornerOverlay() {
    const width = image.naturalWidth, height = image.naturalHeight, viewHeight = width && height ? 100 * height / width : 75;
    cornerOverlay.setAttribute("viewBox", `0 0 100 ${viewHeight}`);
    const stageWidth = stage.getBoundingClientRect().width, radius = stageWidth ? Math.max(3, Math.min(8, 2200 / stageWidth)) : 7;
    const points = readProfile().corners.map(([x, y]) => [x * 100, y * viewHeight]);
    cornerPolygon.setAttribute("points", points.map(([x, y]) => `${x},${y}`).join(" "));
    proposalPolygon.toggleAttribute("hidden", !proposalCorners);
    if (proposalCorners) proposalPolygon.setAttribute("points", proposalCorners.map(([x, y]) => `${x * 100},${y * viewHeight}`).join(" "));
    const names = ["왼쪽 위", "오른쪽 위", "오른쪽 아래", "왼쪽 아래"];
    cornerHandles.forEach((handle, index) => {
      const [x, y] = points[index];
      handle.setAttribute("cx", String(x)); handle.setAttribute("cy", String(y)); handle.setAttribute("r", String(radius));
      handle.setAttribute("aria-label", `${names[index]} 모서리, X ${formatPercent(x)}%, Y ${formatPercent(y)}%`);
    });
  }
  function saveDraft({ announce = true } = {}) {
    const source = select.value;
    if (!source) return;
    const profile = readProfile();
    try {
      localStorage.setItem(rectificationKey(source, currentLens), JSON.stringify(profile));
      if (announce) adjustmentState.textContent = "조정값을 이 브라우저에 저장했습니다.";
    } catch {
      if (announce) adjustmentState.textContent = "브라우저 저장을 사용할 수 없습니다. 이 화면에서만 적용됩니다.";
    }
    return profile;
  }
  function setCorner(index, x, y, { announce = false } = {}) {
    const coordinates = [x, y].map((value) => Math.round(Math.max(0, Math.min(1, value)) * 1000) / 10);
    for (let axis = 0; axis < 2; axis += 1) {
      cornerFields.find((item) => Number(item.dataset.corner) === index && Number(item.dataset.axis) === axis).value = formatPercent(coordinates[axis]);
    }
    updateCornerOverlay(); saveDraft({ announce });
  }
  function selectViewMode(mode) {
    viewMode = mode;
    const editing = mode === "raw";
    frame.dataset.editing = String(editing);
    el("vision-edit-corners").setAttribute("aria-pressed", String(editing));
    el("vision-preview-adjusted").setAttribute("aria-pressed", String(mode === "adjusted"));
    const autoButton = el("vision-preview-auto");
    if (autoButton) autoButton.setAttribute("aria-pressed", String(mode === "auto"));
    cornerHint.hidden = !editing; cornerOverlay.toggleAttribute("hidden", !editing);
    lease = null; leaseExpiresAt = 0;
    if (editing) adjustmentState.textContent = "원본에서 영역을 조정 중입니다. 끝나면 보정 결과를 확인하세요.";
    if (mode === "auto") adjustmentState.textContent = "필드 경계 캘리브레이션이 잡은 모서리로 자동 보정합니다. 감지가 없으면 원본을 보여 줍니다.";
    refreshFrame();
  }
  function loadProfile(source) {
    let profile = DEFAULT_RECTIFICATION;
    try {
      const { saved, warning } = source ? resolveSavedProfile(localStorage, source, currentLens) : { saved: null, warning: null };
      if (saved) profile = { ...DEFAULT_RECTIFICATION, ...JSON.parse(saved) };
      if (warning) adjustmentState.textContent = warning;
    } catch {
      adjustmentState.textContent = "저장한 값을 읽지 못해 기본 조정값을 사용합니다.";
    }
    writeProfile(profile);
    profileFieldsets.forEach((fieldset) => { fieldset.disabled = !source; });
    cornerModes.hidden = !source || !adjustments.open;
  }
  async function refreshSources() {
    const life = scope.capture();
    life.check();
    if (busy) return;
    const work = {kind: "sources"}; busy = work;
    try {
      const result = await call("/api/fleet/vision/sources");
      life.check();
      onSources({ finished: true, status: 200, names: result.sources });
      const previous = selectedSource;
      availableSources = result.sources;
      selectedSource ||= result.sources[0] || "";
      sourceAvailable = result.sources.includes(selectedSource);
      const names = sourceAvailable || !selectedSource ? result.sources : [selectedSource, ...result.sources];
      select.replaceChildren(...names.map((source) => {
        const option = document.createElement("option");
        option.value = source; option.textContent = source === selectedSource && !sourceAvailable ? `${source} · 연결 끊김` : source;
        return option;
      }));
      select.value = selectedSource; select.disabled = result.sources.length === 0;
      if (previous !== selectedSource) {
        currentLens = null; currentLensInfo = null; planeLease = null; proposalCorners = null;
        loadProfile(selectedSource); lease = null;
      }
      lastSourcesAt = Date.now();
      if (selectedSource && !sourceAvailable) {
        lease = null; planeLease = null; proposalCorners = null;
        showState("선택한 카메라 연결 끊김", "warn", `${selectedSource}의 재연결을 기다립니다. 다른 카메라는 직접 선택하세요.`);
      } else if (!result.sources.length) showState("카메라 없음", "warn", "Vision에 등록된 카메라가 없습니다.");
    } catch (error) {
      if (error.name === "AbortError") return;
      if (typeof error.status === "number") onSources({ finished: true, status: error.status, names: [] });
      else onSources({ finished: false });
      lastSourcesAt = Date.now(); showState("영상 연결 불가", "warn", error.message);
    } finally {
      if (life.current() && busy === work) busy = false;
    }
  }
  async function refreshFrame() {
    const life = scope.capture();
    life.check();
    const preview = previewLifetime;
    const current = () => life.current() && preview === previewLifetime && !preview.signal.aborted && isActive();
    if (busy || !isActive()) return;
    if (Date.now() - lastSourcesAt > 30000) await refreshSources();
    life.check();
    if (!current()) return;
    const source = select.value;
    if (!source || !sourceAvailable) return;
    const work = {kind: "frame"}; busy = work;
    const requestedAt = Date.now();
    try {
      if (!lease || Date.now() >= leaseExpiresAt) {
        const issued = await call("/api/fleet/vision/lease", {
          method: "POST", signals: [preview.signal], headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: source, rectification: viewMode === "raw" ? DEFAULT_RECTIFICATION : viewMode === "auto" ? AUTO_RECTIFICATION : readProfile() }),
        });
        life.check();
        if (!current() || source !== select.value) return;
        lease = issued; leaseExpiresAt = Date.now() + 45000;
      }
      if (!current()) return;
      const response = await fetch(lease.frame_path, {
        signal: AbortSignal.any([life.signal, preview.signal]), credentials: "omit", redirect: "error",
        headers: { Authorization: `Bearer ${lease.lease}` }, cache: "no-store",
      });
      life.check();
      if (!current() || source !== select.value) return;
      const lens = parseLensHeader(response.headers.get("X-Source-Lens"));
      if (response.ok) currentLensInfo = lens;
      if (response.ok && (lens?.kind ?? null) !== currentLens) { currentLens = lens?.kind ?? null; loadProfile(source); lease = null; }
      const rectifiedHeader = response.headers.get("X-Frame-Rectified"), rectified = rectifiedHeader === "true" || rectifiedHeader === "auto";
      const badge = frameBadge({ ok: response.ok, status: response.status, rectified: rectifiedHeader === "auto" ? "auto" : rectified,
        frameState: response.headers.get("X-Frame-State"), ageMs: response.headers.get("X-Frame-Age-Ms") });
      if (!response.ok || badge.state !== "live") {
        if (badge.state === "unauthorized") lease = null;
        showState(badge.label, badge.kind, badge.detail); return;
      }
      const blob = await response.blob();
      life.check();
      if (!current() || source !== select.value) return;
      const nextUrl = URL.createObjectURL(blob), nextImage = new Image();
      nextImage.src = nextUrl;
      const decoded = await nextImage.decode().then(() => true, () => false);
      if (!current() || source !== select.value) { URL.revokeObjectURL(nextUrl); return; }
      const frameAge = Number(response.headers.get("X-Frame-Age-Ms")) + Date.now() - requestedAt;
      if (!decoded || !Number.isFinite(frameAge) || frameAge > FRAME_LATE_MS) {
        URL.revokeObjectURL(nextUrl); showState("영상 만료", "warn", "새 프레임을 기다립니다."); return;
      }
      cancelFrameExpiry();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = nextUrl;
      status.textContent = badge.label; status.setAttribute("status", badge.kind); message.textContent = badge.detail;
      image.src = nextUrl; image.hidden = false; stage.hidden = false; updateCornerOverlay();
      frame.dataset.state = "online"; frame.dataset.editing = String(viewMode === "raw" && !rawOnly);
      cornerOverlay.toggleAttribute("hidden", viewMode !== "raw" || rawOnly);
      const seq = response.headers.get("X-Frame-Seq");
      el("vision-meta").textContent = `${new Date().toLocaleTimeString("ko-KR", { hour12: false })} · ${source} · sequence ${seq || "?"} · age ${response.headers.get("X-Frame-Age-Ms") || "?"} ms · ${rectified ? "화면 보정" : "원본"}${lens ? ` · ${LENS_NAMES[lens.kind]} ${lens.focal_mm} mm` : ""}`;
      for (const listener of frameListeners) listener({ image: nextImage, previewElement: image, rectified, source, seq, url: nextUrl, lens: currentLensInfo, ageMs: frameAge, state: badge.state });
      cancelFrameExpiry(); cancelFrameExpiry = scope.timeout(() => showState("영상 만료", "warn", "새 프레임을 기다립니다."), Math.max(0, FRAME_LATE_MS - frameAge));
    } catch (error) {
      if (error.name === "AbortError" || !current()) return;
      lease = null; showState("영상 정지", "warn", error.message || "Vision에 연결할 수 없습니다.");
    } finally {
      if (life.current() && busy === work) busy = false;
    }
  }
  function reset() {
    pausePreview(); selectedSource = ""; sourceAvailable = false; availableSources = [];
    planeLease = null; currentLens = null; currentLensInfo = null; lease = null; leaseExpiresAt = 0;
    lastSourcesAt = 0; proposalCorners = null; select.replaceChildren(); select.disabled = true;
    loadProfile(""); showState("인증 대기", "neutral", NO_SOURCE);
  }
  scope.listen(select, "change", () => {
    pausePreview(); selectedSource = select.value; sourceAvailable = availableSources.includes(selectedSource);
    lease = null; planeLease = null; proposalCorners = null; currentLens = null; currentLensInfo = null;
    loadProfile(select.value); showState("카메라 전환", "neutral", "선택한 영상의 최신 프레임을 기다립니다."); refreshFrame();
  });
  scope.listen(adjustments, "toggle", () => { cornerModes.hidden = !adjustments.open || !select.value; });
  scope.listen(window, "resize", updateCornerOverlay);
  scope.listen(el("vision-edit-corners"), "click", () => selectViewMode("raw"));
  scope.listen(el("vision-preview-adjusted"), "click", () => selectViewMode("adjusted"));
  scope.listen(el("vision-preview-auto"), "click", () => selectViewMode("auto"));
  for (const handle of cornerHandles) {
    scope.listen(handle, "pointerdown", (event) => {
      if (viewMode !== "raw" || !event.isPrimary) return;
      event.preventDefault(); draggingPointerId = event.pointerId; handle.setPointerCapture(event.pointerId);
      const box = stage.getBoundingClientRect();
      if (box.width && box.height) setCorner(Number(handle.dataset.cornerHandle), (event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height);
    });
    scope.listen(handle, "pointermove", (event) => {
      if (viewMode !== "raw" || event.pointerId !== draggingPointerId) return;
      const box = stage.getBoundingClientRect();
      if (box.width && box.height) setCorner(Number(handle.dataset.cornerHandle), (event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height);
    });
    const stopDrag = (event) => { if (event.pointerId === draggingPointerId) { draggingPointerId = null; saveDraft(); } };
    scope.listen(handle, "pointerup", stopDrag); scope.listen(handle, "pointercancel", stopDrag);
    scope.listen(handle, "keydown", (event) => {
      if (viewMode !== "raw") return;
      const movement = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
      if (!movement) return;
      event.preventDefault();
      const step = event.shiftKey ? 0.1 : 1, index = Number(handle.dataset.cornerHandle), profile = readProfile();
      setCorner(index, profile.corners[index][0] + movement[0] * step / 100, profile.corners[index][1] + movement[1] * step / 100, { announce: true });
    });
  }
  for (const field of [...profileFields, ...cornerFields]) {
    scope.listen(field, "input", () => {
      if (!field.reportValidity() || !select.value) return;
      updateCornerOverlay(); saveDraft(); lease = null; refreshTimer?.();
      if (viewMode === "raw") adjustmentState.textContent = "원본에서 영역을 조정 중입니다. 끝나면 보정 결과를 확인하세요.";
      else { adjustmentState.textContent += " 미리보기를 갱신합니다."; refreshTimer = scope.timeout(() => refreshFrame(), 450); }
    });
  }
  scope.listen(el("vision-reset-adjustments"), "click", () => {
    const source = select.value;
    if (source) localStorage.removeItem(rectificationKey(source, currentLens));
    loadProfile(source); adjustmentState.textContent = "기본 조정값으로 초기화했습니다."; lease = null; refreshFrame();
  });
  scope.listen(el("vision-refresh"), "click", () => {
    lease = null;
    const life = scope.capture();
    return refreshSources().then(() => { life.check(); return refreshFrame(); });
  });
  async function fetchFieldProposal(view = "field-proposal") {
    const life = scope.capture();
    life.check();
    const source = select.value;
    if (!source || !sourceAvailable) throw new Error("연결된 카메라를 먼저 선택하세요.");
    if (!lease || Date.now() >= leaseExpiresAt) {
      const issued = await call("/api/fleet/vision/lease", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: source, rectification: viewMode === "raw" ? DEFAULT_RECTIFICATION : readProfile() }),
      });
      life.check();
      lease = issued; leaseExpiresAt = Date.now() + 45000;
    }
    const response = await fetch(lease.frame_path.replace(/\/frame$/, `/${view}`), {
      signal: life.signal, credentials: "omit", redirect: "error", headers: { Authorization: `Bearer ${lease.lease}` }, cache: "no-store",
    });
    life.check();
    if (response.status === 404 && view === "map-proposal" && !response.headers.get("X-Frame-State")) {
      const text = await response.text().catch(() => "");
      life.check();
      throw new Error(text.includes("not configured") ? "Vision에 차선 페인트 지도가 설정되지 않았습니다(vision --map-paint)." : "최신 프레임이 없어 맞출 수 없습니다.");
    }
    if (response.status === 429) {
      const error = new Error("잠시 뒤 다시 찾으세요(초당 1회).");
      error.busy = true; error.retryAfterMs = 1000 * (Number(response.headers.get("Retry-After")) || 1);
      throw error;
    }
    if (response.status === 422) throw new Error("프레임을 해석하지 못했습니다. 잠시 뒤 다시 찾으세요.");
    if (!response.ok) throw new Error(response.headers.get("X-Frame-State") === "stale" ? "최신 프레임이 없어 찾을 수 없습니다." : `Vision 응답 ${response.status}`);
    const body = await response.json();
    life.check();
    return { source, body, proposalState: response.headers.get("X-Proposal-State") };
  }
  function showProposal(corners) {
    proposalCorners = corners;
    if (corners && viewMode !== "raw") selectViewMode("raw"); else updateCornerOverlay();
  }
  function acceptCorners(corners) {
    corners.forEach(([x, y], index) => setCorner(index, x, y));
    proposalCorners = null; saveDraft(); updateCornerOverlay();
  }
  return {
    refreshSources, refreshFrame, reset, pausePreview, fetchFieldProposal, showProposal, acceptCorners,
    fetchMapProposal: () => fetchFieldProposal("map-proposal"),
    showRaw: () => { if (viewMode !== "raw") selectViewMode("raw"); },
    async fetchPlane() {
      const source = select.value;
      if (!source || !sourceAvailable) return { state: "no-source" };
      const life = scope.capture(), preview = previewLifetime;
      const got = await fetchMapPlane(call, source, planeLease, AbortSignal.any([life.signal, preview.signal]));
      life.check();
      if (preview !== previewLifetime || source !== select.value || !sourceAvailable) return { state: "stale", source };
      planeLease = got.lease;
      return { ...got, source };
    },
    currentSource: () => select.value, currentLensInfo: () => currentLensInfo, currentCorners: () => readProfile().corners,
    onFrame(listener) {
      frameListeners.push(listener);
      return () => { const index = frameListeners.indexOf(listener); if (index >= 0) frameListeners.splice(index, 1); };
    },
  };
}
