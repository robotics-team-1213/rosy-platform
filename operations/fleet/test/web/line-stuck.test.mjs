import test from "node:test";
import assert from "node:assert/strict";

// The button helpers live in queues.js (D-540 (d)), which imports the browser's "/common/..." modules.
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const {
  CAUSE_LABEL, DECISIONS, PHASE_LABEL, aiLines, aiProposalText, chainRows, alertsDue, confirmText, decisionButtons, evidenceCaption,
  needsConfirm, outcomeText, pendingStucks, rearText, refusalText, resolverText, stuckFacts,
  previewFresh, headingText, fleetAnswerText,
} = await import("../../fleet/server/web/line-stuck.js");

const STUCK = {
  stuck_id: "stuck-abc", cause: "obstacle_ahead", phase: "ASKING", held_s: 12.4,
  attempts: 0, max_attempts: 2, local_enabled: true, robot_online: true,
  front_clearance_m: 0.123, rear_clearance_m: 0.31, turn_clearance_m: null, preview_seq: 812,
};
const byDecision = (buttons) => Object.fromEntries(buttons.map((b) => [b.decision, b]));

test("only robots with an open stuck are pending", () => {
  const robots = [{ robot_id: "a", line_stuck: STUCK }, { robot_id: "b", line_stuck: null },
    { robot_id: "c" }, { robot_id: "d", line_stuck: { stuck_id: "" } }];
  assert.deepEqual(pendingStucks(robots).map((r) => r.robot_id), ["a"]);
  assert.deepEqual(pendingStucks(undefined), []);
});

test("five answers in CORE order with Korean labels; RESUME and BACK_AND_RETRY confirm", () => {
  assert.deepEqual(DECISIONS, ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]);
  const buttons = decisionButtons(STUCK, { operator: true });
  assert.deepEqual(buttons.map((b) => b.label), ["대기", "재개", "후진 후 재시도", "수동", "중단"]);
  assert.deepEqual(buttons.filter((b) => b.confirm).map((b) => b.decision), ["RESUME", "BACK_AND_RETRY"]);
  assert.ok(buttons.every((b) => b.reason === ""));
  assert.equal(needsConfirm("WAIT"), false);
  assert.equal(needsConfirm("ABORT"), false);
});

test("BACK_AND_RETRY is disabled when local recovery is off or attempts are spent", () => {
  const off = byDecision(decisionButtons({ ...STUCK, local_enabled: false }, { operator: true }));
  assert.match(off.BACK_AND_RETRY.reason, /로컬 복구가 꺼져/);
  assert.equal(off.RESUME.reason, "");
  const spent = byDecision(decisionButtons({ ...STUCK, attempts: 2 }, { operator: true }));
  assert.match(spent.BACK_AND_RETRY.reason, /모두 썼습니다/);
});

test("a viewer, an unreachable robot or an answer in flight blocks every button", () => {
  for (const [stuck, options, pattern] of [
    [STUCK, { operator: false }, /운영자 권한/],
    [{ ...STUCK, robot_online: false }, { operator: true }, /연결이 끊겼습니다/],
    [STUCK, { operator: true, busy: true }, /보내는 중/],
  ]) {
    for (const button of decisionButtons(stuck, options)) assert.match(button.reason, pattern);
  }
});

test("facts show clearances in metres, unknowns as a dash, and the preview seq", () => {
  const facts = Object.fromEntries(stuckFacts(STUCK).map(([key, , value]) => [key, value]));
  assert.equal(facts.front, "0.12 m");
  assert.equal(facts.turn, "—");
  assert.equal(facts.held, "12 s");
  assert.equal(facts.attempts, "0/2");
  assert.equal(facts.preview, "#812");
  assert.ok(!stuckFacts({ ...STUCK, preview_seq: null }).some(([key]) => key === "preview"));
});

test("an empty rear band reads 비어 있음, an unknown one 알 수 없음 (D-407 re-run C)", () => {
  assert.equal(rearText({ rear_clearance_m: 0.31, rear_state: "clear" }), "0.31 m");
  assert.equal(rearText({ rear_clearance_m: null, rear_state: "clear" }), "비어 있음");
  assert.equal(rearText({ rear_clearance_m: null, rear_state: "unknown" }), "알 수 없음");
  assert.equal(rearText({ rear_clearance_m: null }), "알 수 없음");
  const rear = stuckFacts({ ...STUCK, rear_clearance_m: null, rear_state: "unknown" })
    .find(([key]) => key === "rear");
  assert.equal(rear[2], "알 수 없음");
  assert.equal(rear[3], "stuck-fact-unknown");
  const empty = stuckFacts({ ...STUCK, rear_clearance_m: null, rear_state: "clear" })
    .find(([key]) => key === "rear");
  assert.equal(empty[2], "비어 있음");
  assert.equal(empty[3], undefined);
});

test("causes and phases read as operator Korean", () => {
  assert.equal(CAUSE_LABEL.obstacle_ahead, "앞 물체로 멈춤");
  assert.equal(CAUSE_LABEL.lane_lost, "차선을 잃고 멈춤");
  for (const phase of ["ASKING", "WAITING_CONSOLE", "BACKING", "SETTLING"]) assert.ok(PHASE_LABEL[phase]);
});

test("the confirm step names the robot and the risk", () => {
  assert.match(confirmText("rosy_01", "RESUME"), /^rosy_01 재개 — 앞이 비었는지/);
  assert.match(confirmText("rosy_01", "BACK_AND_RETRY"), /뒤가 비었습니까/);
  assert.equal(confirmText("rosy_01", "WAIT"), "");
});

test("CORE refusals keep their code and message verbatim", () => {
  const late = refusalText("rosy_01", "RESUME", {
    code: "STUCK_ID_MISMATCH", status: 409, message: "no open stuck with this id (late or wrong answer)" });
  assert.match(late, /이미 닫혔거나 바뀐 막힘/);
  assert.ok(late.endsWith("(STUCK_ID_MISMATCH: no open stuck with this id (late or wrong answer))"));
  const resume = refusalText("rosy_01", "RESUME", {
    code: "STUCK_DECISION_REFUSED", status: 409, message: "RESUME refused: object_within_stop_distance" });
  assert.match(resume, /정지 거리 안에 아직 물체가 있습니다/);
  assert.match(resume, /RESUME refused: object_within_stop_distance/);
  const unknown = refusalText("rosy_01", "BACK_AND_RETRY", {
    code: "STUCK_DECISION_REFUSED", status: 409, message: "BACK_AND_RETRY refused: new_reason" });
  assert.match(unknown, /CORE가 거부했습니다 \(STUCK_DECISION_REFUSED: BACK_AND_RETRY refused: new_reason\)/);
  assert.match(refusalText("rosy_01", "ABORT", { status: 403, code: "FORBIDDEN", message: "operator role required" }),
    /운영자 권한/);
});

test("transport failures say not delivered or outcome unknown, never refused", () => {
  const unreachable = refusalText("rosy_01", "ABORT", { status: 502, code: "ROBOT_UNREACHABLE",
    message: "answer not delivered: the robot could not be reached" });
  assert.match(unreachable, /^rosy_01 중단 전달 실패 — 로봇에 닿지 않아/);
  const unknown = refusalText("rosy_01", "RESUME", { status: 502, code: "STUCK_DECISION_OUTCOME_UNKNOWN",
    message: "the robot did not reply; CORE may have applied the answer. Re-read the stuck before answering again" });
  assert.match(unknown, /^rosy_01 재개 결과 불명 — /);
  assert.match(unknown, /이미 적용했을 수 있으니 막힘 상태를 다시 확인/);
  assert.match(unknown, /\(STUCK_DECISION_OUTCOME_UNKNOWN: the robot did not reply/);
});

test("accepted answers say what the robot will do", () => {
  assert.match(outcomeText("rosy_01", "WAIT", { outcome: "hold" }), /^rosy_01 대기: 대기로 답했습니다/);
  // D-398: 보이는 글에서 맨 열거값을 뺐다 — 중단 문장 자체가 뜻을 말한다.
  assert.match(outcomeText("rosy_01", "ABORT", { outcome: "idle" }), /차선 추종을 중단했습니다/);
  assert.doesNotMatch(outcomeText("rosy_01", "ABORT", { outcome: "idle" }), /IDLE/);
  assert.match(outcomeText("rosy_01", "MANUAL", {}), /CORE가 받았습니다/);
});

test("resolverText says what the Fleet resolver did, or why a human is needed", () => {
  assert.equal(resolverText(null), "");
  assert.equal(resolverText({ tier: "rule", rule: "R2", decision: "BACK_AND_RETRY", escalated: null }),
    "자동 판단 R2: 후진 후 재시도");
  assert.equal(resolverText({ tier: "human", escalated: "no_rule" }),
    "자동 판단 불가 — 사람 확인 필요 (맞는 규칙 없음)");
  assert.equal(resolverText({ tier: "human", escalated: "calibration" }),
    "자동 판단 불가 — 사람 확인 필요 (보정 중)");
  assert.equal(resolverText({ tier: "human", escalated: "core:ROBOT_UNREACHABLE" }),
    "자동 판단 불가 — 사람 확인 필요 (CORE 응답 ROBOT_UNREACHABLE)");
  assert.equal(resolverText({ tier: "human", escalated: "human_claimed" }), "운영자가 맡음");
});

test("D-540 9: an unnamed operator may WAIT or ABORT but not answer with motion", () => {
  const named = "이름 있는 운영자 로그인이 필요합니다";
  const buttons = byDecision(decisionButtons(STUCK, { operator: true, namedReason: named }));
  assert.equal(buttons.WAIT.reason, "");
  assert.equal(buttons.ABORT.reason, "");
  for (const decision of ["RESUME", "BACK_AND_RETRY", "MANUAL"]) assert.equal(buttons[decision].reason, named);
  assert.match(refusalText("rosy_01", "RESUME", { status: 403, code: "OPERATOR_IDENTITY_REQUIRED", message: "" }),
    /이름 있는 운영자 로그인이 필요합니다/);
});

test("D-577 8: the AI chip says whether AI judgment exists, and each live fact shows confidence and evidence", () => {
  assert.deepEqual(aiLines({}), []);
  assert.deepEqual(aiLines({ ai: { state: "absent" }, ai_facts: [] }), ["AI 판단 없음"]);
  assert.deepEqual(aiLines({ ai: { state: "present", owner_mode: "owner_busy" } }), ["AI 판단 없음 (소유자 사용 중)"]);
  assert.deepEqual(aiLines({ ai: { state: "present", owner_mode: "shared" }, ai_facts: [
    { kind: "stalled", confidence: 0.82, source: "analyzer:stalled@0.1", evidence: { events: [12] } }] }),
  ["AI 판단 있음", 'AI 사실 stalled · 신뢰도 82% · analyzer:stalled@0.1 · 근거 {"events":[12]}']);
});

test("D-577 8: the evidence picture says which camera, which frame and how old", () => {
  assert.equal(evidenceCaption({ source: "front", sequence: 812, age_s: 0.4 }, 0), "사건 기록 영상 · 앞 카메라 #812 · 0초 전 촬영");
  assert.equal(evidenceCaption({ source: "front", sequence: 812, age_s: 0.4 }, 3), "사건 기록 영상 · 앞 카메라 #812 · 3초 전 촬영");
  assert.equal(evidenceCaption(null), "카메라 그림 없음");
  assert.equal(evidenceCaption({ state: "loading" }), "카메라 그림 받는 중");
});

test("live evidence expires and an incident snapshot cannot be shown as current", () => {
  const live = { live: true, age_s: 0.4, source: "front", sequence: 900 };
  assert.ok(previewFresh(live));
  assert.ok(!previewFresh(live, 3));
  assert.ok(!previewFresh({ ...live, live: false }));
  assert.ok(!previewFresh({ ...live, age_s: NaN }));
  assert.match(evidenceCaption(live), /현재 영상/);
  assert.match(evidenceCaption(live, 3), /만료/);
});

test("UI distinguishes map direction advice, transmitted command and CORE receipt", () => {
  assert.match(headingText({ status: "heading_compared", turn_deg: -20, edge_id: "lower", map_version: 5 }), /오른쪽 20°/);
  assert.match(headingText({ status: "pose_untrusted" }), /재확인 필요/);
  assert.match(fleetAnswerText({ tier: "ai", decision: "WAIT", accepted: true, outcome: "hold" }), /AI 판단 → Fleet 전송 대기 → CORE 수락/);
  assert.match(fleetAnswerText({ decision: "RESUME", accepted: false, code: "EMERGENCY_ACTIVE" }), /CORE 거절/);
  assert.match(fleetAnswerText({ decision: "RESUME", accepted: null }), /미확인/);
});

test("D-577 8: one alert when a stuck row appears, one more when it goes 30 s unanswered", () => {
  const seen = new Map();
  const row = (resolver) => [{ robot_id: "rosy_01", line_stuck: { stuck_id: "s1", resolver } }];
  assert.deepEqual(alertsDue(seen, row(null)), [{ robotId: "rosy_01", stuckId: "s1", kind: "new" }]);
  assert.deepEqual(alertsDue(seen, row(null)), []);
  const late = { escalated: "no_rule", age_s: 31 };
  assert.deepEqual(alertsDue(seen, row(late)), [{ robotId: "rosy_01", stuckId: "s1", kind: "overdue" }]);
  assert.deepEqual(alertsDue(seen, row(late)), []);
  assert.deepEqual(alertsDue(seen, row({ escalated: "human_claimed", age_s: 90 })), []);
  assert.deepEqual(alertsDue(seen, []), []);
  assert.equal(seen.size, 0);                       // a closed stuck forgets its alerts
  assert.deepEqual(alertsDue(seen, row(null)).map((a) => a.kind), ["new"]);
});

test("D-577: the stuck row says what Fleet did with the AI proposal", () => {
  assert.equal(aiProposalText(null), "");
  assert.equal(aiProposalText({ decision: "ABORT", verdict: "crosswalk_unknown", class: "held" }),
    "AI 제안 중단: Fleet 보류 (횡단보도 여부 모름)");
  assert.equal(aiProposalText({ decision: "BACK_AND_RETRY", verdict: "ai_fact:rear_blocked", class: "held" }),
    "AI 제안 후진 후 재시도: Fleet 보류 (AI 사실 rear_blocked)");
  assert.equal(aiProposalText({ decision: "BACK_AND_RETRY", verdict: "forwarded", outcome: "STUCK_DECISION_REFUSED",
    class: "refused" }), "AI 제안 후진 후 재시도: CORE 거절 (CORE 응답 STUCK_DECISION_REFUSED)");
  assert.equal(aiProposalText({ decision: "WAIT", verdict: "forwarded", outcome: "accepted", class: "accepted" }),
    "AI 제안 대기: CORE 수락");
  assert.deepEqual(aiLines({ ai: { state: "present", owner_mode: "shared" },
    ai_proposal: { decision: "WAIT", verdict: "forwarded", outcome: null, class: "pending" } }),
  ["AI 판단 있음", "AI 제안 대기: CORE 답 기다림"]);
  assert.match(resolverText({ escalated: "ai_abort:scene_blocked", rule: "ai", decision: "ABORT" }),
    /AI 중단 제안 \(scene_blocked\)/);
  assert.match(resolverText({ escalated: "ai_abort_held:crosswalk_unknown", rule: "R5", decision: "WAIT" }),
    /AI 중단 제안 보류 — 멈춰 둠 \(횡단보도 여부 모름\)/);
});

test("D-577 연동 상태: resolver, credential presence, AI PC heartbeat and hourly counts", () => {
  const now = Date.parse("2026-10-10T03:00:10Z");
  const rows = chainRows({
    status: { state: "present", age_s: 1.2, owner_mode: "shared", input_lag_s: 0.42, service_version: "0.2.0",
      build_commit: "0123456789ab" },
    chain: { resolver: true, proposals_1h: { accepted: 3, held: 2, refused: 1, pending: 0 }, robots: [
      { robot_id: "rosy_40", credential: "enrolled", ai_acting: true,
        last_answer: { decision: "WAIT", rule: "R5", tier: "rule", at: "2026-10-10T03:00:00Z" } },
      { robot_id: "rosy_41", credential: "none", ai_acting: false, last_answer: null }] },
  }, now);
  assert.deepEqual(rows, [
    ["자동 판단", "켜짐"],
    ["rosy_40", "등록 자격 · AI 제안 실행 · 마지막 R5 대기 · 10초 전"],
    ["rosy_41", "자격 없음 · AI 사실만 · 마지막 답 없음"],
    ["AI PC", "신호 1.2초 전 · 공유 · 입력 지연 0.4초 · 버전 0.2.0 @ 0123456789ab"],
    ["AI 제안 1시간", "수락 3 · 보류 2 · 거절 1 · 답 기다림 0"],
  ]);
  assert.equal(chainRows({ status: { state: "absent", age_s: null }, chain: { resolver: false, robots: [] } })[1][1],
    "없음 (신호 받은 적 없음)");
  assert.deepEqual(chainRows(null), [["연동", "확인할 수 없음"]]);
});
