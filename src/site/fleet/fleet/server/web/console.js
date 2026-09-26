// 사이트 관제 화면. 서버(Fleet)만 본다 — 로봇 API 를 직접 부르지 않는다.
//
import { createFormation } from "./formation.js";
import { createSignals } from "./signals.js";
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.

const GRID = { UNKNOWN: -1, FREE_MAX: 25, OCCUPIED_MIN: 65 };
const STATE_MS = 1000;
const MAP_MS = 5000;
const LOG_MAX = 40;
// 군집 제어 오버레이 상수(D-131 1단계). 임계는 T7 벤치 전까지 보수적으로 둔다.
const STREAM_HZ_FLOOR = 2;    // FOR-003 은 ≥5 Hz 다. 이 아래면 지연으로 본다.
const LEADER_AGE_MAX_S = 1.0; // 10 Hz 입력이면 1 초 연령은 이미 유실이다.
const TRACK_WARN_M = 0.3;     // 기본 간격(0.6 m)의 절반을 넘으면 주의 색을 쓴다.

const el = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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
  pendingTasks: {},
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

// --- 지도 ------------------------------------------------------------------

function paintGrid(grid) {
  const canvas = el("map-canvas");
  const { width, height } = grid;
  // 캔버스의 고유 크기는 이 속성이다. CSS 가 `width:100%; height:auto` 라 비율은 여기서
  // 따라온다 — style 속성을 쓰지 않는 이유는 CSP(`style-src 'self'`)가 그것을 막기 때문이다.
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  const image = ctx.createImageData(width, height);
  const free = hexToRgb(css("--paper"));
  const occupied = hexToRgb(css("--ground-deep"));
  const unknown = hexToRgb(css("--ground-soft"));
  for (let row = 0; row < height; row += 1) {
    for (let col = 0; col < width; col += 1) {
      const value = grid.data[row * width + col];
      const rgb = value === GRID.UNKNOWN || value < 0 ? unknown
        : value >= GRID.OCCUPIED_MIN ? occupied
          : value <= GRID.FREE_MAX ? free : unknown;
      const pixel = ((height - 1 - row) * width + col) * 4;
      image.data[pixel] = rgb[0];
      image.data[pixel + 1] = rgb[1];
      image.data[pixel + 2] = rgb[2];
      image.data[pixel + 3] = 255;
    }
  }
  ctx.putImageData(image, 0, 0);
}

function hexToRgb(value) {
  const hex = value.replace("#", "");
  const n = parseInt(hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function worldToCell(grid, x, y) {
  return {
    col: (x - grid.origin.x) / grid.resolution,
    row: (y - grid.origin.y) / grid.resolution,
  };
}

function cellToWorld(grid, col, row) {
  return {
    x: grid.origin.x + (col + 0.5) * grid.resolution,
    y: grid.origin.y + (row + 0.5) * grid.resolution,
  };
}

// --- 군집 제어 오버레이 (D-131 1단계) ---------------------------------------
// 후단이 이미 주는 대형·릴레이·중재 상태를 맵에 되풀이한다. 대형이 비활성이면
// 아무것도 그리지 않는다 — 오버레이는 장식이 아니라 운용자의 현재 작업 대상이다.

function colorOf(robotId) {
  const index = view.robots.findIndex((r) => r.robot_id === robotId);
  return view.colors[(index >= 0 ? index : 0) % view.colors.length];
}

// fleet.formation.geometry.slot_world_position 과 같은 식이다 — distance 는
// 리더 뒤(+), lateral 은 리더 왼쪽(+)이다.
function slotWorld(offset, pose) {
  const hx = Math.cos(pose.yaw);
  const hy = Math.sin(pose.yaw);
  const lx = -Math.sin(pose.yaw);
  const ly = Math.cos(pose.yaw);
  return {
    x: pose.x - offset.distance * hx + offset.lateral * lx,
    y: pose.y - offset.distance * hy + offset.lateral * ly,
  };
}

// 릴레이 건강을 D-72 증거로 옮긴다. fresh 는 아무것도 붙이지 않는다(§7.3 정상은 안 보임).
function streamEvidence(formation, robotId) {
  const relay = formation && formation.relay;
  if (!formation || !formation.active || !relay) return null;
  if (robotId === formation.leader) {
    if (relay.leader_last_error) return { text: "리더 오류", cls: "crit" };
    if (typeof relay.leader_age_s === "number" && relay.leader_age_s > LEADER_AGE_MAX_S) {
      return { text: "리더 지연", cls: "warn" };
    }
    return null;
  }
  const connected = relay.follower_connected || {};
  if (!(robotId in connected)) return null;
  if (connected[robotId] === false) return { text: "끊김", cls: "crit" };
  const hz = relay.follower_tx_hz || {};
  if (relay.paused !== true && typeof hz[robotId] === "number" && hz[robotId] < STREAM_HZ_FLOOR) {
    return { text: "지연", cls: "warn" };
  }
  return null;
}

function drawChip(ctx, grid, cx, cy, text, tone) {
  const fontSize = Math.max(9, Math.round(Math.min(grid.width, grid.height) * 0.035));
  ctx.font = `${fontSize}px ${css("--mono") || "monospace"}`;
  const padding = fontSize * 0.4;
  const width = ctx.measureText(text).width + padding * 2;
  const height = fontSize + padding * 2;
  ctx.save();
  ctx.globalAlpha = 0.92;
  ctx.fillStyle = css("--scrim");
  ctx.fillRect(cx - width / 2, cy - height / 2, width, height);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = css("--surface-line");
  ctx.lineWidth = 0.4;
  ctx.strokeRect(cx - width / 2, cy - height / 2, width, height);
  ctx.fillStyle = tone === "crit" ? css("--status-crit")
    : tone === "warn" ? css("--status-warn") : css("--paper");
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, cx, cy);
  ctx.restore();
}

function poseOf(robotId) {
  const robot = view.robots.find((r) => r.robot_id === robotId);
  return robot && robot.state ? robot.state.pose : null;
}

function cellOf(grid, x, y) {
  const cell = worldToCell(grid, x, y);
  return { cx: cell.col, cy: grid.height - cell.row };
}

function drawFormationOverlay(ctx, grid) {
  const formation = view.formation;
  if (!formation || !formation.active) return;
  const leaderPose = poseOf(formation.leader);
  if (!leaderPose) return;      // 리더 좌표가 없으면 슬롯을 놓을 수 없다
  const leaderCell = cellOf(grid, leaderPose.x, leaderPose.y);
  const size = Math.max(3, Math.min(grid.width, grid.height) * 0.045);
  const entries = Object.entries(formation.assignment || {});
  window.__swarmOverlay = { draws: (window.__swarmOverlay?.draws || 0) + 1, slots: entries.length };
  ctx.save();
  for (const [robotId, offset] of entries) {
    const world = slotWorld(offset, leaderPose);
    const { cx, cy } = cellOf(grid, world.x, world.y);
    // 슬롯 고스트 — 배정된 자리. 로봇 색을 쓴다(누구 자리인지가 축이다).
    ctx.beginPath();
    ctx.arc(cx, cy, size * 0.7, 0, Math.PI * 2);
    ctx.strokeStyle = colorOf(robotId);
    ctx.stroke();
    const pose = poseOf(robotId);
    if (pose) {
      // 로봇 → 슬롯 연결선 + 추적 오차. 오차가 임계를 넘을 때만 주의 색을 얻는다.
      const robotCell = cellOf(grid, pose.x, pose.y);
      const error = Math.hypot(pose.x - world.x, pose.y - world.y);
      ctx.beginPath();
      ctx.setLineDash([2, 2]);
      ctx.moveTo(robotCell.cx, robotCell.cy);
      ctx.lineTo(cx, cy);
      ctx.strokeStyle = error > TRACK_WARN_M ? css("--status-warn") : css("--muted-line");
      ctx.stroke();
      ctx.setLineDash([]);
      drawChip(ctx, grid, (robotCell.cx + cx) / 2, (robotCell.cy + cy) / 2,
        `${error.toFixed(2)}m`, error > TRACK_WARN_M ? "warn" : undefined);
    } else {
      // 좌표를 못 받은 팔로워의 슬롯은 점선으로만 — 리더와의 연결이 끊긴 자리다.
      ctx.beginPath();
      ctx.setLineDash([1, 2]);
      ctx.moveTo(leaderCell.cx, leaderCell.cy);
      ctx.lineTo(cx, cy);
      ctx.strokeStyle = css("--muted-line");
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
  // HOLD 중이면 왜 멈췄는지 맵 위에서 말한다 — 이유 없는 HOLD 는 고장으로 읽힌다.
  if (formation.state === "HOLDING" && formation.reason && formation.reason.length) {
    drawChip(ctx, grid, leaderCell.cx, leaderCell.cy - Math.min(grid.width, grid.height) * 0.08,
      `HOLD · ${formation.reason.join(" / ")}`, "warn");
  }
  ctx.restore();
}

const MEDIATION_SHORT = {
  ROUTE_CONFLICT: "경로 충돌",
  YIELDING: "비켜서는 중",
  YIELDED: "양보 대기",
  NO_YIELD_SPACE: "자리 없음",
};

function drawMediation(ctx, grid) {
  // 누가 누구 때문에 못 가는지는 관계다 — 목록에서 읽는 것과 맵에서 보는 것은 다르다(D-93).
  let lines = 0;
  for (const robot of view.robots) {
    const pose = poseOf(robot.robot_id);
    if (!pose) continue;
    const from = cellOf(grid, pose.x, pose.y);
    if (robot.queued && robot.queued.blocked_by) {
      const blockerPose = poseOf(robot.queued.blocked_by);
      if (blockerPose) {
        lines += 1;
        const to = cellOf(grid, blockerPose.x, blockerPose.y);
        ctx.save();
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(from.cx, from.cy);
        ctx.lineTo(to.cx, to.cy);
        ctx.strokeStyle = css("--status-warn");
        ctx.stroke();
        ctx.restore();
        const mid = cellOf(grid, (pose.x + blockerPose.x) / 2, (pose.y + blockerPose.y) / 2);
        drawChip(ctx, grid, mid.cx, mid.cy,
          MEDIATION_SHORT[robot.queued.reason] || robot.queued.reason || "대기", "warn");
      }
    }
    if (robot.yielding && robot.yielding.bay) {
      lines += 1;
      const to = cellOf(grid, robot.yielding.bay.x, robot.yielding.bay.y);
      ctx.save();
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(from.cx, from.cy);
      ctx.lineTo(to.cx, to.cy);
      ctx.strokeStyle = css("--series-primary");
      ctx.stroke();
      ctx.restore();
      drawChip(ctx, grid, to.cx, to.cy, "비켜설 자리");
    }
  }
  window.__swarmOverlay = window.__swarmOverlay || {};
  window.__swarmOverlay.mediation = lines;
}

function drawOverlay() {
  const grid = view.map;
  if (!grid) return;
  const canvas = el("map-canvas");
  const ctx = canvas.getContext("2d");
  paintGrid(grid);
  // 격자 픽셀 위에 그리므로 선 굵기도 격자 칸 단위다. 0.6칸이면 3 cm 남짓이다.
  ctx.lineWidth = 0.6;
  view.robots.forEach((robot, index) => {
    const pose = robot.state && robot.state.pose;
    if (!pose) return;
    const color = view.colors[index % view.colors.length];
    const cell = worldToCell(grid, pose.x, pose.y);
    const cx = cell.col;
    const cy = grid.height - cell.row;
    const size = Math.max(3, Math.min(grid.width, grid.height) * 0.045);
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-pose.yaw); // 캔버스 y 가 아래로 자라므로 회전도 뒤집는다
    ctx.beginPath();
    ctx.moveTo(size, 0);
    ctx.lineTo(-size * 0.6, size * 0.62);
    ctx.lineTo(-size * 0.6, -size * 0.62);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.globalAlpha = robot.online ? 1 : 0.35;
    ctx.fill();
    ctx.restore();

    // 목표는 Fleet 이 기억하는 값이다(로봇 상태에는 없다) — "내가 무엇을 시켰는가".
    // 대기 중인 미션도 그린다 — 어디로 갈 예정인지가 보여야 순서를 판단한다.
    const goal = robot.goal || robot.queued;
    if (goal && typeof goal.x === "number") {
      const gcell = worldToCell(grid, goal.x, goal.y);
      ctx.beginPath();
      ctx.arc(gcell.col, grid.height - gcell.row, size * 0.5, 0, Math.PI * 2);
      ctx.strokeStyle = css("--series-goal");
      ctx.globalAlpha = 1;
      ctx.stroke();
    }
  });
  drawFormationOverlay(ctx, grid);
  drawMediation(ctx, grid);
}

async function refreshMap() {
  if (auth.locked) return;
  try {
    const grid = await call("/api/fleet/map");
    view.map = grid;
    el("map-tag").textContent = `${grid.width}×${grid.height} · ${grid.map_id || "map"}`;
    drawOverlay();
  } catch (err) {
    el("map-tag").textContent = "맵 없음";
  }
}

// --- 로봇 목록 --------------------------------------------------------------

function navTag(state) {
  const nav = state && state.navigation;
  if (!nav) return { text: "—", cls: "" };
  if (nav === "NAVIGATING") return { text: nav, cls: "nav" };
  if (nav === "ARRIVED") return { text: nav, cls: "ok" };
  if (nav === "FAILED") return { text: nav, cls: "crit" };
  return { text: nav, cls: "" };
}

// 대기에는 세 가지 이유가 있고, 운영자가 할 일이 저마다 다르다. "대기 중" 한 마디로
// 뭉뜽그리면, 손대야 풀리는 상황에서도 사람이 저절로 풀리기를 기다린다.
function queuedReason(queued) {
  const who = queued.blocked_by;
  if (queued.reason === "NO_YIELD_SPACE") {
    return `${who} 가 길을 막았는데 비켜설 자리가 없습니다 — 맵이 좁습니다. `
      + `${who} 를 직접 다른 곳으로 보내 주세요`;
  }
  if (queued.reason === "YIELDING") {
    return `${who} 가 비켜서기를 기다리는 중 — 물러나면 자동 출발합니다`;
  }
  if (queued.reason === "YIELDED") {
    return `${who} 가 지나가기를 기다리는 중 — 지나가면 제 미션으로 돌아갑니다`;
  }
  return `${who} 경로와 겹쳐 대기 중 — 앞이 비면 자동 출발합니다`;
}

function card(robot, index) {
  const node = document.createElement("article");
  node.className = `robot s${index % view.colors.length}`;
  if (!robot.online) node.classList.add("offline");
  if (view.selected === robot.robot_id) node.classList.add("selected");
  // D-224 — ↑/↓ 순회의 착지점. tabindex -1 은 프로그램 포커스만 허용한다
  // (탭 순서를 더럽히지 않는다).
  node.tabIndex = -1;

  const state = robot.state || {};
  const pose = state.pose;
  const nav = navTag(state);
  const estop = state.safety && state.safety.estop;

  const head = document.createElement("div");
  head.className = "robot-head";
  head.innerHTML = `<b>${robot.robot_id}</b><span class="spacer"></span>`;
  const mode = document.createElement("span");
  mode.className = "tag";
  mode.textContent = robot.online ? (state.mode || "—") : "OFFLINE";
  if (!robot.online) mode.classList.add("crit");
  head.appendChild(mode);
  const navEl = document.createElement("span");
  const blocked = robot.queued && robot.queued.reason === "NO_YIELD_SPACE";
  navEl.className = `tag ${blocked ? "crit" : robot.queued ? "warn" : nav.cls}`;
  // 비켜서는 중인 로봇은 "주행 중"이 맞다 — 다만 제 미션을 가는 것이 아니라서 따로 적는다.
  navEl.textContent = robot.yielding ? "비켜서는 중" : robot.queued ? "대기" : nav.text;
  head.appendChild(navEl);
  const evidence = streamEvidence(view.formation, robot.robot_id);
  if (evidence) {
    // 릴레이 건강은 증거다(D-72). fresh 는 아무것도 붙지 않는다 — 붙는 것은 문제뿐이다.
    const evEl = document.createElement("span");
    evEl.className = `tag ${evidence.cls}`;
    evEl.textContent = evidence.text;
    head.appendChild(evEl);
  }
  node.appendChild(head);

  const facts = document.createElement("div");
  facts.className = "facts";
  const battery = state.battery && typeof state.battery.percent === "number"
    ? `${Math.round(state.battery.percent)}%` : "—";
  const rows = [
    ["POSE", pose ? `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}` : "—"],
    ["YAW", pose ? `${(pose.yaw * 180 / Math.PI).toFixed(0)}°` : "—"],
    ["BATTERY", battery],
    ["SAFETY", estop ? "E-STOP" : robot.online ? "OK" : "—"],
  ];
  rows.forEach(([label, value]) => {
    const cellEl = document.createElement("div");
    cellEl.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
    facts.appendChild(cellEl);
  });
  node.appendChild(facts);

  if (robot.yielding) {
    // 운영자가 보내지 않은 좌표로 로봇이 움직인다. 이유를 적지 않으면 오작동으로 읽힌다.
    const why = document.createElement("p");
    why.className = "hint";
    why.textContent = `${robot.yielding.for} 가 지나가도록 비켜서는 중 — `
      + `(${robot.yielding.bay.x.toFixed(2)}, ${robot.yielding.bay.y.toFixed(2)}) 로 물러납니다`;
    node.appendChild(why);
  }

  if (robot.queued) {
    // 왜 안 가는지 화면이 말하지 않으면 운영자는 미션이 사라졌다고 읽는다.
    const why = document.createElement("p");
    why.className = "hint";
    why.textContent = queuedReason(robot.queued);
    node.appendChild(why);
  }

  if (!robot.online && robot.error) {
    const why = document.createElement("p");
    why.className = "hint";
    why.textContent = robot.error.reachable
      ? `로봇이 거절: ${robot.error.code}` : `닿지 않음: ${robot.error.code}`;
    node.appendChild(why);
  }

  const actions = document.createElement("div");
  actions.className = "robot-actions";
  const aim = document.createElement("ui-button");
  aim.setAttribute("kind", "quiet");
  aim.type = "button";
  aim.textContent = view.selected === robot.robot_id ? "지도를 찍으세요" : "목표 지정";
  if (view.selected === robot.robot_id) aim.classList.add("arming");
  aim.disabled = !robot.online || !view.map;
  aim.addEventListener("click", () => {
    view.selected = view.selected === robot.robot_id ? null : robot.robot_id;
    el("map-canvas").classList.toggle("idle", view.selected === null);
    render();
  });
  const cancel = document.createElement("ui-button");
  cancel.setAttribute("kind", "quiet");
  cancel.type = "button";
  cancel.textContent = "취소";
  cancel.disabled = !robot.online;
  cancel.addEventListener("click", async () => {
    try {
      const pending = view.pendingTasks[robot.robot_id];
      if (pending) {
        const readback = await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}`);
        if (readback.task?.status === "QUEUED") {
          await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}/cancel`, { method: "POST" });
          delete view.pendingTasks[robot.robot_id];
          render();
          log(`${robot.robot_id} task ${pending.task_id} QUEUED 취소`, "good");
          return;
        }
        delete view.pendingTasks[robot.robot_id];
      }
      await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/cancel`, { method: "POST" });
      log(`${robot.robot_id} 항법 취소`, "good");
    } catch (err) {
      log(`${robot.robot_id} 취소 실패 — ${err.message}`, "bad");
    }
  });
  actions.append(aim, cancel);
  node.appendChild(actions);
  return node;
}

// D-252: 큐 머리는 ui-triage. <b>는 범주+개수, <small>은 이름들이다. 행은 그대로 둔다.
function setTriageHead(id, label, list) {
  const head = el(id);
  if (!head) return;
  const names = [...list.querySelectorAll("li b")].map((b) => b.textContent);
  head.querySelector("b").textContent = `${label} ${names.length}`;
  head.querySelector("small").textContent = names.join(" · ");
}

function render() {
  const roster = el("roster");
  roster.replaceChildren(...view.robots.map(card));
  signals.render();
  
  // ADR-1000: Populate Queues
  const warnList = el("warning-list");
  const critList = el("critical-list");
  warnList.innerHTML = "";
  critList.innerHTML = "";
  
  let warningCount = 0;
  let criticalCount = 0;
  
  for (const r of view.robots) {
    if (!r.state) continue;
    if (r.state.hitl_requested) {
      // 개입 요청은 이름으로 알린다(Law 0). 원격 조종은 이 서버에 없는
      // 능력이다 — 못 하는 조작을 모의 버튼으로 걸어 두면 경보가 거짓말을
      // 한다(D-218, F-20). 진짜 개입은 그 로봇의 대시보드에서 일어난다.
      const li = document.createElement("li");
      li.innerHTML = `<b>${r.robot_id}</b>: 개입 필요 — 로봇 화면에서 확인`;
      critList.appendChild(li);
      criticalCount++;
    } else if (r.state.capabilities_degraded && r.state.capabilities_degraded.length > 0) {
      const li = document.createElement("li");
      li.innerHTML = `<b>${r.robot_id}</b>: 성능 저하 [${r.state.capabilities_degraded.join(", ")}]`;
      warnList.appendChild(li);
      warningCount++;
    }
  }
  // D-252: 큐 머리는 ui-triage 다. <b>는 범주+개수, <small>은 이름들이다. 행은 그대로.
  setTriageHead("warning-head", "주의 요망", warnList);
  setTriageHead("critical-head", "최우선 개입 요망", critList);

  // ADR-1000 & UX Law 1: Hide empty queues to prevent alarm colors in normal state.
  // CSP `style-src 'self'` 는 style 속성을 막으므로 hidden 속성으로 토글한다
  // (D-201 회차 계측에서 style.display 토글이 실서버에서는 무시됨을 확인).
  warnList.parentElement.hidden = warningCount === 0;
  critList.parentElement.hidden = criticalCount === 0;
  document.querySelector(".queues-panel").hidden = (warningCount + criticalCount) === 0;

  formation.fillLeaders();
  drawOverlay();
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
  const point = cellToWorld(view.map, Math.floor(col), Math.floor(view.map.height - rowFromTop));
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
    if (task && task.status === "QUEUED") {
      view.pendingTasks[robotId] = task;
      const why = task.reason || result.reason || "READY";
      const blockedBy = task.waiting_on?.length ? ` · ${task.waiting_on.join(", ")}` : "";
      log(`${robotId} task ${task.task_id} QUEUED · ${why}${blockedBy} · 취소 가능`, "good");
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
refreshMap();
formation.refreshFormation();
setInterval(formation.refreshFormation, MAP_MS);
setInterval(refreshState, STATE_MS);
setInterval(refreshMap, MAP_MS);
