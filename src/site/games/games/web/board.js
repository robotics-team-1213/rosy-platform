const canvas = document.getElementById("pitch");
const ctx = canvas.getContext("2d");
const MARKER_IDS = [10, 11, 12, 13, 1, 2, 20, 21];
const MARKER_LABEL = {
  10: "코너",
  11: "코너",
  12: "코너",
  13: "코너",
  1: "로봇",
  2: "로봇",
  20: "골",
  21: "골",
};
const PHASE_LABEL = {
  kickoff: "시작 준비",
  play: "경기 진행",
  hold: "경기 보류",
  goal: "득점",
};
const announcement = document.getElementById("match-announcement");
const connection = document.getElementById("connection");
const halt = document.getElementById("halt");
const haltStatus = document.getElementById("halt-status");
const pitchWrap = document.getElementById("pitch-wrap");
const fieldEvidence = document.getElementById("field-evidence");
const score = document.querySelector(".score");
const scoreEvidence = document.getElementById("score-evidence");
const frame = document.getElementById("frame");
let polling = false;
let hasMatch = false;
let lastEvidence = null;
let evidenceAnnouncement = "";

function setTextIfChanged(element, value) {
  if (element.textContent !== value) element.textContent = value;
}

function setFieldEvidence(evidence) {
  const stale = hasMatch && evidence !== "fresh";
  const message = evidence === "delayed"
    ? "지연 · 마지막 수신 위치 · 현재 위치 아님"
    : evidence === "disconnected"
      ? "연결 오류 · 마지막 수신 위치 · 현재 위치 아님"
      : "데이터 대기 · 마지막 수신 위치 · 현재 위치 아님";
  fieldEvidence.hidden = !stale;
  if (stale) {
    setTextIfChanged(fieldEvidence, message);
    canvas.setAttribute("aria-describedby", "field-evidence");
    pitchWrap.dataset.evidence = evidence;
    frame.dataset.evidence = evidence;
  } else {
    canvas.removeAttribute("aria-describedby");
    delete pitchWrap.dataset.evidence;
    delete frame.dataset.evidence;
  }
  score.setAttribute("aria-label", stale ? "마지막 수신 점수" : "점수");
  scoreEvidence.hidden = !stale;
}

function setPhaseEvidence(evidence, phaseCode) {
  const phase = document.getElementById("phase");
  if (phaseCode !== undefined) phase.dataset.phase = phaseCode || "";
  if (!hasMatch) return;
  const label = PHASE_LABEL[phase.dataset.phase] || "단계 미확인";
  const text = evidence === "fresh" ? label : `마지막 수신 단계 · ${label}`;
  setTextIfChanged(phase, text);
  return text;
}

// D-359 §4 — 피치 색은 styles.css `:root` 피치 블록이 소유한다. 캔버스는
// ui.js(window.RosyPalette)로 읽는다. 이 화면은 dark 고정이다.
const tone = (name) => window.RosyPalette.cssColor(name);

function draw(payload) {
  const field = payload.field || { length_m: 2, width_m: 1.4, goal_width_m: 0.35 };
  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = tone("--pitch");
  ctx.fillRect(0, 0, w, h);
  const pad = 36;
  const sx = (w - pad * 2) / field.length_m;
  const sy = (h - pad * 2) / field.width_m;
  const s = Math.min(sx, sy);
  const ox = w / 2;
  const oy = h / 2;
  const X = (x) => ox + x * s;
  const Y = (y) => oy - y * s;
  ctx.strokeStyle = tone("--line");
  ctx.lineWidth = 2;
  ctx.strokeRect(
    X(-field.length_m / 2),
    Y(field.width_m / 2),
    field.length_m * s,
    field.width_m * s,
  );
  ctx.beginPath();
  ctx.moveTo(X(0), Y(-field.width_m / 2));
  ctx.lineTo(X(0), Y(field.width_m / 2));
  ctx.stroke();
  const gw = field.goal_width_m / 2;
  ctx.strokeStyle = tone("--home");
  ctx.strokeRect(X(-field.length_m / 2) - 10, Y(gw), 10, field.goal_width_m * s);
  ctx.strokeStyle = tone("--away");
  ctx.strokeRect(X(field.length_m / 2), Y(gw), 10, field.goal_width_m * s);
  if (payload.home_goal) {
    strokePoly(payload.home_goal, X, Y, tone("--home"));
  }
  if (payload.away_goal) {
    strokePoly(payload.away_goal, X, Y, tone("--away"));
  }
  const robots = payload.robots || {};
  const homeId = field.home_id;
  Object.entries(robots).forEach(([id, pose]) => {
    ctx.fillStyle = tone(id === homeId ? "--home" : "--away");
    wedge(X(pose.x), Y(pose.y), pose.yaw, 11);
    ctx.fillStyle = tone("--pitch-ink");
    ctx.font = window.RosyPalette.canvasFont(12, "body");
    ctx.fillText(id, X(pose.x) + 8, Y(pose.y) - 8);
  });
  if (payload.ball) {
    ctx.fillStyle = tone("--ball");
    ctx.beginPath();
    ctx.arc(X(payload.ball.x), Y(payload.ball.y), 7, 0, Math.PI * 2);
    ctx.fill();
  }
}

function strokePoly(points, X, Y, color) {
  if (!points.length) return;
  ctx.strokeStyle = color;
  ctx.beginPath();
  ctx.moveTo(X(points[0][0]), Y(points[0][1]));
  points.slice(1).forEach((p) => ctx.lineTo(X(p[0]), Y(p[1])));
  ctx.closePath();
  ctx.stroke();
}

function wedge(x, y, yaw, r) {
  ctx.beginPath();
  ctx.moveTo(x + Math.cos(-yaw) * r, y + Math.sin(-yaw) * r);
  ctx.lineTo(x + Math.cos(-yaw + 2.5) * r * 0.7, y + Math.sin(-yaw + 2.5) * r * 0.7);
  ctx.lineTo(x + Math.cos(-yaw - 2.5) * r * 0.7, y + Math.sin(-yaw - 2.5) * r * 0.7);
  ctx.closePath();
  ctx.fill();
}

function chips(payload) {
  const seen = new Set(payload.markers || []);
  const root = document.getElementById("markers");
  root.replaceChildren();
  MARKER_IDS.forEach((id) => {
    const li = document.createElement("li");
    li.textContent = `${id} ${MARKER_LABEL[id] || ""}`.trim();
    if (seen.has(id)) li.className = "on";
    root.append(li);
  });
}

async function tick() {
  if (polling) return;
  polling = true;
  try {
    const res = await fetch("/overlay.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`overlay ${res.status}`);
    const payload = await res.json();
    if (!payload.field) {
      connection.dataset.evidence = "unavailable";
      lastEvidence = "unavailable";
      setFieldEvidence("unavailable");
      setPhaseEvidence("unavailable");
      setTextIfChanged(connection, hasMatch ? "경기 데이터 대기 · 마지막 경기 정보" : "경기 데이터 대기 중");
      if (hasMatch) {
        setTextIfChanged(announcement, "경기 데이터 대기 중. 표시된 경기 정보는 마지막 수신 값입니다.");
      }
      return;
    }
    hasMatch = true;
    const evidence = payload.evidence || "unavailable";
    setFieldEvidence(evidence);
    connection.dataset.evidence = evidence;
    if (payload.evidence === "fresh") {
      setTextIfChanged(connection, "\uD638\uC2A4\uD2B8 \uC5F0\uACB0\uB428");
    } else if (payload.evidence === "delayed") {
      const age = typeof payload.age_s === "number" ? ` \u00B7 \uB9C8\uC9C0\uB9C9 \uC0DD\uC131 ${payload.age_s.toFixed(1)}\uCD08 \uC804` : "";
      setTextIfChanged(connection, `\uC9C0\uC5F0 \u00B7 \uB9C8\uC9C0\uB9C9 \uC218\uC2E0 \uACBD\uAE30 \uC815\uBCF4${age}`);
    } else {
      setTextIfChanged(connection, "\uC2DC\uAC01 \uC815\uBCF4 \uC5C6\uC74C \u00B7 \uB9C8\uC9C0\uB9C9 \uACBD\uAE30 \uC815\uBCF4");
    }
    if (evidence !== lastEvidence) {
      evidenceAnnouncement = evidence === "fresh" ? "" : connection.textContent;
      lastEvidence = evidence;
    }
    const homeScore = payload.score?.[payload.field.home_id] ?? "—";
    const awayScore = payload.score?.[payload.field.away_id] ?? "—";
    const phaseLabel = setPhaseEvidence(evidence, payload.phase);
    document.getElementById("home-name").textContent = payload.field.home_id;
    document.getElementById("away-name").textContent = payload.field.away_id;
    document.getElementById("home-score").textContent = homeScore;
    document.getElementById("away-score").textContent = awayScore;
    const lost = payload.lost_ball || (payload.lost_robots || []).length;
    const lostElement = document.getElementById("lost");
    lostElement.hidden = !lost;
    lostElement.textContent = payload.reason || (payload.lost_ball ? "공을 잃음" : "로봇을 잃음");
    const matchSummary = `${phaseLabel} · ${payload.field.home_id} ${homeScore}, ${payload.field.away_id} ${awayScore}${lost ? ` · ${lostElement.textContent}` : ""}${evidenceAnnouncement ? ` · ${evidenceAnnouncement}` : ""}`;
    setTextIfChanged(announcement, matchSummary);
    draw(payload);
    chips(payload);
    const vis = payload.visibility || {};
    const stair1 = document.getElementById("stair1");
    if (stair1) {
      stair1.textContent = vis.ready
        ? "계단 1 마커 보임 · 경기장 준비 전"
        : "계단 1 아직 · 경기장 준비 전";
    }
    if (!payload.has_frame) {
      frame.hidden = true;
      return;
    }
    frame.onerror = () => {
      frame.hidden = true;
    };
    frame.onload = () => {
      frame.hidden = false;
    };
    frame.src = `/frame.jpg?t=${Date.now()}`;
  } catch (_error) {
    connection.dataset.evidence = "disconnected";
    lastEvidence = "disconnected";
    setFieldEvidence("disconnected");
    setPhaseEvidence("disconnected");
    setTextIfChanged(connection, hasMatch ? "호스트 연결 오류 · 마지막 경기 정보" : "호스트 연결 오류 · 경기 정보 없음");
    setTextIfChanged(announcement, hasMatch
      ? "호스트 연결 오류. 표시된 경기 정보는 마지막 수신 값입니다."
      : "호스트 연결 오류. 경기 정보가 없습니다.");
  } finally {
    polling = false;
  }
}

halt.addEventListener("click", async () => {
  if (halt.disabled) return;
  const restoreFocus = document.activeElement === halt;
  halt.disabled = true;
  haltStatus.dataset.state = "pending";
  setTextIfChanged(haltStatus, "정지 요청 중");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const res = await fetch("/stop", { method: "POST", signal: controller.signal });
    if (!res.ok) throw new Error(`stop ${res.status}`);
    haltStatus.dataset.state = "sent";
    setTextIfChanged(haltStatus, "정지 요청 접수 · 실제 정지 확인 중");
  } catch (error) {
    haltStatus.dataset.state = "error";
    setTextIfChanged(haltStatus, error.name === "AbortError"
      ? "정지 요청 시간 초과 · 다시 눌러 재시도하세요"
      : "정지 요청 실패 · 다시 눌러 재시도하세요");
  } finally {
    clearTimeout(timeout);
    halt.disabled = false;
    if (restoreFocus) halt.focus();
  }
});

// 초점 문법의 키보드 약속(D-224) — "스페이스도 양쪽을 세운다"가 이제 참이다.
// 포커스가 컨트롤에 있으면 브라우저가 이미 Space 를 click 으로 바꾼다 —
// 이중 발사를 막으려 몸에서만 잡는다.
document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.repeat) return;
  if (event.target.closest("button, ui-button, input, select, textarea, a")) return;
  event.preventDefault();
  halt.click();
});

setInterval(tick, 250);
tick();
