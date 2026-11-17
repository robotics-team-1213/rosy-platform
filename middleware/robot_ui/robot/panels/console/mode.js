import { MODE_LABEL, operatorModeLabel } from "/common/core_ui_logic.js";
import { confirmIrreversible } from "/common/ui.js";
import { statusTag } from "/common/status-tag.js";
import { createModeChoice } from "/assets/mode-choice.js";
import { watchStatus } from "/assets/dom.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
// D-359 US-009 — 운용자 글은 공용 MODE_LABEL이다. 열거값은 data-mode와 title에만 남는다.
const MODES = [
  {id: "IDLE", prompt: "현재 동작이 중단될 수 있습니다."},
  {id: "MANUAL", prompt: "주변과 운전 면적을 확인하세요."},
  {id: "NAVIGATION", prompt: "주행 경로를 확인하세요."},
].map((mode) => ({...mode, label: MODE_LABEL[mode.id], prompt: `${MODE_LABEL[mode.id]} 모드로 바꿀까요? ${mode.prompt}`}));

export function mount(root, ctx) {
  const lifetime = new AbortController(); let disposed = false; let confirming = false;
  // 독립 조작 묶음: 이 구획 자체가 ui-panel raised 하나다(상자 안 상자 없음).
  root.classList.add("ui-panel"); root.dataset.surface = "raised";
  const head = el("ui-head", "", "운전 모드");
  const modeStatus = el("ui-status", "", "현재 모드를 불러오는 중입니다.");
  const capabilityStatus = el("ui-status", "", "내비게이션 기능을 확인하는 중입니다.");
  const actionStatus = el("ui-status");
  watchStatus(actionStatus);
  modeStatus.setAttribute("state", "pending"); capabilityStatus.setAttribute("state", "pending"); actionStatus.setAttribute("state", "ready");
  // K20 buttons shared with the compat console (mode-choice.js); the current mode is aria-current, a pick asks first.
  const controls = el("ui-actions", "surface-actions mode-actions");
  const modeChoice = createModeChoice({id: "console-mode", element: controls, onPick: (id, opener) => pick(id, opener)});
  // 막힘은 주황 문장이 아니라 잠금 태그 + 사유 한 줄이다(C1). 쓸 수 있으면 아무것도 보이지 않는다.
  const lockRow = el("div", "mode-lock"); lockRow.hidden = true;
  lockRow.append(statusTag("locked", "내비게이션 잠김"), capabilityStatus);
  root.append(head, modeStatus, lockRow, actionStatus, controls);
  function setStatus(target, text) { if (target.textContent !== text) target.textContent = text; }
  let current = "";
  let navigationAvailable = false;
  let pending = false;
  function update() { modeChoice.show({current, pending, navigationAvailable}); }
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    current = state.mode || ""; setStatus(modeStatus, `현재 모드: ${operatorModeLabel(current, "확인 중")}`);
    modeStatus.setAttribute("state", current ? "ready" : "unavailable");
    if (current) modeStatus.title = current; else modeStatus.removeAttribute("title"); update();
  }, (error) => { current = ""; modeStatus.setAttribute("state", "error"); setStatus(modeStatus, `현재 모드를 읽지 못했습니다: ${error.message}`); update(); });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 5_000, (caps) => {
    navigationAvailable = caps?.navigation?.goal_navigation === true;
    capabilityStatus.textContent = navigationAvailable
      ? "내비게이션 기능을 쓸 수 있습니다."
      : caps?.navigation?.reason || "현재 실행 모드에서 막힘 또는 이 로봇에 없음";
    capabilityStatus.setAttribute("state", "ready");
    lockRow.hidden = navigationAvailable;
    update();
  }, (error) => {
    navigationAvailable = false;
    capabilityStatus.textContent = `내비게이션 기능을 확인할 수 없습니다: ${error.message}`;
    capabilityStatus.setAttribute("state", "error");
    lockRow.hidden = false;
    update();
  });
  async function pick(id, button) {
    const mode = MODES.find((item) => item.id === id);
    if (disposed || confirming || pending || !current || current === id || (id === "NAVIGATION" && !navigationAvailable)) return;
    confirming = true; update();
    const confirmed = await confirmIrreversible({message: mode.prompt, action: `${mode.label} 모드로 변경`, opener: button, signal: lifetime.signal});
    confirming = false;
    if (disposed) return;
    update();
    if (!confirmed || pending || !current || current === id || (id === "NAVIGATION" && !navigationAvailable)) return;
    pending = true; update();
    setStatus(actionStatus, `${mode.label} 모드 요청을 보내는 중입니다.`);
    actionStatus.setAttribute("state", "pending");
    // Ask any active hold-to-drive panel to send zero before changing mode.
    window.dispatchEvent(new Event("rosy:stop-motion"));
    try {
      await ctx.api("/api/v1/mode", {method: "POST", body: JSON.stringify({mode: id})});
      if (!disposed) { actionStatus.setAttribute("state", "ready"); setStatus(actionStatus, `${mode.label} 모드 요청을 로봇이 받았습니다. 현재 모드는 위에서 다시 확인하세요.`); }
    } catch (error) { if (!disposed) { actionStatus.setAttribute("state", "error"); setStatus(actionStatus, `모드 변경 실패: ${error.message}`); } }
    finally { if (!disposed) { pending = false; update(); } }
  }
  update();
  return () => { disposed = true; lifetime.abort(); stopState(); stopCapabilities(); };
}
