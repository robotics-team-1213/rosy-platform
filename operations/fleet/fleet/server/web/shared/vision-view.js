const NO_SOURCE = "관제 카메라 인증 후 영상을 불러옵니다.";
const DEFAULT_RECTIFICATION = Object.freeze({
  fx: 1, fy: 1, cx: 0.5, cy: 0.5, k1: 0, k2: 0, p1: 0, p2: 0, k3: 0,
  corners: [[0, 0], [1, 0], [1, 1], [0, 1]], output_aspect: 0,
});
// D-484: 자동 보정 — 코너는 Vision의 필드 경계 캘리브레이션이 정한다. 렌즈 왜곡값은 없이 보낸다.
const AUTO_RECTIFICATION = Object.freeze({ mode: "auto" });

// D-560 2: Vision이 승인 보정으로 편 지도 평면 영상(지도 +x 오른쪽, +y 위).
const MAP_RECTIFICATION = Object.freeze({ mode: "map" });

// 프레임 나이가 이보다 크면 받았어도 "지연"으로 표시한다(폴링 1.5 s 의 두 배).
export const FRAME_LATE_MS = 3000;

// X-Frame-Plane "min_x,min_y,max_x,max_y,px_per_m" → { min_x, min_y, max_x, max_y, ppm } or null.
export function parsePlaneHeader(value) {
  const parts = String(value ?? "").split(",").map((part) => part.trim());
  if (parts.length !== 5 || parts.some((part) => part === "")) return null;
  const [min_x, min_y, max_x, max_y, ppm] = parts.map(Number);
  if (![min_x, min_y, max_x, max_y, ppm].every(Number.isFinite)) return null;
  return min_x < max_x && min_y < max_y && ppm > 0 ? { min_x, min_y, max_x, max_y, ppm } : null;
}
// D-560 4: plane pixel (u, v) ↔ map metres, by scale and origin only.
export const planeToMap = (plane, u, v) => ({ x: plane.min_x + u / plane.ppm, y: plane.max_y - v / plane.ppm });
export const mapToPlane = (plane, x, y) => ({ u: (x - plane.min_x) * plane.ppm, v: (plane.max_y - y) * plane.ppm });
// The header rectangle must be the picture: within 1 px of the image size, else the plane is unusable.
export const planeFitsImage = (plane, width, height) =>
  Math.abs((plane.max_x - plane.min_x) * plane.ppm - width) <= 1
  && Math.abs((plane.max_y - plane.min_y) * plane.ppm - height) <= 1;

// Approved calibrations of ``source`` on a map of ``siteMap`` (anything with maps[].map_id).
export const planeCalibrationsFor = (calibrations, siteMap, source) => (calibrations || []).filter((row) =>
  row?.source_id === source && (siteMap?.maps || []).some((map) => map.map_id === row.map_id));
// D-560: a plane frame counts while fresh and while its revision is one of those calibrations.
export function planeCalibration(frame, calibrations, siteMap) {
  if (!frame?.calibrationRevision || !(frame.ageMs >= 0 && frame.ageMs <= FRAME_LATE_MS)) return null;
  return planeCalibrationsFor(calibrations, siteMap, frame.source)
    .find((row) => row.calibration_revision === frame.calibrationRevision) || null;
}

// One map-plane frame for ``source``. ``held`` is the previous result's lease, reused while valid.
// → { state: "live", plane, calibrationRevision, ageMs, blob, lease }
//   | { state: "plane-unavailable", lease } (409, an old Vision or Fleet that knows no map mode)
//   | { state: "error", status, lease }.  The caller falls back to its browser warp on plane-unavailable.
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
  const response = await fetch(path, {
    signal, credentials: "omit", redirect: "error", cache: "no-store",
    headers: { Authorization: `Bearer ${lease.lease}` },
  });
  if (response.status === 409 && response.headers.get("X-Frame-State") === "plane-unavailable") {
    return { state: "plane-unavailable", lease };
  }
  if (!response.ok) return { state: "error", status: response.status, lease: response.status === 401 || response.status === 403 ? null : lease };
  const plane = parsePlaneHeader(response.headers.get("X-Frame-Plane"));
  // A Vision without D-560 answers with its raw or corner preview; never draw that as the plane.
  if (response.headers.get("X-Frame-Rectified") !== "map" || !plane) return { state: "plane-unavailable", lease };
  const age = response.headers.get("X-Frame-Age-Ms");
  return { state: "live", plane, calibrationRevision: response.headers.get("X-Frame-Calibration"),
    ageMs: age === null ? NaN : Number(age), blob: await response.blob(), lease };
}

// 프레임 응답 → 배지. 배지는 화면에 보이는 영상의 실제 상태만 말한다(2026-09-30 태블릿 점검:
// 영상이 보이는데 "인증 대기"로 남던 결함). DOM 없는 순수 함수라 node 로 시험한다.
// { ok, status, frameState, ageMs, rectified } → { state, label, kind, detail }
// rectified 는 false | true | "auto"(D-484 필드 경계 자동 보정)다.
export function frameBadge({ ok, status, frameState, ageMs, rectified }) {
  if (ok) {
    const age = Number(ageMs);
    if (Number.isFinite(age) && age > FRAME_LATE_MS) {
      return { state: "stale", label: "영상 지연", kind: "warn",
        detail: `최신 프레임이 ${Math.round(age / 100) / 10} s 전 것입니다.` };
    }
    if (frameState === "field-unavailable") {
      return { state: "live", label: "자동 보정 대기", kind: "neutral",
        detail: "필드 경계를 아직 잡지 못해 원본을 보여 줍니다." };
    }
    const live = rectified === "auto" ? "자동 보정 미리보기"
      : rectified ? "화면 보정 미리보기" : "원본 최신 프레임";
    return { state: "live", label: live, kind: "good", detail: "" };
  }
  if (status === 401 || status === 403) {
    return { state: "unauthorized", label: "영상 권한 없음", kind: "warn",
      detail: "영상 사용 허가가 만료됐거나 거부됐습니다. 다시 요청합니다." };
  }
  if (frameState === "stale") {
    return { state: "stale", label: "영상 정지", kind: "warn",
      detail: "최신 프레임이 없어 영상 표시를 지웠습니다." };
  }
  if (status === 422) {
    return { state: "invalid", label: "보정값 확인", kind: "warn",
      detail: "보정값을 확인하세요. 모서리는 교차하지 않는 사각형이어야 합니다." };
  }
  return { state: "no-frame", label: "영상 수신 대기", kind: "neutral", detail: `Vision 응답 ${status}` };
}

// 화면 보정(D-318)은 렌즈마다 다르다. Vision 이 알려 준 렌즈(X-Source-Lens)로 저장 키를 나눈다.
// 렌즈를 알리지 않는 옛 앱은 예전 키(source 만)를 그대로 쓴다.
const RECTIFICATION_PREFIX = "rosy-camera-rectification:";
const LENS_NAMES = { wide: "초광각", standard: "기본 렌즈" };

// "kind=wide;focal_mm=2.2;hfov_deg=104.1" → { kind, focal_mm, hfov_deg } 또는 null.
export function parseLensHeader(value) {
  if (!value) return null;
  const fields = Object.fromEntries(value.split(";").map((part) => part.split("=").map((item) => item.trim())));
  if (!Object.hasOwn(LENS_NAMES, fields.kind)) return null;
  return { kind: fields.kind, focal_mm: Number(fields.focal_mm), hfov_deg: Number(fields.hfov_deg) };
}

export function rectificationKey(source, lensKind) {
  return lensKind ? `${RECTIFICATION_PREFIX}${source}@${lensKind}` : `${RECTIFICATION_PREFIX}${source}`;
}

// 저장된 보정값 찾기. 렌즈 이전의 예전 키는 기본 렌즈로 찍은 것이라 "standard" 로 복사한다.
// 예전 키는 지우지 않는다: 렌즈를 알리지 않는 옛 앱으로 되돌려도 그 값을 그대로 쓴다.
// 지금 렌즈의 값이 없고 다른 렌즈의 값만 있으면 적용하지 않고 경고를 돌려준다.
// → { saved: string|null, warning: string|null }
export function resolveSavedProfile(storage, source, lensKind) {
  const key = rectificationKey(source, lensKind);
  const legacyKey = rectificationKey(source, null);
  let saved = storage.getItem(key);
  if (lensKind && saved === null) {
    const legacy = storage.getItem(legacyKey);
    if (legacy !== null && lensKind === "standard") {
      storage.setItem(key, legacy);
      saved = legacy;
    }
  }
  if (!lensKind || saved !== null) return { saved, warning: null };
  const others = Object.keys(LENS_NAMES).filter((kind) => kind !== lensKind
    && storage.getItem(rectificationKey(source, kind)) !== null);
  if (storage.getItem(legacyKey) !== null && !others.includes("standard")) others.push("standard");
  if (!others.length) return { saved: null, warning: null };
  return { saved: null, warning: `저장한 화면 보정은 ${LENS_NAMES[others[0]]}용입니다. `
    + `지금 카메라는 ${LENS_NAMES[lensKind]}라 기본값으로 보여 줍니다. 이 렌즈에 맞게 다시 맞추세요.` };
}

// D-560: the latest map-plane picture for one screen. Call refresh() after each preview frame (with
// wanted = false when the screen has no calibration to draw it with). After plane-unavailable it asks
// again only PLANE_RETRY_MS later, so a Vision that cannot make a plane is a state, not an error loop.
// A transient error keeps the current frame until it expires and waits PLANE_ERROR_MS.
const PLANE_RETRY_MS = 30000;
const PLANE_ERROR_MS = 5000;
export function createPlaneFeed({ scope, visionView, onChange, now = Date.now }) {
  let frame = null, busy = false, retryAt = 0, cancelExpiry = () => {};
  function drop() {
    cancelExpiry();
    cancelExpiry = () => {};
    if (frame) URL.revokeObjectURL(frame.url);
    const had = Boolean(frame);
    frame = null;
    return had;
  }
  async function refresh(wanted = true) {
    if (!wanted) { if (drop()) onChange(); return; }
    if (busy || now() < retryAt) return;
    busy = true;
    const life = scope.capture();
    try {
      const got = await visionView.fetchPlane();
      if (got.state === "plane-unavailable") { retryAt = now() + PLANE_RETRY_MS; drop(); return; }
      if (got.state !== "live") { retryAt = now() + PLANE_ERROR_MS; return; }
      const url = URL.createObjectURL(got.blob);
      const image = new Image();
      image.src = url;
      const decoded = await image.decode().then(() => true, () => false);
      if (!life.current() || !decoded) { URL.revokeObjectURL(url); if (!decoded) retryAt = now() + PLANE_ERROR_MS; return; }
      if (!planeFitsImage(got.plane, image.naturalWidth, image.naturalHeight)) {
        URL.revokeObjectURL(url);
        retryAt = now() + PLANE_RETRY_MS;
        drop();
        return;
      }
      drop();
      frame = { image, url, source: got.source, plane: got.plane,
        calibrationRevision: got.calibrationRevision, ageMs: got.ageMs };
      cancelExpiry = scope.timeout(() => { drop(); onChange(); }, Math.max(0, FRAME_LATE_MS - got.ageMs) || 0);
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

// D-410 — 운용 화면(/console)에는 보정 칸이 없다. 없는 칸은 빈 상대로 둔다:
// 읽기는 비어 있고 쓰기는 무해하다. 보정 흐름 자체는 설치 화면에서만 열린다.
const absentPanel = () => ({
  open: false,
  hidden: true,
  textContent: "",
  querySelectorAll: () => [],
  addEventListener: () => {},
  removeEventListener: () => {},
  toggleAttribute: () => {},
  setAttribute: () => {},
});

export function createVisionView({ scope, el, call, isActive = () => true, rawOnly = false, onSources = () => {} }) {
  const select = el("vision-source");
  const frame = el("vision-frame");
  const stage = el("vision-image-stage");
  const image = el("vision-image");
  const cornerOverlay = el("vision-corner-overlay");
  const cornerPolygon = el("vision-corner-polygon");
  const cornerHandles = [...cornerOverlay.querySelectorAll("[data-corner-handle]")];
  const status = el("vision-state");
  const message = el("vision-message");
  const adjustments = el("vision-adjustments") || absentPanel();
  const profileFields = [...adjustments.querySelectorAll("[data-rect]")];
  const cornerFields = [...adjustments.querySelectorAll("[data-corner]")];
  const profileFieldsets = [...adjustments.querySelectorAll("fieldset")];
  const cornerModes = el("vision-corner-modes") || absentPanel();
  const cornerHint = el("vision-corner-hint") || absentPanel();
  const adjustmentState = el("vision-adjustment-state") || absentPanel();
  let lease = null;
  let leaseExpiresAt = 0;
  let planeLease = null;
  let objectUrl = null;
  let busy = false;
  let previewLifetime = new AbortController();
  let lastSourcesAt = 0;
  let refreshTimer = null;
  let viewMode = rawOnly ? "raw" : "adjusted";
  let draggingPointerId = null;
  // D-360: 검토 중인 경기장 제안(정규 좌표 네 점). 수락 전에는 조정값에 들어가지 않는다.
  let proposalCorners = null;
  // 선택한 source 가 마지막 프레임에서 알린 렌즈 종류(wide/standard). 옛 앱이면 null.
  let currentLens = null;
  let currentLensInfo = null;
  const proposalPolygon = el("vision-proposal-polygon");
  const frameListeners = [];
  function pausePreview() {
    previewLifetime.abort(); previewLifetime = new AbortController();
    if (busy?.kind === "frame") busy = false;
  }
  scope.onDispose(() => {
    pausePreview();
    busy = false;
    refreshTimer?.();
    refreshTimer = null;
    lease = null;
    leaseExpiresAt = 0;
    draggingPointerId = null;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  });

  function showState(label, kind = "neutral", detail = label) {
    status.textContent = label;
    status.setAttribute("status", kind);
    message.textContent = detail;
    image.hidden = true;
    stage.hidden = true;
    cornerOverlay.toggleAttribute("hidden", true);
    frame.dataset.state = kind;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }

  function readProfile() {
    // 운용 프리뷰 모드(칸 없음)에서는 저장 전 기본값만이 참이다.
    if (!cornerFields.length || !profileFields.length) return { ...DEFAULT_RECTIFICATION };
    const profile = { ...DEFAULT_RECTIFICATION };
    for (const field of profileFields) profile[field.dataset.rect] = Number(field.value);
    profile.corners = Array.from({ length: 4 }, (_, index) =>
      Array.from({ length: 2 }, (_, axis) => {
        const input = cornerFields.find((item) => Number(item.dataset.corner) === index
          && Number(item.dataset.axis) === axis);
        return Number(input.value) / 100;
      }));
    return profile;
  }

  function writeProfile(profile) {
    for (const field of profileFields) {
      field.value = String(profile[field.dataset.rect] ?? DEFAULT_RECTIFICATION[field.dataset.rect]);
    }
    for (const field of cornerFields) {
      field.value = formatPercent(100 * (profile.corners?.[Number(field.dataset.corner)]?.[Number(field.dataset.axis)]
        ?? DEFAULT_RECTIFICATION.corners[Number(field.dataset.corner)][Number(field.dataset.axis)]));
    }
    updateCornerOverlay();
  }

  function formatPercent(value) {
    const rounded = Math.round(value * 10) / 10;
    return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  }

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
    const width = image.naturalWidth;
    const height = image.naturalHeight;
    const viewHeight = width && height ? 100 * height / width : 75;
    cornerOverlay.setAttribute("viewBox", `0 0 100 ${viewHeight}`);
    const stageWidth = stage.getBoundingClientRect().width;
    const radius = stageWidth ? Math.max(3, Math.min(8, 2200 / stageWidth)) : 7;
    const points = readProfile().corners.map(([x, y]) => [x * 100, y * viewHeight]);
    cornerPolygon.setAttribute("points", points.map(([x, y]) => `${x},${y}`).join(" "));
    proposalPolygon.toggleAttribute("hidden", !proposalCorners);
    if (proposalCorners) {
      proposalPolygon.setAttribute("points",
        proposalCorners.map(([x, y]) => `${x * 100},${y * viewHeight}`).join(" "));
    }
    const names = ["왼쪽 위", "오른쪽 위", "오른쪽 아래", "왼쪽 아래"];
    cornerHandles.forEach((handle, index) => {
      const [x, y] = points[index];
      handle.setAttribute("cx", String(x));
      handle.setAttribute("cy", String(y));
      handle.setAttribute("r", String(radius));
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
      const field = cornerFields.find((item) => Number(item.dataset.corner) === index
        && Number(item.dataset.axis) === axis);
      field.value = formatPercent(coordinates[axis]);
    }
    updateCornerOverlay();
    saveDraft({ announce });
  }

  function selectViewMode(mode) {
    viewMode = mode;
    const editing = mode === "raw";
    frame.dataset.editing = String(editing);
    el("vision-edit-corners").setAttribute("aria-pressed", String(editing));
    el("vision-preview-adjusted").setAttribute("aria-pressed", String(mode === "adjusted"));
    const autoButton = el("vision-preview-auto");
    if (autoButton) autoButton.setAttribute("aria-pressed", String(mode === "auto"));
    cornerHint.hidden = !editing;
    cornerOverlay.toggleAttribute("hidden", !editing);
    lease = null;
    leaseExpiresAt = 0;
    if (editing) adjustmentState.textContent = "원본에서 영역을 조정 중입니다. 끝나면 보정 결과를 확인하세요.";
    if (mode === "auto") adjustmentState.textContent = "필드 경계 캘리브레이션이 잡은 모서리로 자동 보정합니다. 감지가 없으면 원본을 보여 줍니다.";
    refreshFrame();
  }

  function loadProfile(source) {
    let profile = DEFAULT_RECTIFICATION;
    try {
      const { saved, warning } = source ? resolveSavedProfile(localStorage, source, currentLens)
        : { saved: null, warning: null };
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
    // 다른 요청이 진행 중이면 보이던 영상을 그대로 둔다.
    if (busy) return;
    const work = {kind: "sources"}; busy = work;
    try {
      const result = await call("/api/fleet/vision/sources");
      life.check();
      onSources({ finished: true, status: 200, names: result.sources });
      const selected = select.value;
      select.replaceChildren(...result.sources.map((source) => {
        const option = document.createElement("option");
        option.value = source;
        option.textContent = source;
        return option;
      }));
      if (result.sources.includes(selected)) select.value = selected;
      else if (result.sources.length) select.value = result.sources[0];
      select.disabled = result.sources.length === 0;
      loadProfile(select.value);
      lastSourcesAt = Date.now();
      lease = null;
      if (!result.sources.length) {
        loadProfile("");
        showState("카메라 없음", "warn", "Vision에 등록된 카메라가 없습니다.");
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      if (typeof error.status === "number") onSources({ finished: true, status: error.status, names: [] });
      else onSources({ finished: false });
      lastSourcesAt = Date.now();
      showState("영상 연결 불가", "warn", error.message);
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
    if (!source) return;
    const work = {kind: "frame"}; busy = work;
    try {
      if (!lease || Date.now() >= leaseExpiresAt) {
        const issued = await call("/api/fleet/vision/lease", {
          method: "POST",
          signals: [preview.signal],
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_id: source,
            rectification: viewMode === "raw" ? DEFAULT_RECTIFICATION
              : viewMode === "auto" ? AUTO_RECTIFICATION : readProfile(),
          }),
        });
        life.check();
        if (!current() || source !== select.value) return;
        lease = issued;
        leaseExpiresAt = Date.now() + 45000;
      }
      if (!current()) return;
      const response = await fetch(lease.frame_path, {
        signal: AbortSignal.any([life.signal, preview.signal]), credentials: "omit", redirect: "error",
        headers: { Authorization: `Bearer ${lease.lease}` },
        cache: "no-store",
      });
      life.check();
      if (!current() || source !== select.value) return;
      const lens = parseLensHeader(response.headers.get("X-Source-Lens"));
      if (response.ok) currentLensInfo = lens;
      if (response.ok && (lens?.kind ?? null) !== currentLens) {
        // 렌즈가 바뀌면 그 렌즈의 보정값으로 바꾸고, 다음 프레임부터 새 값으로 요청한다.
        currentLens = lens?.kind ?? null;
        loadProfile(source);
        lease = null;
      }
      const rectifiedHeader = response.headers.get("X-Frame-Rectified");
      const rectified = rectifiedHeader === "true" || rectifiedHeader === "auto";
      const badge = frameBadge({
        ok: response.ok, status: response.status,
        rectified: rectifiedHeader === "auto" ? "auto" : rectified,
        frameState: response.headers.get("X-Frame-State"),
        ageMs: response.headers.get("X-Frame-Age-Ms"),
      });
      if (!response.ok) {
        if (badge.state === "unauthorized") lease = null;
        showState(badge.label, badge.kind, badge.detail);
        return;
      }
      const blob = await response.blob();
      life.check();
      if (!current() || source !== select.value) return;
      const nextUrl = URL.createObjectURL(blob);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = nextUrl;
      // 배지를 영상과 같은 순간에 바꾼다 — decode 를 기다리는 동안 옛 배지가 남지 않게.
      status.textContent = badge.label;
      status.setAttribute("status", badge.kind);
      message.textContent = badge.detail;
      image.src = nextUrl;
      image.hidden = false;
      stage.hidden = false;
      await image.decode().catch(() => {});
      life.check();
      if (!current() || source !== select.value) return;
      updateCornerOverlay();
      frame.dataset.state = "online";
      frame.dataset.editing = String(viewMode === "raw" && !rawOnly);
      cornerOverlay.toggleAttribute("hidden", viewMode !== "raw" || rawOnly);
      el("vision-meta").textContent = `${new Date().toLocaleTimeString("ko-KR", { hour12: false })} · ${source} · sequence ${response.headers.get("X-Frame-Seq") || "?"} · age ${response.headers.get("X-Frame-Age-Ms") || "?"} ms · ${rectified ? "화면 보정" : "원본"}${lens ? ` · ${LENS_NAMES[lens.kind]} ${lens.focal_mm} mm` : ""}`;
      const seq = response.headers.get("X-Frame-Seq");
      const frameAge = response.headers.get("X-Frame-Age-Ms");
      for (const listener of frameListeners) listener({ image, rectified, source, seq, url: nextUrl,
        lens: currentLensInfo, ageMs: frameAge === null ? NaN : Number(frameAge), state: badge.state });
    } catch (error) {
      if (error.name === "AbortError" || !current()) return;
      lease = null;
      showState("영상 정지", "warn", error.message || "Vision에 연결할 수 없습니다.");
    } finally {
      if (life.current() && busy === work) busy = false;
    }
  }

  function reset() {
    planeLease = null;
    currentLens = null;
    currentLensInfo = null;
    lease = null;
    leaseExpiresAt = 0;
    lastSourcesAt = 0;
    proposalCorners = null;
    select.replaceChildren();
    select.disabled = true;
    loadProfile("");
    showState("인증 대기", "neutral", NO_SOURCE);
  }

  scope.listen(select, "change", () => {
    lease = null;
    planeLease = null;
    proposalCorners = null;
    currentLens = null;
    currentLensInfo = null;
    loadProfile(select.value);
    showState("카메라 전환", "neutral", "선택한 영상의 최신 프레임을 기다립니다.");
    refreshFrame();
  });
  scope.listen(adjustments, "toggle", () => {
    cornerModes.hidden = !adjustments.open || !select.value;
  });
  scope.listen(window, "resize", updateCornerOverlay);
  scope.listen(el("vision-edit-corners"), "click", () => selectViewMode("raw"));
  scope.listen(el("vision-preview-adjusted"), "click", () => selectViewMode("adjusted"));
  scope.listen(el("vision-preview-auto"), "click", () => selectViewMode("auto"));
  for (const handle of cornerHandles) {
    scope.listen(handle, "pointerdown", (event) => {
      if (viewMode !== "raw" || !event.isPrimary) return;
      event.preventDefault();
      draggingPointerId = event.pointerId;
      handle.setPointerCapture(event.pointerId);
      const box = stage.getBoundingClientRect();
      if (box.width && box.height) {
        setCorner(Number(handle.dataset.cornerHandle),
          (event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height);
      }
    });
    scope.listen(handle, "pointermove", (event) => {
      if (viewMode !== "raw" || event.pointerId !== draggingPointerId) return;
      const box = stage.getBoundingClientRect();
      if (box.width && box.height) {
        setCorner(Number(handle.dataset.cornerHandle),
          (event.clientX - box.left) / box.width, (event.clientY - box.top) / box.height);
      }
    });
    const stopDrag = (event) => {
      if (event.pointerId !== draggingPointerId) return;
      draggingPointerId = null;
      saveDraft();
    };
    scope.listen(handle, "pointerup", stopDrag);
    scope.listen(handle, "pointercancel", stopDrag);
    scope.listen(handle, "keydown", (event) => {
      if (viewMode !== "raw") return;
      const movement = {
        ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
      }[event.key];
      if (!movement) return;
      event.preventDefault();
      const step = event.shiftKey ? 0.1 : 1;
      const index = Number(handle.dataset.cornerHandle);
      const profile = readProfile();
      setCorner(index, profile.corners[index][0] + movement[0] * step / 100,
        profile.corners[index][1] + movement[1] * step / 100, { announce: true });
    });
  }
  for (const field of [...profileFields, ...cornerFields]) {
    scope.listen(field, "input", () => {
      if (!field.reportValidity()) return;
      const source = select.value;
      if (!source) return;
      const profile = readProfile();
      updateCornerOverlay();
      try {
        localStorage.setItem(rectificationKey(source, currentLens), JSON.stringify(profile));
        adjustmentState.textContent = "조정값을 이 브라우저에 저장했습니다.";
      } catch {
        adjustmentState.textContent = "브라우저 저장을 사용할 수 없습니다. 이 화면에서만 적용됩니다.";
      }
      lease = null;
      refreshTimer?.();
      if (viewMode === "raw") {
        adjustmentState.textContent = "원본에서 영역을 조정 중입니다. 끝나면 보정 결과를 확인하세요.";
      } else {
        adjustmentState.textContent += " 미리보기를 갱신합니다.";
        refreshTimer = scope.timeout(() => refreshFrame(), 450);
      }
    });
  }
  scope.listen(el("vision-reset-adjustments"), "click", () => {
    const source = select.value;
    if (source) localStorage.removeItem(rectificationKey(source, currentLens));
    loadProfile(source);
    adjustmentState.textContent = "기본 조정값으로 초기화했습니다.";
    lease = null;
    refreshFrame();
  });
  scope.listen(el("vision-refresh"), "click", () => {
    lease = null;
    const life = scope.capture();
    return refreshSources().then(() => { life.check(); return refreshFrame(); });
  });
  // D-360: Vision 제안은 frame 과 같은 lease 로 same-origin 에서 읽는다. Fleet 은 중계하지 않는다.
  // D-375 지도 맞춤(map-proposal)도 같은 lease·같은 규칙이다.
  async function fetchFieldProposal(view = "field-proposal") {
    const life = scope.capture();
    life.check();
    const source = select.value;
    if (!source) throw new Error("카메라를 먼저 선택하세요.");
    if (!lease || Date.now() >= leaseExpiresAt) {
      const issued = await call("/api/fleet/vision/lease", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_id: source,
          rectification: viewMode === "raw" ? DEFAULT_RECTIFICATION : readProfile(),
        }),
      });
      life.check();
      lease = issued;
      leaseExpiresAt = Date.now() + 45000;
    }
    const path = lease.frame_path.replace(/\/frame$/, `/${view}`);
    const response = await fetch(path, {
      signal: life.signal, credentials: "omit", redirect: "error",
      headers: { Authorization: `Bearer ${lease.lease}` }, cache: "no-store",
    });
    life.check();
    if (response.status === 404 && view === "map-proposal" && !response.headers.get("X-Frame-State")) {
      const text = await response.text().catch(() => "");
      life.check();
      if (text.includes("not configured")) {
        throw new Error("Vision에 차선 페인트 지도가 설정되지 않았습니다(vision --map-paint).");
      }
      throw new Error("최신 프레임이 없어 맞출 수 없습니다.");
    }
    if (response.status === 429) {
      // 속도 제한·계산 중. 지도 맞춤은 이 표시로 Retry-After 뒤 다시 묻는다(오류로 보이지 않는다).
      const error = new Error("잠시 뒤 다시 찾으세요(초당 1회).");
      error.busy = true;
      error.retryAfterMs = 1000 * (Number(response.headers.get("Retry-After")) || 1);
      throw error;
    }
    if (response.status === 422) throw new Error("프레임을 해석하지 못했습니다. 잠시 뒤 다시 찾으세요.");
    if (!response.ok) {
      throw new Error(response.headers.get("X-Frame-State") === "stale"
        ? "최신 프레임이 없어 찾을 수 없습니다." : `Vision 응답 ${response.status}`);
    }
    // D-375: "previous" 는 계산 중이라 돌려준 지난 결과다. 지도 맞춤은 이것을 수락하게 하지 않는다.
    const body = await response.json();
    life.check();
    return { source, body, proposalState: response.headers.get("X-Proposal-State") };
  }

  // 제안을 원본 위 점선 사각형으로 보여 준다. 검토하려면 원본 조정 화면으로 바꾼다.
  function showProposal(corners) {
    proposalCorners = corners;
    if (corners && viewMode !== "raw") selectViewMode("raw");
    else updateCornerOverlay();
  }

  // 운영자가 수락한 모서리만 D-318 브라우저 로컬 초안이 된다.
  function acceptCorners(corners) {
    corners.forEach(([x, y], index) => setCorner(index, x, y));
    proposalCorners = null;
    saveDraft();
    updateCornerOverlay();
  }

  return {
    refreshSources, refreshFrame, reset, pausePreview, fetchFieldProposal, showProposal, acceptCorners,
    fetchMapProposal: () => fetchFieldProposal("map-proposal"),
    // 지도 맞춤 행렬은 원본 프레임 픽셀 기준이라 화면 보정 미리보기에서는 원본으로 바꾼다.
    showRaw: () => { if (viewMode !== "raw") selectViewMode("raw"); },
    // D-560: the map plane for the selected source on its own lease (the preview lease keeps its mode).
    async fetchPlane() {
      const source = select.value;
      if (!source) return { state: "no-source" };
      const life = scope.capture();
      const got = await fetchMapPlane(call, source, planeLease, life.signal);
      life.check();
      planeLease = got.lease;
      return { ...got, source };
    },
    currentSource: () => select.value,
    currentLensInfo: () => currentLensInfo,
    currentCorners: () => readProfile().corners,
    onFrame(listener) {
      frameListeners.push(listener);
      return () => {
        const index = frameListeners.indexOf(listener);
        if (index >= 0) frameListeners.splice(index, 1);
      };
    },
  };
}
