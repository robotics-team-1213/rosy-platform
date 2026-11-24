import { showCad, showCell, showFieldPlane, showMap } from "./scene.js";
import { initPlay } from "./play.js";
import { initFactoryTab } from "./factory-live.js";

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
    throw new Error("Invalid archived map");
  }
  const places = locations.filter((place) => place && xy([place.x, place.y]));
  const edges = map.edges.map((edge) => edge?.polyline).filter((line) =>
    Array.isArray(line) && line.length >= 2 && line.every(xy));
  if (!(places.length || edges.length)) throw new Error("Archive contains no map geometry");
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
let isaacSession;
let cellLoad;
let factoryTab;
let userPickedTab = false;
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
  if (pinkyPollingReady) {
    if (tab.id === "tab-map") {
      startPinkySim();
      startPinkyCamera();
    } else {
      stopPinkySim();
      stopPinkyCamera();
    }
  }
}
let pinkyPollingReady = false;
await customElements.whenDefined("ui-button");
if (directFactory) byId("tab-factory").hidden = false;
activate(directRun ? byId("tab-rec") : directFactory ? byId("tab-factory") : byId("tab-map"));
tabs.forEach((tab, index) => {
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
function updateMapHealth() {
  const states = {
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
  byId("map-alignment-note").hidden = ["cad", "birdview", "field"].includes(mode);
  byId("map-cad-canvas").hidden = mode !== "cad";
  byId("map-cad-controls").hidden = mode !== "cad" || !cadView;
  byId("map-cad-focus").hidden = mode !== "cad" || !cadView?.focus.stations;
  byId("cad-registration").hidden = mode !== "cad" || !cadView || !designAvailable;
  byId("map-cad-status").hidden = !(mode === "cad" && !cadView) && !(cadFailed && ["image", "birdview"].includes(mode));
  for (const view of ["field", "birdview", "vector", "image", "cad"]) {
    byId(`map-mode-${view}`).setAttribute("aria-pressed", String(mode === view));
  }
  if (mode === "cad") startPinkySim();
  else stopPinkySim();
  updateMapHealth();
}
function chooseMapMode(view) {
  choseMapMode = true;
  mapMode(view);
}
const birdviewButton = byId("map-mode-birdview");
birdviewButton.addEventListener("click", () => chooseMapMode("birdview"));
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
  byId("map-mode-vector").hidden = true;
  if (mode === "vector") mapMode(birdviewAvailable ? "birdview" : "image");
  status("map-status", "unavailable", "벡터 지도를 그릴 수 없어 보관 이미지를 표시합니다.");
}
const mapPromise = (async () => {
  let map;
  try {
    const envelope = await readJson("site-map");
    map = mapData(envelope);
    readout("map-readout", [
      ["출처", "Fleet 활성 지도 보관본"],
      ["지도 ID", map.id],
      ["버전", map.version ?? "확인되지 않음"],
      ["활성 시각 (UTC)", date(envelope.activated_at)],
    ]);
  } catch {
    mapFallback();
    return null;
  }
  try {
    await showMap(byId("map-canvas"), map, mapFallback);
    vectorAvailable = true;
    status("map-status", "ready", "보관 지도");
    updateMapHealth();
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
  async function loadPhoto(metadata, image, expectedPath) {
    if (metadata?.bundle_path !== expectedPath || !Number.isFinite(Date.parse(metadata.captured_at))) return false;
    image.src = `./${expectedPath}`;
    return image.decode().then(() => true, () => false);
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

const ISAAC_FRESH_MS = 3000;
const ISAAC_STATES = {
  waiting: "SIM 관측 대기 중",
  running: "SIM 실행 중",
  paused: "SIM 일시정지 또는 시계 정체",
  stopped: "SIM 중지됨",
};
const isLayoutSha = (value) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const vector = (values, length) => Array.isArray(values) && values.length === length &&
  values.every(Number.isFinite);
function validIsaac(sample) {
  return sample?.schema === "rosy.world.isaac-state.v1" && text(sample.run_id) &&
    (sample.scene === "ab" ? isLayoutSha(sample.layout_sha256)
      : sample.scene === "conformance" && sample.layout_sha256 === null) &&
    Number.isSafeInteger(sample.observed_at_ms) && sample.observed_at_ms > 0 &&
    Number.isFinite(sample.sim_time_s) && sample.sim_time_s >= 0 &&
    Number.isSafeInteger(sample.reset_count) && sample.reset_count >= 0 &&
    typeof sample.state === "string" && Object.hasOwn(ISAAC_STATES, sample.state) &&
    Array.isArray(sample.joints) && sample.joints.every((joint) =>
      text(joint?.name) && Number.isFinite(joint.position_rad)) &&
    Array.isArray(sample.objects) && sample.objects.every((object) =>
      text(object?.id) && text(object.frame_id) &&
      vector(object.position_m, 3) && vector(object.orientation_xyzw, 4));
}

function isaacStatus(state, message, summary = message) {
  const node = byId("isaac-status");
  if (node.getAttribute("state") !== state || node.textContent !== message) {
    status("isaac-status", state, message);
  }
  const health = byId("isaac-health");
  const label = `Isaac · ${summary}`;
  if (health.getAttribute("state") !== state || health.textContent !== label) {
    status("isaac-health", state, label);
  }
}

function clearIsaacReadout() {
  const list = byId("isaac-readout");
  list.hidden = true;
  list.replaceChildren();
}

function showIsaac(session, sample) {
  clearTimeout(session.expiry);
  const age = Date.now() - sample.observed_at_ms;
  if (Math.abs(age) > ISAAC_FRESH_MS) {
    clearIsaacReadout();
    return isaacStatus("unavailable", "연결 안 됨 · SIM 관측 시각이 3초 범위를 벗어났습니다.", "관측 만료");
  }
  if (sample.state === "waiting" || sample.state === "stopped" ||
      !sample.joints.length || !sample.objects.length) {
    clearIsaacReadout();
    return isaacStatus("empty", sample.state === "running" || sample.state === "paused"
      ? "표시할 관절과 물체 관측을 기다리는 중입니다." : ISAAC_STATES[sample.state], "관측 대기");
  }
  isaacStatus("ready", ISAAC_STATES[sample.state],
    sample.state === "running" ? "SIM 관측 수신 중" : "SIM 일시정지 또는 시계 정체");
  const ab = sample.scene === "ab";
  readout("isaac-readout", [
    ["SIM 장면", ab ? "OMX A/B (ab)" : "적합성 시험 (conformance)"],
    ...(ab ? [
      ["SIM 배치 SHA-256", sample.layout_sha256],
      ["보관 배치 비교", archiveLayout ? (archiveLayout === sample.layout_sha256 ? "SHA-256 일치" : "SHA-256 불일치") : "보관 SHA-256 확인 불가"],
    ] : []),
    ["실행 ID", sample.run_id],
    ["SIM 시간 (s)", sample.sim_time_s],
    ["시계 초기화 횟수", sample.reset_count],
    ...sample.joints.map(({ name, position_rad }) => [`관절 ${name} (rad)`, position_rad]),
    ...sample.objects.flatMap(({ id, frame_id, position_m, orientation_xyzw }) => [
      [`물체 ${id} · 좌표계`, frame_id],
      [`물체 ${id} · 위치 (X, Y, Z m)`, position_m.join(", ")],
      [`물체 ${id} · 자세 (쿼터니언 XYZW)`, orientation_xyzw.join(", ")],
    ]),
  ]);
  session.expiry = setTimeout(() => {
    clearIsaacReadout();
    isaacStatus("unavailable", "연결 안 됨 · 최근 SIM 관측이 없습니다.", "관측 만료");
  }, ISAAC_FRESH_MS - age);
}

async function pollIsaac(session) {
  const request = new AbortController();
  session.request = request;
  const deadline = setTimeout(() => request.abort(), 2500);
  try {
    const response = await fetch("./data/isaac-live.json", {
      cache: "no-store", redirect: "error", signal: request.signal,
    });
    if (!response.ok) throw new Error("SIM snapshot unavailable");
    const sample = await response.json();
    if (isaacSession !== session) return;
    if (!validIsaac(sample)) throw new Error("Invalid SIM snapshot");
    showIsaac(session, sample);
  } catch {
    if (isaacSession !== session) return;
    clearTimeout(session.expiry);
    clearIsaacReadout();
    isaacStatus("unavailable", "연결 안 됨 · SIM 관측을 읽을 수 없습니다.", "연결 안 됨");
  } finally {
    clearTimeout(deadline);
    if (isaacSession === session) {
      const delay = byId("isaac-health").getAttribute("state") === "unavailable" ? 2000 : 750;
      session.next = setTimeout(() => pollIsaac(session), delay);
    }
  }
}

function stopIsaacStatus() {
  const session = isaacSession;
  isaacSession = undefined;
  if (!session) return;
  session.request?.abort();
  clearTimeout(session.next);
  clearTimeout(session.expiry);
  clearIsaacReadout();
}

function startIsaacStatus() {
  if (document.hidden || isaacSession || byId("isaac-status-panel").hidden) return;
  const session = {};
  isaacSession = session;
  isaacStatus("pending", "SIM 관측을 확인하는 중…", "확인 중");
  void pollIsaac(session);
}

byId("isaac-status-toggle").addEventListener("click", () => {
  const panel = byId("isaac-status-panel");
  panel.hidden = !panel.hidden;
  byId("isaac-status-toggle").setAttribute("aria-pressed", String(!panel.hidden));
  if (panel.hidden) {
    stopIsaacStatus();
    isaacStatus("empty", "SIM 관측이 꺼져 있습니다 — 스위치로 켤 수 있습니다.", "끔");
  } else startIsaacStatus();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && isaacSession) stopIsaacStatus();
  else startIsaacStatus();
  if (document.hidden) stopPinkySim();
  else startPinkySim();
  if (document.hidden) stopPinkyCamera();
  else startPinkyCamera();
  if (document.hidden) factoryTab?.deactivate();
  else if (byId("tab-factory").getAttribute("aria-selected") === "true") void factoryTab?.activate();
});
startIsaacStatus();

const PINKY_SIM_FRAME = "world_261026_cad";
const PINKY_SIM_FRESH_MS = 3000;
let simSession;
function validPinkySim(sample, manifest) {
  return sample?.schema === "rosy.world.pinky-sim.v1" && text(sample.run_id) &&
    typeof sample.robot_id === "string" && /^[a-z][a-z0-9_]{0,31}$/.test(sample.robot_id) &&
    sample.frame_id === PINKY_SIM_FRAME && !!manifest?.site_cad?.source_sha256 &&
    sample.site_cad_sha256 === manifest?.site_cad?.source_sha256 &&
    Number.isSafeInteger(sample.observed_at_ms) && sample.observed_at_ms > 0 &&
    Number.isFinite(sample.sim_time_s) && sample.sim_time_s >= 0 &&
    vector(sample.pose_m, 3) && Number.isFinite(sample.yaw_rad);
}
function hidePinkySim() {
  cadView?.setSim(null);
}
function stopPinkySim() {
  const session = simSession;
  simSession = undefined;
  if (!session) return;
  session.request?.abort();
  clearTimeout(session.next);
  clearTimeout(session.expiry);
  hidePinkySim();
}
function showPinkySim(session, sample) {
  clearTimeout(session.expiry);
  const age = Date.now() - sample.observed_at_ms;
  if (Math.abs(age) > PINKY_SIM_FRESH_MS) {
    hidePinkySim();
    return status("pinky-sim-status", "unavailable",
      "Pinky SIM 사용 불가 · 관측 시각이 3초 범위를 벗어났습니다.");
  }
  cadView.setSim(sample);
  status("pinky-sim-status", "ready", `Pinky SIM 라이브 · 실행 ${sample.run_id}`);
  session.expiry = setTimeout(() => {
    hidePinkySim();
    status("pinky-sim-status", "unavailable", "Pinky SIM 사용 불가 · 최근 관측이 없습니다.");
  }, PINKY_SIM_FRESH_MS - age);
}
async function pollPinkySim(session) {
  const request = new AbortController();
  session.request = request;
  const deadline = setTimeout(() => request.abort(), 2500);
  try {
    const response = await fetch("./data/pinky-sim.json", {
      cache: "no-store", redirect: "error", signal: request.signal,
    });
    if (!response.ok) throw new Error("Pinky SIM snapshot unavailable");
    const sample = await response.json();
    const manifest = await manifestRead;
    if (simSession !== session) return;
    if (!validPinkySim(sample, manifest)) throw new Error("Invalid Pinky SIM snapshot");
    showPinkySim(session, sample);
  } catch {
    if (simSession !== session) return;
    clearTimeout(session.expiry);
    hidePinkySim();
    status("pinky-sim-status", "unavailable", "Pinky SIM 사용 불가 · 관측 파일을 읽을 수 없습니다.");
  } finally {
    clearTimeout(deadline);
    if (simSession === session) {
      const delay = byId("pinky-sim-status").getAttribute("state") === "unavailable" ? 2000 : 750;
      session.next = setTimeout(() => pollPinkySim(session), delay);
    }
  }
}
function startPinkySim() {
  if (document.hidden || simSession || mode !== "cad" || !cadView || byId("panel-map").hidden ||
      byId("pinky-sim-toggle").getAttribute("aria-pressed") !== "true") return;
  const session = {};
  simSession = session;
  status("pinky-sim-status", "pending", "Pinky SIM 관측을 확인하는 중…");
  void pollPinkySim(session);
}
byId("pinky-sim-toggle").addEventListener("click", () => {
  const toggle = byId("pinky-sim-toggle");
  const enabled = toggle.getAttribute("aria-pressed") !== "true";
  toggle.setAttribute("aria-pressed", String(enabled));
  if (enabled) startPinkySim();
  else {
    stopPinkySim();
    status("pinky-sim-status", "empty", "Pinky SIM 위치 표시가 꺼져 있습니다 — 스위치로 다시 켤 수 있습니다.");
  }
});
pinkyPollingReady = true;

const CAMERA_FRESH_MS = 3000;
const CAMERA_SOURCES = {
  field: {file: "field-live.jpg", label: "Rosy Cam 현장 상단", freshMs: 5000},
  gazebo: {file: "pinky-camera.jpg", label: "Gazebo Pinky 전방"},
  mujoco: {file: "mujoco-top.jpg", label: "MuJoCo OMX 셀 상단"},
  isaac: {file: "isaac-view.json", label: "Isaac Sim", telemetry: true},
};
let cameraSource = "gazebo";
let cameraSession;

function clearCameraFrame(session) {
  clearTimeout(session.expiry);
  const image = byId("pinky-camera-image");
  image.hidden = true;
  image.removeAttribute("src");
  if (session.url) URL.revokeObjectURL(session.url);
  session.url = undefined;
}

function stopPinkyCamera() {
  const session = cameraSession;
  cameraSession = undefined;
  if (!session) return;
  session.request?.abort();
  clearTimeout(session.next);
  clearCameraFrame(session);
}

async function pollPinkyCamera(session) {
  const request = new AbortController();
  session.request = request;
  const deadline = setTimeout(() => request.abort(), 2500);
  let nextUrl;
  try {
    const response = await fetch(`./data/${session.file}`, {
      cache: "no-store", redirect: "error", signal: request.signal,
    });
    const modifiedAt = Date.parse(response.headers.get("Last-Modified"));
    const serverAt = Date.parse(response.headers.get("Date"));
    const type = response.headers.get("Content-Type")?.split(";")[0];
    if (!response.ok || type !== (session.telemetry ? "application/json" : "image/jpeg")) {
      throw new Error("Camera source unavailable");
    }
    const metadata = session.telemetry ? await response.json() : null;
    const age = (Number.isFinite(serverAt) ? serverAt : Date.now())
      - (metadata ? metadata.observed_at_ms : modifiedAt);
    const freshMs = session.freshMs ?? CAMERA_FRESH_MS;
    const remaining = performance.now() + freshMs - age;
    if (!Number.isFinite(age) || age < -1000 || age >= freshMs) {
      throw new Error("No recent camera frame");
    }
    let frame;
    if (session.telemetry) {
      if (metadata?.schema !== "rosy.world.isaac-view.v1" || !/^sim-[a-z0-9-]{1,80}$/.test(metadata.run_id)
          || !isLayoutSha(metadata.stage_sha256) || !Number.isSafeInteger(metadata.observed_at_ms)
          || !Number.isFinite(metadata.sim_time_s) || metadata.sim_time_s <= 0
          || !Number.isSafeInteger(metadata.sequence) || metadata.sequence < 1
          || !vector(metadata.cargo_xyz_m, 3) || !["scene", "belt"].includes(metadata.scenario)
          || typeof metadata.jpeg !== "string" || metadata.jpeg.length > 682672) {
        throw new Error("Invalid Isaac frame envelope");
      }
      const previous = session.latest;
      if (previous?.run_id === metadata.run_id && (metadata.sequence <= previous.sequence
          || metadata.sim_time_s <= previous.sim_time_s)) return;
      frame = new Blob([Uint8Array.from(atob(metadata.jpeg), (char) => char.charCodeAt(0))], {type: "image/jpeg"});
    } else frame = await response.blob();
    if (cameraSession !== session) return;
    if (frame.size < 4 || frame.size > 512000) throw new Error("Invalid camera frame");
    nextUrl = URL.createObjectURL(frame);
    const decoded = new Image();
    decoded.src = nextUrl;
    await decoded.decode();
    if (cameraSession !== session) return;
    if (performance.now() >= remaining) throw new Error("Camera frame expired in transit");
    clearTimeout(session.expiry);
    const image = byId("pinky-camera-image");
    const previousUrl = session.url;
    image.src = nextUrl;
    session.url = nextUrl;
    nextUrl = undefined;
    image.hidden = false;
    session.latest = metadata;
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    session.expiry = setTimeout(() => {
      status("pinky-camera-status", "warning", `${session.label} · 수신 지연, 마지막 프레임`);
    }, remaining - performance.now());
    status("pinky-camera-status", "ready", metadata
      ? `Isaac Sim · 실시간 ${metadata.sim_time_s.toFixed(2)}초 · ${metadata.run_id} · ${metadata.scenario === "belt" ? "벨트 시험" : "장면 실행"}`
      : `${session.label} · 영상 수신 중`);
  } catch {
    if (cameraSession !== session) return;
    if (!session.url) {
      status("pinky-camera-status", "unavailable", `${session.label} · 최근 영상 없음`);
    }
  } finally {
    if (nextUrl) URL.revokeObjectURL(nextUrl);
    clearTimeout(deadline);
    if (cameraSession === session) {
      const delay = byId("pinky-camera-status").getAttribute("state") === "unavailable" ? 2000 : 400;
      session.next = setTimeout(() => pollPinkyCamera(session), delay);
    }
  }
}

function startPinkyCamera() {
  if (document.hidden || cameraSession || byId("panel-map").hidden || byId("pinky-camera-panel").hidden) return;
  const session = { ...CAMERA_SOURCES[cameraSource] };
  cameraSession = session;
  byId("pinky-camera-image").alt = `${session.label} 영상`;
  status("pinky-camera-status", "pending", `${session.label} · 연결 중…`);
  void pollPinkyCamera(session);
}

for (const source of Object.keys(CAMERA_SOURCES)) {
  byId(`camera-source-${source}`).addEventListener("click", () => {
    if (source === cameraSource) return;
    stopPinkyCamera();
    cameraSource = source;
    byId("camera-figure").dataset.source = source;
    for (const item of Object.keys(CAMERA_SOURCES)) {
      byId(`camera-source-${item}`).setAttribute("aria-pressed", String(item === source));
    }
    startPinkyCamera();
  });
}
manifestRead.then((manifest) => {
  if ((manifest?.field_original || manifest?.field_photo) && byId("pinky-camera-panel").hidden && cameraSource === "gazebo") {
    byId("camera-source-field").click();
  }
}).catch(() => {});

byId("pinky-camera-toggle").addEventListener("click", () => {
  const panel = byId("pinky-camera-panel");
  panel.hidden = !panel.hidden;
  byId("pinky-camera-toggle").setAttribute("aria-pressed", String(!panel.hidden));
  if (panel.hidden) stopPinkyCamera();
  else startPinkyCamera();
});
if (new URLSearchParams(location.search).get("view") === "isaac") {
  byId("panel-map").prepend(byId("pinky-camera-panel"));
  byId("camera-source-isaac").click();
  byId("pinky-camera-toggle").click();
}
if (new URLSearchParams(location.search).get("view") === "play") {
  byId("world-play").after(byId("pinky-camera-panel"));
  byId("camera-source-gazebo").click();
  byId("pinky-camera-toggle").click();
  initPlay();
}

function recordFallback(message) {
  status("rec-status", "unavailable", message);
  byId("rec-fallback").hidden = false;
  byId("rec-player").hidden = true;
}
async function loadRecording() {
  let recording;
  try {
    recording = recordingData(await readJson("recording"));
  } catch {
    return recordFallback("재생할 보관 기록이 없습니다.");
  }
  const { samples, source, captured_at, map_version } = recording;
  readout("rec-readout", [
    ["출처", source], ["기록 시각 (UTC)", date(captured_at)], ["기록 지도 버전", map_version],
  ]);
  let map;
  try {
    const manifest = await manifestRead;
    map = manifest?.recording_map?.bundle_path === "data/recording-map.json"
      ? mapData(await readJson("recording-map")) : await mapPromise;
  } catch {
    return recordFallback("기록에 연결된 지도를 열 수 없습니다.");
  }
  if (!map || map.version !== map_version || !samples.some(({ frame_id }) => frame_id === map.id)) {
    return recordFallback("보관 지도와 지도 ID 및 버전이 일치하는 기록이 없습니다.");
  }
  const duration = samples.at(-1).offset_ms;
  const range = byId("rec-range");
  const play = byId("rec-play");
  let draw;
  let tick;
  let offset = 0;
  let lastSample;
  const stop = () => {
    cancelAnimationFrame(tick);
    tick = undefined;
    play.setAttribute("aria-pressed", "false");
    play.textContent = "재생";
  };
  const unavailable = () => {
    stop();
    recordFallback("기록 위치를 그릴 수 없어 보관 자료를 표시합니다.");
  };
  try {
    draw = await showMap(byId("rec-canvas"), map, unavailable);
  } catch {
    return unavailable();
  }
  function render(value) {
    offset = value;
    const seconds = (ms) => (ms / 1000).toFixed(2);
    range.value = String(value);
    range.setAttribute("aria-valuetext", `${seconds(value)}초`);
    byId("rec-clock").textContent = `${seconds(value)} / ${seconds(duration)}초`;
    let begin = 0;
    let end = samples.length;
    while (begin < end) {
      const midpoint = Math.floor((begin + end) / 2);
      if (samples[midpoint].offset_ms <= value) begin = midpoint + 1;
      else end = midpoint;
    }
    const sample = samples[begin - 1];
    if (sample === lastSample && value !== 0) return;
    lastSample = sample;
    const positions = sample?.frame_id === map.id ? sample.positions : [];
    draw(positions);
    byId("rec-frame-note").textContent = positions.length
      ? [sample.note, ...positions.map(({ id, x_m, y_m }) => `${id} (${x_m.toFixed(3)}, ${y_m.toFixed(3)}) m`)]
        .filter(text).join(" · ")
      : sample && sample.frame_id !== map.id ? "이 시점의 지도 좌표계가 다릅니다." : "이 시점에 표시할 위치가 없습니다.";
  }
  range.max = String(duration);
  play.hidden = range.parentElement.hidden = duration === 0;
  range.addEventListener("input", () => {
    stop();
    render(Number(range.value));
  });
  play.addEventListener("click", () => {
    if (tick !== undefined) return stop();
    const start = performance.now() - (offset >= duration ? 0 : offset);
    play.setAttribute("aria-pressed", "true");
    play.textContent = "일시 정지";
    function advance(now) {
      const elapsed = Math.min(duration, Math.max(0, now - start));
      render(elapsed);
      if (elapsed < duration) tick = requestAnimationFrame(advance);
      else stop();
    }
    tick = requestAnimationFrame(advance);
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  const panel = byId("panel-rec");
  new MutationObserver(() => { if (panel.hidden) stop(); }).observe(panel, {
    attributes: true, attributeFilter: ["hidden"],
  });
  render(0);
  status("rec-status", "ready", recording.kind === "simulation" ? "시뮬레이션 실행 재생" : "보관 위치 기록");
  byId("rec-player").hidden = false;
  if (directRun && !panel.hidden && duration > 0) play.click();
}

void loadRecording();
