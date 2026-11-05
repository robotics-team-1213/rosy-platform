import { createHoldTicker } from "/common/hold-ticker.js";
import { staleAgeS } from "./state-age.js";

const COMMANDS = [
  ["forward", "전진", 0.03, 0], ["left", "좌회전", 0, 0.10],
  ["backward", "후진", -0.03, 0], ["right", "우회전", 0, -0.10],
];

export function createManualControl({scope, view, call, namedReason, confirmedAction, refreshState}) {
  const root = document.createElement("section");
  root.className = "manual-control";
  root.dataset.manualControl = "";
  root.hidden = true;
  const heading = document.createElement("ui-head");
  const reason = document.createElement("ui-status");
  reason.id = "fleet-manual-reason";
  reason.dataset.manualReason = "";
  reason.setAttribute("role", "status");
  reason.setAttribute("aria-live", "polite");
  const actions = document.createElement("div");
  actions.className = "robot-actions";
  actions.setAttribute("aria-label", "누르는 동안만 움직이는 저속 조종");
  const mode = document.createElement("ui-button");
  mode.type = "button";
  mode.textContent = "수동 모드로 전환…";
  mode.dataset.manualMode = "";
  mode.setAttribute("aria-describedby", reason.id);
  actions.append(mode);
  const buttons = COMMANDS.map(([direction, label, linear, angular]) => {
    const button = document.createElement("ui-button");
    button.type = "button";
    button.setAttribute("kind", "toggle");
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("aria-describedby", reason.id);
    button.setAttribute("aria-label", `${label}. 누르는 동안만 저속으로 움직입니다.`);
    button.textContent = label;
    button.dataset.manualDirection = direction;
    actions.append(button);
    return {button, linear, angular};
  });
  root.append(heading, reason, actions);
  let active = null, pending = null, stopping = null, cancelTimeout = null;
  let failure = "", modePending = false;

  function blocked(requireManual = true) {
    const robot = view.robots.find(row => row.robot_id === view.focusRobot);
    if (namedReason()) return namedReason();
    if (!scope.capture().current() || document.hidden) return "화면을 다시 열고 상태를 확인하세요.";
    if (view.stateUnavailable) return "관제 상태를 확인할 수 없습니다.";
    if (!robot?.online) return "로봇 연결을 확인하세요.";
    if (robot.state?.safety?.estop !== false) return "비상정지 상태를 확인하고 해제하세요.";
    if (view.dispatchControl?.dispatch_enabled !== true || !Number.isSafeInteger(view.dispatchControl.generation))
      return "관제 발행 상태를 확인하고 정지 래치를 해제하세요.";
    if (active && active.generation !== view.dispatchControl.generation) return "발행 상태가 바뀌어 조종을 중단했습니다.";
    if (robot.held || robot.calibration) return "로봇의 작업·점검 상태를 확인하세요.";
    if (robot.capabilities?.teleop !== true) return "이 로봇은 수동 조종을 지원하지 않습니다.";
    if (!["motor", "hardware"].includes(robot.capabilities?.runtime?.mode)) return "주행 장치가 준비되지 않았습니다.";
    if (typeof robot.state_age_s !== "number" || !Number.isFinite(robot.state_age_s)
        || staleAgeS(robot, view.receivedAtMs, Date.now()) !== null)
      return "관제 상태가 오래됐거나 시각을 확인할 수 없습니다.";
    if (!["pose", "velocity"].every(key => robot.state?.evidence?.[key]?.evidence === "fresh"))
      return "최신 위치·속도 관측을 기다립니다.";
    if (robot.goal || robot.queued || (view.trafficTrips || []).some(row => row.robot_id === robot.robot_id)
        || robot.state?.swarm?.active) return "진행 중인 운행을 먼저 취소하세요.";
    if (stopping) return "정지 명령을 전달하는 중입니다.";
    if (modePending) return "수동 모드 전환을 요청하는 중입니다.";
    if (requireManual && robot.state?.mode !== "MANUAL") return "수동 모드로 전환한 뒤 조종하세요.";
    return "";
  }

  scope.listen(mode, "click", async () => {
    const robotId = view.focusRobot, generation = view.dispatchControl?.generation;
    await confirmedAction.run({message: `${robotId}을 수동 모드로 전환할까요?`, opener: mode,
      eligible: () => view.focusRobot === robotId && generation === view.dispatchControl?.generation
        && !blocked(false) && view.robots.find(row => row.robot_id === robotId)?.state?.mode !== "MANUAL",
      request: async owner => {
        modePending = true; failure = ""; update();
        try {
          const result = await call("/api/fleet/do", {method: "POST", signals: [owner.signal],
            headers: {"Content-Type": "application/json"}, body: JSON.stringify({do: "manual", robot: robotId})});
          owner.check();
          if (result?.accepted !== true) throw new Error("로봇이 수동 모드 요청을 수락하지 않았습니다.");
          await refreshState();
        } finally { modePending = false; update(); }
      }, onError: error => { failure = `수동 모드 전환 실패: ${error.message}`; update(); }});
  });

  function send(robotId, linear, angular) {
    return call("/api/fleet/do", {method: "POST", keepalive: linear === 0 && angular === 0,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({do: "move", robot: robotId, linear, angular})}).then(result => {
      if (result?.accepted !== true) throw new Error("로봇이 조종 명령을 수락하지 않았습니다.");
      return result;
    });
  }

  function terminalZero(owner) {
    const immediate = send(owner.robotId, 0, 0);
    // A delayed drive request must finish before the final zero for that same robot.
    const terminal = pending ? Promise.allSettled([pending, immediate]).then(() => send(owner.robotId, 0, 0)) : immediate;
    immediate.catch(() => null);
    stopping = terminal;
    terminal.catch(error => { failure = `정지 명령 전달 실패 · 비상 정지와 연결을 확인하세요: ${error.message}`; reason.textContent = failure; })
      .finally(() => { if (stopping === terminal) stopping = null; });
  }

  function stop() {
    cancelTimeout?.(); cancelTimeout = null;
    const owner = active;
    active = null;
    if (!owner) return;
    owner.button.setAttribute("aria-pressed", "false");
    ticker.stop(owner);
    reason.textContent = "정지 명령을 보냈습니다. 로봇의 정지를 확인하세요.";
  }

  async function tick() {
    if (!active) return;
    if (blocked() || active.robotId !== view.focusRobot) { stop(); return; }
    if (pending) return;
    const request = send(active.robotId, active.linear, active.angular);
    pending = request;
    try { await request; }
    catch (error) { stop(); failure = `조종 명령 실패: ${error.message}`; reason.textContent = failure; }
    finally { if (pending === request) pending = null; }
  }
  const ticker = createHoldTicker({intervalMs: 100, onTick: tick, onZero: terminalZero});

  function start(command, event) {
    event.preventDefault();
    if (active || blocked()) return;
    failure = "";
    active = {...command, robotId: view.focusRobot, generation: view.dispatchControl.generation};
    command.button.setAttribute("aria-pressed", "true");
    if (event.pointerId != null) {
      try { command.button.setPointerCapture(event.pointerId); } catch (_error) { /* Window release also stops. */ }
    }
    cancelTimeout = scope.timeout(stop, 2000);
    ticker.start();
  }

  for (const command of buttons) {
    const {button} = command;
    scope.listen(button, "pointerdown", event => start(command, event));
    for (const type of ["pointerup", "pointercancel", "lostpointercapture", "blur"]) scope.listen(button, type, stop);
    scope.listen(button, "keydown", event => {
      if ([" ", "Enter"].includes(event.key) && !event.repeat) start(command, event);
    });
    scope.listen(button, "keyup", event => { if ([" ", "Enter"].includes(event.key)) stop(); });
  }
  scope.listen(window, "pointerup", stop);
  scope.listen(window, "blur", stop);
  scope.listen(document, "visibilitychange", () => { if (document.hidden) stop(); });
  scope.onDispose(stop);
  function update() {
    if (active && (active.robotId !== view.focusRobot || blocked())) stop();
    root.hidden = !view.focusRobot;
    heading.textContent = `${view.robotNames?.[view.focusRobot] || view.focusRobot || "로봇"} 수동 조종`;
    mode.hidden = view.robots.find(row => row.robot_id === view.focusRobot)?.state?.mode === "MANUAL";
    const modeWhy = blocked(false);
    mode.disabled = Boolean(modeWhy);
    if (modeWhy) mode.setAttribute("reason", modeWhy);
    else mode.removeAttribute("reason");
    const why = blocked();
    for (const {button} of buttons) {
      button.disabled = Boolean(why);
      if (why) button.setAttribute("reason", why);
      else button.removeAttribute("reason");
    }
    if (!active && !stopping) reason.textContent = failure || why || "누르는 동안만 이동 · 최대 2초 · 전후진 0.03m/s · 회전 0.10rad/s";
  }
  scope.interval(update, 100);
  return {root, update, stop};
}
