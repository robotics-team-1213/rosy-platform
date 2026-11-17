import {createConnectionNotice} from "/common/connection-notice.js";
import {bindTopbarToggle, setTopbarOpen} from "/console/assets/fleet-header.js";

// Connection guidance owns presentation; authorization remains in console.js.
export function createConnectionView({scope, el}) {
  bindTopbarToggle(scope.listen);
  const titleNotice = createConnectionNotice(el("connection-guide-title"));
  // The account row is on demand only (D-741 3): this strip's 관제 접속 is the way in, and it opens the row.
  scope.listen(el("connection-guide-action"), "click", event => {
    event.preventDefault(); setTopbarOpen(true);
    el("fleet-login").click();
  });

  function show(reason, token) {
    const auth = reason === "auth";
    // 연결 상태는 머리말 표시(#link-state) 하나가 말한다(D-1117). 이 띠는 행동이 필요한
    // 접속 안내(auth)일 때만 서고, 끊김 문구를 되풀이하지 않는다.
    el("connection-guide").hidden = !auth;
    if (auth) {
      titleNotice.set("auth-wait", "관제 접속 필요");
      el("connection-guide-detail").textContent = token
        ? "관제 토큰이 확인되지 않았습니다. 토큰을 확인한 뒤 다시 접속하세요."
        : "아이디·비밀번호나 관제 토큰으로 접속하면 로봇·카메라·지도 상태를 확인할 수 있습니다.";
    }
    el("map-stage").dataset.mapState = "auth";
    const canvas = el("map-canvas");
    canvas.setAttribute("aria-hidden", "true"); canvas.tabIndex = -1; canvas.classList.add("idle");
    el("map-empty").hidden = false; el("map-legend").hidden = true;
    // 지도 빈 상태는 접속·연결 문구를 다시 쓰지 않고 지도 고유 내용만 말한다.
    el("map-empty-title").textContent = "지도 없음";
    el("map-empty-detail").textContent = "관제에 접속하면 지도와 로봇 좌표를 확인할 수 있습니다.";
    el("map-tag").textContent = "지도 없음";
    // 접속 안내는 위 띠 하나가 말한다. 발행 띠는 접속 전엔 읽을 상태가 없어 접는다.
    el("dispatch-control").hidden = true;
    el("dispatch-rearm").hidden = true;
  }
  return {show, hide: () => {
    el("connection-guide").hidden = true;
    // 지난 세션의 발행 문구를 살아 있는 상태처럼 보이지 않는다. 다음 조회가 덮어쓴다.
    el("dispatch-control-title").textContent = "발행 상태 확인 중";
    el("dispatch-control-detail").textContent = "대기 작업과 정지 세대를 읽고 있습니다.";
    delete el("dispatch-control").dataset.state;
    el("dispatch-control").hidden = false;
  }};
}
