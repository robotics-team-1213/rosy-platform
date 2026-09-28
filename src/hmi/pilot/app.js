// Rosy Pilot 부트스트랩(D-323). 지금은 접속 게이트만 마운트한다.
// 주행 화면(T7)·입력 조정(T8)은 이 파일에서 화면을 갈아끼운다.

import {registerDriver} from "./drivers/registry.js";
import {pinkyCore} from "./drivers/pinky_core.js";
import {mountConnect} from "./screens/connect.js";

registerDriver(pinkyCore.kind, pinkyCore);

const root = document.querySelector('[data-screen="connect"]');
if (root) {
  mountConnect(root, {
    onReady({role}) {
      const note = document.querySelector('[data-pilot-note]');
      if (note) {
        note.textContent =
          `게이트 통과(${role}). 주행 화면은 다음 단계(T7)에서 열립니다.`;
      }
    },
  });
}

// 두 앱(관제 /dashboard · 조종 /pilot) 사이 이동. 경로는 CORE 가 서빙하는 그대로.
for (const button of document.querySelectorAll("[data-goto]")) {
  button.addEventListener("click", () => {
    location.assign(button.dataset.goto);
  });
}
