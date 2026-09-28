// Rosy Pilot 부트스트랩(D-323). 지금은 접속 게이트만 마운트한다.
// 주행 화면(T7)·입력 조정(T8)은 이 파일에서 화면을 갈아끼운다.

import {registerDriver} from "./drivers/registry.js";
import {pinkyCore} from "./drivers/pinky_core.js";
import {mountConnect} from "./screens/connect.js";
import {postJson} from "./client.js";

registerDriver(pinkyCore.kind, pinkyCore);

const root = document.querySelector('[data-screen="connect"]');
if (root) {
  mountConnect(root, {
    onReady({role}) {
      const note = document.querySelector("[data-pilot-note]");
      if (note) note.textContent = `게이트 통과(${role}).`;
    },
  });
}

// 두 앱(관제 /dashboard · 조종 /pilot) 사이 이동. 경로는 CORE 가 서빙하는 그대로.
for (const button of document.querySelectorAll("[data-goto]")) {
  button.addEventListener("click", () => {
    location.assign(button.dataset.goto);
  });
}

// 상단 비상 정지 — 모든 화면에 항상 닿는다. CORE 의 정지는 소프트웨어 정지다
// (triage 규칙: 전원 차단이라 말하지 않는다).
for (const button of document.querySelectorAll("[data-estop]")) {
  button.addEventListener("click", async () => {
    const notice = document.querySelector("#pilot-notice");
    if (notice) notice.textContent = "정지 요청을 보냈습니다";
    await pinkyCore.stop(postJson);
  });
}

// 설치형(D-328): PWA. 서비스 워커는 앱 셸만 캐시하고 /api·/ws 는 네트워크 전용.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/pilot/assets/sw.js", {scope: "/pilot"})
    .catch((error) => console.warn("service worker registration failed", error));
}
