// D-440 6: the robot card's sleep / wake button. CORE owns the power API and keeps a robot that is not IDLE awake.
import { POWER_MODE_LABEL, enumLabel } from "/common/core_ui_logic.js";

export function createPowerButton({ robot, state, view, scope, call, log, isOperator, namedReason, blockWith }) {
  const asleep = ["STANDBY", "IDLE"].includes(state.power?.mode);
  const powerName = asleep ? "깨우기" : "절전";
  const power = document.createElement("ui-button");
  power.setAttribute("kind", "quiet");
  power.type = "button";
  power.dataset.powerAction = asleep ? "wake" : "sleep";
  power.textContent = powerName;
  blockWith(power, !isOperator() ? "운영자 권한이 필요합니다"
    : namedReason() ? namedReason()
    : !robot.online || view.stateUnavailable ? "로봇 연결을 확인하세요"
      : !asleep && state.mode !== "IDLE" ? "일하는 로봇은 절전할 수 없습니다" : "");
  power.addEventListener("click", scope.guard(async () => {
    try {
      const answer = await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/power`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: power.dataset.powerAction }),
      });
      const got = answer.result?.mode;
      // CORE answers with the mode it is in now: a refused sleep comes back ACTIVE.
      const done = got ? (asleep ? got === "ACTIVE" : got !== "ACTIVE") : null;
      log(`${robot.robot_id} ${powerName} · ${done === false ? "로봇이 받아들이지 않았습니다" : enumLabel(POWER_MODE_LABEL, got, "CORE 응답 확인")}`,
        done === false ? "bad" : "good");
    } catch (error) {
      if (error.name !== "AbortError") log(`${robot.robot_id} ${powerName} 실패 · ${error.message}`, "bad");
    }
  }));
  return power;
}
