import {test} from "node:test";
import assert from "node:assert/strict";
import {
  LOC_TEXT,
  REFUSAL_TEXT,
  LOCALIZED_FRESH_S,
  QUEUE_MAX_S,
  POSE_REFUSALS,
  refusalText,
  queueText,
  queueStep,
  revokeText,
  confirmRequest,
  localizationState,
} from "../localization-state.js";

test("all 8 UI states (+ suspect) map to expected tag, text, freshness, severity, and never danger", () => {
  const cases = [
    ["unknown", {}, "unknown", "unknown", "neutral"],
    ["searching", {session_left_s: 18}, "progress", "unknown", "neutral"],
    ["rotating", {motion: {allowed: true, last_operator_request: {by: "alice"}}}, "progress", "unknown", "neutral"],
    ["candidates", {localization: {state: "CANDIDATES"}, report: {request_id: "r1", candidates: [{x: 1, y: 2, yaw: 0, scan_fit: 0.84}]}}, "caution", "unknown", "warn"],
    ["confirming", {confirming: true}, "progress", "unknown", "neutral"],
    ["confirming", {localization: {state: "CANDIDATES", reason: "checking"}}, "progress", "unknown", "neutral"],
    ["localized", {localization: {state: "LOCALIZED"}, age_s: 5}, "fresh", "fresh", "neutral"],
    ["localized", {localization: {state: "LOCALIZED"}, age_s: 45}, "delayed", "delayed", "neutral"],
    ["suspect", {localization: {state: "SUSPECT"}, age_s: 10}, "caution", "fresh", "warn"],
    ["blocked", {anchor_blocked: true, anchor_refused_reason: "CAUTION_ACTIVE"}, "locked", "unknown", "neutral"],
    ["failed", {localization: {state: "UNKNOWN", reason: "스캔 불일치"}}, "caution", "unknown", "warn"],
  ];
  for (const [expectedState, view, expectedTag, expectedFreshness, expectedSeverity] of cases) {
    const out = localizationState(view);
    assert.equal(out.state, expectedState);
    assert.equal(out.tag, expectedTag);
    assert.notEqual(out.tag, "danger");
    assert.equal(out.freshness, expectedFreshness);
    assert.equal(out.severity, expectedSeverity);
    assert.ok(out.text.length > 0);
  }
  assert.equal(LOCALIZED_FRESH_S, 30);
  assert.equal(QUEUE_MAX_S, 120);
  assert.ok(LOC_TEXT.unknown && LOC_TEXT.localized);
  assert.match(localizationState({motion: {allowed: true, last_operator_request: {by: "alice"}}}).text, /요청 alice/);
  assert.match(localizationState({session_left_s: 12}).text, /남은 12초/);
  assert.match(localizationState({localization: {state: "LOCALIZED"}, age_s: 45}).text, /오래됨/);
  const opReq = localizationState({mission_result: "operator_required"});
  assert.equal(opReq.state, "unknown");
  assert.equal(opReq.reason, REFUSAL_TEXT.operator_required);
});

test("priority order: confirming > rotating > candidates > searching > localized(+suspect) > failed > blocked > unknown", () => {
  const full = {
    confirming: true,
    motion: {allowed: true},
    localization: {state: "LOCALIZED", reason: "scan_timeout"},
    report: {request_id: "r1", candidates: [{x: 0, y: 0, yaw: 0, scan_fit: 0.9}]},
    session_left_s: 20,
    anchor_blocked: true,
    age_s: 5,
  };
  assert.equal(localizationState(full).state, "confirming");
  assert.equal(localizationState({...full, confirming: false}).state, "rotating");
  assert.equal(localizationState({
    ...full, confirming: false, motion: {allowed: false}, localization: {state: "CANDIDATES"},
  }).state, "candidates");
  assert.equal(localizationState({
    ...full, confirming: false, motion: {allowed: false}, localization: {state: "UNKNOWN"}, report: null,
  }).state, "searching");
  assert.equal(localizationState({
    ...full, confirming: false, motion: {allowed: false}, session_left_s: 0,
  }).state, "localized");
  assert.equal(localizationState({
    localization: {state: "SUSPECT"}, anchor_blocked: true, age_s: 5,
  }).state, "suspect");
  assert.equal(localizationState({
    localization: {state: "UNKNOWN"}, anchor_blocked: true,
  }).state, "blocked");
  // round 2: a failure or stop of an operator attempt is not hidden by a standing block
  assert.equal(localizationState({
    localization: {state: "UNKNOWN", reason: "scan_timeout"}, anchor_blocked: true,
  }).state, "failed");
  assert.equal(localizationState({
    localization: {state: "UNKNOWN", reason: "scan_timeout"},
  }).state, "failed");
  assert.equal(localizationState({}).state, "unknown");
});

test("freshness and severity remain separate fields", () => {
  const aged = localizationState({localization: {state: "LOCALIZED"}, age_s: 31});
  assert.equal(aged.freshness, "delayed");
  assert.equal(aged.severity, "neutral");

  const suspectFresh = localizationState({localization: {state: "SUSPECT"}, age_s: 3});
  assert.equal(suspectFresh.freshness, "fresh");
  assert.equal(suspectFresh.severity, "warn");
});

test("refusalText returns Korean text for every refusal code and never silent for unknown", () => {
  const codes = [
    "UNKNOWN_ROBOT", "ROBOT_OFFLINE", "RELOCALIZE_TRIP_ACTIVE", "ALREADY_LOCALIZED",
    "LOCALIZATION_DISABLED", "NO_CANDIDATES", "CANDIDATE_NOT_REPORTED", "STALE_REQUEST",
    "CANDIDATE_STALE", "TRIP_POSE_UNTRUSTED", "SITE_POSE_UNKNOWN", "operator_required", "anchor_blocked",
  ];
  for (const code of codes) {
    assert.ok(REFUSAL_TEXT[code], `missing REFUSAL_TEXT.${code}`);
    assert.equal(refusalText(code), REFUSAL_TEXT[code]);
  }
  assert.equal(refusalText("NEW_SERVER_CODE"), "알 수 없는 사유 (NEW_SERVER_CODE)");
  assert.equal(refusalText(""), "알 수 없는 사유 (없음)");
});

test("queueStep waits on pose refusals, fires once, and ends on non-pose refusal, stop, or timeout", () => {
  assert.deepEqual([...POSE_REFUSALS].sort(), ["SITE_POSE_UNKNOWN", "TRIP_POSE_UNTRUSTED"]);
  assert.equal(queueText(90), "출발 대기 · 위치 확정되면 출발 (90초 남음)");

  let queue = {since_s: 100};
  const wait1 = queueStep(queue, {now_s: 110, code: "TRIP_POSE_UNTRUSTED", localized: false, stopped: false});
  assert.equal(wait1.action, "wait");
  assert.equal(wait1.text, "출발 대기 · 위치 확정되면 출발 (110초 남음)");

  const wait2 = queueStep(queue, {now_s: 130, code: "SITE_POSE_UNKNOWN", localized: false, stopped: false});
  assert.equal(wait2.action, "wait");
  assert.equal(wait2.text, "출발 대기 · 위치 확정되면 출발 (90초 남음)");

  const fire = queueStep(queue, {now_s: 140, localized: true, age_s: 3, stopped: false});
  assert.equal(fire.action, "fire");
  assert.equal(queue.done, true);
  assert.equal(queueStep(queue, {now_s: 141, localized: true, age_s: 3}).action, "end");  // the same queue never fires twice
  queue = null;
  assert.equal(queueStep(queue, {now_s: 141, localized: true, age_s: 3}).action, "end");

  const nonPose = queueStep({since_s: 100}, {now_s: 110, code: "ROBOT_OFFLINE", localized: false});
  assert.equal(nonPose.action, "end");
  assert.equal(nonPose.text, REFUSAL_TEXT.ROBOT_OFFLINE);

  const stopped = queueStep({since_s: 100}, {now_s: 110, localized: true, age_s: 1, stopped: true});
  assert.equal(stopped.action, "end");
  assert.equal(stopped.text, "정지로 출발 대기를 끝냈습니다");

  const timedOut = queueStep({since_s: 100}, {now_s: 220, localized: false});
  assert.equal(timedOut.action, "end");
  assert.equal(timedOut.text, "시간 초과로 출발 대기를 끝냈습니다");
});

test("confirmRequest validates request_id, index range, and pose equality", () => {
  const shown = {
    request_id: "req-1",
    candidates: [
      {x: 1.0, y: 2.0, yaw: 0.5, scan_fit: 0.84},
      {x: 1.0, y: 2.0, yaw: 0.5 + Math.PI, scan_fit: 0.71},
    ],
  };
  assert.deepEqual(confirmRequest(shown, shown, 0), {ok: true, body: {candidate_id: 0}});

  const diffReq = {...shown, request_id: "req-2"};
  assert.deepEqual(confirmRequest(shown, diffReq, 0), {
    ok: false, code: "CANDIDATE_STALE", text: REFUSAL_TEXT.CANDIDATE_STALE,
  });
  assert.equal(confirmRequest(shown, shown, 2).code, "CANDIDATE_STALE");
  assert.equal(confirmRequest(shown, shown, -1).code, "CANDIDATE_STALE");
  assert.equal(confirmRequest(shown, shown, 0.5).code, "CANDIDATE_STALE");

  const moved = {
    request_id: "req-1",
    candidates: [
      {x: 1.1, y: 2.0, yaw: 0.5, scan_fit: 0.84},
      shown.candidates[1],
    ],
  };
  assert.equal(confirmRequest(shown, moved, 0).code, "CANDIDATE_STALE");
});

test("candidate top + mirror selection, viewer vs operator actions, and no candidates in localized", () => {
  const report = {
    request_id: "r-9",
    candidates: [
      {x: 0, y: 0, yaw: 0.1, scan_fit: 0.62},
      {x: 1, y: 2, yaw: 0.2, scan_fit: 0.84},
      {x: 1, y: 2, yaw: 0.2 + Math.PI - 0.1, scan_fit: 0.71},
      {x: 1, y: 2, yaw: 0.2 + Math.PI + 0.05, scan_fit: 0.55},
    ],
  };
  const opView = localizationState({
    operator: true,
    online: true,
    localization: {state: "CANDIDATES"},
    report,
  });
  assert.equal(opView.candidates.length, 2);
  assert.deepEqual(opView.candidates.map(c => [c.id, c.role, c.confidence, c.label, c.drawn_as]), [
    [1, "top", 84, "후보 1 · 84%", "candidate"],
    [2, "mirror", 71, "반대 후보 · 71%", "candidate"],
  ]);
  assert.ok(opView.actions.some(a => a.id === "relocalize" && !a.disabled));
  assert.deepEqual(
    opView.actions.filter(a => a.id === "confirm").map(a => a.candidate_id),
    [1, 2],
  );

  const viewer = localizationState({
    operator: false,
    online: true,
    localization: {state: "CANDIDATES"},
    report,
  });
  assert.equal(viewer.actions.some(a => a.id === "relocalize"), false);
  assert.equal(viewer.actions.some(a => a.id === "confirm"), false);

  const tripLocked = localizationState({
    operator: true,
    online: true,
    trip_active: true,
    localization: {state: "UNKNOWN"},
  });
  const relocTrip = tripLocked.actions.find(a => a.id === "relocalize");
  assert.equal(relocTrip.disabled, true);
  assert.equal(relocTrip.reason, REFUSAL_TEXT.RELOCALIZE_TRIP_ACTIVE);

  const localizedFresh = localizationState({
    operator: true,
    online: true,
    localization: {state: "LOCALIZED"},
    age_s: 4,
    report,
  });
  assert.equal(localizedFresh.state, "localized");
  assert.deepEqual(localizedFresh.candidates, []);
  assert.equal(localizedFresh.actions.some(a => a.id === "relocalize"), false);
  assert.equal(localizedFresh.actions.some(a => a.id === "confirm"), false);
});

test("bad input never throws and degrades to unknown", () => {
  for (const bad of [undefined, null, 0, "bad", [], {localization: "oops", report: {candidates: "no"}}]) {
    const out = localizationState(bad);
    assert.equal(out.state, "unknown");
    assert.equal(out.tag, "unknown");
  }
  assert.equal(confirmRequest(null, null, 0).code, "CANDIDATE_STALE");
  assert.equal(queueStep(null, null).action, "end");
});

test("aged localized offers no relocalize; stop and anchor reasons are Korean", () => {
  const aged = localizationState({operator: true, localization: {state: "LOCALIZED"}, age_s: 90});
  assert.equal(aged.tag, "delayed");
  assert.equal(aged.actions.some(a => a.id === "relocalize"), false);
  const stopped = localizationState({operator: true, stopped: true});
  assert.equal(stopped.state, "failed");
  assert.match(stopped.text, /정지됨/);
  assert.ok(stopped.actions.some(a => a.id === "relocalize" && !a.disabled));
  const blocked = localizationState({anchor_blocked: true, anchor_refused_reason: "CAUTION_ACTIVE"});
  assert.match(blocked.text, /주의 상태/);
  assert.doesNotMatch(blocked.text, /CAUTION_ACTIVE/);
});

test("tag_text stays short for the nowrap tag while text keeps the sentence", () => {
  const blocked = localizationState({anchor_blocked: true, anchor_refused_reason: "CAUTION_ACTIVE"});
  assert.equal(blocked.tag_text, "찾기 막힘");
  assert.ok(blocked.text.length > blocked.tag_text.length);
  const aged = localizationState({localization: {state: "LOCALIZED"}, age_s: 90});
  assert.equal(aged.tag_text, "확정 · 90초 전");
  for (const view of [{}, {session_left_s: 5}, {confirming: true}, {stopped: true}]) assert.ok(localizationState(view).tag_text.length <= 8);
});

test("round 2: rotating offers only stop; stop beats stale rotating/candidates; disabled service beats stale pose", () => {
  const rot = localizationState({operator: true, motion: {allowed: true, last_operator_request: {by: "kim", expires_in_s: 88.4}}, queue: {left_s: 50}});
  assert.deepEqual(rot.actions.map(a => a.id), ["stop", "cancel-queue"]);
  assert.equal(rot.evidence, "요청 kim · 88초 남음");
  const stopped = localizationState({operator: true, stopped: true, motion: {allowed: true}, report: {request_id: "r", candidates: [{x: 0, y: 0, yaw: 0, scan_fit: 0.8}]}, localization: {state: "CANDIDATES"}});
  assert.equal(stopped.state, "failed");
  assert.equal(stopped.candidates.length, 0);
  assert.ok(stopped.actions.some(a => a.id === "relocalize"));
  const off = localizationState({operator: true, refused: "LOCALIZATION_DISABLED", localization: {state: "LOCALIZED"}, age_s: 1});
  assert.equal(off.state, "blocked");
  assert.deepEqual(off.actions, []);
  const blockedFailed = localizationState({operator: true, anchor_blocked: true, stopped: true});
  assert.ok(blockedFailed.actions.some(a => a.id === "lift-block"));
});

test("round 3 safety: no queued start fires on a stale pose, twice, after stop, or after a refusal", () => {
  const q = () => ({since_s: 100});
  // stale pose: localized but 96 s old, or age unknown -> keep waiting
  assert.equal(queueStep(q(), {now_s: 110, localized: true, age_s: 96}).action, "wait");
  assert.equal(queueStep(q(), {now_s: 110, localized: true}).action, "wait");
  assert.equal(queueStep(q(), {now_s: 110, localized: true, age_s: NaN}).action, "wait");
  // a fired start that CORE refused for a non-pose reason must end, not re-fire while localized stays true
  assert.equal(queueStep(q(), {now_s: 110, localized: true, age_s: 2, code: "ROBOT_OFFLINE"}).action, "end");
  // a pose refusal while localized+fresh is not a reason to end; the start fires once
  const pose = q();
  assert.equal(queueStep(pose, {now_s: 110, localized: true, age_s: 2, code: "TRIP_POSE_UNTRUSTED"}).action, "fire");
  assert.equal(queueStep(pose, {now_s: 111, localized: true, age_s: 2, code: "TRIP_POSE_UNTRUSTED"}).action, "end");
  // stop closes the queue for good: a later localized poll cannot fire it
  const stopped = q();
  assert.equal(queueStep(stopped, {now_s: 110, stopped: true}).action, "end");
  assert.equal(queueStep(stopped, {now_s: 111, localized: true, age_s: 1}).action, "end");
  // the 120 s bound wins over a late localized
  assert.equal(queueStep(q(), {now_s: 220, localized: true, age_s: 1}).action, "end");
  // bad input never fires
  assert.equal(queueStep(undefined, undefined).action, "end");
  assert.equal(queueStep({since_s: "x"}, {localized: true, age_s: 1, now_s: 1}).action, "end");
});

test("round 3: confirm refuses NaN, bool, float and missing ids; no confirm or motion action while the robot moves or checks", () => {
  const r = {request_id: "a", candidates: [{x: 1, y: 2, yaw: 0.1, scan_fit: 0.8}]};
  for (const id of [NaN, true, 0.5, -1, 1, "0", null, undefined]) assert.equal(confirmRequest(r, r, id).ok, false);
  assert.equal(confirmRequest({...r, request_id: undefined}, {...r, request_id: undefined}, 0).ok, false);
  assert.equal(confirmRequest(r, {request_id: "a", candidates: [{x: 1, y: 2, yaw: NaN}]}, 0).ok, false);
  const checking = localizationState({operator: true, localization: {state: "CANDIDATES", reason: "checking"}, motion: {allowed: true}, report: r});
  assert.equal(checking.state, "confirming");
  assert.deepEqual(checking.actions.map(a => a.id), []);
  const open = localizationState({operator: true, localization: {state: "UNKNOWN"}, motion: {allowed: true}});
  assert.equal(open.actions.some(a => ["pin", "auto-locate", "relocalize"].includes(a.id)), false);
});

test("round 3: pin and auto-locate are operator writes and follow trip/offline like the server", () => {
  const viewer = localizationState({localization: {state: "UNKNOWN"}});
  assert.deepEqual(viewer.actions, []);
  const trip = localizationState({operator: true, trip_active: true});
  for (const id of ["pin", "auto-locate", "relocalize"]) assert.equal(trip.actions.find(a => a.id === id).disabled, true);
  const loc6 = localizationState({operator: true, localization: {state: "LOCALIZED"}, age_s: 1, session_left_s: 96});
  assert.equal(loc6.state, "localized");
  assert.equal(loc6.actions.some(a => a.id === "relocalize"), false);
});

test("revoked gate: Korean closed text, new press offered, never automatic, evidence names requester and close time", () => {
  assert.equal(revokeText("estop"), "비상정지로 회전 권한이 닫혔습니다");
  for (const r of ["mission_cancelled", "mission_done", "mission_obstacle", "mission_timeout"]) assert.equal(revokeText(r), "한 번 회전이 끝났습니다 · 다시 누르면 다시 찾습니다");
  for (const r of ["mission_weird", "mission_", "other", "", null, undefined]) assert.equal(revokeText(r), "회전 권한이 닫혔습니다 · 다시 누르면 다시 찾습니다");
  const view = {operator: true, last_requester: "kim", wall_now_s: 1000, motion: {allowed: false, last_operator_request: {revoked: {reason: "mission_done", at: 940}}}};
  const out = localizationState(view);
  assert.equal(out.state, "unknown");
  assert.equal(out.reason, "한 번 회전이 끝났습니다 · 다시 누르면 다시 찾습니다");
  assert.equal(out.evidence, "요청 kim · 회전 권한 닫힘 · 60초 전");
  assert.ok(out.actions.some(a => a.id === "relocalize" && !a.disabled));  // a new press, offered not taken
  assert.equal(out.actions.some(a => a.id === "stop"), false);
  assert.equal(localizationState({...view, motion: {allowed: false, last_operator_request: {revoked: {reason: "estop", at: 940}}}}).reason, "비상정지로 회전 권한이 닫혔습니다");
  assert.equal(localizationState({operator: true, motion: {last_operator_request: {revoked: {reason: "estop"}}}}).evidence, "회전 권한 닫힘");
  // an open gate still shows the live remaining time; a closed gate never reads as rotating
  assert.equal(localizationState({motion: {allowed: true, last_operator_request: {by: "kim", expires_in_s: 40}}}).evidence, "요청 kim · 40초 남음");
  assert.equal(localizationState({localization: {state: "LOCALIZED"}, age_s: 1, motion: {allowed: false, last_operator_request: {revoked: {reason: "mission_done", at: 1}}}}).reason, "");
});
