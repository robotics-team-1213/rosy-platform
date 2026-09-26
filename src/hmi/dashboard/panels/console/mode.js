function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
const MODES = [
  {id: "IDLE", label: "대기", prompt: "IDLE 모드로 변경할까요? 현재 동작이 중단될 수 있습니다."},
  {id: "MANUAL", label: "수동", prompt: "MANUAL 모드로 변경할까요? 주변과 운전 면적을 확인하세요."},
  {id: "NAVIGATION", label: "내비게이션", prompt: "NAVIGATION 모드로 변경할까요? 주행 경로를 확인하세요."},
];

export function mount(root, ctx) {
  const head = el("ui-head", "", "운전 모드");
  const status = el("p", "surface-message", "현재 모드를 불러오는 중입니다."); status.setAttribute("role", "status");
  const controls = el("div", "surface-actions");
  const buttons = new Map();
  for (const mode of MODES) {
    const button = el("ui-button", "", mode.label); button.setAttribute("kind", "segment"); button.type = "button";
    button.setAttribute("aria-label", `${mode.label} 모드`); button.dataset.mode = mode.id; button.disabled = true;
    controls.append(button); buttons.set(mode.id, button);
  }
  root.append(head, status, controls);
  let current = "";
  let navigationAvailable = false;
  let pending = false;
  function update() {
    for (const [id, button] of buttons) {
      button.disabled = pending || !current || id === current || (id === "NAVIGATION" && !navigationAvailable);
      button.setAttribute("aria-pressed", String(id === current));
    }
  }
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    current = state.mode || ""; status.textContent = `현재 모드: ${current || "확인 중"}`; update();
  }, (error) => { current = ""; status.textContent = `현재 모드를 읽지 못했습니다: ${error.message}`; update(); });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 5_000, (caps) => {
    navigationAvailable = caps?.navigation?.goal_navigation === true;
    if (!navigationAvailable) {
      const nav = buttons.get("NAVIGATION"); nav.title = "이 프로필에서는 Navigation이 제한되거나 제공되지 않습니다.";
      nav.setAttribute("aria-description", nav.title);
    }
    update();
  }, (error) => { navigationAvailable = false; status.textContent = `모드 capability를 확인하지 못했습니다: ${error.message}`; update(); });
  for (const mode of MODES) {
    buttons.get(mode.id).addEventListener("click", async () => {
      const button = buttons.get(mode.id);
      if (button.disabled || pending || (mode.id === "NAVIGATION" && !navigationAvailable)) return;
      if (!window.confirm(mode.prompt)) return;
      pending = true; update();
      // Ask any active hold-to-drive panel to send zero before changing mode.
      window.dispatchEvent(new Event("rosy:stop-motion"));
      try {
        await ctx.api("/api/v1/mode", {method: "POST", body: JSON.stringify({mode: mode.id})});
        status.textContent = `${mode.id} 모드 요청을 전달했습니다.`;
      } catch (error) { status.textContent = `모드 변경 실패: ${error.message}`; }
      finally { pending = false; update(); }
    });
  }
  update();
  return () => { stopState(); stopCapabilities(); };
}
