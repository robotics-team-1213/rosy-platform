// D-395 / fix/fleet-relative-step-nudge — 0.10 m forward/backward step buttons in robot detail.
// One POST per click (no hold auto-repeat, no chaining while running); stop control stays separate.
import { createCauseLine } from "/common/cause-line.js";

export const STEP_DISTANCE_M = 0.10;
const NUDGE_KINDS = new Set(["nudge_forward", "nudge_backward"]);

export function reportingOff(robot) {
  if (!robot) return false;
  if (robot.capabilities?.loc_assist === false || robot.capabilities?.localization === false) return true;
  if (robot.localization === null || robot.localization?.reporting === false) return true;
  return false;
}

export function isNudgeMissionRunning(mission) {
  return Boolean(mission && NUDGE_KINDS.has(mission.kind) && mission.state === "running");
}

export function stepRefusalText(error) {
  const code = String(error?.code || error?.detail?.code || "");
  const raw = String(error?.message || error?.detail?.message || error?.detail || "");
  const hay = `${code} ${raw}`.toLowerCase();
  if (code === "STEP_ROBOT_BUSY" || hay.includes("step_robot_busy")) {
    const holder = error?.holder || error?.detail?.holder || raw.replace(/^STEP_ROBOT_BUSY[:\s-]*/i, "").trim();
    return holder ? `로봇 사용 중 (${holder})` : "로봇이 다른 작업으로 사용 중입니다";
  }
  if (code === "ROBOT_OFFLINE" || hay.includes("robot_offline")) return "로봇이 오프라인입니다";
  if (code === "UNKNOWN_ROBOT" || hay.includes("unknown_robot")) return "등록되지 않은 로봇입니다";
  if (hay.includes("path_not_clear")) return "앞/뒤 막힘";
  if (code === "TRIP_LEASED" || hay.includes("trip_leased")) return "주행 임대 중이라 이동할 수 없습니다";
  if (hay.includes("calibration_lease")) return "보정 임대 중이라 이동할 수 없습니다";
  if (hay.includes("nav not ready") || hay.includes("nav_not_ready")) return "내비게이션이 준비되지 않았습니다";
  if (hay.includes("reporting required") || hay.includes("reporting_required") || hay.includes("d-395")) {
    return "위치 보고가 꺼져 있음";
  }
  return raw || "한 걸음 이동을 실행하지 못했습니다";
}

export function createStepNudge({ scope, call, isOperator = () => true, namedReason = () => "", pollMs = 350, maxPollErrors = 5 } = {}) {
  const runningByRobot = new Map();
  const errorByRobot = new Map();
  let pollTimer = null;
  let epoch = 0;

  function stopPoll() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }
  function isCurrent(runEpoch, life) {
    return runEpoch === epoch && !scope?.signal?.aborted && (!life || life.current());
  }
  scope?.onDispose?.(() => {
    epoch += 1;
    stopPoll();
    runningByRobot.clear();
    errorByRobot.clear();
  });

  async function pollLocalization(robotId, onUpdate, runEpoch, life, failures = 0) {
    stopPoll();
    if (!isCurrent(runEpoch, life) || !runningByRobot.get(robotId)) return;
    try {
      const sig = life?.signal || scope?.signal;
      const loc = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/localization`,
        sig ? { signals: [sig] } : undefined);
      if (!isCurrent(runEpoch, life) || !runningByRobot.get(robotId)) return;
      failures = 0;
      const mission = loc?.mission || loc?.last_mission || loc?.status?.mission;
      if (mission && NUDGE_KINDS.has(mission.kind)) {
        if (mission.state === "done") {
          runningByRobot.delete(robotId);
          onUpdate?.();
          return;
        }
        if (mission.state && mission.state !== "running") {
          runningByRobot.delete(robotId);
          if (mission.reason) errorByRobot.set(robotId, stepRefusalText({ message: mission.reason }));
          onUpdate?.();
          return;
        }
      }
    } catch (err) {
      if (!isCurrent(runEpoch, life) || err?.name === "AbortError") return;
      failures += 1;
      if (failures >= maxPollErrors) {
        runningByRobot.delete(robotId);
        errorByRobot.set(robotId, stepRefusalText(err));
        onUpdate?.();
        return;
      }
    }
    if (isCurrent(runEpoch, life) && runningByRobot.get(robotId)) {
      pollTimer = setTimeout(() => { void pollLocalization(robotId, onUpdate, runEpoch, life, failures); }, pollMs);
    }
  }

  function renderPanel({ robot, onUpdate } = {}) {
    const robotId = robot?.robot_id || "";
    const section = document.createElement("section");
    section.className = "step-nudge";
    section.setAttribute("aria-label", "한 걸음 이동");

    const actions = document.createElement("ui-actions");
    const fwd = document.createElement("ui-button");
    fwd.setAttribute("kind", "quiet");
    fwd.type = "button";
    fwd.dataset.stepNudge = "forward";
    fwd.textContent = "앞으로 0.10 m";

    const bwd = document.createElement("ui-button");
    bwd.setAttribute("kind", "quiet");
    bwd.type = "button";
    bwd.dataset.stepNudge = "backward";
    bwd.textContent = "뒤로 0.10 m";

    const status = document.createElement("p");
    status.className = "hint step-nudge-status";
    status.setAttribute("role", "status");
    status.hidden = true;

    actions.append(fwd, bwd);
    section.append(actions, status);

    const cause = createCauseLine(section);

    function sync() {
      const running = Boolean(runningByRobot.get(robotId))
        || isNudgeMissionRunning(robot?.localization?.mission || robot?.localization?.last_mission);
      const disabledReason = running ? "한 걸음 이동 진행 중입니다"
        : !isOperator() ? "운영자 권한이 필요합니다"
        : namedReason() ? namedReason()
        : !robot?.online ? "로봇이 오프라인입니다"
        : reportingOff(robot) ? "위치 보고가 꺼져 있음"
        : "";
      cause.set([fwd, bwd], disabledReason);
      const err = errorByRobot.get(robotId);
      if (running) {
        status.textContent = "한 걸음 이동 중…";
        status.hidden = false;
      } else if (err) {
        status.textContent = err;
        status.hidden = false;
      } else {
        status.textContent = "";
        status.hidden = true;
      }
    }

    async function sendStep(direction) {
      if (!robotId || runningByRobot.get(robotId) || fwd.disabled || bwd.disabled) return;
      const runEpoch = epoch;
      const life = typeof scope?.capture === "function" ? scope.capture() : null;
      const sig = life?.signal || scope?.signal;
      errorByRobot.delete(robotId);
      runningByRobot.set(robotId, direction);
      sync();
      try {
        await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/step`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ direction, distance_m: STEP_DISTANCE_M }),
          ...(sig ? { signals: [sig] } : {}),
        });
        if (!isCurrent(runEpoch, life)) return;
        void pollLocalization(robotId, () => { sync(); onUpdate?.(); }, runEpoch, life);
      } catch (err) {
        runningByRobot.delete(robotId);
        if (!isCurrent(runEpoch, life)) return;
        if (err?.name !== "AbortError") errorByRobot.set(robotId, stepRefusalText(err));
        sync();
      }
    }

    for (const [btn, dir] of [[fwd, "forward"], [bwd, "backward"]]) {
      btn.addEventListener("keydown", (event) => {
        if (event.repeat && (event.key === " " || event.key === "Enter")) {
          event.preventDefault();
          event.stopImmediatePropagation();
        }
      }, true);
      btn.addEventListener("click", () => { void sendStep(dir); });
    }

    sync();
    return { element: section, sync, sendStep };
  }

  return { renderPanel, isRunning: (id) => Boolean(runningByRobot.get(id)) };
}
