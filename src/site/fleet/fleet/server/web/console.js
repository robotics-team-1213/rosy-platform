// 사이트 관제 화면. 서버(Fleet)만 본다 — 로봇 API 를 직접 부르지 않는다.
//
import { createFormation } from "./formation.js";
import { createMapView } from "./map-view.js";
import { createRoster } from "./roster.js";
import { createLineStuckPanel } from "./line-stuck.js";
import { createSignals } from "./signals.js";
import { createVisionView } from "./vision-view.js";
import { applyRoleToControls } from "./authorization.js";
// D-410 — 기기 등록·카메라 연결 승인·경기장/맵 보정은 설치 화면(install.js)이 가진다.
import { addressMap, movableRobots, renumberBanner } from "./address-drift.js";
import { createPollGate } from "./poll-gate.js";
import { createFleetClient } from "/common/fleet-client.js";
import { createPageScope } from "/common/scope.js";
const pageScope = createPageScope();
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.


const el = (id) => document.getElementById(id);

// 셸 폴링 운율과 로그 상한은 셸이 가진다. 지도 격자·오버레이 임계는 map-view.js에 있다.
const STATE_MS = 1000;
const MAP_MS = 5000;
const LOG_MAX = 120;

// 꺼진 기능(라우트 없음 404)은 다음 로그인·토큰 저장까지 두드리지 않는다. poll-gate.js 참고.
const dispatchGate = createPollGate();
const discoveryGate = createPollGate();

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

// D-359 §6.4 — compact·medium에서 접속·역할·테마는 토글 뒤에 접힌다(세로 예산).
// 넓은 창에서는 CSS가 토글을 숨기고 항목을 줄에 세운다. 잠기면 토큰 칸을 연다.
function setTopbarOpen(open) {
  el("topbar-more").setAttribute("aria-expanded", String(open));
  el("topbar-extra").dataset.open = String(open);
}
pageScope.listen(el("topbar-more"), "click", () => {
  setTopbarOpen(el("topbar-more").getAttribute("aria-expanded") !== "true");
});

function markLocked() {
  auth.locked = true;
  setTopbarOpen(true);
  auth.role = null;
  el("user-role").textContent = "인증 필요";
  el("user-role").setAttribute("status", "crit");
  applyRoleToControls(null, operatorControls());
  const pill = el("online-pill");
  pill.textContent = "토큰 필요";
  pill.setAttribute("status", "crit");
  el("console-token").setAttribute("aria-invalid", "true");
}

function markUnlocked() {
  auth.locked = false;
  el("console-token").removeAttribute("aria-invalid");
}

function operatorControls() {
  // 화면 테마(data-theme-choice)는 이 브라우저의 표시 선호라 권한과 무관하다(D-359 §2.5).
  // 머리 토글(#topbar-more)은 접힌 칸을 여는 표시 조작이다(§6.4).
  return document.querySelectorAll(
    "ui-button:not(#token-save):not(#topbar-more):not(#roster-toggle):not(#vision-refresh):not(#log-clear):not([data-theme-choice]), main input, main select:not(#vision-source)");
}

const view = {
  map: null,
  siteMap: null,   // D-257 천장 카메라 사각형 (GET /api/fleet/site-map)
  sightings: [],   // 카메라 관측 — 표시 전용, CORE pose 와 섞지 않는다
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
  addresses: {},  // robot_id -> GET /api/fleet/discovery/addresses 행(고정 주소 판정)
};

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
  try {
    const body = await fleetClient(path, {...options, signals: [...(options.signals || []), task.signal]});
    task.check();
    markUnlocked();
    return body;
  } catch (error) {
    task.check();
    if (error.status === 401) markLocked();
    throw error;
  }
}

async function refreshDispatchControl() {
  const life = pageScope.capture();
  life.check();
  const title = el("dispatch-control-title");
  const detail = el("dispatch-control-detail");
  const rearm = el("dispatch-rearm");
  if (!dispatchGate.due()) return view.dispatchControl;
  try {
    const state = await call("/api/fleet/dispatch-control");
    life.check();
    dispatchGate.ok();
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
    if (rearm.disabled) rearm.setAttribute("reason", auth.locked ? "관제 토큰 필요" : "재허가 조건 미충족");
    else rearm.removeAttribute("reason");
    return state;
  } catch (err) {
    if (err.name === "AbortError") return;
    view.dispatchControl = null;
    if (dispatchGate.fail(err.status, err.code) === "absent") {
      // 작업 대기열이 없는 Fleet — 발행 래치 자체가 없다. 오류가 아니다.
      title.textContent = "발행 제어 미설정";
      detail.textContent = "이 Fleet에는 작업 대기열이 설정되지 않았습니다.";
    } else {
      title.textContent = "발행 상태를 확인할 수 없음";
      detail.textContent = "상태 확인에 실패해 재허가를 사용할 수 없습니다.";
    }
    rearm.hidden = true;
    rearm.disabled = true;
    rearm.setAttribute("reason", "발행 상태 확인 불가");
    return null;
  }
}

pageScope.listen(el("dispatch-rearm"), "click", async () => {
  const life = pageScope.capture();
  life.check();
  const state = view.dispatchControl;
  if (auth.role !== "operator" || auth.locked || !state?.rearm_available) return;
  if (!window.confirm(`세대 ${state.generation}의 대기 발행을 재허가할까요?`)) return;
  try {
    await call("/api/fleet/dispatch/rearm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_generation: state.generation }),
    });
    life.check();
    log("대기 작업 발행을 재허가했습니다.", "good");
  } catch (err) {
    if (err.name === "AbortError") return;
    log(`발행 재허가 거부: ${err.message}`, "bad");
  }
  await refreshDispatchControl();
  life.check();
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
  lineStuck.render();

  formation.fillLeaders();
  mapView.draw();
  applyRoleToControls(auth.role, operatorControls());
  const hint = el("hint");
  const point = view.selected && view.cursor && view.map
    ? mapView.toWorld(view.map, view.cursor.col, view.cursor.row) : null;
  const nextHint = point
    ? `${view.selected} 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m · 방향키로 이동, Enter로 확인, Escape로 취소`
    : view.map
      ? "로봇 카드의 목표 지정을 누른 뒤 지도를 찍으면 그 로봇에게만 목표가 갑니다."
      : view.siteMap
        ? "천장 카메라 관측 전용 지도입니다. 목표 지정은 로봇 지도가 수신되면 사용할 수 있습니다."
        : "지도가 수신되면 로봇의 목표 지정을 사용할 수 있습니다.";
  if (hint.textContent !== nextHint) hint.textContent = nextHint;
  refreshDiagnostics();
}

let statePollInFlight = false;
pageScope.onDispose(() => {
  statePollInFlight = false;
  view.selected = null;
  view.cursor = null;
  document.querySelectorAll("dialog[open]").forEach(dialog => dialog.close("cancel"));
});
async function refreshState() {
  const life = pageScope.capture();
  life.check();
  if (auth.locked || statePollInFlight) return;
  statePollInFlight = true;
  try {
    const snapshot = await call("/api/fleet/state");
    life.check();
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
    if (err.name === "AbortError") return;
    // D-248: 잠금 pill(토큰 필요)을 서버 없음으로 덮지 않는다 — 401의 이유를 남긴다.
    if (auth.locked) return;
    view.stateUnavailable = true;
    if (view.selected) disarmGoal("Fleet 상태를 확인할 수 없어 목표 지정 취소");
    render();
    const pill = el("online-pill");
    pill.textContent = "Fleet 서버 없음";
    pill.setAttribute("status", "crit");
  } finally {
    if (life.current()) statePollInFlight = false;
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

let scannerLost = false;

async function refreshDiscovery() {
  const life = pageScope.capture();
  life.check();
  // D-410 — 발견 목록·등록은 설치 화면에 있다. 운용 화면은 검색기 건강과
  // 고정 주소 판정(로스터 안내)만 이 요청에서 얻는다.
  if (auth.locked) return;
  if (!discoveryGate.due()) return;
  try {
    const snapshot = await call("/api/fleet/discovery");
    life.check();
    discoveryGate.ok();
    await refreshAddresses();
    life.check();
    // 검색기 임대(45 s)가 끊기면 새 주소 안내가 멈춘다 — 대기와 구별해 알린다.
    if (snapshot.scanner_state === "expired") {
      if (!scannerLost) log("발견 검색기 끊김 — 로봇 발견·주소 이동 안내 불가", "bad");
      scannerLost = true;
      return;
    }
    if (scannerLost && snapshot.scanner_online) log("발견 검색기 다시 연결됨", "good");
    scannerLost = false;
  } catch (err) {
    if (err.name === "AbortError") return;
    if (auth.locked) return;
    if (discoveryGate.fail(err.status, err.code) === "absent") return;
  }
}

// 고정 주소 판정은 발견과 같은 주기로 읽는다. 못 읽으면 까닭 줄을 지운다(짐작하지 않는다).
let addressText = "";

// D-410 — 주소 이동 대화상자(로봇 화면 코드)는 설치 화면에 있다. 운용 화면의
// 이동 안내는 그 화면으로 가는 링크로만 말한다.
function moveLink() {
  const node = document.createElement("a");
  node.href = "/console/install";
  node.textContent = "설치 화면에서 이동";
  return node;
}

async function refreshAddresses() {
  const life = pageScope.capture();
  life.check();
  let payload = null;
  try {
    payload = await call("/api/fleet/discovery/addresses");
    life.check();
  } catch (_err) {
    if (_err.name === "AbortError") return;
    payload = null;
  }
  const banner = el("address-banner");
  const text = renumberBanner(payload, view.robots);
  banner.hidden = !text;
  if (text && banner.textContent !== text) banner.textContent = text;
  // 옮길 수 있는 로봇마다 한 줄과 그 로봇의 지름길. 옮기기마다 그 로봇의 화면 코드를 묻는다.
  const movable = movableRobots(payload);
  const next = JSON.stringify([payload?.robots || [], auth.role, auth.principal]);
  if (next !== addressText) {
    addressText = next;
    el("address-movable").replaceChildren(...movable.map((entry) => {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `${entry.robot_id} → ${entry.seen_addresses[0]}`;
      item.append(label, moveLink());
      return item;
    }));
    view.addresses = addressMap(payload);
    render();
  }
  el("address-drift").hidden = !text && movable.length === 0;
}

async function refreshAuthorization() {
  const life = pageScope.capture();
  life.check();
  // 로그인·토큰 저장마다 꺼진 기능을 한 번씩 다시 묻는다.
  dispatchGate.reset();
  discoveryGate.reset();
  mapView.resetPolling();
  try {
    const identity = await call("/api/fleet/session");
    life.check();
    auth.role = identity.role;
    auth.principal = identity.principal_id;
    const roleName = identity.role === "operator" ? "운영자" :
      identity.role === "viewer" ? "조회 전용" :
        identity.role === "policy-admin" ? "정책 관리자" : "권한 없음";
    el("user-role").textContent = `${identity.principal_id} · ${roleName}`;
    el("user-role").title = el("user-role").textContent; // 넓은 머리에서 12rem으로 잘릴 때의 전문
    el("user-role").setAttribute("status", identity.role === "operator" ? "good" : "neutral");
    // The session already proves the token: unlock now. The state gather can take seconds
    // when a robot times out, and must not hold the operator's controls locked behind it.
    const pill = el("online-pill");
    if (pill.textContent === "토큰 필요") {
      pill.textContent = "상태 확인 중";
      pill.setAttribute("status", "neutral");
    }
    applyRoleToControls(auth.role, operatorControls());
    render();
    // Independent panels refresh side by side; one slow source does not delay the rest.
    await Promise.allSettled([
      refreshState(),
      refreshDispatchControl(),
      refreshDiscovery(),
      formation.refreshFormation(),
    ]);
    life.check();
    render();
  } catch (_err) {
    if (_err.name === "AbortError") return;
    if (!auth.locked) markLocked();
  }
}

// --- 조작 ------------------------------------------------------------------

// D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
// ↑/↓ 로 로스터를 순회하고, Enter 로 그 로봇의 목표 지정을 누르고,
// Escape 으로 선택을 해소한다. 입력 컨트롤에 있을 땐 간섭하지 않는다.
// 포커스 링은 표면 전역 :focus-visible 규약이 그린다.
pageScope.listen(document, "keydown", (event) => {
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
  const life = pageScope.capture();
  life.check();
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
    life.check();
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
    if (err.name === "AbortError") return;
    log(`${robotId} 미션 거절 — ${err.message}`, "bad");
  }
}

function focusGoalButton(robotId) {
  [...document.querySelectorAll("#roster ui-button[data-goal-robot-id]")]
    .find(button => button.dataset.goalRobotId === robotId)?.focus({preventScroll: true});
}

pageScope.listen(el("map-canvas"), "click", async (event) => {
  const life = pageScope.capture();
  life.check();
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
  life.check();
});

pageScope.listen(el("map-canvas"), "keydown", async (event) => {
  const life = pageScope.capture();
  life.check();
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
    life.check();
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

// 전체 정지는 한 번의 누름으로 즉시 실행된다(D-413 — 비상 정지는 확인 없는 비상 출구.
// D-371이 대화상자 위에서 살아 있게 한 이유를 끝까지 밀었다: 어떤 사위에도 즉시 눌린다).
pageScope.listen(el("estop"), "click", async () => {
  const life = pageScope.capture();
  life.check();
  try {
    const result = await call("/api/fleet/estop", { method: "POST" });
    life.check();
    await refreshDispatchControl();
    life.check();
    log(`정지 요청 응답: ${result.stopped}/${result.total} · 물리 정지 미확인`, "bad");
    result.robots.filter((r) => !r.stopped)
      .forEach((r) => log(`  ${r.robot_id} 정지 요청 응답 없음 — ${r.error.code}`, "bad"));
  } catch (err) {
    if (err.name === "AbortError") return;
    log(`전체 정지 실패 — ${err.message}`, "bad");
  }
});


// D-421 — 래치 없는 전체 주행 취소. 응답은 CORE 응답 수이지 물리 정지가 아니다(D-298).
const CANCEL_ALL_RESULT = { failed: "실패", unreachable: "응답 없음" };
const CANCEL_ALL_STEP = { swarm: "대형 추종", navigation: "내비게이션", line_follow: "차선 추종" };
pageScope.listen(el("cancel-all"), "click", async () => {
  const life = pageScope.capture();
  life.check();
  if (!window.confirm("등록된 모든 로봇의 주행(내비게이션 목표·대형 추종·차선 추종)과 대기 작업을 취소합니다. 비상 정지 래치는 걸지 않습니다. 계속할까요?")) return;
  try {
    const result = await call("/api/fleet/cancel-all", { method: "POST" });
    life.check();
    // 0/0 은 성공이 아니다 — 취소할 로봇이 없었다.
    const allAnswered = result.total > 0 && result.cancelled === result.total;
    log(result.total === 0 ? "주행 취소 대상 로봇 없음 — 등록된 로봇을 확인하세요"
      : `주행 취소 요청 응답: ${result.cancelled}/${result.total} · 물리 정지 미확인`,
    allAnswered ? undefined : "bad");
    result.robots.filter((r) => r.result !== "cancelled").forEach((r) => {
      const steps = Object.entries(r.steps).filter(([, step]) => !step.ok).map(([name, step]) =>
        step.error?.sent === false && name === "line_follow" ? "주소 미확인 — 차선 추종 끄기 미전송"
          : `${CANCEL_ALL_STEP[name] || name} ${step.error?.code || "—"}`);
      log(`  ${r.robot_id} 주행 취소 ${CANCEL_ALL_RESULT[r.result] || r.result} — ${steps.join(" · ")}`, "bad");
    });
    const awaiting = result.robots.reduce((n, r) => n + r.tasks.awaiting_core_result.length, 0);
    log(result.tasks.error ? "대기 작업 취소 실패 — 작업 저장소를 확인하세요"
      : `대기 작업 ${result.tasks.canceled.length}개 취소 · 로봇 취소 확인 대기 작업 ${awaiting}개`,
    result.tasks.error ? "bad" : undefined);
    // CORE 가 취소를 확인하면 그 로봇은 다시 배정되고, 확인이 없으면 작업은 대조가 필요하다.
    if (awaiting) log("  확인 대기 작업: 로봇이 취소를 알리면 다시 배정, 알리지 않으면 대조 필요", "bad");
    await refreshDispatchControl();
    life.check();
  } catch (err) {
    if (err.name === "AbortError") return;
    log(`전체 주행 취소 실패 — ${err.message}`, "bad");
  }
});


// D-262: 대형 패널은 formation.js 팩토리가 가진다. 셸은 지도 오버레이와
// 명렬 렌더를 쥐고, 대형 상태는 view.formation 으로 공유한다.
const formation = createFormation({ scope: pageScope, el, view, log, call, render });
formation.bind();

// Fleet 분해 4: 현장 지도 뷰는 map-view.js 팩토리가 그린다.
const mapView = createMapView({ scope: pageScope,
  el, view, auth, call,
  onMapChanged: render,
  onMapUnavailable: () => {
    const selected = view.selected;
    if (selected) disarmGoal("지도를 확인할 수 없어 목표 지정 취소");
    render();
    if (selected) focusGoalButton(selected);
  },
});

// Fleet 분해 3: 명렬 카드와 큐는 roster.js 팩토리가 그린다.
// D-410 — 주소 이동 조작은 설치 화면이 소유해서 moveAddress 훅을 주지 않는다.
const roster = createRoster({ scope: pageScope, el, view, log, call, render,
  streamEvidence: mapView.streamEvidence, isOperator: () => auth.role === "operator" });
// D-407 판단 요청 — 막힌 로봇의 질문과 다섯 답. 예외 큐 패널 안에 산다.
const lineStuck = createLineStuckPanel({ scope: pageScope, el, view, call, log,
  isOperator: () => auth.role === "operator" });

pageScope.listen(el("roster-toggle"), "click", () => {
  view.showAllRobots = !view.showAllRobots;
  render();
});

// D-415 — 로그 지우기
pageScope.listen(el("log-clear"), "click", () => {
  const box = el("log");
  box.replaceChildren(document.createElement("ui-empty"));
  box.firstChild.textContent = "지웠습니다.";
});

// D-415 — 진단 패널 갱신: 상태 주기·발견·로봇 오류·카메라
let lastStateOk = null;
function refreshDiagnostics() {
  const diag = (id, text) => {
    const node = el(id);
    if (node) node.textContent = text;
  };
  diag("diag-state", view.stateUnavailable ? "불가"
    : `${view.robots.length}대 · ${view.stateLoaded ? "갱신됨" : "대기"}`);
  diag("diag-scanner", scannerLost ? "끊김"
    : "정상");
  const robotErrors = view.robots
    .filter((r) => r.error)
    .map((r) => `${r.robot_id}: ${r.error.reachable === false ? "닿지 않음" : "거부"} ${r.error.code ?? ""}`.trim());
  diag("diag-robots", robotErrors.length ? robotErrors.join(" · ") : "오류 없음");
  diag("diag-vision", el("vision-state")?.textContent ?? "—");
}

// D-262: 신호등 카드는 signals.js 팩토리가 그린다.
const signals = createSignals({ scope: pageScope, el, view, log, call, refreshState });
// D-410 — 운용 화면의 카메라는 영상 프리뷰만 띄운다. 경기장/맵 보정 뷰는 설치 화면이 가진다.
const visionView = createVisionView({ scope: pageScope, el, call, auth, authHeaders });

// --- 신호등 (ROSY-SIGNAL-001) --------------------------------------------------

function tickClock() {
  el("clock").textContent = new Date().toTimeString().slice(0, 8);
}

// 토큰 입력 — Enter 와 버튼 모두 저장한다 (form 이 아니라 keydown 이다).
el("console-token").value = auth.token;
function saveToken() {
  pageScope.invalidate();
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
pageScope.listen(el("token-save"), "click", saveToken);
pageScope.listen(el("console-token"), "keydown", (event) => {
  if (event.key === "Enter") saveToken();
});

// D-359 §4 — 로봇 계열 색은 ui.js(window.RosyPalette)가 캔버스용으로 푼다. 테마가
// 바뀌면 다시 풀고 지도를 새로 고침 없이 다시 그린다(캐시는 ui.js가 먼저 비운다).
const robotColours = () => ["--robot-1", "--robot-2", "--robot-3"].map((name) => window.RosyPalette.cssColor(name));
view.colors = robotColours();
pageScope.listen(document, "rosy:theme", () => {
  view.colors = robotColours();
  mapView.draw();
});
tickClock();
pageScope.interval(tickClock, 1000);
applyRoleToControls(null, operatorControls());
render();
refreshAuthorization();
visionView.refreshSources();
mapView.refresh();
pageScope.interval(() => { if (!auth.locked) formation.refreshFormation(); }, MAP_MS);
pageScope.interval(refreshState, STATE_MS);
pageScope.interval(() => { if (!auth.locked) refreshDispatchControl(); }, STATE_MS);
pageScope.interval(refreshDiscovery, MAP_MS);
pageScope.interval(() => mapView.refresh(), MAP_MS);
pageScope.interval(() => mapView.refreshSightings(), STATE_MS);
pageScope.interval(() => visionView.refreshFrame(), 1500);

pageScope.onResume(() => {
  visionView.reset();
  refreshAuthorization();
  visionView.refreshSources();
  mapView.refresh();
});
