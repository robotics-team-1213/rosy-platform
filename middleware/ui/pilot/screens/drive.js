// 주행 화면(D-323 T7). 2축 스틱·홀드 페달·제자리 회전·게임패드·키보드가 모두 같은
// hold-to-drive 원칙 아래 stick.js 매핑을 공유한다. 상태 채널은 link.js,
// 영상은 vision.js(인증 JPEG 폴링). 서버 텍스트로 HTML 을 만들지 않는다.
//
// 부호: angular > 0 은 반시계(좌회전, REP-103). 화면 오른쪽 입력은 우회전이어야
// 한다 — 변환은 stick.js 한 곳에서만 한다.

import {postJson, whoami, api as apiGet, authHeaders, token, inPilotApp} from "../client.js";
import {createDriverStream, STREAM_STALE_WARN_MS} from "../vision.js";
import {createDeviceSession} from "../link.js";
import {createModelStatus, renderModels} from "../models.js";
import {driverFor} from "../drivers/registry.js";
import {
  setStickInput, setPedal, setPivot, releaseAll, currentCommandSource, stickMap,
  inputConfig, saveInputConfig, setServerLimits, currentLimits, setFineAllowed,
} from "../input-state.js";
import {mountInputs} from "./inputs.js";
import {slewCommand} from "../stick.js";
import {mountAutoMode, mountLanePerception} from "./drive-auto.js";
import {mountRobotRecording, mountBrowserRecording} from "./robot-recording.js";
import {readControls, profileFromBaseVelocity} from "../controls.js";
import {calibrationView} from "../calibration.js";
import {el, mountDriveView, buildStage, buildControls, actionIcon} from "./drive-view.js";
import {classifyOperation, saveCameraFile} from "/common/evidence.js";
import {HeadlessState, MODE_LABEL, evidenceAgeText, operatorModeLabel} from "/common/core_ui_logic.js";

const LOOP_MS = 100;
const STATE_POLL_MS = 500;
// ponytail: 1 s detects transport silence at the default 10 Hz; use a negotiated rate if slower streams matter.
const READBACK_GAP_MS = 2 * STATE_POLL_MS; // Server evidence still decides value freshness.
const DEG = 180 / Math.PI;
const PRESET_LABEL = {low: "저속", mid: "보통", high: "빠름"};
const LINK_LABEL = {
  CONNECTING: "상태 연결 중", OPEN: "상태 수신", RETRYING: "상태 재연결 중",
  FORBIDDEN: "상태 접근 거부", OFFLINE: "상태 연결 끊김", BLOCKED: "조종 차단",
};

// `profile` comes from the device's base_velocity control (D-411 B); `unsupported` lists the
// controls this screen cannot draw — shown, never fatal.
export function mountDrive(root, {onExit, profile: given, unsupported = []} = {}) {
  const gate = driverFor("pinky_core");
  const profile = given ?? gate.profile ?? {};
  setFineAllowed(profile.fine);
  const element = {};
  let engaged = false;
  // 이 화면이 실제로 MANUAL 을 잡았는가(engage 가 200). 잡은 적 없는 화면이 나가면서
  // IDLE 을 보내면 남(보정 주인)의 주행을 끊는다.
  let modeHeld = false;
  let perceptionPending = false;

  const drive = root;
  root.replaceChildren(buildStage(), buildControls(profile));
  if (unsupported.length) {
    const notes = el("div", null, {"data-drive-unsupported": ""});
    for (const control of unsupported) {
      notes.append(el("p", `지원하지 않는 조작부 · ${control.label || control.kind}`, {"data-control-unsupported": ""}));
    }
    root.querySelector("[data-drive-stage]").append(notes);
  }
  for (const [key, selector] of Object.entries({
    stage: "[data-drive-stage]", frame: "[data-drive-frame]", empty: "[data-drive-empty]",
    hud: "[data-drive-hud]", stick: "[data-drive-stick]", knob: "[data-drive-stick-knob]",
    forward: "[data-drive-pedal=forward]", reverse: "[data-drive-pedal=reverse]",
    pivotLeft: "[data-drive-pivot=left]", pivotRight: "[data-drive-pivot=right]",
    fine: "[data-drive-fine]", mode: "[data-drive-fact=mode]",
    battery: "[data-drive-fact=battery]", speed: "[data-drive-fact=speed]",
    turn: "[data-drive-fact=turn]", state: "[data-drive-fact=link]",
    latency: "[data-drive-fact=latency]", cap: "[data-drive-fact=cap]",
    visibility: "[data-drive-visibility]",
    motion: "[data-drive-motion]", blocked: "[data-drive-blocked]",
    blockedReason: "[data-drive-blocked-reason]", retake: "[data-drive-retake]",
    view: "[data-drive-view]", zoomFact: "[data-drive-fact=zoom]",
    go: "[data-drive-go]", autoToggle: "[data-drive-auto]",
    manual: "[data-drive-manual]", goal: "[data-drive-goal]",
    intent: "[data-drive-intent]", intentTarget: "[data-intent-target]",
    intentSteer: "[data-intent-steer]", controls: "[data-drive-controls]",
    calibration: "[data-drive-calibration]", calibrationTitle: "[data-drive-calibration-title]",
    calibrationReason: "[data-drive-calibration-reason]", activity: "[data-drive-fact=activity]",
  })) element[key] = root.querySelector(selector);
  // 지도 목표는 로봇 콘솔(/console)이다. 앱 프록시는 그 화면을 열지 않는다.
  if (inPilotApp() && element.goal) element.goal.hidden = true;

  function showMode(mode) {
    element.mode.textContent = operatorModeLabel(mode, "확인 필요");
    element.mode.title = mode;
  }

  function ageText(frame, channel) {
    const observed = Date.parse(frame?.evidence?.[channel]?.received_at);
    const reported = Date.parse(frame?.timestamp);
    return Number.isFinite(observed) && Number.isFinite(reported) && reported >= observed
      ? evidenceAgeText((reported - observed) / 1000) : " · 시각 없음";
  }

  function renderTelemetry(frame) {
    const evidence = new HeadlessState(frame);
    const velocity = frame?.velocity;
    const usableVelocity = typeof velocity?.linear === "number" && Number.isFinite(velocity.linear)
      && typeof velocity?.angular === "number" && Number.isFinite(velocity.angular);
    const velocityState = !frame ? "disconnected"
      : usableVelocity ? evidence.evidenceOf("velocity") : "unavailable";
    element.speed.dataset.evidence = velocityState;
    element.turn.dataset.evidence = velocityState;
    if (velocityState === "fresh" || velocityState === "delayed") {
      element.speed.textContent = Math.abs(velocity.linear).toFixed(2);
      const turn = velocity.angular * DEG;
      const direction = turn > 0.5 ? "↺" : turn < -0.5 ? "↻" : "·";
      element.turn.textContent = `${direction} ${Math.abs(turn).toFixed(0)}°/s`
        + (velocityState === "delayed" ? ` · 지연${ageText(frame, "velocity")}` : "");
    } else {
      element.speed.textContent = "—";
      element.turn.textContent = velocityState === "disconnected" ? "· 속도 연결 끊김" : "· 속도 정보 없음";
    }

    const percent = frame?.battery?.percent;
    const batteryState = !frame ? "disconnected"
      : typeof percent === "number" && Number.isFinite(percent)
        ? evidence.evidenceOf("battery") : "unavailable";
    element.battery.dataset.evidence = batteryState;
    element.battery.textContent = batteryState === "fresh" ? `${Math.round(percent)}%`
      : batteryState === "delayed" ? `${Math.round(percent)}% · 지연${ageText(frame, "battery")}`
      : batteryState === "disconnected" ? "배터리 연결 끊김" : "배터리 정보 없음";
  }

  // --- 보정 세션(D-321 부록): 누가 보정 중인지 보이고, 남의 보정이면 주행 조작을 잠근다 -----
  // 비상 정지(상단 막대)는 이 화면 밖에 있고 잠그지 않는다. 409 CALIBRATION_ACTIVE 가 최종 판정이다.
  let myTokenId = null;
  let identityPending = true;
  let calibrationLocked = false;
  let lastActivity = null;
  let whoamiTimer = null;
  // 이 기기의 토큰 id. 실패하면 늘어나는 간격(1→2→4→8 s, 최대 15 s)으로 다시 묻는다.
  // 401/403 은 토큰 문제라 다시 물어도 같다 — 그때는 멈추고 "남의 보정" 잠금으로 둔다.
  function askWhoami(delayMs = 1000) {
    whoami().then((me) => {
      if (me?.status === 200) {
        myTokenId = me.body?.id ?? null;
        identityPending = false;
      } else if (me?.status === 401 || me?.status === 403) {
        identityPending = false;
      } else {
        throw new Error(`whoami ${me?.status}`);
      }
      renderActivity(lastActivity);
    }).catch(() => {
      whoamiTimer = setTimeout(() => askWhoami(Math.min(delayMs * 2, 15000)), delayMs);
    });
  }
  askWhoami();
  function renderActivity(activity) {
    lastActivity = activity ?? null;
    const view = calibrationView(lastActivity, myTokenId, identityPending);
    element.calibration.hidden = !view.active;
    element.activity.hidden = !view.active;
    element.calibrationTitle.textContent = view.text;
    element.calibrationReason.textContent = view.active
      ? `${view.reason}${view.remaining == null ? "" : ` · 유지 ${view.remaining}초`}` : "";
    element.calibration.dataset.locked = String(view.locked);
    const lock = view.active && view.locked;
    if (lock === calibrationLocked) return;
    calibrationLocked = lock;
    if (lock) {
      releaseAll();
      auto?.release("calibration");
    }
    element.controls.toggleAttribute("data-locked", lock);
    element.controls.setAttribute("aria-disabled", String(lock));
    for (const button of element.controls.querySelectorAll("ui-button")) button.disabled = lock;
  }

  // --- 상태 채널: /ws/state(auth 첫 프레임) + REST teleop -------------------
  let lastSocketReadbackAt = -Infinity;
  const session = createDeviceSession({
    token: token(),
    openSocket: (url) => {
      const target = new URL(url, location.origin);
      target.protocol = target.protocol === "https:" ? "wss:" : "ws:";
      return new WebSocket(target);
    },
    schedule: (fn, ms) => {
      const id = setTimeout(fn, ms);
      return () => clearTimeout(id);
    },
    postJson,
    whoami,
    onState: (state) => {
      element.state.textContent = LINK_LABEL[state] ?? "상태 확인 필요";
      element.state.dataset.state = state;
      element.state.title = state;
      delete element.state.dataset.readback;
      if (["RETRYING", "OFFLINE", "FORBIDDEN"].includes(state)) {
        renderTelemetry(null);
        element.mode.textContent = "—";
      }
    },
    onSnapshot: (frame) => {
      lastSocketReadbackAt = Date.now();
      delete element.state.dataset.readback;
      element.state.textContent = LINK_LABEL[session.state()] ?? "상태 수신";
      renderTelemetry(frame);
      if (frame?.mode) showMode(frame.mode);
      if (frame && "activity" in frame) renderActivity(frame.activity);
    },
    onConflict: (detail) => {
      releaseAll();
      renderInputs();
      showBlocked(`조종이 차단되었습니다 — ${detail?.message ?? detail?.code ?? "이유를 확인하세요"}`);
    },
    onLatency: (ms, failed) => {
      element.latency.textContent = failed ? "조작 응답 시한 초과" : `조작 응답 ${Math.round(ms)}ms`;
      element.latency.dataset.slow = String(failed || ms > 250);
    },
  });
  session.open();

  // --- 영상: 인증 JPEG 폴링 --------------------------------------------------
  const {capture, vision, acceptPreview} = mountBrowserRecording({element, apiGet, authHeaders});

  // --- D-368: 운전자 MJPEG 스트림(폴링 대체, 끊기면 자동 복귀) ----------------
  // 운전자 판정은 서버가 한다(409 = 운전자 아님·이미 열림). 이 화면은 결과만 따른다:
  // 스트림이 붙으면 폴링을 끊고, 끊기면 폴링으로 돌아가 잠시 뒤 다시 시도한다.
  // 주석 쌍(annotated) 캡처는 원본 짝이 필요해 폴링만 가능하다 — raw 모드에서만 스트림.
  const videoFact = el("span", "영상 폴링", {"data-drive-fact": "video"});
  root.querySelector("[data-drive-facts]")?.append(videoFact);
  let streamAlive = true;
  let streaming = false;
  let retryTimer = null;
  function tryStream() {
    if (!streamAlive || streaming) return;
    if (capture.state().previewMode !== "raw") return;
    stream.start(false);
  }
  function scheduleStreamRetry(ms = 3000) {
    if (!streamAlive) return;
    clearTimeout(retryTimer);
    retryTimer = setTimeout(tryStream, ms);
  }
  const stream = createDriverStream({
    headers: () => authHeaders(),
    onFrame: (url, meta) => {
      if (!streaming) {
        streaming = true;
        vision.stop();   // 스트림이 붙었다 — 폴링의 대역폭을 돌려준다
      }
      acceptPreview(url, {blob: meta.blob, rawBlob: meta.blob, sequence: meta.seq,
                          source: meta.source, capturedAt: meta.capturedAt, previewMode: "raw"});
    },
    onStats: ({fps, ageMs}) => {
      videoFact.hidden = false;
      videoFact.textContent = `영상 ${fps}fps${ageMs == null ? "" : ` · ${Math.round(ageMs)}ms`}`;
      videoFact.dataset.stale = String(ageMs != null && ageMs > STREAM_STALE_WARN_MS);
    },
    onLost: ({status}) => {
      streaming = false;
      videoFact.textContent = status === 409 ? "영상 폴링 · 운전자 아님" : "영상 폴링";
      videoFact.dataset.stale = "false";
      vision.start();    // 폴링 복귀(D-368 §5) — start()는 이미 돌면 아무것도 안 한다
      scheduleStreamRetry();
    },
  });
  tryStream();

  // --- 모델(D-423 §3.6): 읽기 전용 상태, 교체는 rosy_ml CLI ------------------
  const modelPanel = document.createElement("details");
  modelPanel.className = "pilot-models";
  const modelList = document.createElement("ul");
  modelPanel.append(Object.assign(document.createElement("summary"), {textContent: "모델"}), modelList);
  element.hud.append(modelPanel);
  const models = createModelStatus({
    apiGet, onUpdate: (rows) => renderModels(modelList, rows),
    schedule: (fn, ms) => { const id = setTimeout(fn, ms); return () => clearTimeout(id); },
  });
  // 접힌 동안은 묻지 않는다(검토 L10): 열면 시작, 닫으면 멈춘다.
  modelPanel.addEventListener("toggle", () => { modelPanel.open ? models.start() : models.stop(); });

  // 태블릿 실측: 누른 지 ~0.5 s 에 Android 길게 누르기 메뉴(카메라 이미지면 "이미지 복사·
  // 다운로드")가 떠서 누르고 있던 터치를 가로챘다. 주행 화면에서는 어디서도 띄우지 않는다.
  const blockContextMenu = (event) => event.preventDefault();
  root.addEventListener("contextmenu", blockContextMenu);

  // --- 배치·배율(D-363): drive-view.js ------------------------------------
  const view = mountDriveView(drive, element);

  // --- 입력: 2축 스틱(노브가 손가락을 따라간다) -------------------------------
  // 잡기 구역(styles.css)은 링보다 넓다. 링 안에서 누르면 링 중심이 0, 링 밖(구역 안)에서
  // 누르면 그 자리가 0 이다(떠 있는 원점 — 닿자마자 최대 편향으로 출발하지 않는다). 그때 링이
  // 손가락 밑으로 옮겨와 원점을 보이고, 놓으면 제자리로 돌아간다.
  const stick = element.stick;
  let stickPointer = null;
  let origin = null;               // {x, y, r}: 이번 누름의 0 점(화면 좌표)과 링 반지름
  function applyStick(event) {
    const radius = origin.r;
    let dx = (event.clientX - origin.x) / radius;
    let dy = (event.clientY - origin.y) / radius;
    const mag = Math.hypot(dx, dy);
    if (mag > 1) { dx /= mag; dy /= mag; }
    setStickInput(dx, -dy);        // 화면 y 는 아래가 + — 위로 밀면 전진
    element.knob.setAttribute("data-knob-x", `${dx * radius * 0.62}px`);
    element.knob.setAttribute("data-knob-y", `${dy * radius * 0.62}px`);
  }
  function releaseStick() {
    stickPointer = null;
    origin = null;
    setStickInput(0, 0);
    element.knob.removeAttribute("data-knob-x");
    element.knob.removeAttribute("data-knob-y");
    stick.removeAttribute("data-float-x");
    stick.removeAttribute("data-float-y");
    stick.classList.remove("active", "floating");
  }
  stick.addEventListener("pointerdown", (event) => {
    if (calibrationLocked) return;
    takeover();
    stickPointer = event.pointerId;
    stick.setPointerCapture(event.pointerId);
    stick.classList.add("active");
    const rect = stick.getBoundingClientRect();
    const centre = {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, r: rect.width / 2};
    const outside = Math.hypot(event.clientX - centre.x, event.clientY - centre.y) > centre.r;
    origin = outside ? {x: event.clientX, y: event.clientY, r: centre.r} : centre;
    if (outside) {
      // Only the drawing is clamped: the ring stays inside its column (phone: no clipped top),
      // while the zero point stays under the finger.
      const column = (stick.closest("[data-drive-right]") ?? stick.parentElement).getBoundingClientRect();
      const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
      const tx = clamp(event.clientX - centre.x, column.left - rect.left, column.right - rect.right);
      const ty = clamp(event.clientY - centre.y, column.top - rect.top, column.bottom - rect.bottom);
      stick.classList.add("floating");
      stick.setAttribute("data-float-x", `${tx}px`);
      stick.setAttribute("data-float-y", `${ty}px`);
    }
    applyStick(event);
  });
  stick.addEventListener("pointermove", (event) => {
    if (event.pointerId === stickPointer) applyStick(event);
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    stick.addEventListener(name, (event) => {
      if (event.pointerId === stickPointer) releaseStick();
    });
  }

  // --- 입력: 홀드 버튼(페달·제자리 회전) — 손을 떼거나 벗어나면 즉시 해제 ----
  function holdButton(node, onHold) {
    const set = (value) => {
      if (value) takeover();
      onHold(value);
      node.classList.toggle("active", value);
      if (value && navigator.vibrate) navigator.vibrate(10);
    };
    node.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      if (calibrationLocked) return;
      set(true);
    });
    for (const name of ["pointerup", "pointercancel", "pointerleave"]) {
      node.addEventListener(name, () => set(false));
    }
    node.addEventListener("contextmenu", (event) => event.preventDefault());
  }
  holdButton(element.forward, (value) => setPedal("forward", value));
  holdButton(element.reverse, (value) => setPedal("reverse", value));
  if (element.pivotLeft) holdButton(element.pivotLeft, (value) => setPivot("left", value));
  if (element.pivotRight) holdButton(element.pivotRight, (value) => setPivot("right", value));

  // --- 보조 자율(D-344)·의도 띠(D-364 §6): drive-auto.js ---------------------
  const auto = mountAutoMode({drive, element, apiGet, releaseAll, onIdle: () => {
    renderCap();             // 수동 상한으로 되돌린다
    session.resume();        // 자동이 끝나면 수동 명령 경로를 다시 연다
    lastCommand = {linear: 0, angular: 0, pivot: false};
  }, blocked: () => perceptionPending || calibrationLocked || !engaged});
  const perception = mountLanePerception(element.hud, {apiGet,
    onPending(value) {
      perceptionPending = value;
      if (element.go) {
        element.go.disabled = value || calibrationLocked;
        if (value) element.go.setAttribute("reason", "인식 적용 중"); else element.go.removeAttribute("reason");
      }
    },
    blocked: () => calibrationLocked || auto.active(),
  });
  // The stop action is explicit; choosing perception never takes motion ownership.
  const idleButton = el("ui-button", "정지 · 설정", {type: "button", kind: "quiet", "data-drive-idle": ""});
  idleButton.setAttribute("kind", "quiet");
  element.hud.append(idleButton);
  idleButton.addEventListener("click", async () => {
    if (perceptionPending || calibrationLocked || auto.active()) return;
    engaged = false;
    releaseAll(); clearKeys(); releaseStick();
    await postJson("/api/v1/teleop", {linear: 0, angular: 0}).catch(() => null);
    session.hidden();
    const response = await gate.disengage(postJson).catch(() => null);
    showBlocked(response?.status === 200 ? "정지 · 설정 중 — 다시 잡으면 수동 운전" : "정지 모드 확인 실패 — 상태를 확인하세요");
    perception.refresh();
  });
  element.goal.addEventListener("click", () => {
    if (inPilotApp() || element.goal.disabled || perceptionPending) return;
    teardown(() => location.assign("/console"));
  });
  function takeover() {
    auto.takeover();
  }

  // --- 입력: 키보드(데스크톱 검증용). Q/E 는 제자리 회전 --------------------
  const keys = {up: false, down: false, left: false, right: false, pivotLeft: false, pivotRight: false};
  const KEY_MAP = {ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down",
                   ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right",
                   ...(profile.pivot !== false ? {KeyQ: "pivotLeft", KeyE: "pivotRight"} : {})};
  const onKey = (event) => {
    const key = KEY_MAP[event.code];
    if (!key) return;
    if (event.type === "keyup") {
      keys[key] = false;         // 떼기는 어디서 일어나도 받는다 — 걸러내면 키가 눌린 채 남는다
      return;
    }
    if (event.target?.closest?.("input, textarea, select, summary")) return;
    keys[key] = true;
    event.preventDefault();
  };
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", onKey);
  const clearKeys = () => {
    for (const key of Object.keys(keys)) keys[key] = false;
  };
  const onFocusIn = (event) => {
    if (event.target?.closest?.("input, textarea, select, summary")) clearKeys();
  };
  window.addEventListener("focusin", onFocusIn);
  const onBlur = () => {
    clearKeys();
    releaseAll();
    releaseStick();
  };
  window.addEventListener("blur", onBlur);

  // 게임패드: 왼쪽 스틱 = 주행, LB/RB(버튼 4/5) = 제자리 회전 좌/우.
  function gamepadSource() {
    if (!navigator.getGamepads) return null;
    const pad = [...navigator.getGamepads()].find(Boolean);
    if (!pad) return null;
    const lb = pad.buttons[4]?.pressed;
    const rb = pad.buttons[5]?.pressed;
    if (profile.pivot !== false && lb !== rb) return {kind: "pivot", dir: lb ? 1 : -1};
    const x = pad.axes[0] ?? 0;
    const y = -(pad.axes[1] ?? 0);
    return x !== 0 || y !== 0 ? {kind: "pad", x, y} : null;
  }

  function keySource() {
    if (keys.pivotLeft !== keys.pivotRight) return {kind: "pivot", dir: keys.pivotLeft ? 1 : -1};
    if (keys.up || keys.down || keys.left || keys.right) return {kind: "keys", ...keys};
    return null;
  }

  // --- hold-to-drive 루프(100ms) — 조종 사실은 녹화 타임라인에 기록 ----------
  let lastCommand = {linear: 0, angular: 0, pivot: false};
  let lastTickAt = performance.now();
  const loop = setInterval(async () => {
    const tickAt = performance.now();
    const dt = (tickAt - lastTickAt) / 1000;
    lastTickAt = tickAt;
    if (!engaged || calibrationLocked || perceptionPending) return;
    const source = currentCommandSource() ?? keySource() ?? gamepadSource();
    if (source && auto.active()) takeover();   // 키·게임패드 개입도 자동을 끈다
    if (auto.active()) return;                  // 자동 중에는 수동 명령을 보내지 않는다(CORE 모드 충돌 방지)
    // 가속은 램프로, 감속·정지는 즉시(stick.slewCommand).
    const command = slewCommand(lastCommand, stickMap(source), dt);
    lastCommand = command;
    renderMotion(command);
    const response = await session.command({linear: command.linear, angular: command.angular});
    if (response?.status !== undefined) {
      capture.recordAction(classifyOperation("POST", "/api/v1/teleop", response.status));
    }
  }, LOOP_MS);

  function renderMotion(command) {
    const moving = command.linear !== 0 || command.angular !== 0;
    element.motion.dataset.kind = !moving ? "idle" : command.pivot ? "pivot" : "drive";
    const side = command.angular > 0 ? "좌" : command.angular < 0 ? "우" : "";
    element.motion.textContent = !moving ? MODE_LABEL.IDLE
      : command.pivot ? `제자리 ${side}회전`
      : `${command.linear >= 0 ? "전진" : "후진"}${side ? ` · ${side}` : ""}`;
  }

  // --- 조종 중 화면 꺼짐 방지(D-365/T7) + 이탈 즉시 0 -----------------------
  let wakeLock = null;
  const requestWakeLock = async () => {
    try { wakeLock = await navigator.wakeLock.request("screen"); } catch (error) { /* 지원 없음 */ }
  };
  requestWakeLock();
  const onVisibility = () => {
    if (document.visibilityState === "visible") {
      requestWakeLock();
      session.visible();
    } else {
      onBlur();
      auto.release("hidden");
      session.hidden();
    }
  };
  document.addEventListener("visibilitychange", onVisibility);

  // --- CORE 수동 한도(프리셋의 기준) ------------------------------------------
  // D-411 B: the device's base_velocity carries the live manual limits; they cap the CORE
  // safety limits (0 = drive announced but held at standstill — shown as such). Both are read
  // together here so a limit changed between the gate and this screen is not stale.
  let announced = {max_linear: profile.max_linear ?? null, max_angular: profile.max_angular ?? null};
  async function loadLimits() {
    const [response, caps] = await Promise.all([
      apiGet("/api/v1/safety/state").catch(() => null),
      apiGet("/api/v1/system/capabilities").catch(() => null),
    ]);
    const base = caps?.status === 200
      ? readControls(caps.body?.controls)?.find((control) => control.kind === "base_velocity") : null;
    if (base) {
      const fresh = profileFromBaseVelocity(base);
      announced = {max_linear: fresh.max_linear, max_angular: fresh.max_angular};
    }
    const goalReady = caps?.body?.navigation?.goal_navigation === true;
    element.goal.disabled = !goalReady;
    if (goalReady) element.goal.removeAttribute("reason");
    else element.goal.setAttribute("reason", caps?.body?.navigation?.reason || "이 기기는 목표 내비게이션을 지원하지 않습니다");
    const limits = response?.status === 200 ? response.body?.limits : null;
    if (limits || base) setServerLimits(withProfileLimits(limits));
    renderCap();
  }
  function withProfileLimits(limits) {
    const capped = {...(limits ?? {})};
    if (announced.max_linear != null) capped.manual_linear = Math.min(announced.max_linear, capped.manual_linear ?? Infinity);
    if (announced.max_angular != null) capped.manual_angular = Math.min(announced.max_angular, capped.manual_angular ?? Infinity);
    return capped;
  }
  function renderCap() {
    const limits = currentLimits();
    const standstill = limits.linear === 0 && limits.angular === 0;
    element.cap.dataset.standstill = String(standstill);
    element.cap.textContent = standstill ? "정지로 제한됨 · 상한 0"
      : `상한 ${limits.linear.toFixed(2)} m/s · ${Math.round(limits.angular * DEG)}°/s`;
  }
  if (announced.max_linear != null || announced.max_angular != null) setServerLimits(withProfileLimits(null));
  loadLimits();

  // --- 로봇 상태 폴링: 실측 속도·회전율 ---------------------------------------
  const stateTimer = setInterval(async () => {
    const state = await apiGet("/api/v1/robot/state", {timeoutMs: READBACK_GAP_MS}).catch(() => null);
    if (!state || state.status !== 200) {
      if (Date.now() - lastSocketReadbackAt >= READBACK_GAP_MS) {
        renderTelemetry(null);
        element.mode.textContent = "—";
        if (session.state() === "OPEN") {
          element.state.textContent = "상태 수신 없음";
          element.state.dataset.readback = "silent";
        }
      }
      return;
    }
    delete element.state.dataset.readback;
    element.state.textContent = LINK_LABEL[session.state()] ?? "상태 수신";
    renderTelemetry(state.body);
    if (state.body?.mode) showMode(state.body.mode);
    renderActivity(state.body?.activity);
  }, STATE_POLL_MS);

  // --- HUD 액션 --------------------------------------------------------------
  const actions = el("ui-actions");
  const browserLabel = el("label", "브라우저 확인 영상", {class: "ui-field-label"});
  const browserMode = el("select", null, {class: "ui-field", "data-browser-record-mode": ""});
  browserMode.className = "ui-field";
  for (const [value, label] of [["raw", "표시 없는 원본"], ["annotated", "원본 + 모델 표시본"]]) {
    const option = el("option", label); option.value = value; browserMode.append(option);
  }
  browserLabel.append(browserMode); element.browserMode = browserMode;
  browserMode.addEventListener("change", () => {
    if (!capture.setPreviewMode(browserMode.value)) browserMode.value = capture.state().previewMode;
    else {
      streaming = false;
      stream.stop();       // 주석 쌍 모드는 스트림이 못 섬긴다 — 폴링 짝으로 갈아탄다
      vision.stop(); vision.start();
      if (browserMode.value === "raw") scheduleStreamRetry(500);
      else videoFact.textContent = "영상 폴링";
    }
  });
  const shotButton = el("ui-button", "촬영", {type: "button", "data-evidence-shot": ""});
  shotButton.setAttribute("kind", "quiet");
  shotButton.addEventListener("click", () => capture.screenshot("pc"));
  const recordButton = el("ui-button", "화면 녹화", {type: "button", "data-evidence-record": ""});
  recordButton.setAttribute("kind", "quiet");
  recordButton.addEventListener("click", () => {
    if (capture.state().recording) capture.stop();
    else capture.start();
  });
  element.shotButton = shotButton;
  element.recordButton = recordButton;
  const saveVideo = el("ui-button", "영상 다시 받기", {type: "button", "data-evidence-save": ""});
  saveVideo.setAttribute("kind", "quiet"); saveVideo.disabled = true; saveVideo.reason = "저장할 영상이 없습니다";
  saveVideo.addEventListener("click", () => { capture.saveVideo("pc"); capture.saveOperations(); });
  element.saveVideo = saveVideo;
  const zoomButton = el("ui-button", "확대 맞춤", {type: "button", "data-drive-zoom": ""});
  zoomButton.setAttribute("kind", "quiet");
  zoomButton.addEventListener("click", () => view.cycleZoom());
  element.zoomButton = zoomButton;
  const fitButton = el("ui-button", "전체 영상", {type: "button", "data-drive-fit": "", "aria-label": "전체 영상 · 잘림 없이 보기"});
  fitButton.setAttribute("kind", "segment");
  actionIcon(fitButton, "fit");
  fitButton.setAttribute("kind", "segment");
  element.fitButton = fitButton;
  fitButton.addEventListener("click", () => view.setZoom(1));
  const fillButton = el("ui-button", "화면 채우기", {type: "button", "data-drive-fill": "", "aria-label": "화면 채우기 · 확대 후 드래그하여 보기"});
  fillButton.setAttribute("kind", "segment");
  actionIcon(fillButton, "expand");
  fillButton.setAttribute("kind", "segment");
  element.fillButton = fillButton;
  fillButton.addEventListener("click", () => view.setZoom("full"));
  const inputsButton = el("ui-button", "입력", {type: "button", "data-drive-inputs": ""});
  inputsButton.setAttribute("kind", "quiet");
  let inputsPanel = null;
  let closeInputs = null;
  inputsButton.addEventListener("click", () => {
    if (closeInputs) {
      closeInputs();
      return;
    }
    hideTools();
    inputsPanel = el("div", null, {"data-inputs-panel": ""});
    root.querySelector("[data-drive-stage]").append(inputsPanel);
    closeInputs = mountInputs(inputsPanel, {onClose: () => {
      inputsPanel?.remove();
      inputsPanel = null;
      closeInputs = null;
      renderInputs();
      toolsButton.focus();
    }, onChange: renderInputs});
  });
  const exit = el("ui-button", "조종 종료", {type: "button", "data-drive-exit": ""});
  exit.setAttribute("kind", "quiet");
  exit.addEventListener("click", () => teardown());
  // D-411 A: 로봇 학습 녹화(카메라 유닛 bag) — 위의 "화면 녹화"(이 기기 브라우저)와 다르다.
  const robotRecordButton = el("ui-button", "로봇 녹화", {type: "button", "data-robot-record": ""});
  robotRecordButton.setAttribute("kind", "quiet");
  const recordingsButton = el("ui-button", "녹화본", {type: "button", "data-recordings-open": ""});
  recordingsButton.setAttribute("kind", "quiet");
  const recordingFact = el("span", null, {"data-drive-fact": "recording", hidden: ""});
  const toolsButton = el("ui-button", "도구", {type: "button", "data-drive-tools": "", "aria-expanded": "false", "aria-controls": "pilot-drive-tools"});
  toolsButton.setAttribute("kind", "quiet");
  actionIcon(toolsButton, "tools");
  toolsButton.setAttribute("kind", "quiet");
  const tools = el("section", null, {id: "pilot-drive-tools", "data-drive-tools-panel": "", "aria-label": "영상과 조종 도구", hidden: ""});
  const toolsActions = el("ui-actions");
  toolsActions.append(zoomButton, browserLabel, shotButton, recordButton, saveVideo, robotRecordButton, recordingsButton, inputsButton);
  tools.append(el("ui-text", "영상·녹화·조종 설정", {scale: "label"}), toolsActions);
  const closeTools = el("ui-button", "닫기", {kind: "quiet", type: "button"});
  closeTools.setAttribute("kind", "quiet");
  function hideTools() {
    tools.hidden = true; toolsButton.setAttribute("aria-expanded", "false");
  }
  closeTools.addEventListener("click", () => {
    tools.hidden = true; toolsButton.setAttribute("aria-expanded", "false"); toolsButton.focus();
  });
  toolsActions.append(closeTools);
  toolsButton.addEventListener("click", () => {
    robotRecording.closeSheet();
    closeInputs?.();
    tools.hidden = !tools.hidden;
    toolsButton.setAttribute("aria-expanded", String(!tools.hidden));
  });
  root.querySelector("[data-drive-stage]").append(tools);
  recordingsButton.addEventListener("click", hideTools);
  actionIcon(exit, "back");
  actions.append(fitButton, fillButton, toolsButton, exit);
  element.hud.append(recordingFact, actions);
  const compactHud = window.matchMedia("(width < 22rem) and (height < 40rem)");
  const lanePanel = element.hud.querySelectorAll("details.pilot-models")[1];
  function placeCompactTools() {
    hideTools();
    modelPanel.open = false;
    lanePanel.open = false;
    if (compactHud.matches) {
      tools.insertBefore(modelPanel, toolsActions);
      tools.insertBefore(lanePanel, toolsActions);
      toolsActions.prepend(fitButton, fillButton);
    } else {
      element.hud.insertBefore(modelPanel, idleButton);
      element.hud.insertBefore(lanePanel, idleButton);
      actions.prepend(fitButton, fillButton);
    }
  }
  compactHud.addEventListener("change", placeCompactTools);
  placeCompactTools();
  const robotRecording = mountRobotRecording({
    toggle: robotRecordButton, detail: recordingFact, openButton: recordingsButton,
    sheetHost: root, anchor: element.hud, save: saveCameraFile,
    returnFocus: toolsButton,
  });
  view.applyZoom();

  // --- 프리셋·정밀 --------------------------------------------------------
  function renderInputs() {
    const config = inputConfig();
    const row = root.querySelector("[data-drive-preset-row]");
    row.replaceChildren();
    for (const name of ["low", "mid", "high"]) {
      const button = el("ui-button", PRESET_LABEL[name], {type: "button", "data-preset": name});
      button.setAttribute("kind", "segment");
      button.setAttribute("aria-pressed", String(config.preset === name));
      button.disabled = calibrationLocked;
      button.addEventListener("click", () => {
        saveInputConfig({preset: name});
        renderInputs();
      });
      row.append(button);
    }
    element.fine?.setAttribute("aria-pressed", String(Boolean(config.fine)));
    renderCap();
  }
  element.fine?.addEventListener("click", () => {
    saveInputConfig({fine: !inputConfig().fine});
    renderInputs();
  });
  renderInputs();

  // --- 진입: 수동 모드를 잡은 뒤에만 명령을 보낸다 ------------------------------
  // 먼저 보내면 IDLE 상태의 첫 teleop 이 409 MODE_CONFLICT 로 세션을 막는다.
  async function engage() {
    if (perceptionPending) return;
    hideBlocked();
    const response = await gate.engage(postJson).catch(() => null);
    if (response?.status === 200) {
      engaged = true;
      modeHeld = true;
      session.resume();
      return;
    }
    engaged = false;
    const detail = response?.body?.detail;
    showBlocked(`수동 모드 전환 실패 — ${detail?.message ?? detail ?? response?.status ?? "연결 없음"}`);
  }
  function showBlocked(message) {
    element.blockedReason.textContent = message;
    element.blocked.hidden = false;
  }
  function hideBlocked() {
    element.blocked.hidden = true;
  }
  element.retake.addEventListener("click", () => engage());
  engage();

  function teardown(after) {
    engaged = false;
    auto.release("exit");
    clearInterval(loop);
    clearInterval(stateTimer);
    closeInputs?.();
    if (capture.state().recording) capture.stop();
    robotRecording.stopIfOwned().finally(() => robotRecording.dispose());
    releaseAll();
    session.hidden();
    session.close?.();
    // D-321 부록: 잡은 적 없거나 남의 보정으로 잠긴 화면은 모드를 돌려놓지 않는다 — /mode IDLE 은
    // 누구에게나 열려 있어서, 그대로 보내면 보정 주인의 MANUAL 을 끊는다.
    if (modeHeld && !calibrationLocked) gate.disengage(postJson).catch(() => {});
    modeHeld = false;
    clearTimeout(whoamiTimer);
    streamAlive = false;
    clearTimeout(retryTimer);
    stream.stop();
    vision.stop();
    models.stop();
    perception.dispose();
    compactHud.removeEventListener("change", placeCompactTools);
    window.removeEventListener("keydown", onKey);
    window.removeEventListener("keyup", onKey);
    window.removeEventListener("blur", onBlur);
    window.removeEventListener("focusin", onFocusIn);
    root.removeEventListener("contextmenu", blockContextMenu);
    view.close();
    document.removeEventListener("visibilitychange", onVisibility);
    wakeLock?.release().catch(() => {});
    wakeLock = null;
    onExit?.();
    if (typeof after === "function") after();
  }
}
