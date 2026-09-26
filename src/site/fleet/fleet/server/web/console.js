// 사이트 관제 화면. 서버(Fleet)만 본다 — 로봇 API 를 직접 부르지 않는다.
//
import { createFormation } from "./formation.js";
import { createMapView } from "./map-view.js";
import { createRoster } from "./roster.js";
import { createSignals } from "./signals.js";
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
  // D-248: 잠기면 폴링이 401 을 두드리지 않는다. 수동 저장·새로고침은 막지 않는다.
  locked: false,
};

function authHeaders() {
  return auth.token ? { "Authorization": `Bearer ${auth.token}` } : {};
}

function markLocked() {
  auth.locked = true;
  const pill = el("online-pill");
  pill.textContent = "토큰 필요";
  pill.setAttribute("status", "crit");
  el("console-token").classList.add("locked");
}

function markUnlocked() {
  auth.locked = false;
  el("console-token").classList.remove("locked");
}

const view = {
  map: null,
  robots: [],
  selected: null, // 목표 지정을 기다리는 robot_id
  colors: [],
  formation: null,
  signals: {},    // ROSY-SIGNAL-001 — snapshot 의 signals 캐시
};

function log(text, kind) {
  const line = document.createElement("div");
  if (kind) line.className = kind;
  const now = new Date().toTimeString().slice(0, 8);
  line.textContent = `${now}  ${text}`;
  const box = el("log");
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


// --- 로봇 목록 --------------------------------------------------------------

function render() {
  const rosterBox = el("roster");
  rosterBox.replaceChildren(...view.robots.map((robot, index) => roster.card(robot, index)));
  signals.render();
  roster.fillQueues();

  formation.fillLeaders();
  mapView.draw();
  const hint = el("hint");
  hint.textContent = view.selected
    ? `${view.selected}에게 보낼 목표를 지도에서 찍으세요. 다시 누르면 취소됩니다.`
    : "오른쪽에서 로봇의 목표 지정을 누른 뒤 지도를 찍으면 그 로봇에게만 목표가 갑니다.";
}

async function refreshState() {
  if (auth.locked) return;
  try {
    const snapshot = await call("/api/fleet/state");
    view.robots = snapshot.robots;
    view.signals = snapshot.signals || {};
    el("fleet-name").textContent = (snapshot.fleet.name || "site").toUpperCase();
    const pill = el("online-pill");
    pill.textContent = `${snapshot.fleet.online}/${snapshot.fleet.total} 연결`;
    pill.setAttribute("status", snapshot.fleet.online === snapshot.fleet.total ? "neutral" : "crit");
    render();
  } catch (err) {
    // D-248: 잠금 pill(토큰 필요)을 서버 없음으로 덮지 않는다 — 401의 이유를 남긴다.
    if (auth.locked) return;
    const pill = el("online-pill");
    pill.textContent = "Fleet 서버 없음";
    pill.setAttribute("status", "crit");
  }
}

// --- 조작 ------------------------------------------------------------------

// D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
// ↑/↓ 로 로스터를 순회하고, Enter 로 그 로봇의 목표 지정을 누르고,
// Escape 으로 선택을 해소한다. 입력 컨트롤에 있을 땐 간섭하지 않는다.
// 포커스 링은 표면 전역 :focus-visible 규약이 그린다.
document.addEventListener("keydown", (event) => {
  if (event.target.closest("input, select, textarea, button, ui-button, a")) return;
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
  const point = mapView.toWorld(view.map, Math.floor(col), Math.floor(view.map.height - rowFromTop));
  const robotId = view.selected;
  view.selected = null;
  canvas.classList.add("idle");
  render();
  try {
    const result = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/goal`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ x: point.x, y: point.y, yaw: 0 }),
    });
    const task = result && result.task ? result.task : null;
    if (task && task.status !== "ACCEPTED") {
      log(`${robotId} 작업 상태 ${task.status}${task.reason ? ` · ${task.reason}` : ""}`, "bad");
      return;
    }
    const receipt = task ? task.receipt : result;
    const where = `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
    if (receipt && receipt.queued) {
      // 자리가 없어 못 가는 것과, 곧 비켜 줄 것을 기다리는 것은 운영자가 할 일이 다르다.
      log(`${robotId} → ${where} ${queuedReason(result)}`,
          receipt.reason === "NO_YIELD_SPACE" ? "bad" : "");
    } else {
      log(`${robotId} → ${where} 미션 하달`, "good");
    }
  } catch (err) {
    log(`${robotId} 미션 거절 — ${err.message}`, "bad");
  }
});

el("estop").addEventListener("click", async () => {
  if (!window.confirm("등록된 모든 로봇을 정지시킵니다. 계속할까요?")) return;
  try {
    const result = await call("/api/fleet/estop", { method: "POST" });
    log(`전체 정지: ${result.stopped}/${result.total}`, result.stopped === result.total ? "good" : "bad");
    result.robots.filter((r) => !r.stopped)
      .forEach((r) => log(`  ${r.robot_id} 정지 실패 — ${r.error.code}`, "bad"));
  } catch (err) {
    log(`전체 정지 실패 — ${err.message}`, "bad");
  }
});


// D-262: 대형 패널은 formation.js 팩토리가 가진다. 셸은 지도 오버레이와
// 명렬 렌더를 쥐고, 대형 상태는 view.formation 으로 공유한다.
const formation = createFormation({ el, view, log, call, render });
formation.bind();

// Fleet 분해 4: 현장 지도 뷰는 map-view.js 팩토리가 그린다.
const mapView = createMapView({ el, view, css, auth, call });

// Fleet 분해 3: 명렬 카드와 큐는 roster.js 팩토리가 그린다.
const roster = createRoster({ el, view, log, call, render, streamEvidence: mapView.streamEvidence });

// D-262: 신호등 카드는 signals.js 팩토리가 그린다.
const signals = createSignals({ el, view, log, call, refreshState });

// --- 신호등 (ROSY-SIGNAL-001) --------------------------------------------------

function tickClock() {
  el("clock").textContent = new Date().toTimeString().slice(0, 8);
}

// 토큰 입력 — Enter 와 버튼 모두 저장한다 (form 이 아니라 keydown 이다).
el("console-token").value = auth.token;
function saveToken() {
  auth.token = el("console-token").value.trim();
  // 새 토큰은 직접 재시도한다 — 잠금 플래그가 있으면 직접 호출도 건너뛰므로 먼저 푼다.
  markUnlocked();
  if (auth.token) {
    sessionStorage.setItem("rosy-console-token", auth.token);
  } else {
    sessionStorage.removeItem("rosy-console-token");
  }
  refreshState();
  formation.refreshFormation();
}
el("token-save").addEventListener("click", saveToken);
el("console-token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") saveToken();
});

view.colors = [css("--robot-1"), css("--robot-2"), css("--robot-3")];
tickClock();
setInterval(tickClock, 1000);
refreshState();
mapView.refresh();
formation.refreshFormation();
setInterval(formation.refreshFormation, MAP_MS);
setInterval(refreshState, STATE_MS);
setInterval(() => mapView.refresh(), MAP_MS);
