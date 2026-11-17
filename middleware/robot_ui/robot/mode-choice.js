// Driving mode (IDLE / MANUAL / NAVIGATION) for the compat console and the console panel: one definition (S2).
// K20 commands, not a K1 choice (panel 2026-11-14): a pick is a confirmed request to the robot, and native radios would
// ask for a confirmation on every arrow key and cannot show "no value" for SAFE_STOP. The mode the robot reports is
// shown by the current button (disabled, aria-current), the status line and the hero; each other button asks.
import {MODE_LABEL} from "/common/core_ui_logic.js";

export const MODE_IDS = ["IDLE", "MANUAL", "NAVIGATION"];

/** onPick(modeId, button): the user pressed another mode's button. */
export function createModeChoice({id, onPick, element = document.createElement("ui-actions")}) {
  element.id = id; element.setAttribute("aria-label", "로봇 운전 모드");
  const buttons = new Map();
  for (const mode of MODE_IDS) {
    const button = document.createElement("ui-button"); button.setAttribute("kind", "quiet"); button.type = "button";
    button.textContent = MODE_LABEL[mode]; button.setAttribute("aria-label", `${MODE_LABEL[mode]} 모드`);
    button.dataset.mode = mode; button.title = mode; button.disabled = true; button.setAttribute("reason", "현재 모드 확인 중");
    button.addEventListener("click", () => { if (!button.disabled) onPick(mode, button); });
    buttons.set(mode, button); element.append(button);
  }
  return {
    element,
    /** state: {current, pending, navigationAvailable}. Reasons are the same sentences on both pages. */
    show({current, pending, navigationAvailable}) {
      for (const [mode, button] of buttons) {
        const reason = !current ? "현재 모드 확인 중" : mode === current ? "" : pending ? "모드 변경 처리 중"
          : mode === "NAVIGATION" && !navigationAvailable ? "이 로봇에서 쓸 수 없음" : "";
        button.disabled = !current || mode === current || pending || Boolean(reason);
        if (reason) button.setAttribute("reason", reason); else button.removeAttribute("reason");
        if (mode === current) button.setAttribute("aria-current", "true"); else button.removeAttribute("aria-current");
      }
    },
  };
}
