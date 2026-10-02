// D-410 — 설치·보정 화면 엔트리. 운용 셸(console.js)과 같은 모듈을 쓰지만
// 로스터·지도·대형·신호등·발행 상태는 없다. 관제 토큰은 같은 세션 저장소
// (rosy-console-token)를 공유한다 — 운용 화면에서 접속했으면 여기도 풀려 있다.

import { applyRoleToControls } from "./authorization.js";
import { createEnrollmentPanel } from "./enrollment.js";
import { createCameraPairingPanel } from "./camera-pairing.js";
import { createVisionView } from "./vision-view.js";
import { createFieldView } from "./field-view.js";
import { createMapFitView } from "./map-fit-view.js";
import { createPollGate } from "./poll-gate.js";
import { confirmIrreversible, openLiveDialog } from "/common/ui.js";

const el = (id) => document.getElementById(id);

const STATE_MS = 1000;
const MAP_MS = 5000;
const LOG_MAX = 40;

// 꺼진 기능(라우트 없음 404)은 다음 로그인·토큰 저장까지 두드리지 않는다.
const discoveryGate = createPollGate();

const auth = {
  token: sessionStorage.getItem("rosy-console-token") || "",
  role: null,
  principal: null,
  // D-248: 잠기면 폴링이 401 을 두드리지 않는다.
  locked: false,
};

function authHeaders() {
  return auth.token ? { "Authorization": `Bearer ${auth.token}` } : {};
}

function operatorControls() {
  // 화면 테마(data-theme-choice)와 머리 토글은 권한과 무관다(D-359 §2.5·§6.4).
  return document.querySelectorAll(
    "ui-button:not(#token-save):not(#topbar-more):not(#vision-refresh):not([data-theme-choice]), main input, main select:not(#vision-source)");
}

function applyRole() {
  applyRoleToControls(auth.role, operatorControls());
}

function setTopbarOpen(open) {
  el("topbar-more").setAttribute("aria-expanded", String(open));
  el("topbar-extra").dataset.open = String(open);
}

function markLocked() {
  auth.locked = true;
  setTopbarOpen(true);
  auth.role = null;
  el("user-role").textContent = "인증 필요";
  el("user-role").setAttribute("status", "crit");
  const pill = el("online-pill");
  pill.textContent = "토큰 필요";
  pill.setAttribute("status", "crit");
  el("console-token").setAttribute("aria-invalid", "true");
  applyRole();
}

function markUnlocked() {
  auth.locked = false;
  el("console-token").removeAttribute("aria-invalid");
}

function log(text, kind) {
  const line = document.createElement("div");
  if (kind) line.className = kind;
  const now = new Date().toTimeString().slice(0, 8);
  line.textContent = `${now}  ${text}`;
  const box = el("log");
  box.querySelector("ui-empty")?.remove();
  box.prepend(line);
  while (box.childElementCount > LOG_MAX) box.lastElementChild.remove();
}

async function call(path, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeaders() };
  const resp = await fetch(path, { ...options, headers });
  let body = null;
  try {
    body = await resp.json();
  } catch (err) {
    body = null;
  }
  if (resp.status === 401) {
    markLocked();
    throw new Error("관제 토큰이 필요합니다 — 상단에 입력하고 접속을 누르세요");
  }
  if (!resp.ok) {
    const detail = body && body.detail ? body.detail : {};
    const error = new Error(detail.message || detail.code || `HTTP ${resp.status}`);
    error.status = resp.status;
    error.code = detail.code;
    throw error;
  }
  markUnlocked();
  return body;
}

// 설치 전용 얇은 view — 카메라 관측·사이트 사각형만 있다(D-257).
const view = { siteMap: null, sightings: [], robots: [], addresses: {} };

// 기기 등록·카메라 연결 승인 (D-341). 주소 이동 안내는 운용 화면 로스터가 가진다.
const enrollment = createEnrollmentPanel({
  headers: authHeaders,
  identity: () => ({ role: auth.role, principal_id: auth.principal }),
  log,
  dialogs: { confirmIrreversible, openLiveDialog },
  onMoved: () => { enrollment.refresh(); },
});
const cameraPairing = createCameraPairingPanel({
  headers: authHeaders,
  identity: () => ({ role: auth.role, principal_id: auth.principal }),
  locked: () => auth.locked,
  log,
  dialogs: { confirmIrreversible, openLiveDialog },
});

// 카메라 설치·보정 체인 (D-360/D-375). 지도가 없으니 레이어 변경은 맵 맞춤 뷰만 다시 그린다.
const visionView = createVisionView({ el, call, auth, authHeaders });
let mapFit = null;
const fieldView = createFieldView({ el, view, visionView,
  onLayersChanged: () => { mapFit?.render(); } });
mapFit = createMapFitView({ el, view, call, visionView, onChanged: () => fieldView.render() });

el("topbar-more").addEventListener("click", () => {
  setTopbarOpen(el("topbar-more").getAttribute("aria-expanded") !== "true");
});

function tickClock() {
  el("clock").textContent = new Date().toTimeString().slice(0, 8);
}

el("console-token").value = auth.token;
function saveToken() {
  auth.token = el("console-token").value.trim();
  auth.role = null;
  applyRole();
  if (auth.token) {
    sessionStorage.setItem("rosy-console-token", auth.token);
  } else {
    sessionStorage.removeItem("rosy-console-token");
  }
  visionView.reset();
  mapFit.reset();
  refreshAuthorization();
  visionView.refreshSources();
}
el("token-save").addEventListener("click", saveToken);
el("console-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") saveToken();
});

// 전체 정지는 운용 표면의 규칙을 그대로 따른다(D-280 — 모든 관제 표면 첫 화면).
el("estop").addEventListener("click", async () => {
  if (!window.confirm("등록된 모든 로봇을 정지시킵니다. 계속할까요?")) return;
  try {
    const result = await call("/api/fleet/estop", { method: "POST" });
    log(`정지 요청 응답: ${result.stopped}/${result.total} · 물리 정지 미확인`, "bad");
  } catch (err) {
    log(`전체 정지 실패 — ${err.message}`, "bad");
  }
});

async function refreshDiscovery() {
  if (auth.locked) return;
  await enrollment.refresh();
  if (!discoveryGate.due()) return;
  try {
    const snapshot = await call("/api/fleet/discovery");
    discoveryGate.ok();
    const status = el("discovery-status");
    status.textContent = snapshot.scanner_online
      ? `${snapshot.devices.length}대 발견` : "검색기 연결 대기";
  } catch (err) {
    if (discoveryGate.fail(err.status, err.code) === "absent") {
      const status = el("discovery-status");
      status.textContent = "발견 미설정";
      status.setAttribute("status", "neutral");
    }
  }
}

async function refreshAuthorization() {
  discoveryGate.reset();
  enrollment.resetPolling();
  cameraPairing.resetPolling();
  try {
    const identity = await call("/api/fleet/session");
    auth.role = identity.role;
    auth.principal = identity.principal_id;
    const roleName = identity.role === "operator" ? "운영자" :
      identity.role === "viewer" ? "조회 전용" :
        identity.role === "policy-admin" ? "정책 관리자" : "권한 없음";
    el("user-role").textContent = `${identity.principal_id} · ${roleName}`;
    el("user-role").title = el("user-role").textContent;
    el("user-role").setAttribute("status", identity.role === "operator" ? "good" : "neutral");
    const pill = el("online-pill");
    if (pill.textContent === "토큰 필요") {
      pill.textContent = "설치 준비 중";
      pill.setAttribute("status", "neutral");
    }
    applyRole();
    await Promise.allSettled([
      cameraPairing.refresh({ credentials: true }),
      refreshDiscovery(),
    ]);
  } catch (_err) {
    if (!auth.locked) markLocked();
  }
}

tickClock();
setInterval(tickClock, 1000);
applyRole();
refreshAuthorization();
visionView.refreshSources();
setInterval(refreshDiscovery, MAP_MS);
setInterval(() => { if (!auth.locked) visionView.refreshFrame(); }, STATE_MS + 500);
