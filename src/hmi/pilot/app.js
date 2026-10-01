// Rosy Pilot 부트스트랩(D-323). 게이트 → 주행 화면 전환.
// 입력 조정(T8)은 주행 화면 위 칩에서 연다.

import {registerDriver} from "./drivers/registry.js";
import {pinkyCore} from "./drivers/pinky_core.js";
import {omxSim} from "./drivers/omx_sim.js";
import {mountConnect} from "./screens/connect.js";
import {mountDrive} from "./screens/drive.js";
import {postJson} from "./client.js";
import {mountArm} from "./screens/arm.js";

registerDriver(pinkyCore.kind, pinkyCore);
registerDriver(omxSim.kind, omxSim);

const connectRoot = document.querySelector('[data-screen="connect"]');
const driveRoot = document.querySelector('[data-screen="drive"]');
const armRoot = document.querySelector('[data-screen="arm"]');
let simTarget = null;

function showConnect() {
  document.body.dataset.pilotScreen = "connect";
  driveRoot.hidden = true;
  connectRoot.hidden = false;
  mountConnect(connectRoot, {onEnter: showDrive});
}

function showDrive() {
  document.body.dataset.pilotScreen = "drive";
  connectRoot.hidden = true;
  driveRoot.hidden = false;
  mountDrive(driveRoot, {
    onExit: () => {
      driveRoot.hidden = true;
      showConnect();
    },
  });
}

// 상단 비상 정지 — 모든 화면에 항상 닿는다. CORE 의 정지는 소프트웨어 정지다
// (triage 규칙: 전원 차단이라 말하지 않는다).
for (const button of document.querySelectorAll("[data-estop]")) {
  button.addEventListener("click", async () => {
    const notice = document.querySelector("#pilot-notice");
    if (notice) notice.textContent = "정지 요청을 보냈습니다";
    if (simTarget) {
      // The arm screen owns cancellation; this Pinky stop control is hidden in SIM mode.
      return;
    }
    await pinkyCore.stop(postJson);
  });
}

// 두 앱(관제 /dashboard · 조종 /pilot) 사이 이동.
for (const button of document.querySelectorAll("[data-goto]")) {
  button.addEventListener("click", () => {
    location.assign(button.dataset.goto);
  });
}

// 설치형(D-365): PWA. 서비스 워커는 앱 셸만 캐시하고 /api·/ws 는 네트워크 전용.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/pilot/assets/sw.js", {scope: "/pilot"})
    .catch((error) => console.warn("service worker registration failed", error));
}

async function start() {
  try {
    const target = await omxSim.discover();
    if (target === null) { showConnect(); return; }
    simTarget = target;
    document.body.dataset.pilotScreen = "arm";
    connectRoot.hidden = true;
    driveRoot.hidden = true;
    armRoot.hidden = false;
    document.querySelectorAll("[data-estop], [data-goto]").forEach((button) => { button.hidden = true; });
    mountArm(armRoot, target, omxSim);
  } catch (error) {
    const notice = document.querySelector("#pilot-notice");
    if (notice) notice.textContent = `대상 확인 실패 · ${error.message}`;
  }
}
start();
