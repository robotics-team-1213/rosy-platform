// D-410 — 설치·보정 화면 엔트리. 운용 셸(console.js)과 같은 모듈을 쓰지만
// 로스터·지도·대형·신호등·발행 상태는 없다. 관제 토큰은 같은 세션 저장소
// (rosy-console-token)를 공유한다 — 운용 화면에서 접속했으면 여기도 풀려 있다.

import { applyRoleToControls } from "./authorization.js";
import { developmentToken } from "./development-auth.js";
import { DISCOVERY_LABELS, createEnrollmentPanel } from "./enrollment.js";
import { createCameraPairingPanel } from "./camera-pairing.js";
import { createCameraPeerPanel } from "./camera-peer.js";
import { createVisionView } from "./vision-view.js";
import { createFieldView } from "./field-view.js";
import { createMapFitView } from "./map-fit-view.js";
import { createPollGate } from "./poll-gate.js";
import { createPeerPicker } from "./peer-picker.js";
import { addressMap, movableRobots } from "./address-drift.js";
import { createFleetClient } from "/common/fleet-client.js";
import { createPageScope } from "/common/scope.js";
import { createTaskChooser } from "/common/task-chooser.js";
import { confirmIrreversible, openLiveDialog } from "/common/ui.js";

const pageScope = createPageScope();

const el = (id) => document.getElementById(id);
pageScope.onDispose(() => {
  document.querySelectorAll("dialog[open]").forEach(dialog => dialog.close("cancel"));
});

const STATE_MS = 1000;
const MAP_MS = 5000;
const LOG_MAX = 40;

// 꺼진 기능(라우트 없음 404)은 다음 로그인·토큰 저장까지 두드리지 않는다.
const discoveryGate = createPollGate();
let peerPicker = null;

const auth = {
  token: sessionStorage.getItem("rosy-console-token") || "",
  role: null,
  principal: null,
  // D-248: 잠기면 폴링이 401 을 두드리지 않는다.
  locked: false,
};
function stopNotice(message = "", state = "warning") {
  const notice = el("estop-feedback");
  notice.textContent = message;
  notice.hidden = !message;
  notice.setAttribute("state", state);
}

function authHeaders() {
  return auth.token ? { "Authorization": `Bearer ${auth.token}` } : {};
}

function operatorControls() {
  // 화면 테마(data-theme-choice)와 머리 토글은 권한과 무관다(D-359 §2.5·§6.4).
  return [...document.querySelectorAll(
    "ui-button:not(#token-save):not(#topbar-more):not(#vision-refresh):not([data-theme-choice]), main input, main select:not(#vision-source)")]
    .filter(control => !control.closest(".ui-task-chooser")
      && !control.closest("#peer-picker")
      && !["discovery-retry", "camera-confirm-close", "enroll-cancel", "camera-approve-cancel"].includes(control.id));
}

function applyRole() {
  applyRoleToControls(auth.role, operatorControls());
}

function setTopbarOpen(open) {
  el("topbar-more").setAttribute("aria-expanded", String(open));
  el("topbar-extra").dataset.open = String(open);
}

function markLocked() {
  stopNotice();
  auth.locked = true;
  setTopbarOpen(true);
  auth.role = null;
  peerPicker?.reset();
  el("user-role").textContent = "인증 필요";
  el("user-role").setAttribute("status", "crit");
  const pill = el("online-pill");
  pill.textContent = "접속 전";
  pill.setAttribute("status", "neutral");
  pill.dataset.locked = "true"; // 해제 때 문구가 아니라 이 표시로 잠금 pill을 알아본다
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

const fleetClient = createFleetClient({ credential: () => auth.token });

async function call(path, options = {}) {
  const task = pageScope.capture();
  task.check();
  const cameraPreview = path === "/api/fleet/vision/sources" || path === "/api/fleet/vision/lease";
  try {
    const body = await fleetClient(path, {...options, signals: [...(options.signals || []), task.signal]});
    task.check();
    if (!cameraPreview) markUnlocked();
    return body;
  } catch (error) {
    task.check();
    if (error.status === 401 && !cameraPreview) markLocked();
    throw error;
  }
}

// Task navigation preserves mounted owners and drafts across auth/page epochs.
const taskChooser = createTaskChooser({beforeSelect: from => {
  if (from === "calibration") visionView.pausePreview();
  return true;
}, tasks: [
  {id: "peers", title: "장비 찾기", panel: el("peer-picker")},
  {id: "robots", title: "로봇 등록", panel: el("robot-enrollment")},
  {id: "cameras", title: "카메라 연결 승인", panel: el("camera-link")},
  {id: "calibration", title: "카메라 설치·보정", panel: el("camera-calibration")},
]});
el("install-chooser").append(taskChooser.element);
taskChooser.setReady();
pageScope.subscribe(() => {
  taskChooser.resume();
  return () => { void taskChooser.pause().then(() => { if (pageScope.capture().current()) taskChooser.resume(); }); };
});

// 설치 전용 얇은 view — 카메라 관측·사이트 사각형만 있다(D-257).
const view = { siteMap: null, sightings: [], robots: [], addresses: {} };

// 기기 등록·카메라 연결 승인 (D-341). 주소 이동 안내는 운용 화면 로스터가 가진다.
const enrollment = createEnrollmentPanel({ scope: pageScope,
  headers: authHeaders,
  identity: () => ({ role: auth.role, principal_id: auth.principal }),
  log,
  dialogs: { confirmIrreversible, openLiveDialog },
  candidateAddress: async robotId => {
    const life = pageScope.capture(), token = auth.token, role = auth.role;
    const snapshot = await call("/api/fleet/discovery/addresses", {signals: [AbortSignal.timeout(10000)]});
    life.check();
    if (token !== auth.token || role !== auth.role || auth.locked) throw new DOMException("Address context changed", "AbortError");
    const entry = addressMap(snapshot)[robotId];
    return movableRobots(snapshot).includes(entry) && entry.seen_addresses?.length === 1 ? entry.seen_addresses[0] : null;
  },
  onMoved: () => { enrollment.refresh(); },
});
const cameraPairing = createCameraPairingPanel({ scope: pageScope,
  headers: authHeaders,
  identity: () => ({ role: auth.role, principal_id: auth.principal }),
  locked: () => auth.locked,
  log,
  dialogs: { confirmIrreversible, openLiveDialog },
});
const cameraPeer = createCameraPeerPanel({scope:pageScope,headers:authHeaders,
  identity:()=>({role:auth.role,principal_id:auth.principal}),locked:()=>auth.locked,
  dialogs:{confirmIrreversible},onUnauthorized:markLocked});

// 카메라 설치·보정 체인 (D-360/D-375). 지도가 없으니 레이어 변경은 맵 맞춤 뷰만 다시 그린다.
const visionView = createVisionView({ scope: pageScope, el, call,
  isActive: () => !el("camera-calibration").hidden });
let mapFit = null;
const fieldView = createFieldView({ scope: pageScope, el, view, visionView,
  onLayersChanged: () => { mapFit?.render(); } });
mapFit = createMapFitView({ scope: pageScope, el, view, call, visionView, onChanged: () => fieldView.render() });
peerPicker = createPeerPicker({scope: pageScope, el, call,
  isLocked: () => auth.locked || !auth.role,
  isActive: () => taskChooser.selectedId === "peers",
  sources: () => [...el("vision-source").options].map(option => option.value),
  onCamera: async source => {
    const life = pageScope.capture();
    await taskChooser.choose("calibration"); life.check();
    if (taskChooser.selectedId !== "calibration" || auth.locked) return;
    const select = el("vision-source");
    if (![...select.options].some(option => option.value === source)) return;
    select.value = source; select.dispatchEvent(new Event("change")); select.focus();
  }});

pageScope.listen(el("topbar-more"), "click", () => {
  setTopbarOpen(el("topbar-more").getAttribute("aria-expanded") !== "true");
});

function tickClock() {
  el("clock").textContent = new Date().toTimeString().slice(0, 8);
}

el("console-token").value = auth.token;
function saveToken() {
  stopNotice();
  pageScope.invalidate();
  peerPicker.reset();
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
pageScope.listen(el("token-save"), "click", saveToken);
pageScope.listen(el("console-token"), "keydown", (event) => {
  if (event.key === "Enter") saveToken();
});

// 전체 정지는 한 번의 누름으로 즉시 실행된다(D-414 — 비상 정지는 확인 없는
// 비상 출구다. D-371이 대화상자 위에서 살아 있게 했던 이유를 끝까지 밀었다).
pageScope.listen(el("estop"), "click", async () => {
  const life = pageScope.capture();
  life.check();
  stopNotice("비상 정지 요청 중…", "pending");
  try {
    const result = await call("/api/fleet/estop", { method: "POST" });
    life.check();
    const summary = result.total > 0
      ? `정지 요청 응답: ${result.stopped}/${result.total} · 물리 정지 미확인`
      : "정지 요청 대상 로봇 없음 — 등록 목록과 현장 상태를 확인하세요.";
    stopNotice(summary, result.total > 0 && result.stopped === result.total ? "warning" : "error");
    log(summary, "bad");
    (result.robots || []).filter((r) => !r.stopped)
      .forEach((r) => log(`  ${r.robot_id} 정지 요청 응답 없음 — ${r.error.code}`, "bad"));
  } catch (err) {
    if (err.name === "AbortError") return;
    stopNotice(err.status >= 500 || !err.status
      ? "비상 정지 결과 확인 불가 — Fleet 연결과 로봇 상태를 즉시 확인하세요."
      : `비상 정지 요청 거절 — ${err.message}`, "error");
    log(`전체 정지 실패 — ${err.message}`, "bad");
  }
});

let discoveryPending = false;
let scannerLost = false;
function discoveryState(label, message, tone = "neutral") {
  const status = el("discovery-status");
  status.textContent = label; status.setAttribute("status", tone);
  el("discovery-list").replaceChildren(); el("discovery-list").hidden = true;
  el("discovery-empty").textContent = message; el("discovery-empty").hidden = false;
}
pageScope.onDispose(() => { discoveryPending = false; });
async function refreshDiscovery() {
  const life = pageScope.capture();
  life.check();
  if (auth.locked || discoveryPending) return;
  discoveryPending = true;
  try {
    await enrollment.refresh(); life.check();
    if (!discoveryGate.due()) return;
    const snapshot = await call("/api/fleet/discovery");
    life.check();
    discoveryGate.ok();
    if (!snapshot.scanner_online) {
      const expired = snapshot.scanner_state === "expired";
      if (expired && !scannerLost) log("발견 검색기 끊김 — 로봇 발견·주소 이동 안내 불가", "bad");
      scannerLost = expired;
      discoveryState(expired ? "검색기 끊김" : "검색기 연결 대기",
        expired ? `마지막 스캔 ${snapshot.scanner_age_s ?? "?"}초 전 · 검색기 연결을 확인하고 다시 시도하세요. 새 주소로 옮기기는 검색기가 돌아온 뒤 가능합니다.`
          : "검색기가 아직 연결되지 않았습니다. 검색기 연결을 확인한 뒤 다시 시도하세요.", expired ? "crit" : "warn");
      return;
    }
    if (scannerLost) log("발견 검색기 다시 연결됨", "good");
    scannerLost = false;
    discoveryState(`${snapshot.devices.length}대 발견`, "아직 발견된 로봇이 없습니다. 로봇 전원과 같은 현장 네트워크인지 확인하고 다시 시도하세요.");
    // D-413 — 발견(mDNS) 장치는 이 화면의 주인공이다: 이름·주소·단계·상태와
    // 곧바로 누르는 등록 버튼(enrollment.decorateDiscoveryRow).
    const rows = snapshot.devices.map((device) => {
      const item = document.createElement("li");
      const label = document.createElement("b");
      label.textContent = device.name;
      const detail = document.createElement("small");
      detail.textContent = `${device.address}:${device.port} · ${device.stage || "부팅 중"}`;
      const state = document.createElement("span");
      state.textContent = DISCOVERY_LABELS[device.status] || "확인 필요";
      state.className = `discovery-state ${device.status}`;
      item.append(label, detail, state);
      enrollment.decorateDiscoveryRow(item, device);
      return item;
    });
    el("discovery-list").replaceChildren(...rows);
    el("discovery-list").hidden = !rows.length; el("discovery-empty").hidden = !!rows.length;
  } catch (err) {
    if (err.name === "AbortError" || !life.current()) return;
    const absent = discoveryGate.fail(err.status, err.code) === "absent";
    discoveryState(auth.locked ? "인증 필요" : absent ? "발견 미설정" : "발견 상태 확인 불가",
      auth.locked ? "관제 토큰으로 다시 접속한 뒤 발견 목록을 확인하세요."
        : absent ? "이 Fleet에는 발견 검색이 설정되지 않았습니다. 설정 후 다시 확인하세요."
          : "발견 목록을 확인할 수 없습니다. 검색기와 연결을 확인한 뒤 다시 시도하세요.", auth.locked ? "crit" : absent ? "neutral" : "warn");
  } finally { if (life.current()) discoveryPending = false; }
}
pageScope.listen(el("discovery-retry"), "click", () => { discoveryGate.reset(); return refreshDiscovery(); });

async function refreshAuthorization(renewed = false) {
  const life = pageScope.capture();
  life.check();
  discoveryGate.reset();
  enrollment.resetPolling();
  cameraPairing.resetPolling();
  try {
    const identity = await call("/api/fleet/session");
    life.check();
    auth.role = identity.role;
    auth.principal = identity.principal_id;
    if (identity.principal_id.startsWith("development-")) {
      el("console-token").hidden = true;
      el("token-save").hidden = true;
    }
    const roleName = identity.role === "operator" ? "운영자" :
      identity.role === "viewer" ? "조회 전용" :
        identity.role === "policy-admin" ? "정책 관리자" : "권한 없음";
    el("user-role").textContent = `${identity.principal_id} · ${roleName}`;
    el("user-role").title = el("user-role").textContent;
    el("user-role").setAttribute("status", identity.role === "operator" ? "good" : "neutral");
    const pill = el("online-pill");
    if (pill.dataset.locked === "true") {
      delete pill.dataset.locked;
      pill.textContent = "설치 준비 중";
      pill.setAttribute("status", "neutral");
    }
    applyRole();
    await Promise.allSettled([
      cameraPairing.refresh({ credentials: true }),
      cameraPeer.refresh(),
      refreshDiscovery(),
      peerPicker.refresh(),
    ]);
    life.check();
  } catch (_err) {
    if (_err.name === "AbortError") return;
    if (_err.status === 401 && !renewed) {
      try {
        const token = await developmentToken(auth.token);
        if (token && token !== auth.token) {
          auth.token = token;
          el("console-token").value = token;
          el("console-token").hidden = true;
          el("token-save").hidden = true;
          await refreshAuthorization(true);
          return;
        }
      } catch (_issueError) { /* Paired and unavailable consoles keep the token prompt. */ }
    }
    if (!auth.locked) markLocked();
  }
}

tickClock();
pageScope.interval(tickClock, 1000);
applyRole();
refreshAuthorization();
visionView.refreshSources();
pageScope.interval(refreshDiscovery, MAP_MS);
pageScope.interval(() => peerPicker.refresh(), MAP_MS);
pageScope.interval(() => visionView.refreshFrame(), STATE_MS + 500);

pageScope.onResume(() => {
  visionView.reset();
  mapFit.reset();
  refreshAuthorization();
  visionView.refreshSources();
});
