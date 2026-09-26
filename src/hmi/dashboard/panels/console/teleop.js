import { HeadlessState } from "/common/core_ui_logic.js";
import { createHoldTicker } from "/common/hold-ticker.js";

const TELEOP_INTERVAL_MS = 100;
const COMMANDS = [
  {label: "전진", linear: 0.05, angular: 0},
  {label: "좌회전", linear: 0, angular: 0.35},
  {label: "후진", linear: -0.05, angular: 0},
  {label: "우회전", linear: 0, angular: -0.35},
];

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "수동 운전");
  const status = el("ui-status", "", "운전 자격을 확인하는 중입니다.");
  const confirmLabel = el("label", "ui-field-label surface-confirmation", "주변과 바퀴가 안전한지 확인했습니다.");
  const confirmed = el("input"); confirmed.type = "checkbox"; confirmLabel.prepend(confirmed);
  const controls = el("div", "surface-teleop-controls"); controls.setAttribute("aria-label", "누르는 동안만 움직이는 저속 운전");
  const buttons = COMMANDS.map((command) => {
    const button = el("ui-button", "", command.label); button.setAttribute("kind", "toggle"); button.setAttribute("size", "primary"); button.type = "button"; button.dataset.linear = String(command.linear); button.dataset.angular = String(command.angular); button.disabled = true;
    button.setAttribute("aria-label", `${command.label}. 누르는 동안에만 저속으로 움직입니다.`); controls.append(button); return button;
  });
  root.append(head, status, confirmLabel, controls);

  let state = null;
  let capabilities = null;
  let safety = null;
  let pending = null;
  let activeButton = null;
  function eligible() {
    if (ctx.role === "viewer" || capabilities?.teleop !== true || safety?.estop === true || state?.mode !== "MANUAL" || !confirmed.checked) return false;
    const evidence = new HeadlessState(state);
    return evidence.isFresh("pose") && evidence.isFresh("velocity");
  }
  function describeHold() {
    if (ctx.role === "viewer") return "Operator 권한이 필요합니다.";
    if (capabilities && capabilities.teleop !== true) return `현재 runtime/profile에서 teleop을 사용할 수 없습니다${capabilities.withheld?.reason ? ` · ${capabilities.withheld.reason}` : ""}.`;
    if (safety?.estop === true) return "비상정지가 활성화되어 있습니다.";
    if (!state || !new HeadlessState(state).isFresh("pose") || !new HeadlessState(state).isFresh("velocity")) return "pose와 velocity의 최신 상태를 기다립니다.";
    if (state.mode !== "MANUAL") return "저속 운전 전에 MANUAL 모드로 전환하세요.";
    if (!confirmed.checked) return "주변 안전 확인이 필요합니다.";
    return "버튼을 누르는 동안만 100ms 간격으로 저속 명령을 보냅니다.";
  }
  function update() {
    const can = eligible();
    buttons.forEach((button) => { button.disabled = !can && button !== activeButton; });
    if (!can && ticker.active) stop("운전 조건이 바뀌어 정지했습니다.");
    if (!ticker.active) status.textContent = describeHold();
  }
  function send(linear, angular, keepalive = false) {
    return ctx.api("/api/v1/teleop", {method: "POST", body: JSON.stringify({linear, angular}), keepalive});
  }
  function terminalZero(immediate = false) {
    const prior = pending || Promise.resolve();
    if (immediate) send(0, 0, true).catch(() => null);
    const terminal = prior.catch(() => null).then(() => send(0, 0, true));
    pending = terminal;
    terminal.catch((error) => { status.textContent = `정지 명령 전달 실패 · 서버 watchdog 대기: ${error.message}`; })
      .finally(() => { if (pending === terminal) pending = null; });
    return terminal;
  }
  async function tick() {
    if (!ticker.active) return;
    if (!eligible()) { stop("운전 조건이 끊겨 정지했습니다.", true); return; }
    if (pending || !activeButton) return;
    const request = send(Number(activeButton.dataset.linear), Number(activeButton.dataset.angular));
    pending = request;
    try { await request; }
    catch (error) { if (ticker.active) stop(`주행 명령 실패: ${error.message}`, true); }
    finally { if (pending === request) pending = null; }
  }
  const ticker = createHoldTicker({intervalMs: TELEOP_INTERVAL_MS, onTick: tick, onZero: terminalZero});
  function stop(message = "정지 명령을 보냈습니다.", immediate = false) {
    ticker.stop(immediate);
    activeButton?.classList.remove("active"); activeButton = null;
    buttons.forEach((button) => { button.disabled = !eligible(); });
    status.textContent = message;
    return pending || Promise.resolve();
  }
  function start(button, event) {
    event.preventDefault();
    if (!eligible() || ticker.active) return;
    if (event.pointerId != null && button.setPointerCapture) {
      try { button.setPointerCapture(event.pointerId); } catch (_error) { /* Browser may not expose capture on a custom element. */ }
    }
    activeButton = button; button.classList.add("active");
    status.textContent = `${button.getAttribute("aria-label").split(".")[0]} 명령 전송 중 · 놓으면 정지합니다.`;
    ticker.start();
  }

  const listeners = new AbortController();
  for (const button of buttons) {
    button.addEventListener("pointerdown", (event) => start(button, event), {signal: listeners.signal});
    button.addEventListener("pointerup", () => stop(), {signal: listeners.signal});
    button.addEventListener("pointercancel", () => stop("입력이 취소되어 정지했습니다.", true), {signal: listeners.signal});
    button.addEventListener("lostpointercapture", () => stop("포인터 입력이 끊겨 정지했습니다.", true), {signal: listeners.signal});
    button.addEventListener("keydown", (event) => { if ([" ", "Enter"].includes(event.key) && !event.repeat) start(button, event); }, {signal: listeners.signal});
    button.addEventListener("keyup", (event) => { if ([" ", "Enter"].includes(event.key)) stop(); }, {signal: listeners.signal});
    button.addEventListener("blur", () => { if (activeButton === button) stop("운전 버튼에서 포커스가 벗어나 정지했습니다.", true); }, {signal: listeners.signal});
  }
  window.addEventListener("blur", () => stop("창 포커스를 잃어 정지했습니다.", true), {signal: listeners.signal});
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop("화면이 숨겨져 정지했습니다.", true); }, {signal: listeners.signal});
  confirmed.addEventListener("change", update, {signal: listeners.signal});
  window.addEventListener("rosy:stop-motion", (event) => {
    const wasActive = ticker.active;
    const pendingStop = stop("공유 운전 제어에서 정지했습니다.", true);
    if (Array.isArray(event.detail?.waits)) {
      event.detail.waits.push(wasActive ? pendingStop : terminalZero(true));
    }
  }, {signal: listeners.signal});

  const stopState = ctx.store.poll("/api/v1/robot/state", 500, (data) => { state = data; update(); }, (error) => { state = null; status.textContent = `로봇 상태를 읽지 못해 운전을 막았습니다: ${error.message}`; stop("상태 연결이 끊겨 정지했습니다.", true); });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 5_000, (data) => { capabilities = data; update(); }, (error) => { capabilities = null; status.textContent = `운전 capability 확인 실패: ${error.message}`; update(); });
  const stopSafety = ctx.store.poll("/api/v1/safety/state", 500, (data) => { safety = data; update(); }, (error) => { safety = null; status.textContent = `안전 상태 연결 실패: ${error.message}`; stop("안전 상태를 확인할 수 없어 정지했습니다.", true); });
  update();

  return {
    async beforeHide() {
      if (ticker.active) await stop("조작 그룹을 바꾸기 위해 정지했습니다.", true);
      else await terminalZero(true);
      return true;
    },
    unmount() { stop("운전 패널을 닫아 정지했습니다.", true); listeners.abort(); stopState(); stopCapabilities(); stopSafety(); },
  };
}
