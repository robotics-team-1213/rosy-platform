// Console owns motion commands; setup owns teaching and dock inventory.
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "도킹 운용");
  const message = el("ui-status", "", "도킹 지원 여부를 확인하는 중입니다.");
  const facts = el("dl", "ui-readout");
  const form = el("div", "ui-form");
  const label = el("label", "ui-field-label", "도킹 위치");
  const select = el("select"); select.setAttribute("aria-label", "도킹 위치 선택"); label.append(select);
  const dock = el("ui-button", "", "도킹 시작"); dock.setAttribute("kind", "primary"); dock.type = "button"; dock.disabled = true;
  const actions = el("ui-actions", "surface-actions");
  const undock = el("ui-button", "", "언도크"); undock.setAttribute("kind", "quiet"); undock.type = "button";
  const cancel = el("ui-button", "", "도킹 취소"); cancel.setAttribute("kind", "quiet"); cancel.type = "button";
  actions.append(undock, cancel); form.append(label, dock); root.append(head, message, facts, form, actions);

  let supported = false;
  let hasDocks = false;
  let statusKnown = false;
  let currentState = null;
  let pendingCommands = 0;
  function enableActions() {
    const enabled = supported;
    dock.disabled = !enabled || !hasDocks || !select.value;
    undock.disabled = cancel.disabled = !enabled;
  }
  function renderStatus(data) {
    if (typeof data.supported === "boolean") supported = data.supported;
    statusKnown = true;
    currentState = data.state;
    facts.replaceChildren(el("dt", "", "기능 지원"), el("dd", "", supported ? "사용 가능" : "제한 또는 미지원"),
      el("dt", "", "상태"), el("dd", "", data.state || "—"),
      el("dt", "", "현재 도크"), el("dd", "", data.dock_id || "—"),
      el("dt", "", "단계"), el("dd", "", data.phase || "—"),
      el("dt", "", "오류"), el("dd", "", data.error || "없음"));
    enableActions();
  }
  const stopStatus = ctx.store.poll("/api/v1/docking/status", 1_000, (data) => {
    renderStatus(data);
    message.textContent = supported ? "도킹 capability가 활성화되어 있습니다." : "도킹 capability가 없어서 주행 명령을 막았습니다.";
  }, (error) => { supported = false; statusKnown = false; message.textContent = `도킹 상태를 확인할 수 없어 명령을 막았습니다: ${error.message}`; enableActions(); });
  const stopDocks = ctx.store.poll("/api/v1/docking/docks", 10_000, (data) => {
    const docks = data.docks || [];
    hasDocks = docks.length > 0;
    select.replaceChildren(...docks.map((item) => { const option = el("option", "", `${item.id} · ${item.type || "유형 없음"}`); option.value = item.id; return option; }));
    select.disabled = !hasDocks;
    enableActions();
  }, (error) => { hasDocks = false; select.replaceChildren(); select.disabled = true; message.textContent = `도크 목록을 읽지 못해 동작을 막았습니다: ${error.message}`; enableActions(); });

  async function run(button, path, body, prompt, success) {
    if (!supported || button.disabled || !window.confirm(prompt)) return;
    pendingCommands += 1;
    button.disabled = true;
    try {
      const result = await ctx.api(path, {method: "POST", ...(body ? {body: JSON.stringify(body)} : {})});
      if (typeof result?.state === "string") renderStatus(result);
      message.textContent = success;
    }
    catch (error) { message.textContent = `도킹 요청 실패: ${error.message}`; }
    finally { pendingCommands -= 1; enableActions(); }
  }
  dock.addEventListener("click", () => {
    const id = select.value;
    if (!id) return;
    run(dock, "/api/v1/docking/dock", {dock: id}, `${id} 도크로 주행할까요? 주변 안전을 확인하세요.`, `${id} 도킹 요청을 CORE가 받았습니다.`);
  });
  select.addEventListener("change", enableActions);
  undock.addEventListener("click", () => run(undock, "/api/v1/docking/undock", null, "언도크할까요?", "언도크 요청을 CORE가 받았습니다."));
  cancel.addEventListener("click", () => run(cancel, "/api/v1/docking/cancel", null, "도킹을 취소할까요?", "도킹 취소 요청을 CORE가 받았습니다."));
  return {
    beforeHide() {
      if (pendingCommands > 0) return {message: "도킹 요청이 처리 중입니다. 상태 확인 뒤 조작 그룹을 바꾸세요."};
      if (!statusKnown) return {message: "도킹 상태를 확인할 수 없어 조작 그룹을 유지합니다."};
      if (["DOCKING", "UNDOCKING"].includes(currentState)) return {message: "도킹 작업이 끝나거나 취소 상태를 확인한 뒤 조작 그룹을 바꾸세요."};
      return true;
    },
    unmount() { stopStatus(); stopDocks(); },
  };
}
