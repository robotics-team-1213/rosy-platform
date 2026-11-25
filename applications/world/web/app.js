import { showCad, showCell, showFieldPlane, showMap } from "./scene.js";
import { initFactoryTab } from "./factory-live.js";
import { initLiveFeeds, isLayoutSha } from "./live-feeds.js";
import { activeSiteMap } from "./active-site-map.js";

const byId = (id) => document.getElementById(id);
const status = (id, state, text) => {
  const element = byId(id);
  if (element.getAttribute("state") !== state) element.setAttribute("state", state);
  if (element.textContent !== text) element.textContent = text;
};
const date = (value) => {
  if (!Number.isFinite(value) && typeof value !== "string") return "확인되지 않음";
  const timestamp = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isFinite(timestamp.getTime()) ? timestamp.toISOString() : "확인되지 않음";
};
const text = (value) => typeof value === "string" && value.trim().length > 0;
const captureClock = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "medium", timeStyle: "medium", timeZone: "Asia/Seoul",
});
const xy = (values) => Array.isArray(values) && values.length >= 2 &&
  Number.isFinite(values[0]) && Number.isFinite(values[1]);

function readout(id, entries) {
  const element = byId(id);
  element.replaceChildren(...entries.flatMap(([name, value]) => {
    const term = document.createElement("dt");
    const details = document.createElement("dd");
    term.textContent = name;
    details.textContent = value;
    return [term, details];
  }));
  element.hidden = false;
}

async function readJson(name) {
  const response = await fetch(`./data/${name}.json`);
  if (!response.ok) throw new Error(`Cannot read ${name} (${response.status})`);
  return response.json();
}

function mapData(envelope) {
  const map = envelope?.map;
  const locations = map?.places ?? map?.nodes;
  if (!text(map?.map_id) || !Array.isArray(locations) || !Array.isArray(map.edges)) {
    throw new Error("Invalid site map");
  }
  const places = locations.filter((place) => place && xy([place.x, place.y]));
  const edges = map.edges.map((edge) => edge?.polyline).filter((line) =>
    Array.isArray(line) && line.length >= 2 && line.every(xy));
  if (!(places.length || edges.length)) throw new Error("Site map contains no geometry");
  return { id: map.map_id, version: envelope.version, places, edges };
}

function recordingData(recording) {
  if (recording?.schema !== "rosy.world.recording.v1" || !text(recording.source) ||
      !Number.isSafeInteger(recording.map_version) || recording.map_version < 1 ||
      !text(recording.captured_at) || !Number.isFinite(Date.parse(recording.captured_at)) ||
      !Array.isArray(recording.samples) || recording.samples.length === 0) {
    throw new Error("Invalid recording header");
  }
  let previous = -1;
  for (const sample of recording.samples) {
    if (!Number.isFinite(sample?.offset_ms) || sample.offset_ms < 0 ||
        sample.offset_ms < previous || !text(sample.frame_id) || !Array.isArray(sample.positions) ||
        !sample.positions.every((position) => position && text(position.id) &&
          Number.isFinite(position.x_m) && Number.isFinite(position.y_m))) {
      throw new Error("Invalid recording sample");
    }
    previous = sample.offset_ms;
  }
  return recording;
}

const tabs = [...document.querySelectorAll('[role="tab"]')];
const viewParam = new URLSearchParams(location.search).get("view");
const directRun = viewParam === "run";
const directFactory = viewParam === "factory";
const directR08 = viewParam === "r08";
let cellLoad;
let factoryTab;
let userPickedTab = false;
let liveFeeds;
let syncActiveMapPoll;
function activate(tab) {
  for (const item of tabs) {
    item.setAttribute("aria-selected", String(item === tab));
    item.tabIndex = item === tab ? 0 : -1;
    byId(item.getAttribute("aria-controls")).hidden = item !== tab;
  }
  document.querySelector(".world-health").hidden = tab.id !== "tab-map";
  if (tab.id === "tab-factory") void factoryTab?.activate();
  else factoryTab?.deactivate();
  if (tab.id === "tab-cell") cellLoad ??= loadCell();
  syncActiveMapPoll?.();
  if (liveFeeds) {
    if (tab.id === "tab-map") {
      liveFeeds.startPinkySim();
      liveFeeds.startPinkyCamera();
    } else {
      liveFeeds.stopPinkySim();
      liveFeeds.stopPinkyCamera();
    }
  }
}
await customElements.whenDefined("ui-button");
if (directFactory) byId("tab-factory").hidden = false;
activate(directRun ? byId("tab-rec") : directFactory ? byId("tab-factory") : byId("tab-map"));
tabs.forEach((tab) => {
  tab.addEventListener("click", () => { userPickedTab = true; activate(tab); });
  tab.addEventListener("keydown", (event) => {
    const visibleTabs = tabs.filter((item) => !item.hidden);
    const cur = visibleTabs.indexOf(tab);
    const keys = {
      ArrowLeft: (cur + visibleTabs.length - 1) % visibleTabs.length,
      ArrowRight: (cur + 1) % visibleTabs.length,
      Home: 0,
      End: visibleTabs.length - 1,
    };
    if (!Object.hasOwn(keys, event.key)) return;
    event.preventDefault();
    userPickedTab = true;
    const next = visibleTabs[keys[event.key]];
    activate(next);
    next.focus();
  });
});
byId("btn-theme").addEventListener("click", () => {
  window.RosyTheme.set(window.RosyTheme.resolved() === "dark" ? "light" : "dark");
});

let vectorAvailable = false;
let birdviewAvailable = false;
let imageFailed = false;
let cadFailed = false;
let cadView;
let fieldView;
let cadPreset = "top";
let choseMapMode = false;
let mode = "vector";
let archivedMapReadout;
let archiveMapUnavailable = false;
const activeMapCanvas = byId("map-active-canvas");
const activeMap = activeSiteMap({
  canvas: activeMapCanvas, showMap, mapData, date,
  onUpdate() {
    if (mode !== "active") return;
    showMapSource();
    updateMapHealth();
  },
});
const activeMapLabel = () => ({
  ready: "Fleet 활성 지도",
  unavailable: "현장 활성 지도 미수신",
  pending: "현장 활성 지도를 읽는 중…",
})[activeMap.state];
syncActiveMapPoll = () => activeMap.watch(mode === "active" &&
  byId("tab-map").getAttribute("aria-selected") === "true");

function showMapSource() {
  const active = mode === "active";
  const entries = active ? activeMap.entries : archivedMapReadout;
  byId("map-readout").hidden = !entries;
  if (entries) readout("map-readout", entries);
  if (active) {
    status("map-status", activeMap.state, activeMapLabel());
  } else {
    status("map-status", vectorAvailable ? "ready" : archiveMapUnavailable ? "unavailable" : "pending",
      vectorAvailable ? "보관 지도" : archiveMapUnavailable ? "보관 차로 그래프를 그릴 수 없습니다" : "보관 지도를 읽는 중…");
  }
  activeMapCanvas.hidden = !active || !activeMap.entries;
}

function updateMapHealth() {
  const states = {
    active: [activeMap.state, `지도 · ${activeMapLabel()}`],
    vector: vectorAvailable ? ["ready", "지도 · 보관 차로 그래프"] : ["pending", "지도 · 불러오는 중"],
    birdview: ["ready", "지도 · 보관 버드뷰"],
    field: ["ready", "지도 · Rosy Cam 현장 사진"],
    image: imageFailed ? ["unavailable", "지도 · 자료 없음"] : ["ready", "지도 · 보관 이미지"],
    cad: cadView ? ["ready", designActive ? "3D · R08 CAD194 표시 중" : "3D · 보관 CAD 표시 중"]
      : ["pending", "3D · 보관 CAD 불러오는 중"],
  };
  status("view-health", ...states[mode]);
}
function mapMode(next) {
  mode = next;
  byId("map-canvas").hidden = mode !== "vector";
  byId("map-birdview-figure").hidden = mode !== "birdview";
  byId("map-field-figure").hidden = mode !== "field";
  if (mode === "field") fieldView?.redraw();
  byId("map-image-figure").hidden = mode !== "image" || imageFailed;
  byId("map-empty").hidden = mode !== "image" || !imageFailed;
  byId("map-provenance").hidden = ["cad", "birdview", "field"].includes(mode);
  byId("map-alignment-note").hidden = ["active", "cad", "birdview", "field"].includes(mode);
  byId("map-cad-canvas").hidden = mode !== "cad";
  byId("map-cad-controls").hidden = mode !== "cad" || !cadView;
  byId("map-cad-focus").hidden = mode !== "cad" || !cadView?.focus.stations;
  byId("cad-registration").hidden = mode !== "cad" || !cadView || !designAvailable;
  byId("map-cad-status").hidden = !(mode === "cad" && !cadView) && !(cadFailed && ["image", "birdview"].includes(mode));
  for (const view of ["active", "field", "birdview", "vector", "image", "cad"]) {
    byId(`map-mode-${view}`).setAttribute("aria-pressed", String(mode === view));
  }
  if (mode === "cad") liveFeeds?.startPinkySim();
  else liveFeeds?.stopPinkySim();
  showMapSource();
  syncActiveMapPoll();
  updateMapHealth();
}
function chooseMapMode(view) {
  choseMapMode = true;
  mapMode(view);
}
const birdviewButton = byId("map-mode-birdview");
birdviewButton.addEventListener("click", () => chooseMapMode("birdview"));
byId("map-mode-active").addEventListener("click", () => chooseMapMode("active"));
byId("map-mode-vector").addEventListener("click", () => { if (vectorAvailable) chooseMapMode("vector"); });
byId("map-mode-image").addEventListener("click", () => chooseMapMode("image"));
const image = byId("map-image");
function archiveImageFailed() {
  imageFailed = true;
  if (mode === "image") mapMode("image");
}
image.addEventListener("error", archiveImageFailed);
if (image.complete && !image.naturalWidth) archiveImageFailed();
function mapFallback() {
  vectorAvailable = false;
  archiveMapUnavailable = true;
  byId("map-mode-vector").hidden = true;
  if (mode === "vector") mapMode(birdviewAvailable ? "birdview" : "image");
  if (mode !== "active") status("map-status", "unavailable", "벡터 지도를 그릴 수 없어 보관 이미지를 표시합니다.");
}
const mapPromise = (async () => {
  let map;
  try {
    const envelope = await readJson("site-map");
    map = mapData(envelope);
    archivedMapReadout = [
      ["출처", "Fleet 활성 지도 보관본"],
      ["지도 ID", map.id],
      ["버전", map.version ?? "확인되지 않음"],
      ["활성 시각 (UTC)", date(envelope.activated_at)],
    ];
    if (mode !== "active") showMapSource();
  } catch {
    mapFallback();
    return null;
  }
  try {
    await showMap(byId("map-canvas"), map, mapFallback);
    vectorAvailable = true;
    if (mode !== "active") {
      showMapSource();
      updateMapHealth();
    }
  } catch {
    mapFallback();
  }
  return map;
})();

const CAD_PATH = "data/site-cad.stl.gz";
const REGISTRATION_PATH = "data/site-registration.json";
const BIRDVIEW_PATH = "data/site-birdview.jpg";
const manifestRead = fetch("./manifest.json", { redirect: "error" })
  .then((response) => response.ok && response.json()).catch(() => null);
function equipmentUrl(manifest, kind) {
  const path = `data/${kind}-equipment.json.gz`;
  return manifest?.equipment?.[kind]?.bundle_path === path ? `./${path}` : undefined;
}
const cadButton = byId("map-mode-cad");
const cadCanvas = byId("map-cad-canvas");
const designButton = byId("cad-design");
const designStatus = byId("cad-design-status");
let designAvailable = false;
let designActive = false;
let designBusy = false;
let designSource;
async function readDesignSource() {
  const [manifest, map, report] = await Promise.all([manifestRead, mapPromise, readJson("site-registration")]);
  const bundle = report.bundle;
  const transform = report.site_from_cell;
  const translation = transform?.translation_m;
  if (report.schema !== "rosy.world.registration-check.v1" || report.basis !== "archived-cad" ||
      report.status !== "candidate" || report.use !== "display-only" || !map ||
      bundle?.site_map_id !== map.id || bundle.site_map_version !== map.version ||
      bundle.site_map_sha256 !== manifest.inputs["site-map/world_261026_v7_active.json"]?.sha256 ||
      bundle.site_cad_sha256 !== manifest.site_cad.source_sha256 ||
      bundle.cell_model_sha256 !== manifest.equipment.cell.source_sha256 ||
      !/^[a-f0-9]{64}$/.test(bundle.cell_layout_sha256) || !Number.isFinite(transform?.yaw_rad) ||
      !Array.isArray(translation) || translation.length !== 3 ||
      !translation.every((coordinate) => Number.isFinite(coordinate) && Math.abs(coordinate) < 5)) {
    throw new Error("Registration does not match the archived CAD and R08 cell");
  }
  return { transform, layoutHash: bundle.cell_layout_sha256, url: equipmentUrl(manifest, "cell") };
}
designButton.addEventListener("click", async () => {
  if (!cadView || designBusy) return;
  designBusy = true;
  if (!designSource) designStatus.textContent = "R08 설계 배치를 읽는 중…";
  try {
    designSource ??= await readDesignSource();
    await cadView.setDesign(!designActive, designSource);
    designActive = !designActive;
    updateMapHealth();
    designButton.setAttribute("aria-pressed", String(designActive));
    designStatus.textContent = designActive
      ? "R08 표시 중 · 보관 CAD 상판 기준 · 최신 현장 정합 미확인"
      : "보관 CAD 상판 기준 · 최신 현장 정합 미확인";
  } catch {
    designStatus.textContent = "R08 설계 배치를 열 수 없습니다. 보관 CAD를 표시합니다.";
  } finally {
    designBusy = false;
  }
});
let cad;
for (const view of ["top", "iso"]) {
  byId(`cad-view-${view}`).addEventListener("click", () => {
    cadPreset = view;
    cadView?.select(view);
    for (const option of ["top", "iso"]) {
      byId(`cad-view-${option}`).setAttribute("aria-pressed", String(option === view));
    }
  });
}
const cadRegions = ["all", "stations", "pinky", "omx"];
for (const region of cadRegions) {
  byId(`cad-focus-${region}`).addEventListener("click", () => {
    if (!cadView) return;
    cadView.select(cadPreset, cadView.focus[region] ?? null);
    for (const option of cadRegions) {
      byId(`cad-focus-${option}`).setAttribute("aria-pressed", String(option === region));
    }
  });
}
byId("cad-open-cell").addEventListener("click", () => {
  const tab = byId("tab-cell");
  activate(tab);
  tab.focus();
});
function cadFallback() {
  const restoreFocus = document.activeElement === cadButton || document.activeElement === cadCanvas;
  cadFailed = true;
  cadButton.hidden = true;
  status("map-cad-status", "unavailable", "CAD 3D를 표시할 수 없습니다. 보관 이미지를 확인하세요.");
  if (mode === "cad") mapMode(birdviewAvailable ? "birdview" : "image");
  if (restoreFocus) byId(`map-mode-${birdviewAvailable ? "birdview" : "image"}`).focus();
}
cadButton.addEventListener("click", () => {
  chooseMapMode("cad");
  if (cad) return;
  status("map-cad-status", "pending", "CAD 3D를 읽는 중…");
  cad = manifestRead.then((manifest) => {
    const equipment = equipmentUrl(manifest, "site");
    designAvailable = !manifest?.site_map_override && !!equipmentUrl(manifest, "cell") &&
      manifest?.equipment?.registration?.bundle_path === REGISTRATION_PATH;
    byId("site-equipment-note").hidden = !equipment;
    return showCad(cadCanvas, `./${CAD_PATH}`, cadFallback, equipment);
  })
    .then((selectView) => {
      cadView = selectView;
      mapMode(mode);
      if (directR08 && mode === "cad" && designAvailable && !designActive) designButton.click();
    })
    .catch(cadFallback);
});
factoryTab = initFactoryTab({
  manifestRead, readDesignSource, showCad, equipmentUrl, CAD_PATH, REGISTRATION_PATH,
});
if (directFactory) void factoryTab.activate();
manifestRead
  .then((manifest) => {
    if (manifest?.factory_timeline?.bundle_path) {
      byId("tab-factory").hidden = false;
      if (!viewParam && !userPickedTab) activate(byId("tab-factory"));
    }
    cadButton.hidden = manifest?.site_cad?.bundle_path !== CAD_PATH;
    if (directR08 && !cadButton.hidden && !choseMapMode) cadButton.click();
    const birdview = manifest?.site_birdview;
    if (birdview?.bundle_path !== BIRDVIEW_PATH) return;
    const photo = new Image();
    photo.id = "map-birdview";
    photo.alt = "보정된 ROSY 현장 천장 사진. 아래는 순환 차로, 왼쪽 위는 주차 칸, 오른쪽은 노란 OMX 작업대와 컨베이어.";
    photo.addEventListener("load", () => {
      byId("map-birdview-figure").prepend(photo);
      if (Number.isFinite(Date.parse(birdview.captured_at))) {
        const captured = captureClock.format(new Date(birdview.captured_at));
        byId("map-birdview-caption").textContent = `Rosy Cam · ${captured} KST · 지도 평면 보정`;
      }
      birdviewAvailable = true;
      birdviewButton.hidden = false;
      if (!choseMapMode && !manifest.site_map_override && !manifest.field_photo && !manifest.field_original) mapMode("birdview");
    }, { once: true });
    photo.src = `./${BIRDVIEW_PATH}`;
  })
  .catch(() => {});

const fieldButton = byId("map-mode-field");
const fieldPhoto = byId("map-field-photo");
const correctedPhoto = byId("map-field-corrected");
const fieldOrbit = byId("map-field-orbit");
const fieldCanvas = byId("map-field-plane");
fieldButton.addEventListener("click", () => chooseMapMode("field"));
manifestRead.then(async (manifest) => {
  const original = manifest?.field_original;
  const photo = manifest?.field_photo;
  const corrected = photo?.bundle_path === "data/field-photo.jpg" && Array.isArray(photo.plane)
    && photo.plane.length === 5 && photo.plane.every(Number.isFinite);
  async function loadPhoto(metadata, imgEl, expectedPath) {
    if (metadata?.bundle_path !== expectedPath || !Number.isFinite(Date.parse(metadata.captured_at))) return false;
    imgEl.src = `./${expectedPath}`;
    return imgEl.decode().then(() => true, () => false);
  }
  const [hasOriginal, hasCorrected] = await Promise.all([
    loadPhoto(original, fieldPhoto, "data/field-original.jpg"),
    corrected ? loadPhoto(photo, correctedPhoto, "data/field-photo.jpg") : false,
  ]);
  if (!hasOriginal && !hasCorrected) return;
  const rawButton = byId("map-field-original");
  const mapButton = byId("map-field-map");
  function select(view) {
    fieldPhoto.hidden = view !== "original";
    correctedPhoto.hidden = view !== "map";
    fieldCanvas.hidden = view !== "orbit";
    rawButton.setAttribute("aria-pressed", String(view === "original"));
    mapButton.setAttribute("aria-pressed", String(view === "map"));
    fieldOrbit.setAttribute("aria-pressed", String(view === "orbit"));
    const isOriginal = view === "original";
    const captured = captureClock.format(new Date((isOriginal ? original : photo).captured_at));
    byId("map-field-caption").textContent =
      `Rosy Cam · ${captured} KST · ${isOriginal ? "카메라 원본" : "지도 평면 보정"}`;
  }
  rawButton.hidden = !hasOriginal;
  mapButton.hidden = !hasCorrected;
  fieldOrbit.hidden = !hasCorrected;
  rawButton.addEventListener("click", () => select("original"));
  mapButton.addEventListener("click", () => select("map"));
  fieldOrbit.addEventListener("click", async () => {
    select("orbit");
    try {
      fieldView ??= await showFieldPlane(fieldCanvas, correctedPhoto, photo.plane, () => select("map"));
      if (!fieldCanvas.hidden) fieldView("iso");
    } catch {
      select("map");
      fieldOrbit.hidden = true;
    }
  });
  select(hasOriginal ? "original" : "map");
  fieldButton.hidden = false;
  if (!choseMapMode && !directR08) mapMode("field");
}).catch(() => {});

function cellFallback() {
  byId("cell-view").hidden = true;
  byId("cell-fallback").hidden = false;
  byId("cell-tools").hidden = true;
}
let archiveLayout;
async function loadCell() {
  const [geometry, calibration, r2sCal] = await Promise.allSettled([
    readJson("geometry"),
    readJson("calibration"),
    readJson("r2s-calibration"),
  ]);
  const r2sData = r2sCal.status === "fulfilled" ? r2sCal.value : null;
  byId("cal-tag").hidden = false;
  byId("cell-calibration-note").textContent = r2sData?.geometry_audit?.honest_note
    ? r2sData.geometry_audit.honest_note
    : calibration.status === "fulfilled" &&
      calibration.value?.status === "unverified"
      ? "카메라 재보정, 동작 및 패드 확인이 기록에 남아 있지 않습니다."
      : "이 보관본에서 현장 보정을 확인할 수 없습니다.";
  if (geometry.status === "rejected") {
    status("cell-status", "unavailable", "셀 형상 파일을 읽을 수 없습니다.");
    return cellFallback();
  }
  const { arm_axes_m: axes, preset, scope, layout_sha256: layout } = geometry.value ?? {};
  if (isLayoutSha(layout)) archiveLayout = layout;
  const points = [axes?.arm_a, axes?.arm_b];
  const valid = points.every((point) => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite));
  const audit = r2sData?.geometry_audit;
  readout("cell-readout", [
    ["출처", "Isaac 셀 형상 보관본"],
    ["프리셋", preset ?? "확인되지 않음"],
    ...(audit ? [
      ["팔 베이스 간격 (CAD·실물)", `${audit.canonical_plate_inner_gap_mm ?? audit.planned_plate_inner_gap_mm} mm (${audit.canonical_preset ?? audit.planned_preset} · 사진 참고 ${audit.measured_plate_inner_gap_mm}±3 mm · v25 후보 ${audit.future_v25_candidate_mm ?? 190} mm)`],
      ["D435 상단 보정", `${r2sData?.cameras?.d435_top?.source ?? "TOP_CAMERA_20261114"} · ${audit.d435_fit_rms_px} px RMS (1σ≈${audit.sigma_xy_mm} mm)`],
      ...(r2sData?.map_gate?.available ? [
        ["omx_map_gate", r2sData.map_gate.ok ? "PASS (194 mm · 브리지 v7)" : "FAIL"],
      ] : []),
    ] : []),
    ...(valid ? points.map((point, index) => [
      `팔 ${index === 0 ? "A" : "B"} 베이스 (X, Y, Z m)`,
      point.map((position) => position.toFixed(4)).join(", "),
    ]) : []),
  ]);
  byId("cell-scope-note").textContent = scope === "visual layout, no live articulation or PhysX acceptance"
    ? "보관된 시각 배치 자료입니다. 실시간 관절 값과 PhysX 검증 결과는 없습니다."
    : "보관된 베이스 좌표를 표시합니다.";
  byId("cell-scope-note").hidden = false;
  if (!valid) {
    status("cell-status", "unavailable", "보관된 베이스 좌표를 읽을 수 없습니다.");
    return cellFallback();
  }
  try {
    const equipment = equipmentUrl(await manifestRead, "cell");
    const select = await showCell(byId("cell-canvas"), points, cellFallback, equipment, {
      r2sPalette: r2sData?.palette ?? null,
    });
    const cellViewEl = byId("cell-view");
    const overlayEl = byId("cell-r2s-overlay");
    const alphaButtons = [
      ["0", byId("cell-r2s-alpha-0")],
      ["50", byId("cell-r2s-alpha-50")],
      ["80", byId("cell-r2s-alpha-80")],
    ];
    const views = ["iso", "front", "top", "d435"];
    function setAlpha(alpha) {
      if (overlayEl) overlayEl.dataset.r2sAlpha = alpha;
      for (const [val, btn] of alphaButtons) btn?.setAttribute("aria-pressed", String(val === alpha));
    }
    function applyCellView(view) {
      if (view === "d435" && r2sData?.cameras?.d435_top?.cell_frame) {
        if (cellViewEl) cellViewEl.dataset.d435 = "true";
        select.setExactCamera?.(r2sData.cameras.d435_top.cell_frame);
      } else {
        if (cellViewEl) cellViewEl.dataset.d435 = "false";
        setAlpha("0");
        select(view);
      }
      for (const option of views) {
        byId(`cell-preset-${option}`)?.setAttribute("aria-pressed", String(view === option));
      }
    }
    for (const view of views) {
      byId(`cell-preset-${view}`)?.addEventListener("click", () => applyCellView(view));
    }
    for (const [val, btn] of alphaButtons) {
      btn?.addEventListener("click", () => {
        if (val !== "0") applyCellView("d435");
        setAlpha(val);
      });
    }
    if (!r2sData?.cameras?.d435_top?.cell_frame) {
      byId("cell-preset-d435").hidden = true;
    }
    if (equipment) {
      byId("cell-scope-note").textContent = "R08 CAD194 설계 배치입니다. 선체·접안부, 임시 놓기판, 반출대, 화물과 팔을 표시합니다. 현장 좌표와 설치 상태는 확인이 필요합니다.";
    }
    status("cell-status", "ready", equipment ? "OMX 셀 CAD · R2S 비교 가능" : "보관 OMX 셀 배치");
  } catch {
    cellFallback();
    status("cell-status", "ready", "보관 OMX 셀 형상 자료");
  }
}

liveFeeds = initLiveFeeds({
  byId,
  status,
  readout,
  date,
  text,
  readJson,
  mapData,
  recordingData,
  manifestRead,
  mapPromise,
  directRun,
  getMode: () => mode,
  getCadView: () => cadView,
  getArchiveLayout: () => archiveLayout,
  getFactoryTab: () => factoryTab,
});
