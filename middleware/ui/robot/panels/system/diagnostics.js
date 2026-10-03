export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.textContent = "진단 상태";
  const summary = document.createElement("p");
  const list = document.createElement("ul");
  list.className = "diagnostic-list";
  function render(data) {
    summary.textContent = `전체 상태: ${data.health || "UNKNOWN"}`;
    list.replaceChildren();
    for (const [name, status] of Object.entries(data.components || {})) {
      const row = document.createElement("li");
      row.textContent = `${name}: ${status}`;
      list.append(row);
    }
  }
  function fail(error) {
    summary.textContent = `진단을 불러오지 못했습니다: ${error.message}`;
    list.replaceChildren();
  }
  el.append(head, summary, list);
  return ctx.store.poll("/api/v1/diagnostics", 5_000, render, fail);
}
