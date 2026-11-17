// 주행 화면의 틀과 배치(D-363). drive.js 에서 나눴다: 무대·HUD·조작부 마크업, 영상 비율에 맞춘
// side/below 배치, 배율 순환(맞춤 → 1.2× → 1.4× → 가득 → 전체화면)과 잘림 표시.
// 조종 입력·명령 루프는 drive.js, 보조 자율은 drive-auto.js 가 가진다.

import {inputConfig, saveInputConfig} from "../input-state.js";
import {EVIDENCE_LABEL, MODE_LABEL} from "/common/core_ui_logic.js";
import {createChoiceGroup} from "/common/choice-group.js";

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

export {actionIcon} from "/common/ui.js";
import {actionIcon} from "/common/ui.js";

// K20 명령 두 개(전체 영상 / 화면 채우기): 배율은 중간 값(1.2×·1.4×·가득)이 있어 둘 중 하나로 고르는 값이 아니다.
// 지금 배율은 확대 단추 글자와 잘림 표시가 말한다. 패널 3자 결론(2026-11-14): 라디오로 두면 "아무것도 아님"을 못 그린다.
// 드라이브 도구판과 영상 보기 화면이 같은 두 단추를 쓴다.
export function buildFitFill(view) {
  const fit = el("ui-button", "전체 영상", {type: "button", "data-drive-fit": "", "aria-label": "전체 영상 · 잘림 없이 보기"});
  fit.setAttribute("kind", "quiet");
  const fill = el("ui-button", "화면 채우기", {type: "button", "data-drive-fill": "", "aria-label": "화면 채우기 · 확대 후 드래그하여 보기"});
  fill.setAttribute("kind", "quiet");
  actionIcon(fit, "fit"); actionIcon(fill, "expand");
  fit.addEventListener("click", () => view.setZoom(1));
  fill.addEventListener("click", () => view.setZoom("full"));
  return [fit, fill];
}

function frameRatio(frame) {
  return (frame.naturalWidth && frame.naturalHeight) ? frame.naturalWidth / frame.naturalHeight : 4 / 3;
}

// --- 배치(D-363): 영상은 원본 비율 그대로, 조작부는 영상 밖 --------------------
export function mountDriveView(drive, element) {
  let pan = {x: 0, y: 0};
  let dragging = null;
  let scale = 1;

  function applyPan() {
    const box = element.view.getBoundingClientRect();
    const ratio = frameRatio(element.frame);
    const cover = getComputedStyle(element.frame).objectFit === "cover";
    const width = cover ? Math.max(box.width, box.height * ratio)
      : Math.min(box.width, box.height * ratio) * scale;
    const height = width / ratio;
    const xLimit = Math.max(0, (width - box.width) / 2);
    const yLimit = Math.max(0, (height - box.height) / 2);
    pan.x = Math.max(-xLimit, Math.min(xLimit, pan.x));
    pan.y = Math.max(-yLimit, Math.min(yLimit, pan.y));
    const frame = element.frame;
    if (cover) {
      const x = xLimit ? 50 - pan.x / (2 * xLimit) * 100 : 50;
      const y = yLimit ? 50 - pan.y / (2 * yLimit) * 100 : 50;
      frame.setAttribute("data-pan-x", `${x}%`);
      frame.setAttribute("data-pan-y", `${y}%`);
      frame.removeAttribute("data-shift-x");
      frame.removeAttribute("data-shift-y");
      frame.removeAttribute("data-frame-scale");
    } else {
      frame.removeAttribute("data-pan-x");
      frame.removeAttribute("data-pan-y");
      if (scale > 1.001) {
        frame.setAttribute("data-shift-x", `${pan.x}px`);
        frame.setAttribute("data-shift-y", `${pan.y}px`);
        frame.setAttribute("data-frame-scale", String(scale));
      } else {
        frame.removeAttribute("data-shift-x");
        frame.removeAttribute("data-shift-y");
        frame.removeAttribute("data-frame-scale");
      }
    }
    return xLimit > 0 || yLimit > 0;
  }

  const panStart = (event) => {
    if (event.button !== 0 || event.target.closest("ui-button, input, select") || !applyPan()) return;
    dragging = {id: event.pointerId, x: event.clientX, y: event.clientY, initial: {...pan}};
    element.view.setPointerCapture(event.pointerId);
    event.preventDefault();
  };
  const panMove = (event) => {
    if (dragging?.id !== event.pointerId) return;
    pan = {x: dragging.initial.x + event.clientX - dragging.x, y: dragging.initial.y + event.clientY - dragging.y};
    applyPan();
  };
  const panEnd = () => { dragging = null; };
  for (const [name, callback] of [["pointerdown", panStart], ["pointermove", panMove],
    ["pointerup", panEnd], ["pointercancel", panEnd], ["lostpointercapture", panEnd]]) {
    element.view.addEventListener(name, callback);
  }
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
    // attr()는 자기 속성만 읽는다. 좌우 칸이 각각 data-band를 갖는다.
    const bandPx = `${Math.max(0, Math.floor(band))}px`;
    for (const sideColumn of drive.querySelectorAll("[data-drive-left], [data-drive-right]")) {
      sideColumn.setAttribute("data-band", bandPx);
    }
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
    scale = 1;
    const step = inputConfig().zoom ?? 1;
    const full = step === "full";
    const below = drive.dataset.driveLayout === "below";
    drive.dataset.viewMode = full ? "full" : "fit";
    // K20: the current zoom is the current-value button (shared aria-current style); 1.2x/1.4x match neither.
    const mark = (b, on) => on ? b.setAttribute("aria-current", "true") : b.removeAttribute("aria-current");
    document.querySelectorAll("[data-drive-fit]").forEach(b => mark(b, step === 1));
    document.querySelectorAll("[data-drive-fill]").forEach(b => mark(b, full));
    element.view.removeAttribute("data-view-height");
    let crop;
    if (below) {
      // 세로 화면: 영상이 이미 폭을 채운다. 확대는 영상 높이를 늘리고 좌우를 자른다(cover).
      const width = element.view.getBoundingClientRect().width;
      const ratio = frameRatio(element.frame);
      const maxHeight = drive.clientHeight * (full ? 1 : 0.72);
      const fitHeight = width / ratio;
      const fill = Math.max(1, maxHeight / fitHeight);
      const z = full || step === "fill" ? fill : Math.min(Number(step) || 1, fill);
      if (z > 1.001) {
        element.frame.setAttribute("data-fit", "cover");
        element.view.setAttribute("data-view-height", `${Math.round(fitHeight * z)}px`);
      } else element.frame.removeAttribute("data-fit");
      drive.dataset.zoomed = String(z > 1.001);
      crop = {axis: "좌우", percent: Math.round((1 - 1 / z) * 100), z};
    } else {
      element.frame.removeAttribute("data-fit");
      const z = full ? 1 : zoomValue(step);
      scale = z;
      drive.dataset.zoomed = String(full || z > 1.001);
      crop = full ? {...coverCrop(), z: 1} : {axis: "위아래", percent: Math.round((1 - 1 / z) * 100), z};
    }
    element.zoomFact.hidden = crop.percent <= 0;
    element.zoomFact.textContent = crop.percent > 0 ? `${crop.axis} ${crop.percent}% 잘림 · 드래그하여 보기` : "";
    if (element.zoomButton) {
      element.zoomButton.textContent = full ? "전체화면"
        : step === "fill" ? "확대 가득" : crop.z > 1.001 ? `확대 ${crop.z.toFixed(1)}×` : "확대 맞춤";
    }
    applyPan();
  }
  // 설치 앱에서는 전체화면 API 로 상태 표시줄까지 숨긴다. 지원이 없으면 화면 안에서만 채운다.
  function syncFullscreen(full) {
    try {
      if (full && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
      if (!full && document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    } catch (error) { /* 지원 없음 */ }
  }
  function setZoom(next) {
    pan = {x: 0, y: 0};
    dragging = null;
    saveInputConfig({zoom: next});
    syncFullscreen(next === "full");
    applyZoom();
  }
  function cycleZoom() {
    const current = inputConfig().zoom ?? 1;
    const index = ZOOM_STEPS.findIndex((stepValue) => stepValue === current);
    const next = ZOOM_STEPS[(index + 1) % ZOOM_STEPS.length];
    setZoom(next);
  }

  const layoutObserver = new ResizeObserver(() => { applyLayout(); applyZoom(); });
  layoutObserver.observe(drive);
  const onFrame = () => { applyLayout(); applyZoom(); };
  element.frame.addEventListener("load", onFrame);
  applyLayout();

  return {
    applyZoom,
    cycleZoom,
    setZoom,
    close() {
      layoutObserver.disconnect();
      element.frame.removeEventListener("load", onFrame);
      for (const [name, callback] of [["pointerdown", panStart], ["pointermove", panMove],
        ["pointerup", panEnd], ["pointercancel", panEnd], ["lostpointercapture", panEnd]]) {
        element.view.removeEventListener(name, callback);
      }
      syncFullscreen(false);
      // 같은 section 에 다시 마운트된다 — 지난 배치·배율 표시를 남기지 않는다.
      for (const key of ["driveLayout", "viewMode", "zoomed"]) delete drive.dataset[key];
      for (const sideColumn of drive.querySelectorAll("[data-drive-left], [data-drive-right]")) {
        sideColumn.removeAttribute("data-band");
      }
      element.view.removeAttribute("data-view-height");
      for (const name of ["data-fit", "data-pan-x", "data-pan-y", "data-shift-x", "data-shift-y", "data-frame-scale"]) {
        element.frame.removeAttribute(name);
      }
    },
  };
}

// --- 마크업: 서버 텍스트로 HTML 을 만들지 않는다 ------------------------------
export function buildStage() {
  const stage = el("div", null, {"data-drive-stage": ""});
  const frame = el("img", null, {alt: "전방 카메라", "data-drive-frame": "", hidden: ""});
  const empty = el("ui-empty", "카메라 프레임 수신 대기", {"data-drive-empty": ""});
  const blocked = el("div", null, {"data-drive-blocked": "", hidden: ""});
  const retake = el("ui-button", "수동 모드 다시 잡기", {type: "button", "data-drive-retake": ""});
  retake.setAttribute("kind", "primary");
  blocked.append(el("ui-text", "", {scale: "value", "data-drive-blocked-reason": ""}), retake);
  // 영상 틀: 확대(D-363 §5) 때 넘치는 부분을 이 틀 안에서만 자른다.
  const view = el("div", null, {"data-drive-view": ""});
  // 자동 의도 띠: 가운데 눈금, 겨누는 점, 실제 조향 방향(D-364 §6)
  const intent = el("div", null, {"data-drive-intent": "", hidden: ""});
  const track = el("span", null, {"data-intent-track": ""});
  track.append(el("i", null, {"data-intent-centre": ""}), el("i", null, {"data-intent-target": ""}));
  intent.append(track, el("span", "", {"data-intent-steer": ""}));
  // 보정 중 띠(D-321 부록): 영상 위쪽. 다른 토큰의 보정이면 잠금 사유까지 여기 적는다.
  const calibration = el("div", null, {"data-drive-calibration": "", hidden: ""});
  calibration.append(el("ui-text", "", {scale: "value", "data-drive-calibration-title": ""}),
                     el("ui-status", "", {state: "warning", role: "none", "aria-live": "off", "data-drive-calibration-reason": ""}));
  view.append(frame, empty, intent, calibration);
  stage.append(view, buildHud(), blocked);
  return stage;
}

function buildHud() {
  // 머리는 속도 · 동작 · 연결 태그뿐이다(주역은 영상). 상한·응답·모드·배터리·영상 전송은 [data-drive-facts]에 두고
  // drive.js 가 도구 판으로 옮긴다. 조건부 표시(확대 잘림·보정 중·녹화·조도)만 머리에 남는다.
  const hud = el("div", null, {"data-drive-hud": ""});
  const gauge = el("div", null, {"data-drive-gauge": ""});
  gauge.append(
    el("span", EVIDENCE_LABEL.unavailable, {"data-drive-fact": "speed"}),
    el("ui-text", "m/s", {scale: "unit", hidden: ""}), // shown by drive.js once a speed is known
    el("span", "· 속도 확인 중", {"data-drive-fact": "turn"}),
  );
  const motion = el("span", MODE_LABEL.IDLE, {"data-drive-motion": "", "data-kind": "idle"});
  const link = el("span", "…", {"data-drive-fact": "link", "aria-live": "off"});
  const zoom = el("span", "", {"data-drive-fact": "zoom", hidden: ""});
  const activity = el("span", "보정 중", {"data-drive-fact": "activity", hidden: ""});
  const visibility = el("ui-status", "조도가 낮아 차선·물체를 판정할 수 없습니다", {
    "data-drive-visibility": "", state: "warning", role: "none", "aria-live": "off", hidden: ""});
  const facts = el("div", null, {"data-drive-facts": ""});
  facts.append(
    el("span", "", {"data-drive-fact": "cap"}),
    el("span", EVIDENCE_LABEL.unavailable, {"data-drive-fact": "latency"}),
    el("span", EVIDENCE_LABEL.unavailable, {"data-drive-fact": "mode"}),
    el("span", EVIDENCE_LABEL.unavailable, {"data-drive-fact": "battery"}),
  );
  hud.append(gauge, motion, link, zoom, activity, visibility, facts);
  return hud;
}

// 조작 버튼의 종류(D-345 공용 컨트롤): 고르는 것(속도·운전 모드)은 createChoiceGroup(native radio),
// 켜고 끄는 정밀은 kind=toggle(aria-pressed),
// 누르는 동안만 움직이는 페달·제자리·진행은 toggle(누르는 동안 .active 로 채워진다) + size primary.
// 진행은 tone="good" — 자동 대기(초록 테두리)와 자동 진행(초록 채움)이 HUD 의 초록 알약과 같은 말을 한다.
// 게임형 큰 표적은 styles.css 의 배치 규칙(min-height·폭)이 정한다 — 면·글자·테두리는 components.css.
export function buildControls(profile) {
  const controls = el("div", null, {"data-drive-controls": ""});
  // 좌: 속도·정밀 / 페달 / 제자리 회전   우: 2축 주행 스틱
  const left = el("div", null, {"data-drive-left": ""});
  const tune = el("div", null, {"data-drive-presets": ""});
  // 속도 프리셋: 입력 설정(inputs.js)과 같은 값이라 여기 한 곳에만 둔다. 값·잠금은 drive.js 가 채운다.
  const presetGroup = createChoiceGroup({id: "drive-preset", label: "속도", mode: "single",
    items: [["low", "저속"], ["mid", "보통"], ["high", "빠름"]].map(([value, label]) => ({value, label}))});
  presetGroup.element.setAttribute("data-drive-preset-row", "");
  presetGroup.element.querySelector("legend").classList.add("sr-only");   // the three chip words say "speed" on their own
  tune.append(presetGroup.element);
  if (profile.fine !== false) {
    const fine = el("ui-button", "정밀", {type: "button", "data-drive-fine": "", "aria-pressed": "false"});
    fine.setAttribute("kind", "toggle");
    tune.append(fine);
  }
  const pedals = el("div", null, {"data-drive-pedals": ""});
  const forward = el("ui-button", "전진", {type: "button", size: "primary", "data-drive-pedal": "forward"});
  forward.setAttribute("kind", "toggle");
  actionIcon(forward, "forward");
  forward.setAttribute("kind", "toggle");
  const reverse = el("ui-button", "후진", {type: "button", size: "primary", "data-drive-pedal": "reverse"});
  reverse.setAttribute("kind", "toggle");
  actionIcon(reverse, "reverse");
  reverse.setAttribute("kind", "toggle");
  pedals.append(forward, reverse);
  left.append(tune);
  const modeItems = [{value: "manual", label: "수동"}];
  if (profile.autonomy?.includes("line")) modeItems.push({value: "auto", label: "차선 자동"});
  // One value is no choice (K1 is 2-5): without line autonomy the group stays hidden.
  const modeGroup = createChoiceGroup({id: "drive-mode", label: "운전 모드", mode: "single", items: modeItems, value: "manual"});
  modeGroup.element.setAttribute("data-drive-modes", "");
  modeGroup.element.querySelector("legend").classList.add("sr-only");
  modeGroup.element.querySelector("input[value=manual]").setAttribute("data-drive-manual", "");
  modeGroup.element.querySelector("input[value=auto]")?.setAttribute("data-drive-auto", "");
  const modes = modeGroup.element; modes.hidden = modeItems.length < 2;
  left.append(modes);
  left.append(pedals);
  if (profile.autonomy?.includes("line")) {
    const go = el("ui-button", "진행 · 누르는 동안", {type: "button", size: "primary", tone: "good", "data-drive-go": "",
                                                    "aria-label": "차선 따라 진행(누르는 동안만)"});
    go.setAttribute("kind", "toggle");
    actionIcon(go, "forward");
    left.append(go);
  }
  if (profile.pivot !== false) {
    const pivots = el("div", null, {"data-drive-pivots": ""});
    const pivotLeft = el("ui-button", "좌회전", {type: "button", size: "primary", "data-drive-pivot": "left",
                                                  "aria-label": "제자리 좌회전(누르는 동안)"});
    pivotLeft.setAttribute("kind", "toggle");
    actionIcon(pivotLeft, "left");
    const pivotRight = el("ui-button", "우회전", {type: "button", size: "primary", "data-drive-pivot": "right",
                                                   "aria-label": "제자리 우회전(누르는 동안)"});
    pivotRight.setAttribute("kind", "toggle");
    actionIcon(pivotRight, "right");
    pivots.append(pivotLeft, pivotRight);
    left.append(pivots);
  }

  const right = el("div", null, {"data-drive-right": ""});
  const stick = el("div", null, {"data-drive-stick": "", role: "application",
                                 "aria-label": "주행 스틱 — 위 전진, 아래 후진, 좌우 조향, 옆으로만 밀면 제자리 회전"});
  stick.append(el("div", null, {"data-drive-stick-knob": ""}));
  right.append(stick);
  if (profile.pivot !== false) right.append(el("span", "아래에 회전 조작", {"data-drive-scroll-cue": ""}));

  controls.append(left, right);
  controls.presetGroup = presetGroup; controls.modeGroup = modeGroup;
  return controls;
}
