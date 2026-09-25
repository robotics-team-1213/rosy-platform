// Dock preparation and operator actions follow DNC API roles and support flags.
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "도킹 준비 및 상태");
  const status = el("p", "surface-message", "도킹 상태를 불러오는 중입니다."); status.setAttribute("role", "status");
  const facts = el("dl", "surface-readout");
  const list = el("ul", "waypoint-list"); list.setAttribute("aria-label", "등록된 도크");
  const actions = el("div", "surface-actions");
  const undock = el("ui-button", "", "언도크"); undock.type = "button";
  const cancel = el("ui-button", "", "도킹 취소"); cancel.type = "button";
  actions.append(undock, cancel);
  root.append(head, status, facts, list, actions);

  let supported = false;
  let docks = [];
  function renderDocks() {
    list.replaceChildren();
    if (!docks.length) { list.append(el("li", "", "등록된 도크가 없습니다.")); return; }
    for (const dock of docks) {
      const row = el("li", ""); row.dataset.dockId = dock.id;
      const detail = el("span", "", `${dock.id} · ${dock.type || "유형 없음"} · 맵 ${dock.map_id || "미지정"}`);
      const teach = el("ui-button", "", "현재 위치 기록"); teach.type = "button";
      const go = el("ui-button", "", "도킹 시작"); go.type = "button";
      teach.disabled = !dock.id; go.disabled = !supported;
      teach.addEventListener("click", async () => {
        if (!window.confirm(`현재 로봇 위치를 ${dock.id} 도크 포즈로 기록할까요? 먼저 실제 도킹 위치에 로봇을 맞추세요.`)) return;
        teach.disabled = true;
        try { await ctx.api(`/api/v1/docking/docks/${encodeURIComponent(dock.id)}/teach`, {method: "POST"}); status.textContent = `${dock.id}의 현재 위치 기록을 요청했습니다.`; }
        catch (error) { status.textContent = `위치 기록 실패: ${error.message}`; }
        finally { teach.disabled = false; }
      });
      go.addEventListener("click", async () => {
        if (!supported || !window.confirm(`${dock.id} 도크로 이동을 요청할까요? 주변 안전을 확인하세요.`)) return;
        go.disabled = true;
        try { await ctx.api("/api/v1/docking/dock", {method: "POST", body: JSON.stringify({dock: dock.id})}); status.textContent = `${dock.id} 도킹 요청을 CORE가 받았습니다.`; }
        catch (error) { status.textContent = `도킹 요청 실패: ${error.message}`; }
        finally { go.disabled = !supported; }
      });
      row.append(detail, teach, go); list.append(row);
    }
  }

  const stopStatus = ctx.store.poll("/api/v1/docking/status", 2_000, (data) => {
    supported = data.supported === true;
    facts.replaceChildren(el("dt", "", "지원"), el("dd", "", supported ? "사용 가능" : "미지원 또는 제한"),
      el("dt", "", "상태"), el("dd", "", data.state || "—"),
      el("dt", "", "도크 ID"), el("dd", "", data.dock_id || "—"),
      el("dt", "", "단계"), el("dd", "", data.phase || "—"),
      el("dt", "", "오류"), el("dd", "", data.error || "없음"));
    status.textContent = supported ? "도킹 기능이 지원됩니다." : "도킹 기능이 현재 capability에 없어 동작을 막았습니다.";
    cancel.disabled = !supported; undock.disabled = !supported; renderDocks();
  }, (error) => {
    supported = false; cancel.disabled = undock.disabled = true;
    status.textContent = `도킹 상태를 확인하지 못해 동작을 막았습니다: ${error.message}`; renderDocks();
  });
  const stopDocks = ctx.store.poll("/api/v1/docking/docks", 10_000, (data) => { docks = data.docks || []; renderDocks(); }, (error) => { status.textContent = `등록된 도크를 읽지 못했습니다: ${error.message}`; });

  async function command(button, path, prompt, success) {
    if (!supported || !window.confirm(prompt)) return;
    button.disabled = true;
    try { await ctx.api(path, {method: "POST"}); status.textContent = success; }
    catch (error) { status.textContent = `요청 실패: ${error.message}`; }
    finally { button.disabled = !supported; }
  }
  undock.addEventListener("click", () => command(undock, "/api/v1/docking/undock", "언도크를 요청할까요?", "언도크 요청을 CORE가 받았습니다."));
  cancel.addEventListener("click", () => command(cancel, "/api/v1/docking/cancel", "현재 도킹 작업을 취소할까요?", "도킹 취소를 CORE가 받았습니다."));

  return () => { stopStatus(); stopDocks(); };
}
