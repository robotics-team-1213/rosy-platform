import { HEALTH_LABEL, enumLabel } from "/common/core_ui_logic.js";
export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.textContent = "진단 상태";
  const summary = document.createElement("p");
  const list = document.createElement("ul");
  list.className = "diagnostic-list";
  function render(data) {
    summary.textContent = `전체 상태: ${enumLabel(HEALTH_LABEL, data.health, "확인 전")}`;
    summary.title = data.health || "";
    list.replaceChildren();
    for (const [name, status] of Object.entries(data.components || {})) {
      const row = document.createElement("li");
      row.textContent = `${name}: ${enumLabel(HEALTH_LABEL, status)}`;
      list.append(row);
    }
    if (!list.children.length) { const row = document.createElement("li"); row.textContent = "구성 요소 진단을 아직 받지 못했습니다. 다음 조회를 기다리거나 장치 연결을 확인하세요."; list.append(row); }
  }
  function fail(error) {
    summary.textContent = `진단을 불러오지 못했습니다: ${error.message}`;
    list.replaceChildren();
  }
  el.append(head, summary, list);
  return ctx.store.poll("/api/v1/diagnostics", 5_000, render, fail);
}
