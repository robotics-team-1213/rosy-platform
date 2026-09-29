// 사이트 관제 화면. 서버(Fleet)만 본다 — 로봇 API 를 직접 부르지 않는다.
//
import { createFormation } from "./formation.js";
import { createMapView } from "./map-view.js";
import { createRoster } from "./roster.js";
import { createSignals } from "./signals.js";
import { createVisionView } from "./vision-view.js";
import { applyRoleToControls } from "./authorization.js";
import { DISCOVERY_LABELS, createEnrollmentPanel } from "./enrollment.js";
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.


const el = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// 셸 폴링 운율과 로그 상한은 셸이 가진다. 지도 격자·오버레이 임계는 map-view.js에 있다.
const STATE_MS = 1000;
const MAP_MS = 5000;
const LOG_MAX = 40;

// 관제 토큰 — 서버가 루프백 밖으로 열리면 모든 /api/fleet/* 이 401 로 막힌다
// (cli.run_console 강제, app.authorize). 토큰은 세션 스토리지에만 둔다 —
// localStorage 에 두면 공유 관제PC 의 다음 근무자가 그대로 물려받는다.
const auth = {
  token: sessionStorage.getItem("rosy-console-token") || "",
  role: null,
  // D-248: 잠기면 폴링이 401 을 두드리지 않는다. 수동 저장·새로고침은 막지 않는다.
  locked: false,
};

function authHeaders() {
  return auth.token ? { "Authorization": `Bearer ${auth.token}` } : {};
}

function markLocked() {
  auth.locked = true;
  auth.role = null;
  el("user-role").textContent = "인증 필요";
  el("user-role").setAttribute("status", "crit");
  applyRoleToControls(null, operatorControls());
  const pill = el("online-pill");
  pill.textContent = "토큰 필요";
  pill.setAttribute("status", "crit");
  el("console-token").classList.add("locked");
  showDiscoveryUnavailable("인증 필요", "관제 토큰을 입력하면 발견 목록을 다시 확인합니다.");
}

function markUnlocked() {
  auth.locked = false;
  el("console-token").classList.remove("locked");
}

function operatorControls() {
  return document.querySelectorAll(
    "ui-button:not(#token-save):not(#roster-toggle):not(#vision-refresh), main input, main select:not(#vision-source)");
}

const view = {
  map: null,
  robots: [],
  showAllRobots: false,
  selected: null, // 목표 지정을 기다리는 robot_id
  cursor: null, // 지도 좌표계의 col/row, 아래쪽 행이 0
  colors: [],
  formation: null,
  formationUnavailable: false,
  signals: {},    // ROSY-SIGNAL-001 — snapshot 의 signals 캐시
  pendingTasks: {},
  dispatchControl: null,
  stateUnavailable: false,
  stateLoaded: false,
};

function log(text, kind) {
  const line = document.createElement("div");
  if (kind) line.className = kind;
  const now = new Date().toTimeString().slice(0, 8);
  line.textContent = `${now}  ${text}`;
  const box = el("log");
  box.querySelector(".log-empty")?.remove();
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
    // 토큰 없이(또는 틀린 토큰으로) 왔다 — 폴링이 계속 401 을 두드리기 전에
    // 화면에 이유를 남긴다. 다음 refreshState 가 성공하면 markUnlocked 로 풀린다.
    markLocked();
    throw new Error("관제 토큰이 필요합니다 — 상단에 입력하고 접속을 누르세요");
  }
  if (!resp.ok) {
    const detail = body && body.detail ? body.detail : {};
    throw new Error(detail.message || detail.code || `HTTP ${resp.status}`);
  }
  markUnlocked();
  return body;
}

async function refreshDispatchControl() {
  const title = el("dispatch-control-title");
  const detail = el("dispatch-control-detail");
  const rearm = el("dispatch-rearm");
  try {
    const state = await call("/api/fleet/dispatch-control");
    view.dispatchControl = state;
    if (state.dispatch_enabled) {
      title.textContent = "발행 허용";
      detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개`;
    } else if (state.reason === "PROCESS_RESTARTED") {
      title.textContent = "재시작 뒤 발행 대기";
      detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개 · 미확정 동작 ${state.unresolved_actions}개`;
    } else {
      title.textContent = "정지 래치로 발행 차단";
      detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개 · 미확정 동작 ${state.unresolved_actions}개`;
    }
    rearm.hidden = !(auth.role === "operator" && !state.dispatch_enabled);
    rearm.disabled = auth.locked || !state.rearm_available;
    return state;
  } catch (_err) {
    view.dispatchControl = null;
    title.textContent = "발행 상태를 확인할 수 없음";
    detail.textContent = "상태 확인에 실패해 재허가를 사용할 수 없습니다.";
    rearm.hidden = true;
    rearm.disabled = true;
    return null;
  }
}

el("dispatch-rearm").addEventListener("click", async () => {
  const state = view.dispatchControl;
  if (auth.role !== "operator" || auth.locked || !state?.rearm_available) return;
  if (!window.confirm(`세대 ${state.generation}의 대기 발행을 재허가할까요?`)) return;
  try {
    await call("/api/fleet/dispatch/rearm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_generation: state.generation }),
    });
    log("대기 작업 발행을 재허가했습니다.", "good");
  } catch (err) {
    log(`발행 재허가 거부: ${err.message}`, "bad");
  }
  await refreshDispatchControl();
});


// --- 로봇 목록 --------------------------------------------------------------

function render() {
  const rosterBox = el("roster");
  const focused = document.activeElement;
  const focusedCard = focused?.closest?.("#roster article");
  const focusedId = focusedCard?.dataset.robotId;
  const focusedButton = focusedCard && focused !== focusedCard
    ? [...focusedCard.querySelectorAll("ui-button")].indexOf(focused) : -1;
  const attention = view.robots.filter((robot) => roster.needsAttention(robot));
  const normalCount = view.robots.length - attention.length;
  const toggle = el("roster-toggle");
  toggle.hidden = normalCount === 0;
  toggle.setAttribute("aria-expanded", String(view.showAllRobots));
  toggle.textContent = view.showAllRobots ? "개입 대상만 보기" : `전체 로봇 보기 · 정상 ${normalCount}대`;
  const shown = view.showAllRobots ? view.robots : view.robots.filter((robot) =>
    roster.needsAttention(robot) || robot.robot_id === view.selected);
  if (shown.length) {
    rosterBox.replaceChildren(...shown.map((robot) => roster.card(robot, view.robots.indexOf(robot))));
  } else if (view.robots.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.setAttribute("role", "status");
    empty.textContent = `개입할 로봇 없음 · 정상 ${normalCount}대`;
    rosterBox.replaceChildren(empty);
  } else {
    const message = view.stateUnavailable ? "Fleet 상태를 확인할 수 없습니다. 연결을 확인하세요."
      : view.stateLoaded ? "등록된 로봇이 없습니다. 발견 목록에서 페어링 상태를 확인하세요."
        : "로봇 목록 불러오는 중";
    if (rosterBox.childElementCount !== 1 ||
        rosterBox.firstElementChild?.getAttribute("role") !== "status" ||
        rosterBox.firstElementChild.textContent !== message) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.setAttribute("role", "status");
      empty.textContent = message;
      rosterBox.replaceChildren(empty);
    }
  }
  if (focusedId) {
    const nextCard = [...rosterBox.querySelectorAll("article")]
      .find((card) => card.dataset.robotId === focusedId);
    const nextFocused = focusedButton >= 0
      ? nextCard?.querySelectorAll("ui-button")[focusedButton] : nextCard;
    nextFocused?.focus({preventScroll: true});
  }
  signals.render();
  roster.fillQueues();

  formation.fillLeaders();
  mapView.draw();
  applyRoleToControls(auth.role, operatorControls());
  const hint = el("hint");
  const point = view.selected && view.cursor && view.map
    ? mapView.toWorld(view.map, view.cursor.col, view.cursor.row) : null;
  const nextHint = point
    ? `${view.selected} 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m · 방향키로 이동, Enter로 확인, Escape로 취소`
    : view.map
      ? "오른쪽에서 로봇의 목표 지정을 누른 뒤 지도를 찍으면 그 로봇에게만 목표가 갑니다."
      : "지도가 수신되면 로봇의 목표 지정을 사용할 수 있습니다.";
  if (hint.textContent !== nextHint) hint.textContent = nextHint;
}

let statePollInFlight = false;
async function refreshState() {
  if (auth.locked || statePollInFlight) return;
  statePollInFlight = true;
  try {
    const snapshot = await call("/api/fleet/state");
    view.robots = snapshot.robots;
    view.stateUnavailable = false;
    view.stateLoaded = true;
    if (view.selected) {
      const selectedRobot = view.robots.find((robot) => robot.robot_id === view.selected);
      if (!selectedRobot?.online || selectedRobot.state?.safety?.estop !== false) {
        disarmGoal("안전·연결 상태가 바뀌어 목표 지정 취소");
      }
    }
    view.signals = snapshot.signals || {};
    el("fleet-name").textContent = (snapshot.fleet.name || "site").toUpperCase();
    const pill = el("online-pill");
    pill.textContent = `${snapshot.fleet.online}/${snapshot.fleet.total} 연결`;
    pill.setAttribute("status", snapshot.fleet.online === snapshot.fleet.total ? "neutral" : "crit");
    render();
  } catch (err) {
    // D-248: 잠금 pill(토큰 필요)을 서버 없음으로 덮지 않는다 — 401의 이유를 남긴다.
    if (auth.locked) return;
    view.stateUnavailable = true;
    if (view.selected) disarmGoal("Fleet 상태를 확인할 수 없어 목표 지정 취소");
    render();
    const pill = el("online-pill");
    pill.textContent = "Fleet 서버 없음";
    pill.setAttribute("status", "crit");
  } finally {
    statePollInFlight = false;
  }
}

function disarmGoal(reason) {
  view.selected = null;
  view.cursor = null;
  const canvas = el("map-canvas");
  canvas.classList.add("idle");
  canvas.tabIndex = -1;
  log(reason, "bad");
}

const discoveryLabels = DISCOVERY_LABELS;
const enrollment = createEnrollmentPanel({
  headers: authHeaders,
  identity: () => ({ role: auth.role, principal_id: auth.principal }),
  log,
});

function showDiscoveryUnavailable(label, message) {
  const status = el("discovery-status");
  status.textContent = label;
  status.setAttribute("status", "warn");
  const list = el("discovery-list");
  if (list.childElementCount === 1 && list.firstElementChild?.dataset.unavailable === "true" &&
      list.firstElementChild.textContent === message) return;
  const item = document.createElement("li");
  item.className = "hint";
  item.dataset.unavailable = "true";
  item.textContent = message;
  list.replaceChildren(item);
}

async function refreshDiscovery() {
  if (auth.locked) return;
  await enrollment.refresh();
  try {
    const snapshot = await call("/api/fleet/discovery");
    const status = el("discovery-status");
    status.textContent = snapshot.scanner_online
      ? `${snapshot.devices.length}대 발견` : "검색기 연결 대기";
    status.setAttribute("status", snapshot.scanner_online ? "neutral" : "warn");
    const rows = snapshot.devices.map((device) => {
      const item = document.createElement("li");
      const label = document.createElement("b");
      label.textContent = device.name;
      const detail = document.createElement("small");
      detail.textContent = `${device.address}:${device.port} · ${device.stage || "부팅 중"}`;
      const state = document.createElement("span");
      state.textContent = discoveryLabels[device.status] || "확인 필요";
      state.className = `discovery-state ${device.status}`;
      item.append(label, detail, state);
      enrollment.decorateDiscoveryRow(item, device);
      return item;
    });
    el("discovery-list").replaceChildren(...rows);
  } catch (_err) {
    if (!auth.locked) showDiscoveryUnavailable(
      "발견 상태 확인 불가", "발견 목록을 확인할 수 없습니다. Fleet 연결을 확인하세요.");
  }
}

async function refreshAuthorization() {
  try {
    const identity = await call("/api/fleet/session");
    auth.role = identity.role;
    auth.principal = identity.principal_id;
    const roleName = identity.role === "operator" ? "운영자" :
      identity.role === "viewer" ? "조회 전용" :
        identity.role === "policy-admin" ? "정책 관리자" : "권한 없음";
    el("user-role").textContent = `${identity.principal_id} · ${roleName}`;
    el("user-role").setAttribute("status", identity.role === "operator" ? "good" : "neutral");
    await refreshState();
    await refreshDispatchControl();
    await refreshDiscovery();
    await formation.refreshFormation();
    render();
  } catch (_err) {
    if (!auth.locked) markLocked();
  }
}

// --- 조작 ------------------------------------------------------------------

// D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
// ↑/↓ 로 로스터를 순회하고, Enter 로 그 로봇의 목표 지정을 누르고,
// Escape 으로 선택을 해소한다. 입력 컨트롤에 있을 땐 간섭하지 않는다.
// 포커스 링은 표면 전역 :focus-visible 규약이 그린다.
document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.target.closest("input, select, textarea, button, ui-button, a, canvas")) return;
  const cards = [...document.querySelectorAll("#roster article")];
  if (!cards.length) return;
  const active = document.activeElement;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    const idx = cards.indexOf(active);
    const next = idx < 0
      ? cards[event.key === "ArrowDown" ? 0 : cards.length - 1]
      : cards[(idx + (event.key === "ArrowDown" ? 1 : -1) + cards.length) % cards.length];
    next.focus();
  } else if (event.key === "Enter" && cards.includes(active)) {
    const aim = active.querySelector(".robot-actions ui-button");
    if (aim && !aim.disabled) {
      event.preventDefault();
      aim.click();
    }
  } else if (event.key === "Escape" && view.selected) {
    const selectedCard = cards.find((c) => c.classList.contains("selected"));
    const aim = selectedCard && selectedCard.querySelector(".robot-actions ui-button");
    if (aim) aim.click();
  }
});

async function commitGoal(col, row) {
  if (!view.selected || !view.map) return;
  const selectedRobot = view.robots.find((robot) => robot.robot_id === view.selected);
  if (view.stateUnavailable || auth.role !== "operator" ||
      !selectedRobot?.online || selectedRobot.state?.safety?.estop !== false) {
    disarmGoal("안전·연결·권한 상태를 확인할 수 없어 목표 지정 취소");
    render();
    return;
  }
  const point = mapView.toWorld(view.map, col, row);
  const robotId = view.selected;
  if (!window.confirm(`${robotId}에게 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m를 보낼까요?`)) return;
  view.selected = null;
  view.cursor = null;
  const canvas = el("map-canvas");
  canvas.classList.add("idle");
  canvas.tabIndex = -1;
  render();
  focusGoalButton(robotId);
  try {
    const result = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/goal`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ x: point.x, y: point.y, yaw: 0 }),
    });
    const task = result && result.task ? result.task : null;
    if (task && task.status === "QUEUED") {
      view.pendingTasks[robotId] = task;
      const why = task.reason || result.reason || "READY";
      const blockedBy = task.waiting_on?.length ? ` · ${task.waiting_on.join(", ")}` : "";
      const position = task.queue_position ? `#${task.queue_position}` : "순번 대기";
      log(`${robotId} task ${task.task_id} QUEUED · ${position} · ${why}${blockedBy} · 취소 가능`, "good");
      return;
    }
    if (task && task.status === "UNKNOWN") {
      view.pendingTasks[robotId] = task;
      log(`${robotId} task ${task.task_id} UNKNOWN · CORE 결과 수동 확인 필요`, "bad");
      return;
    }
    if (task && task.status !== "ACCEPTED") {
      log(`${robotId} task ${task.task_id} ${task.status}${task.reason ? ` · ${task.reason}` : ""}`, "bad");
      return;
    }
    if (task) delete view.pendingTasks[robotId];
    const receipt = task ? task.receipt : result;
    const where = `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
    if (receipt && receipt.queued) {
      log(`${robotId} → ${where} ${roster.queuedReason(result)}`,
          receipt.reason === "NO_YIELD_SPACE" ? "bad" : "");
    } else {
      log(`${robotId} → ${where} 미션 하달`, "good");
    }
  } catch (err) {
    log(`${robotId} 미션 거절 — ${err.message}`, "bad");
  }
}

function focusGoalButton(robotId) {
  [...document.querySelectorAll("#roster ui-button[data-goal-robot-id]")]
    .find(button => button.dataset.goalRobotId === robotId)?.focus({preventScroll: true});
}

el("map-canvas").addEventListener("click", async (event) => {
  if (!view.selected || !view.map) return;
  const canvas = el("map-canvas");
  const rect = canvas.getBoundingClientRect();
  // D-201 — 캔버스는 object-fit: contain 으로 그려진다. 레터박스(빈 여백)를
  // 제외한 그려진 영역 안에서만 셀 좌표가 성립한다.
  const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
  const drawnW = view.map.width * scale;
  const drawnH = view.map.height * scale;
  const offX = (rect.width - drawnW) / 2;
  const offY = (rect.height - drawnH) / 2;
  const col = ((event.clientX - rect.left - offX) / drawnW) * view.map.width;
  const rowFromTop = ((event.clientY - rect.top - offY) / drawnH) * view.map.height;
  if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) {
    return; // 여백을 찍은 것 — 목표가 아니다.
  }
  view.cursor = { col: Math.floor(col), row: view.map.height - 1 - Math.floor(rowFromTop) };
  render();
  await commitGoal(view.cursor.col, view.cursor.row);
});

el("map-canvas").addEventListener("keydown", async (event) => {
  if (!view.selected || !view.map || !view.cursor) return;
  const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
  if (event.key in moves) {
    event.preventDefault();
    const [dx, dy] = moves[event.key];
    view.cursor.col = Math.max(0, Math.min(view.map.width - 1, view.cursor.col + dx));
    view.cursor.row = Math.max(0, Math.min(view.map.height - 1, view.cursor.row + dy));
    render();
  } else if (event.key === "Enter") {
    event.preventDefault();
    await commitGoal(view.cursor.col, view.cursor.row);
  } else if (event.key === "Escape") {
    event.preventDefault();
    const robotId = view.selected;
    view.selected = null;
    view.cursor = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle");
    canvas.tabIndex = -1;
    render();
    focusGoalButton(robotId);
  }
});

el("estop").addEventListener("click", async () => {
  if (!window.confirm("등록된 모든 로봇을 정지시킵니다. 계속할까요?")) return;
  try {
    const result = await call("/api/fleet/estop", { method: "POST" });
    await refreshDispatchControl();
    log(`정지 요청 응답: ${result.stopped}/${result.total} · 물리 정지 미확인`, "bad");
    result.robots.filter((r) => !r.stopped)
      .forEach((r) => log(`  ${r.robot_id} 정지 요청 응답 없음 — ${r.error.code}`, "bad"));
  } catch (err) {
    log(`전체 정지 실패 — ${err.message}`, "bad");
  }
});


// D-262: 대형 패널은 formation.js 팩토리가 가진다. 셸은 지도 오버레이와
// 명렬 렌더를 쥐고, 대형 상태는 view.formation 으로 공유한다.
const formation = createFormation({ el, view, log, call, render });
formation.bind();

// Fleet 분해 4: 현장 지도 뷰는 map-view.js 팩토리가 그린다.
const mapView = createMapView({
  el, view, css, auth, call,
  onMapChanged: render,
  onMapUnavailable: () => {
    const selected = view.selected;
    if (selected) disarmGoal("지도를 확인할 수 없어 목표 지정 취소");
    render();
    if (selected) focusGoalButton(selected);
  },
});

// Fleet 분해 3: 명렬 카드와 큐는 roster.js 팩토리가 그린다.
const roster = createRoster({ el, view, log, call, render,
  streamEvidence: mapView.streamEvidence, isOperator: () => auth.role === "operator" });
el("roster-toggle").addEventListener("click", () => {
  view.showAllRobots = !view.showAllRobots;
  render();
});

// D-262: 신호등 카드는 signals.js 팩토리가 그린다.
const signals = createSignals({ el, view, log, call, refreshState });
const visionView = createVisionView({ el, call, auth, authHeaders });

// --- 신호등 (ROSY-SIGNAL-001) --------------------------------------------------

function tickClock() {
  el("clock").textContent = new Date().toTimeString().slice(0, 8);
}

// 토큰 입력 — Enter 와 버튼 모두 저장한다 (form 이 아니라 keydown 이다).
el("console-token").value = auth.token;
function saveToken() {
  auth.token = el("console-token").value.trim();
  // 새 토큰은 직접 재시도한다 — 잠금 플래그가 있으면 직접 호출도 건너뛰므로 먼저 푼다.
  auth.role = null;
  applyRoleToControls(null, operatorControls());
  if (auth.token) {
    sessionStorage.setItem("rosy-console-token", auth.token);
  } else {
    sessionStorage.removeItem("rosy-console-token");
  }
  visionView.reset();
  refreshAuthorization();
  visionView.refreshSources();
}
el("token-save").addEventListener("click", saveToken);
el("console-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") saveToken();
});

view.colors = [css("--robot-1"), css("--robot-2"), css("--robot-3")];
tickClock();
setInterval(tickClock, 1000);
applyRoleToControls(null, operatorControls());
render();
refreshAuthorization();
visionView.refreshSources();
mapView.refresh();
setInterval(() => { if (!auth.locked) formation.refreshFormation(); }, MAP_MS);
setInterval(refreshState, STATE_MS);
setInterval(() => { if (!auth.locked) refreshDispatchControl(); }, STATE_MS);
setInterval(refreshDiscovery, MAP_MS);
setInterval(() => mapView.refresh(), MAP_MS);
setInterval(() => visionView.refreshFrame(), 1500);
