// Connection guidance owns presentation; authorization remains in console.js.
export function createConnectionView({scope, el}) {
  let openedForLock = false;
  function setTopbarOpen(open) {
    el("topbar-more").setAttribute("aria-expanded", String(open));
    el("topbar-extra").dataset.open = String(open);
  }
  scope.listen(el("topbar-more"), "click", () => {
    openedForLock = false;
    setTopbarOpen(el("topbar-more").getAttribute("aria-expanded") !== "true");
  });
  scope.listen(el("connection-guide-action"), "click", event => {
    openedForLock = false;
    event.preventDefault(); setTopbarOpen(true);
    // D-519 — the 아이디 field when the login form shows, else the token field.
    const form = document.getElementById("password-login");
    if (form && !form.hidden) form.querySelector("[data-login=login]").focus();
    else {
      el("token-access").open = true;
      el("console-token").focus();
    }
  });

  function show(reason, token) {
    el("connection-guide").hidden = false;
    const title = reason === "auth" ? "관제 접속 필요" : "관제 연결 확인 필요";
    el("connection-guide-title").textContent = title;
    el("connection-guide-detail").textContent = reason !== "auth"
      ? "관제 PC의 연결 상태를 확인한 뒤 다시 접속하세요."
      : token ? "관제 토큰이 확인되지 않았습니다. 토큰을 확인한 뒤 다시 접속하세요."
        : "아이디·비밀번호나 관제 토큰으로 접속하면 로봇·카메라·지도 상태를 확인할 수 있습니다.";
    el("map-stage").dataset.mapState = "auth";
    const canvas = el("map-canvas");
    canvas.setAttribute("aria-hidden", "true"); canvas.tabIndex = -1; canvas.classList.add("idle");
    el("map-empty").hidden = false; el("map-legend").hidden = true;
    el("map-empty-title").textContent = title;
    el("map-empty-detail").textContent = "관제에 접속하면 지도와 로봇 좌표를 확인할 수 있습니다.";
    el("map-tag").textContent = "접속 필요";
    // 접속 안내는 위 띠 하나가 말한다. 발행 띠는 접속 전엔 읽을 상태가 없어 접는다.
    el("dispatch-control").hidden = true;
    el("dispatch-rearm").hidden = true;
  }
  return {open: () => {
    if (el("topbar-more").getAttribute("aria-expanded") !== "true") {
      setTopbarOpen(true);
      openedForLock = true;
    }
  }, show, hide: () => {
    el("connection-guide").hidden = true;
    if (openedForLock) setTopbarOpen(false);
    openedForLock = false;
    // 지난 세션의 발행 문구를 살아 있는 상태처럼 보이지 않는다. 다음 조회가 덮어쓴다.
    el("dispatch-control-title").textContent = "발행 상태 확인 중";
    el("dispatch-control-detail").textContent = "대기 작업과 정지 세대를 읽고 있습니다.";
    delete el("dispatch-control").dataset.state;
    el("dispatch-control").hidden = false;
  }};
}
