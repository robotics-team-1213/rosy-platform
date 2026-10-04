// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }
import { DOCK_STATE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { confirmIrreversible } from "/common/ui.js";
// Console owns motion commands; setup owns teaching and dock inventory.
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const lifetime = new AbortController(); let disposed = false; let confirming = false;
  const head = el("ui-head", "", "도킹 운용");
  const statusMessage = el("ui-status", "", "도킹 상태를 확인하는 중입니다.");
  const dockListStatus = el("ui-status", "", "도크 목록을 불러오는 중입니다.");
  const actionStatus = el("ui-status");
  statusMessage.setAttribute("state", "pending"); dockListStatus.setAttribute("state", "pending"); actionStatus.setAttribute("state", "ready");
  actionStatus.setAttribute("role", "status");
  actionStatus.setAttribute("aria-live", "polite");
  const facts = el("dl", "ui-readout");
  const form = el("div", "ui-form");
  const label = el("label", "ui-field-label", "도킹 위치");
  const select = el("select", "ui-field"); select.setAttribute("aria-label", "도킹 위치 선택"); label.append(select);
  const dock = el("ui-button", "", "도킹 시작"); dock.setAttribute("kind", "primary"); dock.type = "button"; dock.disabled = true;
  const actions = el("ui-actions", "surface-actions");
  const undock = el("ui-button", "", "언도크"); undock.setAttribute("kind", "quiet"); undock.type = "button";
  const cancel = el("ui-button", "", "도킹 취소"); cancel.setAttribute("kind", "quiet"); cancel.type = "button";
  actions.append(undock, cancel); form.append(label, dock); root.append(head, statusMessage, dockListStatus, actionStatus, facts, form, actions);

  let supported = false;
  let hasDocks = false;
  let statusKnown = false;
  let currentState = null;
  let pendingCommands = 0;
  function setStatus(target, text) { if (target.textContent !== text) target.textContent = text; }
  function enableActions() {
    const locked = pendingCommands > 0;
    select.disabled = locked || !hasDocks;
    // 명령 처리 중(locked)은 짧은 잠금이라 사유 없이 끈다.
    const base = locked ? "" : !statusKnown ? "상태 확인 중" : !supported ? "도킹 미지원" : "";
    setOff(dock, locked || !statusKnown || !supported || !hasDocks || !select.value,
      base || (locked ? "" : !hasDocks ? "등록된 도크 없음" : "도크를 고르세요"));
    setOff(undock, locked || !statusKnown || !supported, base);
    setOff(cancel, locked || !statusKnown || !supported, base);
  }
  function renderStatus(data) {
    if (typeof data.supported === "boolean") supported = data.supported;
    statusKnown = true;
    currentState = data.state;
    facts.replaceChildren(el("dt", "", "기능 지원"), el("dd", "", supported ? "사용 가능" : "제한 또는 미지원"),
      el("dt", "", "상태"), Object.assign(el("dd", "", enumLabel(DOCK_STATE_LABEL, data.state)), {title: data.state || ""}),
      el("dt", "", "현재 도크"), el("dd", "", data.dock_id || "—"),
      el("dt", "", "단계"), el("dd", "", data.phase || "—"),
      el("dt", "", "오류"), el("dd", "", data.error || "없음"));
    enableActions();
  }
  const stopStatus = ctx.store.poll("/api/v1/docking/status", 1_000, (data) => {
    renderStatus(data);
    setStatus(statusMessage, supported ? "도킹 기능을 쓸 수 있습니다." : "도킹 기능이 없어 주행 명령을 막았습니다.");
    statusMessage.setAttribute("state", supported ? "ready" : "warning");
  }, (error) => {
    supported = false; statusKnown = false; currentState = null;
    facts.replaceChildren(el("dt", "", "상태"), el("dd", "", "확인 불가 · 다시 확인 중"));
    statusMessage.textContent = `도킹 상태를 확인할 수 없어 명령을 막았습니다: ${error.message}`;
    statusMessage.setAttribute("state", "error"); enableActions();
  });
  const stopDocks = ctx.store.poll("/api/v1/docking/docks", 10_000, (data) => {
    const docks = data.docks || [];
    const selectedId = select.value;
    hasDocks = docks.length > 0;
    select.replaceChildren(...docks.map((item) => { const option = el("option", "", `${item.id} · ${item.type || "유형 없음"}`); option.value = item.id; return option; }));
    if (docks.some((item) => String(item.id) === selectedId)) select.value = selectedId;
    dockListStatus.textContent = hasDocks ? `등록된 도크 ${docks.length}개` : "등록된 도크가 없습니다.";
    dockListStatus.setAttribute("state", hasDocks ? "ready" : "warning");
    enableActions();
  }, (error) => {
    hasDocks = false; select.replaceChildren();
    dockListStatus.textContent = `도크 목록을 읽지 못했습니다. 이전 선택을 지우고 다시 확인 중입니다: ${error.message}`;
    dockListStatus.setAttribute("state", "error"); enableActions();
  });

  async function run(button, path, body, prompt, pendingMessage, success) {
    if (disposed || confirming || !supported || !statusKnown || pendingCommands > 0 || button.disabled) return;
    confirming = true; enableActions();
    const confirmed = await confirmIrreversible({message: prompt, action: button.textContent, opener: button, signal: lifetime.signal});
    confirming = false;
    if (disposed) return;
    enableActions();
    if (!confirmed || !supported || !statusKnown || pendingCommands > 0 || button.disabled || (body?.dock && body.dock !== select.value)) return;
    pendingCommands += 1;
    enableActions();
    setStatus(actionStatus, pendingMessage);
    actionStatus.setAttribute("state", "pending");
    try {
      const result = await ctx.api(path, {method: "POST", ...(body ? {body: JSON.stringify(body)} : {})});
      if (disposed) return;
      if (typeof result?.state === "string") renderStatus(result);
      actionStatus.setAttribute("state", "ready"); setStatus(actionStatus, success);
    }
    catch (error) { if (!disposed) { actionStatus.setAttribute("state", "error"); setStatus(actionStatus, `도킹 요청 실패: ${error.message}`); } }
    finally { pendingCommands -= 1; if (!disposed) enableActions(); }
  }
  dock.addEventListener("click", () => {
    const id = select.value;
    if (!id) return;
    run(dock, "/api/v1/docking/dock", {dock: id}, `${id} 도크로 주행할까요? 주변 안전을 확인하세요.`, `${id} 도킹 요청을 보내는 중입니다.`, `${id} 도킹 요청을 CORE가 받았습니다.`);
  });
  select.addEventListener("change", enableActions);
  undock.addEventListener("click", () => run(undock, "/api/v1/docking/undock", null, "언도크할까요?", "언도크 요청을 보내는 중입니다.", "언도크 요청을 CORE가 받았습니다."));
  cancel.addEventListener("click", () => run(cancel, "/api/v1/docking/cancel", null, "도킹을 취소할까요?", "도킹 취소 요청을 보내는 중입니다.", "도킹 취소 요청을 CORE가 받았습니다."));
  return {
    beforeHide() {
      if (pendingCommands > 0) return {message: "도킹 요청이 처리 중입니다. 상태 확인 뒤 조작 그룹을 바꾸세요."};
      if (!statusKnown) return {message: "도킹 상태를 확인할 수 없어 조작 그룹을 유지합니다."};
      if (["DOCKING", "UNDOCKING"].includes(currentState)) return {message: "도킹 작업이 끝나거나 취소 상태를 확인한 뒤 조작 그룹을 바꾸세요."};
      return true;
    },
    unmount() { disposed = true; lifetime.abort(); stopStatus(); stopDocks(); },
  };
}
