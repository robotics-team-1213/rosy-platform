// Rosy Pilot 부트스트랩(D-323). 게이트 → 주행 화면 전환.
// 입력 조정(T8)은 주행 화면 위 칩에서 연다.

import {registerDriver} from "./drivers/registry.js";
import {pinkyCore} from "./drivers/pinky_core.js";
import {omxSim} from "./drivers/omx_sim.js";
import {mountConnect} from "./screens/connect.js";
import {mountDrive} from "./screens/drive.js";
import {postJson, inPilotApp} from "./client.js";
import {mountArm} from "./screens/arm.js";
import {readControls, widgetPlan, fallbackPinkyControls, profileFromBaseVelocity} from "./controls.js";

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

// D-411 B: the device's rosy.controls/1 decides the drive profile. No `controls` field = an
// old CORE → the legacy Pinky profile; an empty list = no drive control right now.
function showDrive({capabilities} = {}) {
  document.body.dataset.pilotScreen = "drive";
  connectRoot.hidden = true;
  driveRoot.hidden = false;
  const exit = () => { driveRoot.hidden = true; showConnect(); };
  const items = readControls(capabilities?.controls) ?? fallbackPinkyControls(pinkyCore.profile);
  const plan = widgetPlan(items, ["base_velocity"]);
  const base = plan.find((entry) => entry.supported)?.control;
  if (!base) {
    const back = document.createElement("ui-button");
    back.setAttribute("type", "button");
    back.setAttribute("kind", "quiet");
    back.textContent = "접속 화면으로";
    back.addEventListener("click", exit);
    driveRoot.replaceChildren(
      Object.assign(document.createElement("ui-empty"), {textContent: "이 기기는 지금 주행 조작부를 알리지 않습니다"}),
      ...plan.map(({control}) => Object.assign(document.createElement("p"), {
        textContent: `지원하지 않는 조작부 · ${control.label || control.kind}`})),
      back);
    return;
  }
  mountDrive(driveRoot, {
    profile: profileFromBaseVelocity(base),
    unsupported: plan.filter((entry) => !entry.supported).map((entry) => entry.control),
    onExit: exit,
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

// 두 앱(관제 /dashboard · 조종 /pilot) 사이 이동. 앱 안에서는 프록시 밖으로 나가지 않는다.
for (const button of document.querySelectorAll("[data-goto]")) {
  if (inPilotApp()) button.hidden = true;
  button.addEventListener("click", () => {
    if (inPilotApp()) return;
    location.assign(button.dataset.goto);
  });
}

// 설치형(D-365): PWA. 서비스 워커는 앱 셸만 캐시하고 /api·/ws 는 네트워크 전용.
// 안드로이드 셸은 번들 자산을 직접 주고 sw.js 를 거부한다.
if (!inPilotApp() && "serviceWorker" in navigator) {
  navigator.serviceWorker.register("/pilot/assets/sw.js", {scope: "/pilot"})
    .catch((error) => console.warn("service worker registration failed", error));
}

let discovering = false;
async function start() {
  if (discovering) return;
  discovering = true;
  document.body.dataset.pilotScreen = "connect";
  const retry = connectRoot.querySelector("[data-discovery-retry]");
  if (retry) retry.disabled = true;
  const notice = document.querySelector("#pilot-notice");
  if (notice) notice.textContent = "조종 대상을 확인하고 있습니다.";
  try {
    const target = await omxSim.discover();
    if (notice?.textContent === "조종 대상을 확인하고 있습니다.") notice.textContent = "";
    if (target === null) { showConnect(); return; }
    simTarget = target;
    document.body.dataset.pilotScreen = "arm";
    connectRoot.hidden = true;
    driveRoot.hidden = true;
    armRoot.hidden = false;
    document.querySelectorAll("[data-estop], [data-goto]").forEach((button) => { button.hidden = true; });
    mountArm(armRoot, target, omxSim);
  } catch (_error) {
    if (notice?.textContent === "조종 대상을 확인하고 있습니다.") notice.textContent = "";
    const heading = Object.assign(document.createElement("h2"), {id: "pilot-gate-heading", textContent: "조종 대상 확인"});
    const message = Object.assign(document.createElement("ui-empty"), {textContent: "조종 대상을 확인하지 못했습니다. 연결과 대상 정보를 확인한 뒤 다시 시도하세요."});
    const retry = document.createElement("ui-button");
    retry.setAttribute("kind", "quiet"); retry.setAttribute("type", "button");
    retry.dataset.discoveryRetry = ""; retry.textContent = "대상 다시 확인";
    retry.addEventListener("click", start);
    connectRoot.replaceChildren(heading, message, retry);
  } finally {
    discovering = false;
    const retry = connectRoot.querySelector("[data-discovery-retry]");
    if (retry) retry.disabled = false;
  }
}
start();
