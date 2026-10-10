// D-407 판단 요청 — 차선 추종이 막힌 로봇이 관제에 묻는다. 막힘은 CORE 가 열고 판단하며,
// 화면은 서버(Fleet)가 모은 막힘(robot.line_stuck)을 보이고 운영자의 답 하나를 Fleet 에
// 넘길 뿐이다. 거부(늦은 답, 재개 거부 사유)는 CORE 의 말 그대로 옮긴다.
// 상태 폴링은 1 s 마다 다시 그리므로, 바뀐 항목만 다시 만든다 — 확인 단계와 포커스가
// 폴링에 지워지지 않게 한다. 색은 클래스로만 준다(CSP style-src 'self').

import { primaryButton, quietButton, setReason, stuckOverdue } from "./queues.js";

export const DECISIONS = Object.freeze(["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]);

export const DECISION_LABEL = Object.freeze({
  WAIT: "대기",
  RESUME: "재개",
  BACK_AND_RETRY: "후진 후 재시도",
  MANUAL: "수동",
  ABORT: "중단",
});

export const CAUSE_LABEL = Object.freeze({
  obstacle_ahead: "앞 물체로 멈춤",
  lane_lost: "차선을 잃고 멈춤",
  no_motion: "5초 넘게 움직이지 않음",
});

export const PHASE_LABEL = Object.freeze({
  ASKING: "관제 답 기다림 · 시간이 지나면 로컬 복구",
  WAITING_CONSOLE: "관제 답만 기다림",
  BACKING: "로컬 복구 · 후진 중",
  SETTLING: "로컬 복구 · 다시 보는 중",
});

// CORE stuck_recovery 의 거부 사유. 모르는 사유는 받은 그대로 보인다.
export const REFUSAL_REASON = Object.freeze({
  no_scan: "LiDAR 스캔이 없습니다",
  scan_stale: "LiDAR 스캔이 오래되었습니다",
  object_within_stop_distance: "정지 거리 안에 아직 물체가 있습니다",
  local_recovery_disabled: "이 로봇은 로컬 복구가 꺼져 있습니다",
  attempts_exhausted: "후진 시도를 모두 썼습니다",
  calibration_active: "보정 세션 중입니다",
  body_geometry_unset: "몸 치수(URDF) 설정이 없습니다",
  rear_blind: "뒤 사각을 확인할 수 없습니다",
  rear_blocked: "뒤가 막혀 있습니다",
  linear_limit_zero: "수동 속도 한도가 0입니다",
});

// D-438: why the Fleet resolver handed a stuck to a human.
const ESCALATION_REASON = Object.freeze({
  no_rule: "맞는 규칙 없음",
  rule_budget: "자동 판단 횟수 소진",
  deadline: "60초 안에 풀리지 않음",
  restuck_after_resume: "자동 재개 뒤 다시 막힘",
  estop: "비상정지",
  calibration: "보정 중",
  no_resolver_token: "자동 판단 토큰 없음",
  crosswalk_human: "횡단보도 위 — 사람이 확인",
  // D-577 1: R5 held the robot (WAIT) instead of backing off after a lost lane.
  "lane_lost_hold:peer_behind": "차선 잃음 — 뒤에 다른 로봇",
  "lane_lost_hold:attempts": "차선 잃음 — 후진 시도 소진",
  "lane_lost_hold:local_disabled": "차선 잃음 — 로컬 복구 꺼짐",
  "lane_lost_hold:crosswalk": "차선 잃음 — 횡단보도 안",
  "lane_lost_hold:crosswalk_unknown": "차선 잃음 — 횡단보도 여부 모름",
  "lane_lost_hold:peer_unknown": "차선 잃음 — 주변 로봇 위치 모름",
  "lane_lost_hold:pose": "차선 잃음 — Fleet 위치 오래됨",
  "lane_lost_hold:refused": "차선 잃음 — 후진 거절됨",
  "lane_lost_hold:rule_budget": "차선 잃음 — 자동 판단 횟수 소진",
  // 2026-10-10: the same holds for a no_motion stuck (zero command >= stuck_report_s, any reason).
  "no_motion_hold:peer_behind": "멈춤 — 뒤에 다른 로봇",
  "no_motion_hold:attempts": "멈춤 — 후진 시도 소진",
  "no_motion_hold:local_disabled": "멈춤 — 로컬 복구 꺼짐",
  "no_motion_hold:crosswalk": "멈춤 — 횡단보도 안",
  "no_motion_hold:crosswalk_unknown": "멈춤 — 횡단보도 여부 모름",
  "no_motion_hold:peer_unknown": "멈춤 — 주변 로봇 위치 모름",
  "no_motion_hold:pose": "멈춤 — Fleet 위치 오래됨",
  "no_motion_hold:refused": "멈춤 — 후진 거절됨",
  "no_motion_hold:rule_budget": "멈춤 — 자동 판단 횟수 소진",
});

// D-577 Safety-Review 2026-10-10: why Fleet held an AI PC proposal back (then its rules answered).
const AI_HELD_REASON = Object.freeze({
  trip: "운행 중 로봇은 대기만",
  word_not_allowed: "이 막힘에 쓸 수 없는 답",
  core_refused_before: "CORE가 이 막힘에서 AI 답을 거절함",
  stuck_mismatch: "다른 막힘의 제안",
  after_answer: "이미 답한 막힘",
  crosswalk: "횡단보도 안",
  crosswalk_unknown: "횡단보도 여부 모름",
  rear_blocked: "뒤가 막힘",
  peer_ahead: "앞에 다른 로봇",
  peer_behind: "뒤에 다른 로봇",
  peer_unknown: "주변 로봇 위치 모름",
  pose: "Fleet 위치 오래됨",
  local_disabled: "로컬 복구 꺼짐",
  attempts: "후진 시도 소진",
  rule_budget: "자동 판단 횟수 소진",
  refused: "후진 거절됨",
});

const AI_CLASS_TEXT = Object.freeze({
  accepted: "CORE 수락", refused: "CORE 거절", pending: "CORE 답 기다림", held: "Fleet 보류",
});

/** Fleet's hold reason for an AI proposal, in operator words (an acting AI fact names its kind). */
export function aiHeldText(verdict) {
  if (typeof verdict === "string" && verdict.startsWith("ai:")) return `AI 사실 ${verdict.slice(3)}`;
  if (typeof verdict === "string" && verdict.startsWith("ai_fact:")) return `AI 사실 ${verdict.slice(8)}`;
  return AI_HELD_REASON[verdict] || verdict;
}

/** D-577: the newest AI proposal for this stuck, with Fleet's verdict and CORE's outcome. */
export function aiProposalText(proposal) {
  if (!proposal) return "";
  const word = DECISION_LABEL[proposal.decision] || proposal.decision;
  const why = proposal.class === "held" ? ` (${aiHeldText(proposal.verdict)})`
    : proposal.class === "refused" ? ` (CORE 응답 ${proposal.outcome})` : "";
  return `AI 제안 ${word}: ${AI_CLASS_TEXT[proposal.class] || proposal.class}${why}`;
}

function escalationText(code) {
  const ai = /^(ai_wait|ai_abort|ai_abort_held):(.*)$/.exec(code);
  if (ai?.[1] === "ai_abort_held") return `AI 중단 제안 보류 — 멈춰 둠 (${aiHeldText(ai[2])})`;
  if (ai) return `AI ${ai[1] === "ai_wait" ? "대기" : "중단"} 제안 (${ai[2]})`;
  const held = /^(\w+)_hold:ai:(.*)$/.exec(code);
  if (held) return `자동 후진 보류 — AI 사실 ${held[2]}`;
  return ESCALATION_REASON[code] || code;
}

/** One line about what the Fleet resolver did for this stuck. */
export function resolverText(note) {
  if (!note) return "";
  if (note.escalated) {
    if (note.escalated === "human_claimed") return "운영자가 맡음";
    const code = note.escalated.startsWith("core:") ? note.escalated.slice(5) : "";
    const why = code ? `CORE 응답 ${code}` : escalationText(note.escalated);
    if (note.decision) return `자동 판단 ${note.rule}: ${DECISION_LABEL[note.decision] || note.decision} — 사람 확인 필요 (${why})`;
    return `자동 판단 불가 — 사람 확인 필요 (${why})`;
  }
  return `자동 판단 ${note.rule}: ${DECISION_LABEL[note.decision] || note.decision}`;
}

const AI_STATE_TEXT = Object.freeze({ present: "AI 판단 있음", absent: "AI 판단 없음" });

/** D-577 5·8: the AI chip and one line per live fact (kind, confidence, source, evidence ids); shadow only. */
export function aiLines(stuck) {
  const ai = stuck.ai;
  if (!ai) return [];
  const chip = ai.state === "present" && ai.owner_mode === "owner_busy" ? "AI 판단 없음 (소유자 사용 중)"
    : AI_STATE_TEXT[ai.state] || "AI 판단 없음";
  const facts = (stuck.ai_facts || []).map((fact) => `AI 사실 ${fact.kind} · 신뢰도 ${Math.round(fact.confidence * 100)}%`
    + ` · ${fact.source} · 근거 ${JSON.stringify(fact.evidence)}`);
  const proposal = aiProposalText(stuck.ai_proposal);
  return proposal ? [chip, proposal, ...facts] : [chip, ...facts];
}

const CREDENTIAL_TEXT = Object.freeze({ enrolled: "등록 자격", token: "판단 토큰", none: "자격 없음" });
const OWNER_MODE_TEXT = Object.freeze({ available: "사용 가능", shared: "공유", owner_busy: "소유자 사용 중" });

const secondsAgo = (iso, nowMs) => {
  const at = Date.parse(iso);
  return Number.isFinite(at) ? `${Math.max(0, Math.round((nowMs - at) / 1000))}초 전` : "";
};

/** D-577 연동 상태: [label, text] rows from GET /api/fleet/ai (presence only, never a secret). */
export function chainRows(body, nowMs = Date.now()) {
  const chain = body?.chain;
  const status = body?.status;
  if (!chain || !status) return [["연동", "확인할 수 없음"]];
  const rows = [["자동 판단", chain.resolver ? "켜짐" : "꺼짐"]];
  for (const robot of chain.robots || []) {
    const last = robot.last_answer;
    const answer = !last ? "답 없음"
      : last.decision === "ESCALATE" ? `사람에게 (${escalationText(last.escalated)})`
        : `${last.rule || last.tier} ${DECISION_LABEL[last.decision] || last.decision}`;
    rows.push([robot.robot_id, [CREDENTIAL_TEXT[robot.credential] || robot.credential,
      robot.ai_acting ? "AI 제안 실행" : "AI 사실만", `마지막 ${answer}`,
      last ? secondsAgo(last.at, nowMs) : ""].filter(Boolean).join(" · ")]);
  }
  rows.push(["AI PC", status.state === "present"
    ? [`신호 ${status.age_s}초 전`, OWNER_MODE_TEXT[status.owner_mode] || status.owner_mode,
      typeof status.input_lag_s === "number" ? `입력 지연 ${status.input_lag_s.toFixed(1)}초` : "",
      `버전 ${status.service_version} @ ${status.build_commit || "커밋 모름"}`].filter(Boolean).join(" · ")
    : status.age_s == null ? "없음 (신호 받은 적 없음)" : `없음 (마지막 신호 ${status.age_s}초 전)`]);
  const n = chain.proposals_1h || {};
  rows.push(["AI 제안 1시간", `수락 ${n.accepted ?? 0} · 보류 ${n.held ?? 0} · 거절 ${n.refused ?? 0}`
    + ` · 답 기다림 ${n.pending ?? 0}`]);
  return rows;
}

/** D-577 연동 상태 fold (D-540: the header stays one line, status sits beside 진단 at the rail end).
 * Reads GET /api/fleet/ai every 2 s while the fold is open (a locked page shows "확인할 수 없음"). */
function watchChainStatus({ scope, call }) {
  const fold = globalThis.document?.getElementById("chain-status");
  if (!fold) return;
  async function refresh() {
    if (!fold.open) return;
    const body = await call("/api/fleet/ai").catch(() => null);
    document.getElementById("chain-readout").replaceChildren(...chainRows(body).flatMap(([label, text]) => {
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = label;
      dd.textContent = text;
      return [dt, dd];
    }));
  }
  scope.listen(fold, "toggle", refresh);
  scope.interval(refresh, 2000);
}

const OUTCOME_TEXT = Object.freeze({
  hold: "대기로 답했습니다 — 다음 요청까지 멈춰 있습니다",
  back: "후진 후 재시도를 시작했습니다",
  resume: "재개했습니다 — 차선 추종을 다시 시작합니다",
  manual: "수동 모드로 넘겼습니다",
  idle: "차선 추종을 중단했습니다",
});

const CONFIRMED = new Set(["RESUME", "BACK_AND_RETRY"]);

const metres = (value) => (typeof value === "number" && Number.isFinite(value)
  ? `${value.toFixed(2)} m` : "—");

export function pendingStucks(robots) {
  return (robots || []).filter((robot) => robot && robot.line_stuck && robot.line_stuck.stuck_id);
}

export function needsConfirm(decision) {
  return CONFIRMED.has(decision);
}

/** Rear clearance text: a distance, or "비어 있음" (band empty) vs "알 수 없음" (CORE could not
 * tell), from rear_state. A null distance alone cannot tell those apart. */
export function rearText(stuck) {
  if (typeof stuck.rear_clearance_m === "number" && Number.isFinite(stuck.rear_clearance_m)) {
    return metres(stuck.rear_clearance_m);
  }
  if (stuck.rear_state === "clear") return "비어 있음";
  if (stuck.rear_state === "blocked") return "막힘";
  return "알 수 없음";
}

/** Fact rows for one stuck: [key, label, value, cssClass?]. */
export function stuckFacts(stuck) {
  const attempts = `${stuck.attempts ?? 0}/${stuck.max_attempts ?? 0}`;
  const held = typeof stuck.held_s === "number" ? `${Math.round(stuck.held_s)} s` : "—";
  const rear = rearText(stuck);
  const rows = [
    ["front", "앞 여유", metres(stuck.front_clearance_m)],
    ["rear", "뒤 여유", rear, rear === "알 수 없음" ? "stuck-fact-unknown" : undefined],
    ["turn", "회전 여유", metres(stuck.turn_clearance_m)],
    ["held", "멈춘 시간", held],
    ["attempts", "후진 시도", attempts],
  ];
  if (stuck.preview_seq !== null && stuck.preview_seq !== undefined) {
    rows.push(["preview", "카메라 미리보기", `#${stuck.preview_seq}`]);
  }
  return rows;
}

/** One button per CORE decision, disabled with the first reason that applies. */
export function decisionButtons(stuck, { operator, namedReason = "", busy = false }) {
  return DECISIONS.map((decision) => {
    let reason = "";
    if (!operator) reason = "운영자 권한이 필요합니다";
    // D-540 9: 대기·중단은 멈춤이라 열려 있고, 움직이는 답만 이름 있는 운영자다.
    else if (namedReason && decision !== "WAIT" && decision !== "ABORT") reason = namedReason;
    else if (stuck.robot_online === false) reason = "로봇 연결이 끊겼습니다";
    else if (busy) reason = "답을 보내는 중";
    else if (decision === "BACK_AND_RETRY" && !stuck.local_enabled) {
      reason = "이 로봇은 로컬 복구가 꺼져 있습니다";
    } else if (decision === "BACK_AND_RETRY" && (stuck.attempts ?? 0) >= (stuck.max_attempts ?? 0)) {
      reason = "후진 시도를 모두 썼습니다";
    }
    return { decision, label: DECISION_LABEL[decision], confirm: needsConfirm(decision), reason };
  });
}

const CAMERA_LABEL = Object.freeze({ front: "앞 카메라" });

export function previewFresh(preview, elapsedS = 0) {
  return preview?.live === true && Number.isFinite(preview.age_s)
    && preview.age_s >= 0 && preview.age_s + elapsedS <= 3;
}

export function headingText(review) {
  if (!review) return "";
  if (review.status !== "heading_compared" || !Number.isFinite(review.turn_deg)) {
    return `지도 방향 재확인 필요 (${review.status})`;
  }
  const turn = review.turn_deg;
  return `지도 방향: ${turn === 0 ? "현재 방향 일치" : `${turn > 0 ? "왼쪽" : "오른쪽"} ${Math.abs(turn)}°`}`
    + ` · 차로 ${review.edge_id || "미확인"} · 지도 v${review.map_version}`
    + ` · ${review.turn_spot ? "회전 지점" : "회전 지점 아님"} · 회전 허가 아님`;
}

export function fleetAnswerText(answer) {
  if (!answer) return "";
  const decision = DECISION_LABEL[answer.decision] || answer.decision;
  const source = answer.tier === "ai" ? "AI 판단" : answer.tier === "human" ? "운영자 판단" : "Fleet 규칙";
  const receipt = answer.accepted === true ? "CORE 수락 · 복구 완료는 별도 확인"
    : answer.accepted === false ? `CORE 거절 (${answer.code || answer.message || "사유 미확인"})`
      : "CORE 처리 결과 미확인";
  return `${source} → Fleet 전송 ${decision} → ${receipt}${answer.outcome ? ` · 상태 ${OUTCOME_TEXT[answer.outcome] || answer.outcome}` : ""}`;
}

/** D-577 8: caption of the stuck's evidence picture; `elapsedS` = seconds since Fleet answered. */
export function evidenceCaption(preview, elapsedS = 0) {
  if (!preview) return "카메라 그림 없음";
  if (preview.state === "loading") return "카메라 그림 받는 중";
  if (preview.live && !previewFresh(preview, elapsedS)) return "현재 영상 만료 — 새 프레임 기다림";
  const age = Math.round((preview.age_s ?? 0) + elapsedS);
  return `${preview.live ? "현재 영상" : "사건 기록 영상"} · ${CAMERA_LABEL[preview.source] || preview.source || "카메라"} #${preview.sequence} · ${age}초 전 촬영`;
}

/** D-577 8: alerts to raise now — once when a stuck row appears, once more when it goes overdue.
 * `seen` (robot|stuck -> "new"|"overdue") is updated in place; a closed stuck is forgotten. */
export function alertsDue(seen, robots) {
  const due = [];
  const live = new Set();
  for (const robot of pendingStucks(robots)) {
    const key = `${robot.robot_id}|${robot.line_stuck.stuck_id}`;
    live.add(key);
    const kind = stuckOverdue(robot.line_stuck) ? "overdue" : "new";
    if (seen.get(key) === kind || seen.get(key) === "overdue") continue;
    seen.set(key, kind);
    due.push({ robotId: robot.robot_id, stuckId: robot.line_stuck.stuck_id, kind });
  }
  for (const key of [...seen.keys()]) if (!live.has(key)) seen.delete(key);
  return due;
}

/** Console-only alert (user 2026-10-09: no phone or messenger): a short tone and a browser notice. */
function browserAlert(text) {
  try {
    const audio = new AudioContext();
    const tone = audio.createOscillator();
    tone.connect(audio.destination);
    tone.start();
    tone.stop(audio.currentTime + 0.2);
    tone.onended = () => audio.close();
  } catch { /* no audio device: the queue row still shows */ }
  if (globalThis.Notification?.permission === "granted") new Notification("ROSY 판단 요청", { body: text });
  else if (globalThis.Notification?.permission === "default") Notification.requestPermission().catch(() => {});
}

export function confirmText(robotId, decision) {
  if (decision === "RESUME") {
    return `${robotId} 재개 — 앞이 비었는지 직접 확인했습니까? `
      + "CORE가 정지 거리 안 물체를 다시 보고 거부할 수 있습니다.";
  }
  if (decision === "BACK_AND_RETRY") {
    return `${robotId} 후진 후 재시도 — 로봇이 짧게 뒤로 물러난 뒤 다시 봅니다. 뒤가 비었습니까?`;
  }
  return "";
}

export function outcomeText(robotId, decision, result) {
  const outcome = result && result.outcome;
  return `${robotId} ${DECISION_LABEL[decision] || decision}: ${OUTCOME_TEXT[outcome] || "CORE가 받았습니다"}`;
}

/** CORE's refusal in operator Korean, with CORE's own code and message kept verbatim. */
export function refusalText(robotId, decision, err) {
  const code = err && err.code;
  const message = (err && err.message) || "";
  let why;
  if (code === "STUCK_ID_MISMATCH") why = "이미 닫혔거나 바뀐 막힘입니다 — 새 요청을 보고 다시 답하세요";
  else if (code === "STUCK_DECISION_REFUSED") {
    const reason = message.includes(": ") ? message.slice(message.lastIndexOf(": ") + 2) : "";
    why = REFUSAL_REASON[reason] || "CORE가 거부했습니다";
  } else if (code === "EMERGENCY_ACTIVE") why = "비상정지 중입니다";
  else if (code === "CALIBRATION_ACTIVE") why = "보정 세션이 로봇을 쥐고 있습니다";
  else if (code === "OPERATOR_IDENTITY_REQUIRED") why = "이름 있는 운영자 로그인이 필요합니다";
  else if (err && err.status === 403) why = "운영자 권한이 필요합니다";
  else if (code === "ROBOT_UNREACHABLE") why = "로봇에 닿지 않아 답이 전해지지 않았습니다";
  else if (code === "STUCK_DECISION_OUTCOME_UNKNOWN") {
    why = "로봇이 응답하지 않았습니다. CORE가 이미 적용했을 수 있으니 막힘 상태를 다시 확인한 뒤 답하세요";
  } else why = "답을 전하지 못했습니다";
  const verb = code === "STUCK_DECISION_OUTCOME_UNKNOWN" ? "결과 불명"
    : code === "ROBOT_UNREACHABLE" ? "전달 실패" : "거부";
  const raw = code ? `${code}: ${message}` : message;
  return `${robotId} ${DECISION_LABEL[decision] || decision} ${verb} — ${why}${raw ? ` (${raw})` : ""}`;
}

export function createLineStuckPanel({ scope, view, call, log, isOperator, namedReason = () => "",
  notify = browserAlert }) {
  watchChainStatus({ scope, call });
  // robot_id -> { stuck_id, decision } (확인 단계), { stuck_id, text, kind } (마지막 결과)
  const confirming = new Map();
  const alerted = new Map();
  // D-577 8: robot_id -> { stuck_id, state: loading|ok|none, preview, at } — one picture per stuck.
  const previews = new Map();
  const results = new Map();
  const busy = new Set();
  const signatures = new Map();
  scope.onDispose(() => {
    previews.clear();
    confirming.clear();
    busy.clear();
    signatures.clear();
  });

  async function send(robotId, stuckId, decision) {
    const life = scope.capture();
    life.check();
    if (busy.has(robotId)) return;   // one answer in flight per robot (no double submit)
    confirming.delete(robotId);
    busy.add(robotId);
    render();
    try {
      const result = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/line-stuck/decision`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stuck_id: stuckId, decision }),
      });
      life.check();
      const text = outcomeText(robotId, decision, result.result);
      results.set(robotId, { stuck_id: stuckId, text, kind: "good" });
      log(text, "good");
    } catch (err) {
      if (err.name === "AbortError") return;
      const text = refusalText(robotId, decision, err);
      results.set(robotId, { stuck_id: stuckId, text, kind: "bad" });
      log(text, "bad");
    } finally {
      if (life.current()) {
        busy.delete(robotId);
        render();
      }
    }
  }

  function choose(robotId, stuckId, decision) {
    // D-438: a human decision claims the stuck so the resolver stays silent. Fire and forget.
    call(`/api/fleet/robots/${encodeURIComponent(robotId)}/line-stuck/claim`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stuck_id: stuckId }),
    }).catch(() => {});
    if (needsConfirm(decision)) {
      confirming.set(robotId, { stuck_id: stuckId, decision });
      render("confirm-yes", robotId);
      return;
    }
    send(robotId, stuckId, decision);
  }

  function cancelConfirm(robotId, decision) {
    confirming.delete(robotId);
    render(`decision-${decision}`, robotId);
  }

  async function loadPreview(robotId, stuckId) {
    const pending = { stuck_id: stuckId, state: "loading", at: Date.now() };
    previews.set(robotId, pending);
    let entry;
    try {
      const preview = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/line-stuck/evidence`
        + `?stuck_id=${encodeURIComponent(stuckId)}&live=true`);
      entry = { stuck_id: stuckId, state: "ok", preview, at: pending.at };
    } catch (err) {
      if (err.name === "AbortError") return;
      entry = { stuck_id: stuckId, state: "none", at: Date.now() };
    }
    if (previews.get(robotId) !== pending) return;   // the stuck closed or changed while fetching
    previews.set(robotId, entry);
    render();
  }

  function evidence(robotId) {
    const entry = previews.get(robotId);
    const figure = document.createElement("figure");
    figure.className = "stuck-evidence";
    const caption = document.createElement("figcaption");
    if (entry?.state === "ok" && previewFresh(entry.preview, (Date.now() - entry.at) / 1000)) {
      const img = document.createElement("img");
      img.src = `data:${entry.preview.media_type};base64,${entry.preview.jpeg_base64}`;
      img.alt = `${robotId} 현재 앞 카메라 영상`;
      figure.append(img);
    }
    caption.textContent = evidenceCaption(entry?.state === "ok" ? entry.preview
      : entry?.state === "loading" ? { state: "loading" } : null, entry?.at ? (Date.now() - entry.at) / 1000 : 0);
    figure.append(caption);
    return figure;
  }

  function item(robotId, stuck) {
    const li = document.createElement("div");
    li.className = "stuck-item";
    li.dataset.robotId = robotId;
    li.dataset.stuckId = stuck.stuck_id;
    if (stuck.robot_online === false) li.classList.add("offline");

    // D-540 3: the queue row above already names the robot.
    const head = document.createElement("div");
    head.className = "stuck-head";
    const cause = document.createElement("ui-tag");
    cause.setAttribute("status", "crit");
    cause.textContent = CAUSE_LABEL[stuck.cause] || stuck.cause || "원인 미상";
    cause.title = stuck.cause || "";
    const phase = document.createElement("ui-tag");
    phase.setAttribute("status", stuck.phase === "BACKING" || stuck.phase === "SETTLING" ? "warn" : "neutral");
    phase.textContent = PHASE_LABEL[stuck.phase] || stuck.phase || "—";
    phase.title = stuck.phase || "";
    head.append(cause, phase);
    if (stuck.robot_online === false) {
      const offline = document.createElement("ui-tag");
      offline.setAttribute("status", "warn");
      offline.textContent = "연결 끊김 · 마지막 값";
      head.append(offline);
    }

    const facts = document.createElement("dl");
    facts.className = "stuck-facts";
    for (const [key, label, value, tone] of stuckFacts(stuck)) {
      const cell = document.createElement("div");
      cell.dataset.fact = key;
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      if (tone) dd.classList.add(tone);
      cell.append(dt, dd);
      facts.append(cell);
    }

    // render() already dropped a confirm step whose stuck id is no longer the live one.
    const pending = confirming.get(robotId);
    const specs = decisionButtons(stuck, { operator: isOperator(), namedReason: namedReason(), busy: busy.has(robotId) });
    const actions = document.createElement("div");
    actions.className = "stuck-actions";
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", `${robotId} 판단`);
    for (const spec of specs) {
      const node = quietButton(spec.confirm ? `${spec.label}…` : spec.label);
      node.dataset.decision = spec.decision;
      node.dataset.focusKey = `decision-${spec.decision}`;
      node.setAttribute("aria-label", `${robotId} ${spec.label} (${spec.decision})`);
      setReason(node, spec.reason);
      if (spec.confirm) {
        node.setAttribute("aria-expanded", String(pending?.decision === spec.decision));
      }
      node.addEventListener("click", scope.guard(() => choose(robotId, stuck.stuck_id, spec.decision)));
      actions.append(node);
    }
    li.append(head, facts);
    const boundary = stuck.inquiry?.lane_boundary;
    const boundaryText = boundary ? `차선 경계: ${boundary.state} · 변화 #${boundary.revision} · 같은 경계에서는 AI 재문의 대기` : "";
    for (const text of [headingText(stuck.heading_review), boundaryText, fleetAnswerText(stuck.fleet_answer)].filter(Boolean)) {
      const line = document.createElement("p");
      line.className = "stuck-resolver";
      line.textContent = text;
      li.append(line);
    }
    const note = resolverText(stuck.resolver);
    if (note) {
      const line = document.createElement("p");
      line.className = "stuck-resolver";
      line.textContent = note;
      li.append(line);
    }
    for (const text of aiLines(stuck)) {
      const line = document.createElement("p");
      line.className = "stuck-resolver";
      line.textContent = text;
      li.append(line);
    }
    li.append(actions, evidence(robotId));

    if (pending) {
      const box = document.createElement("div");
      box.className = "stuck-confirm";
      box.setAttribute("role", "group");
      const text = document.createElement("p");
      text.id = `stuck-confirm-${robotId}`;
      text.textContent = confirmText(robotId, pending.decision);
      box.setAttribute("aria-labelledby", text.id);
      const yes = primaryButton(`${DECISION_LABEL[pending.decision]} 보내기`);
      yes.dataset.focusKey = "confirm-yes";
      // 보내기는 그 답 버튼과 같은 사유로 막힌다(권한·연결·전송 중·로컬 복구 꺼짐).
      setReason(yes, specs.find((spec) => spec.decision === pending.decision)?.reason || "");
      yes.addEventListener("click", scope.guard(() => send(robotId, stuck.stuck_id, pending.decision)));
      const no = quietButton("취소");
      no.dataset.focusKey = "confirm-no";
      no.addEventListener("click", scope.guard(() => cancelConfirm(robotId, pending.decision)));
      box.addEventListener("keydown", scope.guard((event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          cancelConfirm(robotId, pending.decision);
        }
      }));
      const row = document.createElement("div");
      row.className = "stuck-confirm-actions";
      row.append(yes, no);
      box.append(text, row);
      li.append(box);
    }

    const last = results.get(robotId);
    if (last && last.stuck_id === stuck.stuck_id) {
      const result = document.createElement("p");
      result.className = "stuck-result";
      result.dataset.kind = last.kind;
      result.setAttribute("role", last.kind === "bad" ? "alert" : "status");
      result.textContent = last.text;
      li.append(result);
    }
    return li;
  }

  // D-540 3: each answer lives in its queue row's slot (roster.fillQueues makes the slot).
  function render(focusKey = null, focusRobot = null) {
    const stucks = view.stateUnavailable ? [] : pendingStucks(view.robots);
    const live = new Map(stucks.map((robot) => [robot.robot_id, robot.line_stuck.stuck_id]));
    // A confirm step belongs to one stuck id: a closed or replaced stuck drops it.
    for (const [key, entry] of [...confirming]) {
      if (live.get(key) !== entry.stuck_id) confirming.delete(key);
    }
    for (const key of [...signatures.keys()]) if (!live.has(key)) signatures.delete(key);
    for (const key of [...previews.keys()]) if (live.get(key) !== previews.get(key).stuck_id) previews.delete(key);
    for (const due of alertsDue(alerted, stucks)) {
      notify(due.kind === "overdue" ? `${due.robotId}: 30초 넘게 답 없음 — 로봇은 멈춰 기다립니다`
        : `${due.robotId}: 판단 요청 — 차선 추종이 막혔습니다`);
    }

    const active = document.activeElement;
    const activeItem = active?.closest?.(".stuck-item");
    const keepFocus = focusKey
      ? { robot: focusRobot, key: focusKey }
      : activeItem ? { robot: activeItem.dataset.robotId, key: active.dataset?.focusKey } : null;

    for (const robot of stucks) {
      const slot = document.querySelector(`[data-decision-slot="${CSS.escape(`${robot.robot_id}|stuck`)}"]`);
      if (!slot) continue;
      const stuck = robot.line_stuck;
      // 시계처럼 매 폴링 바뀌는 값은 서명에서 뺀다.
      const { held_s: _held, ask_remaining_s: _ask, observed_age_s: _age, ...stable } = stuck;
      const preview = previews.get(robot.robot_id);
      if (!preview || (preview.state !== "loading" && Date.now() - preview.at >= 2000)) {
        loadPreview(robot.robot_id, stuck.stuck_id);
      }
      const signature = JSON.stringify([stable, confirming.get(robot.robot_id) || null,
        previews.get(robot.robot_id)?.state || null, previews.get(robot.robot_id)?.at || null,
        results.get(robot.robot_id) || null, busy.has(robot.robot_id), isOperator(), namedReason()]);
      const node = slot.firstElementChild;
      if (!node || signatures.get(robot.robot_id) !== signature) {
        slot.replaceChildren(item(robot.robot_id, stuck));
        signatures.set(robot.robot_id, signature);
      } else {
        // 멈춘 시간만 바뀌었다 — 항목을 다시 만들지 않는다(포커스·확인 단계 유지).
        const held = node.querySelector('[data-fact="held"] dd');
        if (held) held.textContent = stuckFacts(stuck).find(([key]) => key === "held")[2];
        const entry = previews.get(robot.robot_id);
        const caption = node.querySelector(".stuck-evidence figcaption");
        if (caption && entry?.state === "ok") caption.textContent = evidenceCaption(entry.preview, (Date.now() - entry.at) / 1000);
        if (entry?.state === "ok" && !previewFresh(entry.preview, (Date.now() - entry.at) / 1000)) {
          node.querySelector(".stuck-evidence img")?.remove();
        }
      }
    }

    if (keepFocus?.robot && keepFocus.key) {
      const owner = document.querySelector(`.stuck-item[data-robot-id="${CSS.escape(keepFocus.robot)}"]`);
      // The focused control may be gone (confirm step dropped): land on the item's first answer.
      const target = owner?.querySelector(`[data-focus-key="${keepFocus.key}"]`)
        || owner?.querySelector("ui-button[data-decision]");
      if (target && document.activeElement !== target) target.focus({ preventScroll: true });
    }
  }

  return { render };
}
