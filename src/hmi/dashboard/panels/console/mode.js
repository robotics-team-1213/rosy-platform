import { MODE_LABEL, enumLabel } from "/common/core_ui_logic.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
// D-359 US-009 — 운용자 글은 공용 MODE_LABEL이다. 열거값은 data-mode와 title에만 남는다.
const MODES = [
  {id: "IDLE", prompt: "현재 동작이 중단될 수 있습니다."},
  {id: "MANUAL", prompt: "주변과 운전 면적을 확인하세요."},
  {id: "NAVIGATION", prompt: "주행 경로를 확인하세요."},
].map((mode) => ({...mode, label: MODE_LABEL[mode.id], prompt: `${MODE_LABEL[mode.id]} 모드로 바꿀까요? ${mode.prompt}`}));

export function mount(root, ctx) {
  const head = el("ui-head", "", "운전 모드");
  const modeStatus = el("ui-status", "", "현재 모드를 불러오는 중입니다.");
  const capabilityStatus = el("ui-status", "", "Navigation 기능 지원 확인 중입니다.");
  const actionStatus = el("ui-status");
  actionStatus.setAttribute("role", "status");
  actionStatus.setAttribute("aria-live", "polite");
  const controls = el("ui-actions", "surface-actions");
  const buttons = new Map();
  for (const mode of MODES) {
    const button = el("ui-button", "", mode.label); button.setAttribute("kind", "segment"); button.type = "button";
    button.setAttribute("aria-label", `${mode.label} 모드`); button.dataset.mode = mode.id; button.title = mode.id; button.disabled = true;
    controls.append(button); buttons.set(mode.id, button);
  }
  root.append(head, modeStatus, capabilityStatus, actionStatus, controls);
  function setStatus(target, text) { if (target.textContent !== text) target.textContent = text; }
  let current = "";
  let navigationAvailable = false;
  let pending = false;
  function update() {
    for (const [id, button] of buttons) {
      button.disabled = pending || !current || id === current || (id === "NAVIGATION" && !navigationAvailable);
      // D-359 §5.3 — 사유는 같은 조건에서 나온다. 지금 모드는 눌림(aria-pressed)이 말한다.
      const reason = pending ? "모드 변경 처리 중"
        : !current ? "현재 모드 확인 중"
          : id !== current && id === "NAVIGATION" && !navigationAvailable ? "이 프로필에서 쓸 수 없음" : "";
      if (reason) button.setAttribute("reason", reason);
      else button.removeAttribute("reason");
      button.setAttribute("aria-pressed", String(id === current));
    }
  }
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    current = state.mode || ""; setStatus(modeStatus, `현재 모드: ${enumLabel(MODE_LABEL, current, "확인 중")}`);
    if (current) modeStatus.title = current; else modeStatus.removeAttribute("title"); update();
  }, (error) => { current = ""; setStatus(modeStatus, `현재 모드를 읽지 못했습니다: ${error.message}`); update(); });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 5_000, (caps) => {
    navigationAvailable = caps?.navigation?.goal_navigation === true;
    capabilityStatus.textContent = navigationAvailable
      ? "Navigation 기능을 사용할 수 있습니다."
      : `Navigation을 사용할 수 없습니다.${caps?.navigation?.reason ? ` ${caps.navigation.reason}` : " 이 profile에서 제한되거나 제공되지 않습니다."}`;
    capabilityStatus.setAttribute("state", navigationAvailable ? "ready" : "warning");
    update();
  }, (error) => {
    navigationAvailable = false;
    capabilityStatus.textContent = `Navigation 기능 지원을 확인할 수 없습니다: ${error.message}`;
    capabilityStatus.setAttribute("state", "error");
    update();
  });
  for (const mode of MODES) {
    buttons.get(mode.id).addEventListener("click", async () => {
      const button = buttons.get(mode.id);
      if (button.disabled || pending || (mode.id === "NAVIGATION" && !navigationAvailable)) return;
      if (!window.confirm(mode.prompt)) return;
      pending = true; update();
      setStatus(actionStatus, `${mode.label} 모드 요청을 보내는 중입니다.`);
      // Ask any active hold-to-drive panel to send zero before changing mode.
      window.dispatchEvent(new Event("rosy:stop-motion"));
      try {
        await ctx.api("/api/v1/mode", {method: "POST", body: JSON.stringify({mode: mode.id})});
        setStatus(actionStatus, `${mode.label} 모드 요청을 CORE가 받았습니다. 현재 모드는 위에서 다시 확인하세요.`);
      } catch (error) { setStatus(actionStatus, `모드 변경 실패: ${error.message}`); }
      finally { pending = false; update(); }
    });
  }
  update();
  return () => { stopState(); stopCapabilities(); };
}
