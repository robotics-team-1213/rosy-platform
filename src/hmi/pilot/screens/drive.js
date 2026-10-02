// 주행 화면(D-323 T7). 2축 스틱·홀드 페달·제자리 회전·게임패드·키보드가 모두 같은
// hold-to-drive 원칙 아래 stick.js 매핑을 공유한다. 상태 채널은 link.js,
// 영상은 vision.js(인증 JPEG 폴링). 서버 텍스트로 HTML 을 만들지 않는다.
//
// 부호: angular > 0 은 반시계(좌회전, REP-103). 화면 오른쪽 입력은 우회전이어야
// 한다 — 변환은 stick.js 한 곳에서만 한다.

import {postJson, whoami, api as apiGet, authHeaders, token} from "../client.js";
import {createDeviceSession} from "../link.js";
import {createVisionPreview} from "../vision.js";
import {driverFor} from "../drivers/registry.js";
import {
  setStickInput, setPedal, setPivot, releaseAll, currentCommandSource, stickMap,
  inputConfig, saveInputConfig, setServerLimits, currentLimits,
} from "../input-state.js";
import {mountInputs} from "./inputs.js";
import {slewCommand} from "../stick.js";
import {mountAutoMode} from "./drive-auto.js";
import {mountRobotRecording} from "./robot-recording.js";
import {calibrationView} from "../calibration.js";
import {el, mountDriveView, buildStage, buildControls} from "./drive-view.js";
import {createCameraCapture, classifyOperation, saveCameraFile} from "/common/evidence.js";
import {MODE_LABEL} from "/common/core_ui_logic.js";

const LOOP_MS = 100;
const STATE_POLL_MS = 500;
const DEG = 180 / Math.PI;
const PRESET_LABEL = {low: "저", mid: "중", high: "고"};

export function mountDrive(root, {onExit} = {}) {
  const gate = driverFor("pinky_core");
  const profile = gate.profile ?? {};
  const element = {};
  let engaged = false;
  // 이 화면이 실제로 MANUAL 을 잡았는가(engage 가 200). 잡은 적 없는 화면이 나가면서
  // IDLE 을 보내면 남(보정 주인)의 주행을 끊는다.
  let modeHeld = false;

  const drive = root;
  root.replaceChildren(buildStage(), buildControls(profile));
  for (const [key, selector] of Object.entries({
    stage: "[data-drive-stage]", frame: "[data-drive-frame]", empty: "[data-drive-empty]",
    hud: "[data-drive-hud]", stick: "[data-drive-stick]", knob: "[data-drive-stick-knob]",
    forward: "[data-drive-pedal=forward]", reverse: "[data-drive-pedal=reverse]",
    pivotLeft: "[data-drive-pivot=left]", pivotRight: "[data-drive-pivot=right]",
    fine: "[data-drive-fine]", mode: "[data-drive-fact=mode]",
    battery: "[data-drive-fact=battery]", speed: "[data-drive-fact=speed]",
    turn: "[data-drive-fact=turn]", state: "[data-drive-fact=link]",
    latency: "[data-drive-fact=latency]", cap: "[data-drive-fact=cap]",
    motion: "[data-drive-motion]", blocked: "[data-drive-blocked]",
    blockedReason: "[data-drive-blocked-reason]", retake: "[data-drive-retake]",
    view: "[data-drive-view]", zoomFact: "[data-drive-fact=zoom]",
    go: "[data-drive-go]", autoToggle: "[data-drive-auto]",
    intent: "[data-drive-intent]", intentTarget: "[data-intent-target]",
    intentSteer: "[data-intent-steer]", controls: "[data-drive-controls]",
    calibration: "[data-drive-calibration]", calibrationTitle: "[data-drive-calibration-title]",
    calibrationReason: "[data-drive-calibration-reason]", activity: "[data-drive-fact=activity]",
  })) element[key] = root.querySelector(selector);

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
    onState: (state) => { element.state.textContent = state; element.state.dataset.state = state; },
    onSnapshot: (frame) => {
      const percent = frame?.battery?.percent;
      if (percent !== undefined && percent !== null) element.battery.textContent = `${Math.round(percent)}%`;
      if (frame?.mode) element.mode.textContent = frame.mode;
      if (frame && "activity" in frame) renderActivity(frame.activity);
    },
    onConflict: (detail) => {
      releaseAll();
      renderInputs();
      showBlocked(`조종이 차단되었습니다 — ${detail?.message ?? detail?.code ?? "이유를 확인하세요"}`);
    },
    onLatency: (ms, failed) => {
      element.latency.textContent = failed ? "시한 초과" : `${Math.round(ms)}ms`;
      element.latency.dataset.slow = String(failed || ms > 250);
    },
  });
  session.open();

  // --- 영상: 인증 JPEG 폴링 --------------------------------------------------
  const capture = createCameraCapture({
    save: saveCameraFile,
    storeOnRobot: null,          // 로봇 SD 업로드는 dashboard 경로 재사용 예정(후속).
    onChange: (state) => {
      if (!element.frame.hidden) element.empty.textContent = state.message;
      if (element.shotButton) element.shotButton.disabled = !state.ready;
      if (element.recordButton) {
        element.recordButton.disabled = !state.supported;
        element.recordButton.textContent = state.recording ? "화면 녹화 중지" : "화면 녹화";
      }
    },
  });

  const vision = createVisionPreview({
    apiGet,
    fetchFrame: async (path) => {
      const response = await fetch(path, {headers: authHeaders(), cache: "no-store"});
      // 409·429 본문(JSON)을 이미지로 띄우지 않는다 — 거부하면 다음 틱에 다시 당긴다.
      if (!response.ok) throw new Error(`frame ${response.status}`);
      return response.blob();
    },
    onFrame: (url, meta) => {
      element.frame.src = url;
      element.frame.hidden = false;
      element.empty.hidden = true;
      const image = new Image();
      image.onload = () => capture.acceptFrame({
        image, blob: meta.blob, sequence: meta.seq, source: "front",
        capturedAt: meta.at / 1000,
      });
      image.src = url;
    },
    onUnavailable: (message) => {
      element.frame.hidden = true;
      element.empty.hidden = false;
      element.empty.textContent = message;
      capture.unavailable(message);
    },
  });
  vision.start();

  // 태블릿 실측: 누른 지 ~0.5 s 에 Android 길게 누르기 메뉴(카메라 이미지면 "이미지 복사·
  // 다운로드")가 떠서 누르고 있던 터치를 가로챘다. 주행 화면에서는 어디서도 띄우지 않는다.
  const blockContextMenu = (event) => event.preventDefault();
  root.addEventListener("contextmenu", blockContextMenu);

  // --- 배치·배율(D-363): drive-view.js ------------------------------------
  const view = mountDriveView(drive, element);

  // --- 입력: 2축 스틱(노브가 손가락을 따라간다) -------------------------------
  const stick = element.stick;
  let stickPointer = null;
  function applyStick(event) {
    const rect = stick.getBoundingClientRect();
    const radius = rect.width / 2;
    let dx = (event.clientX - (rect.left + radius)) / radius;
    let dy = (event.clientY - (rect.top + radius)) / radius;
    const mag = Math.hypot(dx, dy);
    if (mag > 1) { dx /= mag; dy /= mag; }
    setStickInput(dx, -dy);        // 화면 y 는 아래가 + — 위로 밀면 전진
    element.knob.style.transform =
      `translate(calc(-50% + ${dx * radius * 0.62}px), calc(-50% + ${dy * radius * 0.62}px))`;
  }
  function releaseStick() {
    stickPointer = null;
    setStickInput(0, 0);
    element.knob.style.transform = "translate(-50%, -50%)";
    stick.classList.remove("active");
  }
  stick.addEventListener("pointerdown", (event) => {
    if (calibrationLocked) return;
    takeover();
    stickPointer = event.pointerId;
    stick.setPointerCapture(event.pointerId);
    stick.classList.add("active");
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
  }});
  function takeover() {
    auto.takeover();
  }

  // --- 입력: 키보드(데스크톱 검증용). Q/E 는 제자리 회전 --------------------
  const keys = {up: false, down: false, left: false, right: false, pivotLeft: false, pivotRight: false};
  const KEY_MAP = {ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down",
                   ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right",
                   KeyQ: "pivotLeft", KeyE: "pivotRight"};
  const onKey = (event) => {
    const key = KEY_MAP[event.code];
    if (!key) return;
    if (event.type === "keyup") {
      keys[key] = false;         // 떼기는 어디서 일어나도 받는다 — 걸러내면 키가 눌린 채 남는다
      return;
    }
    if (event.target?.closest?.("input, textarea")) return;
    keys[key] = true;
    event.preventDefault();
  };
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", onKey);
  const clearKeys = () => {
    for (const key of Object.keys(keys)) keys[key] = false;
  };
  const onFocusIn = (event) => {
    if (event.target?.closest?.("input, textarea")) clearKeys();
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
    if (lb !== rb) return {kind: "pivot", dir: lb ? 1 : -1};
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
    if (!engaged || calibrationLocked) return;
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
  async function loadLimits() {
    const response = await apiGet("/api/v1/safety/state").catch(() => null);
    if (response?.status === 200 && response.body?.limits) setServerLimits(response.body.limits);
    renderCap();
  }
  function renderCap() {
    const limits = currentLimits();
    element.cap.textContent =
      `상한 ${limits.linear.toFixed(2)} m/s · ${Math.round(limits.angular * DEG)}°/s`;
  }
  loadLimits();

  // --- 로봇 상태 폴링: 실측 속도·회전율 ---------------------------------------
  const stateTimer = setInterval(async () => {
    const state = await apiGet("/api/v1/robot/state").catch(() => null);
    if (!state || state.status !== 200) return;
    const percent = state.body?.battery?.percent;
    if (percent !== undefined && percent !== null) element.battery.textContent = `${Math.round(percent)}%`;
    if (state.body?.mode) element.mode.textContent = state.body.mode;
    renderActivity(state.body?.activity);
    const velocity = state.body?.velocity;
    if (velocity) {
      element.speed.textContent = Math.abs(Number(velocity.linear ?? 0)).toFixed(2);
      const turn = Number(velocity.angular ?? 0) * DEG;
      element.turn.textContent = `${turn > 0.5 ? "↺" : turn < -0.5 ? "↻" : "·"} ${Math.abs(turn).toFixed(0)}°/s`;
    }
  }, STATE_POLL_MS);

  // --- HUD 액션 --------------------------------------------------------------
  const actions = el("ui-actions");
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
  const zoomButton = el("ui-button", "확대 맞춤", {type: "button", "data-drive-zoom": ""});
  zoomButton.setAttribute("kind", "quiet");
  zoomButton.addEventListener("click", () => view.cycleZoom());
  element.zoomButton = zoomButton;
  const inputsButton = el("ui-button", "입력", {type: "button", "data-drive-inputs": ""});
  inputsButton.setAttribute("kind", "quiet");
  let inputsPanel = null;
  let closeInputs = null;
  inputsButton.addEventListener("click", () => {
    if (closeInputs) {
      closeInputs();
      return;
    }
    inputsPanel = el("div", null, {"data-inputs-panel": ""});
    root.querySelector("[data-drive-stage]").append(inputsPanel);
    closeInputs = mountInputs(inputsPanel, {onClose: () => {
      inputsPanel?.remove();
      inputsPanel = null;
      closeInputs = null;
      renderInputs();
    }, onChange: renderInputs});
  });
  const exit = el("ui-button", "나가기", {type: "button", "data-drive-exit": ""});
  exit.setAttribute("kind", "quiet");
  exit.addEventListener("click", () => teardown());
  // D-411 A: 로봇 학습 녹화(카메라 유닛 bag) — 위의 "화면 녹화"(이 기기 브라우저)와 다르다.
  const robotRecordButton = el("ui-button", "로봇 녹화", {type: "button", "data-robot-record": ""});
  robotRecordButton.setAttribute("kind", "quiet");
  const recordingsButton = el("ui-button", "녹화본", {type: "button", "data-recordings-open": ""});
  recordingsButton.setAttribute("kind", "quiet");
  const recordingFact = el("span", null, {"data-drive-fact": "recording", hidden: ""});
  actions.append(zoomButton, shotButton, recordButton, robotRecordButton, recordingsButton, inputsButton, exit);
  element.hud.append(recordingFact, actions);
  const robotRecording = mountRobotRecording({
    toggle: robotRecordButton, detail: recordingFact, openButton: recordingsButton,
    sheetHost: root.querySelector("[data-drive-stage]"), save: saveCameraFile,
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
    element.fine.setAttribute("aria-pressed", String(Boolean(config.fine)));
    renderCap();
  }
  element.fine.addEventListener("click", () => {
    saveInputConfig({fine: !inputConfig().fine});
    renderInputs();
  });
  renderInputs();

  // --- 진입: 수동 모드를 잡은 뒤에만 명령을 보낸다 ------------------------------
  // 먼저 보내면 IDLE 상태의 첫 teleop 이 409 MODE_CONFLICT 로 세션을 막는다.
  async function engage() {
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

  function teardown() {
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
    vision.stop();
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
  }
}
