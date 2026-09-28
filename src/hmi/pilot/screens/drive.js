// 주행 화면(D-323 T7). 원형 휠·홀드 페달·게임패드·키보드가 모두 같은
// hold-to-drive 원칙 아래 stick.js 매핑을 공유한다. 상태 채널은 link.js,
// 영상은 vision.js(인증 JPEG 폴링). 서버 텍스트로 HTML 을 만들지 않는다.

import {postJson, whoami, api as apiGet, authHeaders, token} from "../client.js";
import {createDeviceSession} from "../link.js";
import {createVisionPreview} from "../vision.js";
import {driverFor} from "../drivers/registry.js";
import {setSteerInput, setPedal, currentCommandSource, stickMap} from "../input-state.js";

const WHEEL_SWEEP_DEG = 45;

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

export function mountDrive(root, {onExit} = {}) {
  const gate = driverFor("pinky_core");
  const element = {};

  root.replaceChildren(buildStage(), buildControls());
  for (const [key, selector] of Object.entries({
    stage: "[data-drive-stage]", frame: "[data-drive-frame]", empty: "[data-drive-empty]",
    hud: "[data-drive-hud]", readout: "[data-drive-readout]", wheel: "[data-drive-wheel]",
    indicator: "[data-drive-wheel-indicator]", forward: "[data-drive-pedal=forward]",
    reverse: "[data-drive-pedal=reverse]", mode: "[data-drive-fact=mode]",
    battery: "[data-drive-fact=battery]", speed: "[data-drive-fact=speed]",
    state: "[data-drive-fact=link]",
  })) element[key] = root.querySelector(selector);

  // --- 상태 채널: /ws/state(auth 첫 프레임) + REST teleop -------------------
  const session = createDeviceSession({
    token: token(),
    openSocket: (url) => {
      const target = new URL(url, location.origin);
      target.protocol = target.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(target);
      socket.onopen = () => socket.send(JSON.stringify({type: "auth", token: token()}));
      return socket;
    },
    schedule: (fn, ms) => {
      const id = setTimeout(fn, ms);
      return () => clearTimeout(id);
    },
    postJson,
    whoami,
    onState: (state) => { element.state.textContent = state; },
    onSnapshot: (frame) => {
      const percent = frame?.battery?.percent;
      if (percent !== undefined) element.battery.textContent = `${Math.round(percent)}%`;
      if (frame?.mode) element.mode.textContent = frame.mode;
    },
    onConflict: (detail) => {
      element.empty.textContent =
        `조종이 차단되었습니다 — ${detail?.message ?? detail?.code ?? "이유를 확인하세요"}`;
    },
  });
  session.open();

  // --- 영상: 인증 JPEG 폴링 --------------------------------------------------
  const vision = createVisionPreview({
    apiGet,
    fetchFrame: async (path) => (await fetch(path, {headers: authHeaders()})).blob(),
    onFrame: (url) => {
      element.frame.src = url;
      element.frame.hidden = false;
      element.empty.hidden = true;
    },
    onUnavailable: (message) => {
      element.frame.hidden = true;
      element.empty.hidden = false;
      element.empty.textContent = message;
    },
  });
  vision.start();

  // --- 입력: 원형 휠(각도 오프셋→steer) --------------------------------------
  const wheel = element.wheel;
  function applyWheel(event) {
    const rect = wheel.getBoundingClientRect();
    const dx = event.clientX - (rect.left + rect.width / 2);
    const steer = Math.max(-1, Math.min(1, dx / (rect.width / 2)));
    setSteerInput(steer);
    element.indicator.style.transform = `rotate(${steer * WHEEL_SWEEP_DEG}deg)`;
  }
  wheel.addEventListener("pointerdown", (event) => {
    wheel.setPointerCapture(event.pointerId);
    applyWheel(event);
  });
  wheel.addEventListener("pointermove", (event) => {
    if (event.buttons || event.pointerType === "touch") applyWheel(event);
  });
  for (const name of ["pointerup", "pointercancel", "pointerleave"]) {
    wheel.addEventListener(name, () => {
      setSteerInput(0);
      element.indicator.style.transform = "rotate(0deg)";
    });
  }

  // --- 입력: 홀드 페달 --------------------------------------------------------
  for (const [node, key] of [[element.forward, "forward"], [element.reverse, "reverse"]]) {
    const set = (value) => {
      setPedal(key, value);
      node.classList.toggle("active", value);
    };
    node.addEventListener("pointerdown", () => set(true));
    for (const name of ["pointerup", "pointercancel", "pointerleave"]) {
      node.addEventListener(name, () => set(false));
    }
  }

  // --- 입력: 키보드(데스크톱 검증용) ----------------------------------------
  const keys = {up: false, down: false, left: false, right: false};
  const KEY_MAP = {ArrowUp: "up", KeyW: "up", ArrowDown: "down", KeyS: "down",
                   ArrowLeft: "left", KeyA: "left", ArrowRight: "right", KeyD: "right"};
  const keyHandler = (value) => (event) => {
    const key = KEY_MAP[event.code];
    if (!key) return;
    keys[key] = value;
    event.preventDefault();
  };
  window.addEventListener("keydown", keyHandler(true));
  window.addEventListener("keyup", keyHandler(false));

  // --- hold-to-drive 루프(100ms) ---------------------------------------------
  const loop = setInterval(() => {
    let source = currentCommandSource();
    if (keys.up || keys.down || keys.left || keys.right) {
      source = {kind: "keys", ...keys};
    } else if (!source && navigator.getGamepads) {
      const pad = [...navigator.getGamepads()].find(Boolean);
      if (pad) source = {kind: "pad", x: pad.axes[0] ?? 0, y: -(pad.axes[1] ?? 0)};
    }
    session.command(stickMap(source));
  }, 100);

  // --- 조종 중 화면 꺼짐 방지(D-328/T7) + 이탈 즉시 0 -----------------------
  let wakeLock = null;
  const requestWakeLock = async () => {
    try { wakeLock = await navigator.wakeLock.request("screen"); } catch (error) { /* 지원 없음 */ }
  };
  requestWakeLock();
  const onVisibility = () => {
    if (document.visibilityState === "visible") {
      requestWakeLock();
    } else {
      session.hidden();
    }
  };
  document.addEventListener("visibilitychange", onVisibility);

  // --- 로봇 상태 폴링 --------------------------------------------------------
  const stateTimer = setInterval(async () => {
    const state = await apiGet("/api/v1/robot/state").catch(() => null);
    if (!state || state.status !== 200) return;
    const percent = state.body?.battery?.percent;
    if (percent !== undefined) element.battery.textContent = `${Math.round(percent)}%`;
    const velocity = state.body?.velocity;
    if (velocity) element.speed.textContent = `${Number(velocity.linear ?? 0).toFixed(2)} m/s`;
  }, 1000);

  const actions = el("ui-actions");
  const exit = el("ui-button", "게이트로", {kind: "quiet", type: "button", "data-drive-exit": ""});
  exit.addEventListener("click", () => teardown());
  actions.append(exit);
  element.hud.append(actions);

  // 진입: 수동 모드 전환(409 MODE_CONFLICT 등은 안내로).
  gate.engage(postJson).then((response) => {
    if (response.status !== 200) {
      element.empty.textContent = `수동 모드 전환 실패 — ${response.body?.detail ?? response.status}`;
    }
  }).catch(() => {});

  function teardown() {
    clearInterval(loop);
    clearInterval(stateTimer);
    session.hidden();
    session.close?.();
    gate.disengage(postJson).catch(() => {});
    vision.stop();
    window.removeEventListener("keydown", keyHandler(true));
    window.removeEventListener("keyup", keyHandler(false));
    document.removeEventListener("visibilitychange", onVisibility);
    wakeLock?.release().catch(() => {});
    wakeLock = null;
    onExit?.();
  }
}

function buildStage() {
  const stage = el("div", null, {"data-drive-stage": ""});
  const frame = el("img", null, {alt: "전방 카메라", "data-drive-frame": "", hidden: ""});
  const empty = el("ui-empty", "카메라 프레임 수신 대기", {"data-drive-empty": ""});
  const hud = el("div", null, {"data-drive-hud": ""});
  hud.append(buildHudFacts());
  stage.append(frame, empty, hud);
  return stage;
}

function buildHudFacts() {
  const facts = el("div", null, {"data-drive-readout": ""});
  const grid = el("ui-grid", null, {columns: "2"});
  for (const [key, label, initial] of [
    ["link", "LINK", "CONNECTING"], ["mode", "MODE", "—"],
    ["battery", "BATT", "—"], ["speed", "SPEED", "0.00 m/s"],
  ]) {
    const cell = el("div");
    cell.append(
      el("ui-text", label, {scale: "label"}),
      el("ui-text", initial, {scale: "value", "data-drive-fact": key}),
    );
    grid.append(cell);
  }
  facts.append(grid);
  return facts;
}

function buildControls() {
  const controls = el("div", null, {"data-drive-controls": ""});
  const wheelWrap = el("div", null, {"data-drive-wheel-wrap": ""});
  const wheel = el("div", null, {"data-drive-wheel": "", "aria-label": "조향 휠"});
  const indicator = el("div", null, {"data-drive-wheel-indicator": ""});
  wheel.append(indicator);
  wheelWrap.append(wheel);
  const pedals = el("div", null, {"data-drive-pedals": ""});
  pedals.append(
    el("ui-button", "전진", {kind: "primary", type: "button", "data-drive-pedal": "forward"}),
    el("ui-button", "후진", {kind: "segment", type: "button", "data-drive-pedal": "reverse"}),
  );
  controls.append(wheelWrap, pedals);
  return controls;
}
