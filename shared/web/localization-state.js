/**
 * C19 localization state adapter (pure, no DOM or DOM-module imports).
 *
 * Exports:
 *   LOCALIZED_FRESH_S = 30
 *   QUEUE_MAX_S = 120
 *   POSE_REFUSALS            Set of refusal codes that keep a queued start waiting
 *   LOC_TEXT                 Base Korean labels per localization UI state
 *   REFUSAL_TEXT             Korean messages per server/client refusal code
 *   refusalText(code)        -> Korean message (never silent for unknown codes)
 *   queueText(left_s)        -> "출발 대기 · 위치 확정되면 출발 (n초 남음)"
 *   queueStep(queue, input)  -> {action: "wait"|"fire"|"end", text}; input {now_s, code, localized, age_s, stopped}; fires only on localized with age_s <= 30; marks queue.done
 *   confirmRequest(shown, current, candidateId) -> {ok:true, body:{candidate_id}} | {ok:false, code:"CANDIDATE_STALE", text}
 *   revokeText(reason)       -> estop / mission_<known> / generic closed text (a new press is the only way back, never automatic)
 *   localizationState(view)  -> {state, text, tag, evidence ("요청 {by} · n초 남음"), tag_text (short, for the nowrap statusTag), freshness, severity, reason, actions[], candidates[]}
 */

export const LOCALIZED_FRESH_S = 30;
export const QUEUE_MAX_S = 120;

export const POSE_REFUSALS = new Set(["TRIP_POSE_UNTRUSTED", "SITE_POSE_UNKNOWN"]);

export const LOC_TEXT = Object.freeze({
  unknown: "위치 모름",
  searching: "위치 모름 · 자동 찾는 중",
  rotating: "회전하며 찾는 중",
  candidates: "후보 확인 필요",
  confirming: "위치 확인 중",
  localized: "확정",
  suspect: "위치 의심 · 다시 확인 필요",
  failed: "위치 찾기 실패",
  blocked: "자동 찾기 막힘",
});

export const REFUSAL_TEXT = Object.freeze({
  UNKNOWN_ROBOT: "등록되지 않은 로봇입니다",
  ROBOT_OFFLINE: "로봇 상태를 읽을 수 없습니다 · 연결을 확인하세요",
  RELOCALIZE_TRIP_ACTIVE: "운행·편대 중에는 위치 다시 찾기를 할 수 없습니다 · 먼저 정지하세요",
  ALREADY_LOCALIZED: "이미 위치가 확정되어 있습니다",
  LOCALIZATION_DISABLED: "이 Fleet에는 위치 서비스가 없습니다",
  NO_CANDIDATES: "로봇이 보고한 후보가 없습니다",
  CANDIDATE_NOT_REPORTED: "로봇이 보고한 후보만 확정할 수 있습니다",
  STALE_REQUEST: "요청이 만료되었습니다 · 후보를 다시 확인하세요",
  CANDIDATE_STALE: "후보가 바뀌었습니다 · 다시 고르세요",
  TRIP_POSE_UNTRUSTED: "위치를 신뢰할 수 없어 출발할 수 없습니다",
  SITE_POSE_UNKNOWN: "측정된 사이트 위치가 없어 출발할 수 없습니다",
  operator_required: "위치 다시 찾기를 눌러야 회전합니다",
  anchor_blocked: "운영자가 자동 찾기를 막아 두었습니다 · 해제가 필요합니다",
});

// Reasons the server reports as codes (auto-locate anchor refusals, ladder results); unknown codes stay visible.
export const REASON_TEXT = Object.freeze({
  CAUTION_ACTIVE: "주의 상태가 켜져 있습니다",
  lamp: "표지등을 확인할 수 없습니다",
  stopped: "정지됨",
  timeout: "시간 초과",
  checking: "로봇이 확인 중입니다",
});
const reasonText = code => REASON_TEXT[code] ?? REASON_TEXT[String(code).toLowerCase()] ?? `알 수 없는 사유 (${code})`;

// last_operator_request.revoked.reason: "estop" or "mission_<CORE reason>". One press gives one motion; a new press is the only way back.
export const REVOKE_TEXT = Object.freeze({
  estop: "비상정지로 회전 권한이 닫혔습니다",
  mission: "한 번 회전이 끝났습니다 · 다시 누르면 다시 찾습니다",
  other: "회전 권한이 닫혔습니다 · 다시 누르면 다시 찾습니다",
});
const MISSION_SUFFIXES = new Set(["cancelled", "done", "obstacle", "timeout", "stopped", "aborted", "rejected"]);
export function revokeText(reason) {
  const r = nonEmptyText(reason);
  if (r === "estop") return REVOKE_TEXT.estop;
  if (r.startsWith("mission_") && MISSION_SUFFIXES.has(r.slice(8))) return REVOKE_TEXT.mission;
  return REVOKE_TEXT.other;
}

const MIRROR_TOLERANCE_RAD = 0.35;

const isRecord = value => value !== null && typeof value === "object" && !Array.isArray(value);
const finiteOrNull = value => (typeof value === "number" && Number.isFinite(value) ? value : null);
const nonEmptyText = value => (typeof value === "string" && value.trim() ? value.trim() : "");

export function refusalText(code) {
  const key = nonEmptyText(code);
  if (!key) return "알 수 없는 사유 (없음)";
  return REFUSAL_TEXT[key] ?? `알 수 없는 사유 (${key})`;
}

export function queueText(left_s) {
  const n = finiteOrNull(left_s);
  const secs = n === null ? 0 : Math.max(0, Math.round(n));
  return `출발 대기 · 위치 확정되면 출발 (${secs}초 남음)`;
}

// queueStep marks the queue `done` when it answers fire or end, so a repeated poll can never fire twice (round 3).
// Order: stop, finished queue, non-pose refusal, 120 s bound, then fire only on a FRESH localized pose.
// A refusal code is read before `localized`: a fired start that CORE refused must not fire again.
export function queueStep(queue, input) {
  const {now_s, code, localized, age_s, stopped} = isRecord(input) ? input : {};
  const finish = (text) => { if (isRecord(queue)) queue.done = true; return {action: "end", text}; };
  if (stopped) return finish("정지로 출발 대기를 끝냈습니다");
  if (!isRecord(queue) || queue.done === true || finiteOrNull(queue.since_s) === null) return {action: "end", text: ""};
  const refusal = nonEmptyText(code);
  if (refusal && !POSE_REFUSALS.has(refusal)) return finish(refusalText(refusal));
  const now = finiteOrNull(now_s);
  if (now === null || Math.max(0, now - queue.since_s) >= QUEUE_MAX_S) return finish("시간 초과로 출발 대기를 끝냈습니다");
  const age = finiteOrNull(age_s);
  if (localized === true && age !== null && age >= 0 && age <= LOCALIZED_FRESH_S) {
    queue.done = true;
    return {action: "fire", text: ""};
  }
  return {action: "wait", text: queueText(QUEUE_MAX_S - (now - queue.since_s))};
}

function staleRefusal() {
  return {ok: false, code: "CANDIDATE_STALE", text: refusalText("CANDIDATE_STALE")};
}

export function confirmRequest(shown, current, candidateId) {
  if (!isRecord(shown) || !isRecord(current)) return staleRefusal();
  if (!Array.isArray(shown.candidates) || !Array.isArray(current.candidates)) return staleRefusal();
  if (shown.request_id == null || current.request_id == null || shown.request_id !== current.request_id) return staleRefusal();
  if (!Number.isInteger(candidateId) || candidateId < 0) return staleRefusal();
  if (candidateId >= shown.candidates.length || candidateId >= current.candidates.length) return staleRefusal();
  const a = shown.candidates[candidateId];
  const b = current.candidates[candidateId];
  if (!isRecord(a) || !isRecord(b)) return staleRefusal();
  if (a.x !== b.x || a.y !== b.y || a.yaw !== b.yaw) return staleRefusal();
  return {ok: true, body: {candidate_id: candidateId}};
}

function selectCandidates(rawList) {
  if (!Array.isArray(rawList) || rawList.length === 0) return [];
  const valid = [];
  for (let i = 0; i < rawList.length; i++) {
    const item = rawList[i];
    if (!isRecord(item)) continue;
    const x = finiteOrNull(item.x), y = finiteOrNull(item.y), yaw = finiteOrNull(item.yaw), fit = finiteOrNull(item.scan_fit);
    if (x === null || y === null || yaw === null || fit === null) continue;
    valid.push({id: i, x, y, yaw, scan_fit: fit});
  }
  if (valid.length === 0) return [];
  let top = valid[0];
  for (const item of valid) if (item.scan_fit > top.scan_fit) top = item;
  let mirror = null;
  for (const item of valid) {
    if (item.id === top.id) continue;
    const dyaw = Math.abs(Math.atan2(Math.sin(item.yaw - top.yaw), Math.cos(item.yaw - top.yaw)));
    if (Math.abs(dyaw - Math.PI) < MIRROR_TOLERANCE_RAD && (!mirror || item.scan_fit > mirror.scan_fit)) mirror = item;
  }
  const toEntry = (item, role) => {
    const confidence = Math.round(item.scan_fit * 100);
    return {
      id: item.id, x: item.x, y: item.y, yaw: item.yaw, scan_fit: item.scan_fit, confidence, role,
      label: role === "top" ? `후보 1 · ${confidence}%` : `반대 후보 · ${confidence}%`,
      drawn_as: "candidate",
    };
  };
  return mirror ? [toEntry(top, "top"), toEntry(mirror, "mirror")] : [toEntry(top, "top")];
}

function resolveState(v) {
  const loc = isRecord(v.localization) ? v.localization : null;
  const locState = nonEmptyText(loc?.state).toUpperCase();
  const locReason = nonEmptyText(loc?.reason);
  const report = isRecord(v.report) ? v.report : null;
  const reportList = Array.isArray(report?.candidates) ? report.candidates : [];
  const motion = isRecord(v.motion) ? v.motion : null;
  const reqBy = nonEmptyText(motion?.last_operator_request?.by);  // absent once the gate closed
  const sessionLeft = finiteOrNull(v.session_left_s);
  const age = finiteOrNull(v.age_s);
  const freshness = (locState === "LOCALIZED" || locState === "SUSPECT") && age !== null && age >= 0
    ? (age <= LOCALIZED_FRESH_S ? "fresh" : "delayed") : "unknown";

  if (nonEmptyText(v.refused) === "LOCALIZATION_DISABLED") {  // round 2: a stale pose or report must not hide "no service"
    return {state: "blocked", tag: "locked", text: `${LOC_TEXT.blocked} · ${REFUSAL_TEXT.LOCALIZATION_DISABLED}`, freshness: "unknown", severity: "neutral", reportList: [], locReason};
  }
  if (v.confirming === true || locReason === "checking") {
    return {state: "confirming", tag: "progress", text: LOC_TEXT.confirming, freshness: "unknown", severity: "neutral", reportList, locReason};
  }
  if (v.stopped === true && locState !== "LOCALIZED") {  // round 2: a stop must not read as "still rotating/searching"
    return {state: "failed", tag: "caution", text: `${LOC_TEXT.failed} · ${REASON_TEXT.stopped}`, freshness: "unknown", severity: "warn", reportList, locReason: "stopped"};
  }
  if (motion?.allowed === true) {
    const text = reqBy ? `${LOC_TEXT.rotating} · 요청 ${reqBy}` : LOC_TEXT.rotating;
    return {state: "rotating", tag: "progress", text, freshness: "unknown", severity: "neutral", reportList, locReason};
  }
  if (locState === "CANDIDATES" || (locState !== "LOCALIZED" && locState !== "SUSPECT" && reportList.length > 0)) {
    return {state: "candidates", tag: "caution", text: `후보 ${reportList.length}개 · 확인 필요`, freshness: "unknown", severity: "warn", reportList, locReason};
  }
  if (sessionLeft !== null && sessionLeft > 0 && locState !== "LOCALIZED" && locState !== "SUSPECT") {
    return {state: "searching", tag: "progress", text: `${LOC_TEXT.searching} · 남은 ${Math.max(1, Math.round(sessionLeft))}초`, freshness: "unknown", severity: "neutral", reportList, locReason};
  }
  if (locState === "SUSPECT") {
    return {state: "suspect", tag: "caution", text: LOC_TEXT.suspect, freshness, severity: "warn", reportList, locReason};
  }
  if (locState === "LOCALIZED") {
    if (age !== null && age >= 0) {
      const secs = Math.round(age);
      const text = freshness === "fresh" ? `확정 · ${secs}초 전` : `확정 · ${secs}초 전 (오래됨)`;
      return {state: "localized", tag: freshness, text, freshness, severity: "neutral", reportList, locReason};
    }
    return {state: "localized", tag: "delayed", text: "확정 · 시각 미확인", freshness: "unknown", severity: "neutral", reportList, locReason};
  }
  const missionResult = nonEmptyText(v.mission_result);
  if ((locReason && locReason !== "checking") || (missionResult && missionResult !== "operator_required" && missionResult !== "succeeded" && missionResult !== "ok")) {
    const detail = locReason || missionResult;
    const text = detail ? `${LOC_TEXT.failed} · ${reasonText(detail)}` : LOC_TEXT.failed;
    return {state: "failed", tag: "caution", text, freshness: "unknown", severity: "warn", reportList, locReason};
  }
  if (v.anchor_blocked === true) {
    const blockedReason = nonEmptyText(v.anchor_refused_reason);
    const text = blockedReason ? `${LOC_TEXT.blocked} · ${reasonText(blockedReason)}` : LOC_TEXT.blocked;
    return {state: "blocked", tag: "locked", text, freshness: "unknown", severity: "neutral", reportList, locReason};
  }
  return {state: "unknown", tag: "unknown", text: LOC_TEXT.unknown, freshness: "unknown", severity: "neutral", reportList, locReason};
}

function buildActions(v, state, freshness, candidates) {
  const actions = [];
  const isOperator = v.operator === true;
  const offline = v.online === false;
  const tripActive = v.trip_active === true;
  const moving = v.stopped !== true && (state === "rotating" || state === "confirming" || v.motion?.allowed === true);
  // Why a motion/write action is disabled right now (the server refuses the same cases); null when it may run.
  const blockReason = tripActive ? refusalText("RELOCALIZE_TRIP_ACTIVE") : offline ? refusalText("ROBOT_OFFLINE") : null;
  const operatorAction = (id, label, extra = {}) => {
    const row = {id, label, ...extra};
    if (blockReason) { row.disabled = true; row.reason = blockReason; }
    actions.push(row);
  };

  if (state === "blocked" && nonEmptyText(v.refused) === "LOCALIZATION_DISABLED") return actions;
  if (moving) {  // round 3: while wheels may turn or the robot's 3 s check runs, nothing may start more motion
    if (state === "rotating") actions.push({id: "stop", label: "정지"});
    if (isRecord(v.queue)) actions.push({id: "cancel-queue", label: "취소"});
    return actions;
  }
  // pin, auto-locate and relocalize are operator writes on main (viewer 403; a trip refuses the pin and relocalize 409)
  if (isOperator && state !== "localized") {
    operatorAction("pin", "위치 찍기");
    if (state !== "searching") {
      if (v.anchor_blocked === true) actions.push({id: "auto-locate", label: "자동 위치 찾기", disabled: true, reason: refusalText("anchor_blocked")});
      else operatorAction("auto-locate", "자동 위치 찾기");
    }
    // The server refuses ALREADY_LOCALIZED for any LOCALIZED robot, aged or not: never offer that press.
    operatorAction("relocalize", "위치 다시 찾기");
  }
  if (isOperator && state === "candidates") {
    for (const c of candidates) operatorAction("confirm", "이 위치가 맞음", {candidate_id: c.id});
  }
  if (isOperator && v.anchor_blocked === true) actions.push({id: "lift-block", label: "막힘 해제"});
  if (isRecord(v.queue)) actions.push({id: "cancel-queue", label: "취소"});
  return actions;
}

// The statusTag is nowrap: its word stays short; the full sentence is `text` and the detail is `reason`.
const TAG_TEXT = {unknown: "위치 모름", searching: "찾는 중", rotating: "회전 중", confirming: "확인 중",
  suspect: "위치 의심", failed: "찾기 실패", blocked: "찾기 막힘"};
function tagText(state, text, candidateCount) {
  if (state === "candidates") return `후보 ${candidateCount}개`;
  if (state === "localized") return text.replace(" (오래됨)", "");
  return TAG_TEXT[state] ?? text;
}

export function localizationState(view) {
  const v = isRecord(view) ? view : {};
  const resolved = resolveState(v);
  const {state, tag, text, freshness, severity, reportList, locReason} = resolved;
  const candidates = (state === "candidates" || state === "confirming") ? selectCandidates(reportList) : [];
  const actions = buildActions(v, state, freshness, candidates);

  const lor = isRecord(v.motion?.last_operator_request) ? v.motion.last_operator_request : null;
  const revoked = isRecord(lor?.revoked) ? lor.revoked : null;
  // The gate's own view names the requester only while open; once closed the caller passes the requester it remembered.
  const by = nonEmptyText(lor?.by) || nonEmptyText(v.last_requester);
  const left = finiteOrNull(lor?.expires_in_s);
  let evidence = "";
  if (revoked) {
    const at = finiteOrNull(revoked.at), wall = finiteOrNull(v.wall_now_s);
    const ago = at !== null && wall !== null && wall >= at ? ` · ${Math.round(wall - at)}초 전` : "";
    evidence = `${by ? `요청 ${by} · ` : ""}회전 권한 닫힘${ago}`;
  } else if (by) evidence = `요청 ${by}${left !== null && left > 0 ? ` · ${Math.round(left)}초 남음` : ""}`;
  let reason = "";
  const refused = nonEmptyText(v.refused);
  if (refused) reason = refusalText(refused);
  else if (isRecord(v.queue) && finiteOrNull(v.queue.left_s) !== null) reason = queueText(v.queue.left_s);
  else if (nonEmptyText(v.mission_result) === "operator_required") reason = refusalText("operator_required");
  else if (revoked && state !== "localized") reason = revokeText(revoked.reason);
  else if (state === "blocked") reason = nonEmptyText(v.anchor_refused_reason) ? reasonText(nonEmptyText(v.anchor_refused_reason)) : refusalText("anchor_blocked");
  else if (state === "failed" && locReason) reason = reasonText(locReason);

  return {state, text, tag, tag_text: tagText(state, text, reportList.length), evidence, freshness, severity, reason, actions, candidates};
}
