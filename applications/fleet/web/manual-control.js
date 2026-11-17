import { createHoldTicker } from "/common/hold-ticker.js";
import { statusTag } from "/common/status-tag.js";
import { EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { robotPoseText, sitePoseText } from "./localization-badge.js";
import { staleAgeS } from "./state-age.js";

// Speeds are the robot's own live manual limit (CORE state.speed_limits, D-1005); these signs only pick the axis.
const COMMANDS = [
  ["forward", "전진", 1, 0], ["left", "좌회전", 0, 1],
  ["backward", "후진", -1, 0], ["right", "우회전", 0, -1],
];
// A robot that does not report its limit (older CORE) drives no faster than this pad always did.
const FALLBACK = {manual_linear: 0.03, manual_angular: 0.10};
const STEP = {linear: 0.01, angular: 0.05};
const MIN_SET = {linear: 0.01, angular: 0.05};
const num = value => Number(Number(value).toFixed(3));

export function manualSpeeds(state) {
  const limits = state?.speed_limits, usable = value => Number.isFinite(value) && value >= 0;
  const known = usable(limits?.manual_linear) && usable(limits?.manual_angular);
  const linear = known ? limits.manual_linear : FALLBACK.manual_linear;
  const angular = known ? limits.manual_angular : FALLBACK.manual_angular;
  const set = known && usable(limits.set_linear) && usable(limits.set_angular)
    ? {linear: limits.set_linear, angular: limits.set_angular} : null;
  const max = known && limits.max_linear > 0 && limits.max_angular > 0
    ? {linear: limits.max_linear, angular: limits.max_angular} : null;
  const sealed = known && usable(limits.approved_linear) ? {linear: limits.approved_linear, angular: limits.approved_angular} : null;
  return {linear, angular, set, max, sealed};
}

export function speedText({linear, angular, set, sealed}) {
  const bound = set && sealed && (linear < set.linear || angular < set.angular)
    ? ` (설정 ${num(set.linear)}·${num(set.angular)}, 측정 봉인 ${num(sealed.linear)}·${num(sealed.angular)}로 제한)` : "";
  return `전후진 ${num(linear)}m/s · 회전 ${num(angular)}rad/s${bound}`;
}

const evidenceWord = (robot, key) => EVIDENCE_LABEL[robot.state?.evidence?.[key]?.evidence] || EVIDENCE_LABEL.unavailable;

export function createManualControl({scope, view, call, namedReason, confirmedAction, refreshState, onStatusChange = null}) {
  const root = document.createElement("section");
  root.className = "manual-control";
  root.dataset.manualControl = "";
  root.hidden = true;
  // Not in the live region: its age text changes every second.
  const pose = document.createElement("p");
  pose.dataset.manualPose = "";
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
  mode.setAttribute("kind", "quiet");
  mode.textContent = "수동 모드로 전환…";
  mode.dataset.manualMode = "";
  mode.setAttribute("aria-describedby", reason.id);
  actions.append(mode);
  const adjust = [["slower", "속도 −", -1], ["faster", "속도 +", 1]].map(([key, label, sign]) => {
    const button = document.createElement("ui-button");
    button.type = "button";
    button.setAttribute("kind", "quiet");
    button.textContent = label;
    button.dataset.manualSpeed = key;
    button.setAttribute("aria-describedby", reason.id);
    actions.append(button);
    return {button, sign};
  });
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
    return {direction, button, linear, angular};
  });
  // One lock + one cause line for the whole pad; the per-button "위 사유" captions stay as the `reason` attribute
  // (tests and aria-describedby read it) but are not drawn six times (concept rule 18, CSS .manual-control).
  const lockMark = statusTag("locked");
  lockMark.className = "manual-lock";
  lockMark.hidden = true;
  root.append(pose, reason, actions);
  reason.before(lockMark);
  let active = null, pending = null, stopping = null, cancelTimeout = null;
  let failure = "", notice = "", modePending = false, speedPending = false;
  let lastUpdatedRobotId = null, lastStatusSig = null;
  const activeRobotId = () => (typeof view.robotSelection?.get === "function" ? view.robotSelection.get() : null);

  function blocked(requireManual = true, targetRobotId = activeRobotId()) {
    const robot = (view.robots || []).find(row => row.robot_id === targetRobotId);
    if (namedReason()) return namedReason();
    if (!scope.capture().current() || document.hidden) return "화면을 다시 열고 상태를 확인하세요.";
    if (view.stateUnavailable) return "관제 상태를 확인할 수 없습니다.";
    if (!robot?.online) return "로봇 연결을 확인하세요.";
    if (robot.state?.safety?.estop === true) return "비상정지 상태를 확인하고 해제하세요.";
    if (robot.state?.safety?.estop !== false) return "정지 상태를 확인할 수 없습니다. 연결을 확인하세요.";
    if (view.dispatchControl?.dispatch_enabled !== true || !Number.isSafeInteger(view.dispatchControl.generation))
      return "관제 발행 상태를 확인하고 정지 래치를 해제하세요.";
    if (active && active.generation !== view.dispatchControl.generation) return "발행 상태가 바뀌어 조종을 중단했습니다.";
    if (robot.held || robot.calibration) return "로봇의 작업·점검 상태를 확인하세요.";
    if (robot.capabilities?.teleop !== true) return "이 로봇은 수동 조종을 지원하지 않습니다.";
    if (!["motor", "hardware"].includes(robot.capabilities?.runtime?.mode)) return "주행 장치가 준비되지 않았습니다.";
    if (typeof robot.state_age_s !== "number" || !Number.isFinite(robot.state_age_s))
      return "관제 상태의 시각을 받지 못했습니다. 연결을 확인하세요.";
    if (staleAgeS(robot, view.receivedAtMs, Date.now()) !== null) return "관제 상태가 오래됐습니다. 새 상태를 기다리세요.";
    const notFresh = [["pose", "위치"], ["velocity", "속도"]]
      .filter(([key]) => robot.state?.evidence?.[key]?.evidence !== "fresh")
      .map(([key, name]) => `${name} ${evidenceWord(robot, key)}`);
    if (notFresh.length) return `${notFresh.join(" · ")} · 최신 관측을 기다립니다.`;
    if (robot.goal || robot.queued || (view.trafficTrips || []).some(row => row.robot_id === robot.robot_id)
        || robot.state?.swarm?.active) return "진행 중인 운행을 먼저 취소하세요.";
    if (stopping) return "정지 명령을 전달하는 중입니다.";
    if (modePending) return "수동 모드 전환을 요청하는 중입니다.";
    if (requireManual && robot.state?.mode !== "MANUAL") return "수동 모드로 전환한 뒤 조종하세요.";
    if (requireManual) { const s = manualSpeeds(robot.state); if (!(s.linear > 0 && s.angular > 0)) return "수동 속도 한도가 0입니다. 속도를 올리세요."; }
    return "";
  }

  // The operator raises or lowers the robot's manual speed here; CORE refuses anything above the signed ceiling.
  for (const {button, sign} of adjust) {
    scope.listen(button, "click", async () => {
      const robotId = activeRobotId(), robot = view.robots.find(row => row.robot_id === robotId);
      const s = manualSpeeds(robot?.state);
      if (!s.set || !s.max || blocked(false)) return;
      const next = (key) => num(Math.min(s.max[key], Math.max(MIN_SET[key], s.set[key] + sign * STEP[key])));
      speedPending = true; failure = ""; update();
      try {
        await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/speed-limits`, {method: "PUT",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({manual_linear: next("linear"), manual_angular: next("angular")})});
        await refreshState();
      } catch (error) { failure = `속도 변경 실패: ${error.message}`; }
      finally { speedPending = false; update(); }
    });
  }

  async function requestManualMode(opener = mode) {
    const robotId = activeRobotId(), generation = view.dispatchControl?.generation;
    await confirmedAction.run({message: `${robotId}을 수동 모드로 전환할까요?`, opener,
      eligible: () => activeRobotId() === robotId && generation === view.dispatchControl?.generation
        && !blocked(false) && (view.robots || []).find(row => row.robot_id === robotId)?.state?.mode !== "MANUAL",
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
  }

  function enterManual(target) {
    const opener = target?.currentTarget || (typeof target?.focus === "function" ? target : mode);
    return requestManualMode(opener);
  }

  scope.listen(mode, "click", () => requestManualMode(mode));

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
      .finally(() => { if (stopping === terminal) { stopping = null; onStatusChange?.(); } });
  }

  function stop() {
    cancelTimeout?.(); cancelTimeout = null;
    const owner = active;
    active = null;
    if (view.manualDriveRobot === owner?.robotId) view.manualDriveRobot = null;
    if (!owner) return;
    owner.releaseAbort?.abort();
    if (typeof owner.triggerEl?.setAttribute === "function") owner.triggerEl.setAttribute("aria-pressed", "false");
    if (owner.button && owner.button !== owner.triggerEl) owner.button.setAttribute("aria-pressed", "false");
    owner.onPressChange?.(false, owner.direction);
    ticker.stop(owner);
    reason.textContent = "정지 명령을 보냈습니다. 로봇의 정지를 확인하세요.";
    update();
    onStatusChange?.();
  }

  async function tick() {
    if (!active) return;
    if (blocked() || active.robotId !== activeRobotId()) { stop(); return; }
    if (pending) return;
    const request = send(active.robotId, active.linear, active.angular);
    pending = request;
    try { await request; }
    catch (error) { stop(); failure = `조종 명령 실패: ${error.message}`; reason.textContent = failure; onStatusChange?.(); }
    finally { if (pending === request) pending = null; }
  }
  const ticker = createHoldTicker({intervalMs: 100, onTick: tick, onZero: terminalZero});

  function start(command, event, options = {}) {
    event?.preventDefault?.();
    if (active || blocked()) return;
    failure = ""; notice = "";
    const robotId = activeRobotId();
    const speeds = manualSpeeds((view.robots || []).find(row => row.robot_id === robotId)?.state);
    const triggerEl = options.button || event?.currentTarget || command.button;
    const onPressChange = typeof options.onPressChange === "function" ? options.onPressChange : null;
    let releaseAbort = null;
    if (triggerEl && triggerEl !== command.button && typeof triggerEl.addEventListener === "function" && typeof AbortController === "function") {
      releaseAbort = new AbortController();
      for (const type of ["pointerup", "pointercancel", "lostpointercapture", "blur"]) {
        triggerEl.addEventListener(type, stop, {signal: releaseAbort.signal});
      }
    }
    active = {...command, linear: command.linear * speeds.linear, angular: command.angular * speeds.angular,
      robotId, generation: view.dispatchControl.generation, triggerEl, onPressChange, releaseAbort};
    view.manualDriveRobot = active.robotId;  // motion-source.js: this console is the driver
    if (typeof triggerEl?.setAttribute === "function") triggerEl.setAttribute("aria-pressed", "true");
    onPressChange?.(true, command.direction);
    if (event?.pointerId != null && typeof triggerEl?.setPointerCapture === "function") {
      try { triggerEl.setPointerCapture(event.pointerId); } catch (_error) { /* Window release also stops. */ }
    }
    cancelTimeout = scope.timeout(() => { stop(); notice = "2초 한도로 멈췄습니다. 계속하려면 다시 누르세요."; }, 2000);
    ticker.start();
    update();
    onStatusChange?.();
  }

  function startDirection(direction, event, options) {
    const command = buttons.find(item => item.direction === direction);
    if (!command) return false;
    start(command, event, options);
    return Boolean(active);
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
  function buildPoseText(id, focused) {
    const robot = view.stateUnavailable ? null : focused;
    const guideRow = view.stateUnavailable ? null : (view.guide?.robots || []).find(row => row.robot_id === id);
    const age = robot && Number.isFinite(robot.state_age_s)
      ? `상태 ${Math.round(robot.state_age_s + Math.max(0, Date.now() - (view.receivedAtMs ?? Date.now())) / 1000)}초 전` : "상태 시각 없음";
    return robot
      ? [sitePoseText(guideRow) || `위치 ${robotPoseText(robot.state, robot.localization)}`, `위치 관측 ${evidenceWord(robot, "pose")}`, age].join(" · ")
      : (id ? "상태 확인 불가" : "");
  }

  function getStatus(robotId = activeRobotId()) {
    const id = robotId ?? activeRobotId();
    const focused = (view.robots || []).find(row => row.robot_id === id);
    const isManual = focused?.state?.mode === "MANUAL";
    const enterManualWhy = blocked(false, id);
    const blockReason = blocked(true, id);
    const shown = manualSpeeds(focused?.state);
    const isActive = Boolean(id) && active?.robotId === id;
    return {
      robotId: id,
      isManual,
      canEnterManual: !isManual && !enterManualWhy,
      canDrive: !blockReason,
      blockReason,
      enterManualWhy,
      speedText: speedText(shown),
      poseText: buildPoseText(id, focused),
      notice,
      failure,
      activeDirection: isActive ? active.direction : null,
      isActive,
    };
  }

  function update() {
    const robotId = activeRobotId();
    if (!robotId && !active && !stopping && root.hidden && lastUpdatedRobotId === null) return;
    if (active && (active.robotId !== robotId || blocked())) stop();
    root.hidden = !robotId;
    root.setAttribute("aria-label", `${view.robotNames?.[robotId] || robotId || "로봇"} 수동 조종`);
    const focused = (view.robots || []).find(row => row.robot_id === robotId);
    const isManual = focused?.state?.mode === "MANUAL";
    mode.hidden = isManual;
    const modeWhy = blocked(false);
    mode.disabled = Boolean(modeWhy);
    // One cause, said once in the status line above (DESIGN: 한 원인은 한 번 말한다).
    if (modeWhy) mode.setAttribute("reason", "위 사유");
    else mode.removeAttribute("reason");
    const why = blocked();
    lockMark.hidden = !why;
    const shown = manualSpeeds(focused?.state);
    for (const {button} of adjust) {
      button.disabled = Boolean(modeWhy) || speedPending || !shown.set || !shown.max;
      if (button.disabled) button.setAttribute("reason", "위 사유"); else button.removeAttribute("reason");
    }
    for (const {button} of buttons) {
      button.disabled = Boolean(why);
      if (why) button.setAttribute("reason", "위 사유");
      else button.removeAttribute("reason");
    }
    pose.textContent = buildPoseText(robotId, focused);
    const speed = speedText(shown);
    if (!active && !stopping) reason.textContent = [failure, why].filter(Boolean).join(" · ") || notice || `누르는 동안만 이동 · 최대 2초 · ${speed}`;
    const statusSig = JSON.stringify([
      robotId || null, isManual, modeWhy, why, speed,
      Boolean(active), active?.direction || null, Boolean(stopping),
      modePending, speedPending, failure, notice,
    ]);
    lastUpdatedRobotId = robotId ?? null;
    if (statusSig !== lastStatusSig) {
      lastStatusSig = statusSig;
      onStatusChange?.();
    }
  }
  scope.interval(() => {
    if (!activeRobotId() && !active && !stopping) return;
    update();
  }, 1000);
  return {root, update, stop, getStatus, enterManual, startDirection};
}
