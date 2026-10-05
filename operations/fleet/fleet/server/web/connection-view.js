// Connection guidance owns presentation; authorization remains in console.js.
export function createConnectionView({scope, el}) {
  function setTopbarOpen(open) {
    el("topbar-more").setAttribute("aria-expanded", String(open));
    el("topbar-extra").dataset.open = String(open);
  }
  scope.listen(el("topbar-more"), "click", () => {
    setTopbarOpen(el("topbar-more").getAttribute("aria-expanded") !== "true");
  });
  for (const id of ["workflow-connect", "connection-guide-action"]) {
    scope.listen(el(id), "click", event => {
      event.preventDefault(); setTopbarOpen(true); el("console-token").focus();
    });
  }
  scope.listen(el("workflow-start"), "click", () => { el("start-point-tools").open = true; });

  function show(reason, token) {
    el("connection-guide").hidden = false;
    const title = reason === "auth" ? "관제 접속 필요" : "관제 연결 확인 필요";
    el("connection-guide-title").textContent = title;
    el("connection-guide-detail").textContent = reason !== "auth"
      ? "관제 PC의 연결 상태를 확인한 뒤 다시 접속하세요."
      : token ? "관제 토큰이 확인되지 않았습니다. 토큰을 확인한 뒤 다시 접속하세요."
        : "관제 토큰으로 접속하면 로봇·카메라·지도 상태를 확인할 수 있습니다.";
    el("map-stage").dataset.mapState = "auth";
    const canvas = el("map-canvas");
    canvas.setAttribute("aria-hidden", "true"); canvas.tabIndex = -1; canvas.classList.add("idle");
    el("map-empty").hidden = false; el("map-legend").hidden = true;
    el("map-empty-title").textContent = title;
    el("map-empty-detail").textContent = "관제에 접속하면 지도와 로봇 좌표를 확인할 수 있습니다.";
    el("map-tag").textContent = "접속 필요";
    el("dispatch-control-title").textContent = title;
    el("dispatch-control-detail").textContent = "관제에 접속하면 대기 작업과 발행 상태를 확인할 수 있습니다.";
    el("dispatch-rearm").hidden = true;

  }
  return {open: () => setTopbarOpen(true), show, hide: () => { el("connection-guide").hidden = true; }};
}
