// 주행 화면의 틀과 배치(D-363). drive.js 에서 나눴다: 무대·HUD·조작부 마크업, 영상 비율에 맞춘
// side/below 배치, 배율 순환(맞춤 → 1.2× → 1.4× → 가득 → 전체화면)과 잘림 표시.
// 조종 입력·명령 루프는 drive.js, 보조 자율은 drive-auto.js 가 가진다.

import {inputConfig, saveInputConfig} from "../input-state.js";

// 영상이 실제로 그려지는 폭을 계산해 좌우 띠가 조작부를 담을 만큼 넓으면 "side",
// 아니면 영상 아래에 조작부를 두는 "below" 로 바꾼다.
const SIDE_MIN_BAND_PX = 200;
// 배율(D-363 §5): 맞춤 1.0× → 1.2× → 1.4× → 가득(화면 폭) → 전체화면 → 맞춤
const ZOOM_STEPS = [1, 1.2, 1.4, "fill", "full"];

export function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

function frameRatio(frame) {
  return (frame.naturalWidth && frame.naturalHeight) ? frame.naturalWidth / frame.naturalHeight : 4 / 3;
}

// --- 배치(D-363): 영상은 원본 비율 그대로, 조작부는 영상 밖 --------------------
export function mountDriveView(drive, element) {
  function applyLayout() {
    const width = drive.clientWidth;
    const height = drive.clientHeight;
    if (!width || !height) return;
    const ratio = frameRatio(element.frame);
    const hudHeight = element.hud.getBoundingClientRect().height + 8;
    const videoHeight = height - hudHeight;
    const band = (width - videoHeight * ratio) / 2;
    const side = band >= SIDE_MIN_BAND_PX;
    drive.dataset.driveLayout = side ? "side" : "below";
    drive.style.setProperty("--band", `${Math.max(0, Math.floor(band))}px`);
    drive.style.setProperty("--video-ratio", String(ratio));
  }
  function zoomValue(step) {
    const box = element.view.getBoundingClientRect();
    const ratio = frameRatio(element.frame);
    if (!box.width || !box.height) return 1;
    // 맞춤일 때 영상이 차지하는 폭 → 화면 폭을 채우는 배율
    const fitWidth = Math.min(box.width, box.height * ratio);
    const fill = Math.max(1, box.width / fitWidth);
    return step === "fill" ? fill : Math.min(Number(step) || 1, fill);
  }
  function coverCrop() {
    // 전체화면(cover): 화면 비와 영상 비 중 어느 쪽이 잘리는가
    const box = element.view.getBoundingClientRect();
    const ratio = frameRatio(element.frame);
    if (!box.width || !box.height) return {axis: "위아래", percent: 0};
    const boxRatio = box.width / box.height;
    return boxRatio >= ratio
      ? {axis: "위아래", percent: Math.round((1 - ratio / boxRatio) * 100)}
      : {axis: "좌우", percent: Math.round((1 - boxRatio / ratio) * 100)};
  }
  function applyZoom() {
    const step = inputConfig().zoom ?? 1;
    const full = step === "full";
    const below = drive.dataset.driveLayout === "below";
    drive.dataset.viewMode = full ? "full" : "fit";
    element.view.style.height = "";
    let crop;
    if (below) {
      // 세로 화면: 영상이 이미 폭을 채운다. 확대는 영상 높이를 늘리고 좌우를 자른다(cover).
      const width = element.view.getBoundingClientRect().width;
      const ratio = frameRatio(element.frame);
      const maxHeight = drive.clientHeight * (full ? 1 : 0.72);
      const fitHeight = width / ratio;
      const fill = Math.max(1, maxHeight / fitHeight);
      const z = full || step === "fill" ? fill : Math.min(Number(step) || 1, fill);
      element.frame.style.transform = "";
      element.frame.style.objectFit = z > 1.001 ? "cover" : "";
      if (z > 1.001) element.view.style.height = `${Math.round(fitHeight * z)}px`;
      drive.dataset.zoomed = String(z > 1.001);
      crop = {axis: "좌우", percent: Math.round((1 - 1 / z) * 100), z};
    } else {
      element.frame.style.objectFit = "";
      const z = full ? 1 : zoomValue(step);
      element.frame.style.transform = z > 1.001 ? `scale(${z.toFixed(3)})` : "";
      drive.dataset.zoomed = String(full || z > 1.001);
      crop = full ? {...coverCrop(), z: 1} : {axis: "위아래", percent: Math.round((1 - 1 / z) * 100), z};
    }
    element.zoomFact.hidden = crop.percent <= 0;
    element.zoomFact.textContent = crop.percent > 0 ? `${crop.axis} ${crop.percent}% 잘림` : "";
    if (element.zoomButton) {
      element.zoomButton.textContent = full ? "전체화면"
        : step === "fill" ? "확대 가득" : crop.z > 1.001 ? `확대 ${crop.z.toFixed(1)}×` : "확대 맞춤";
    }
  }
  // 설치 앱에서는 전체화면 API 로 상태 표시줄까지 숨긴다. 지원이 없으면 화면 안에서만 채운다.
  function syncFullscreen(full) {
    try {
      if (full && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
      if (!full && document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    } catch (error) { /* 지원 없음 */ }
  }
  function cycleZoom() {
    const current = inputConfig().zoom ?? 1;
    const index = ZOOM_STEPS.findIndex((stepValue) => stepValue === current);
    const next = ZOOM_STEPS[(index + 1) % ZOOM_STEPS.length];
    saveInputConfig({zoom: next});
    syncFullscreen(next === "full");
    applyZoom();
  }

  const layoutObserver = new ResizeObserver(() => { applyLayout(); applyZoom(); });
  layoutObserver.observe(drive);
  element.frame.addEventListener("load", () => { applyLayout(); applyZoom(); });
  applyLayout();

  return {
    applyZoom,
    cycleZoom,
    close() {
      layoutObserver.disconnect();
      syncFullscreen(false);
      // 같은 section 에 다시 마운트된다 — 지난 배치·배율 표시를 남기지 않는다.
      for (const key of ["driveLayout", "viewMode", "zoomed"]) delete drive.dataset[key];
      drive.style.removeProperty("--band");
      drive.style.removeProperty("--video-ratio");
    },
  };
}

// --- 마크업: 서버 텍스트로 HTML 을 만들지 않는다 ------------------------------
export function buildStage() {
  const stage = el("div", null, {"data-drive-stage": ""});
  const frame = el("img", null, {alt: "전방 카메라", "data-drive-frame": "", hidden: ""});
  const empty = el("ui-empty", "카메라 프레임 수신 대기", {"data-drive-empty": ""});
  const blocked = el("div", null, {"data-drive-blocked": "", role: "alert", hidden: ""});
  const retake = el("ui-button", "수동 모드 다시 잡기", {type: "button", "data-drive-retake": ""});
  retake.setAttribute("kind", "primary");
  blocked.append(el("ui-text", "", {scale: "value", "data-drive-blocked-reason": ""}), retake);
  // 영상 틀: 확대(D-363 §5) 때 넘치는 부분을 이 틀 안에서만 자른다.
  const view = el("div", null, {"data-drive-view": ""});
  // 자동 의도 띠: 가운데 눈금, 겨누는 점, 실제 조향 방향(D-364 §6)
  const intent = el("div", null, {"data-drive-intent": "", hidden: "", "aria-live": "polite"});
  const track = el("span", null, {"data-intent-track": ""});
  track.append(el("i", null, {"data-intent-centre": ""}), el("i", null, {"data-intent-target": ""}));
  intent.append(track, el("span", "", {"data-intent-steer": ""}));
  view.append(frame, empty, intent);
  stage.append(view, buildHud(), blocked);
  return stage;
}

function buildHud() {
  // 한 줄 스트립: 실측 속도(주인공) · 회전율 · 동작 · 상한 | 링크·지연·모드·배터리 | 액션
  const hud = el("div", null, {"data-drive-hud": ""});
  const gauge = el("div", null, {"data-drive-gauge": ""});
  gauge.append(
    el("span", "0.00", {"data-drive-fact": "speed"}),
    el("ui-text", "m/s", {scale: "unit"}),
    el("span", "· 0°/s", {"data-drive-fact": "turn"}),
  );
  const motion = el("span", "대기", {"data-drive-motion": "", "data-kind": "idle"});
  const cap = el("span", "", {"data-drive-fact": "cap"});
  const zoom = el("span", "", {"data-drive-fact": "zoom", hidden: ""});
  const facts = el("div", null, {"data-drive-facts": ""});
  facts.append(
    el("span", "…", {"data-drive-fact": "link"}),
    el("span", "—", {"data-drive-fact": "latency"}),
    el("span", "—", {"data-drive-fact": "mode"}),
    el("span", "—", {"data-drive-fact": "battery"}),
  );
  hud.append(gauge, motion, cap, zoom, facts);
  return hud;
}

// 조작 버튼의 종류(D-345 공용 컨트롤): 속도·정밀은 한 판 안의 segment(aria-pressed), 차선 자동은
// 켜고 끄는 toggle(data-active), 누르는 동안만 움직이는 페달·제자리·진행은 toggle(누르는 동안
// .active 로 채워진다) + size primary.
// 게임형 큰 표적은 styles.css 의 배치 규칙(min-height·폭)이 정한다 — 면·글자·테두리는 components.css.
export function buildControls(profile) {
  const controls = el("div", null, {"data-drive-controls": ""});
  // 좌: 속도·정밀 / 페달 / 제자리 회전   우: 2축 주행 스틱
  const left = el("div", null, {"data-drive-left": ""});
  const tune = el("div", null, {"data-drive-presets": ""});
  const fine = el("ui-button", "정밀", {type: "button", "data-drive-fine": "", "aria-pressed": "false"});
  fine.setAttribute("kind", "segment");
  tune.append(
    el("ui-text", "속도", {scale: "label"}),
    el("ui-actions", null, {"data-drive-preset-row": ""}),
    fine,
  );
  const pedals = el("div", null, {"data-drive-pedals": ""});
  const forward = el("ui-button", "전진 ▲", {type: "button", size: "primary", "data-drive-pedal": "forward"});
  forward.setAttribute("kind", "toggle");
  const reverse = el("ui-button", "후진 ▼", {type: "button", size: "primary", "data-drive-pedal": "reverse"});
  reverse.setAttribute("kind", "toggle");
  pedals.append(forward, reverse);
  left.append(tune);
  if (profile.autonomy?.includes("line")) {
    const autoToggle = el("ui-button", "차선 자동", {type: "button", "data-drive-auto": "", "aria-pressed": "false",
                                                    "data-active": "false"});
    autoToggle.setAttribute("kind", "toggle");
    left.append(autoToggle);
  }
  left.append(pedals);
  if (profile.autonomy?.includes("line")) {
    const go = el("ui-button", "진행 ▶ 누르는 동안", {type: "button", size: "primary", "data-drive-go": "",
                                                     "aria-label": "차선 따라 진행(누르는 동안만)"});
    go.setAttribute("kind", "toggle");
    left.append(go);
  }
  if (profile.pivot !== false) {
    const pivots = el("div", null, {"data-drive-pivots": ""});
    const pivotLeft = el("ui-button", "↺ 제자리", {type: "button", size: "primary", "data-drive-pivot": "left",
                                                  "aria-label": "제자리 좌회전(누르는 동안)"});
    pivotLeft.setAttribute("kind", "toggle");
    const pivotRight = el("ui-button", "제자리 ↻", {type: "button", size: "primary", "data-drive-pivot": "right",
                                                   "aria-label": "제자리 우회전(누르는 동안)"});
    pivotRight.setAttribute("kind", "toggle");
    pivots.append(pivotLeft, pivotRight);
    left.append(pivots);
  }

  const right = el("div", null, {"data-drive-right": ""});
  const stick = el("div", null, {"data-drive-stick": "", role: "application",
                                 "aria-label": "주행 스틱 — 위 전진, 아래 후진, 좌우 조향, 옆으로만 밀면 제자리 회전"});
  stick.append(el("div", null, {"data-drive-stick-knob": ""}));
  right.append(stick);

  controls.append(left, right);
  return controls;
}
