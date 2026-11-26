import test from "node:test";
import assert from "node:assert/strict";
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { workKey, workLine, workStatus, formatWorkTime, autoAdmitScope, autoAdmitDetail, canAdmitWorkHere, requestsNotice, requestsPause, summarizeWorkCounts } = await import("../../../../applications/fleet/web/work/work-view.js");

test("two ledgers can reuse the same ID without sharing selection", () => {
  assert.notEqual(workKey({source: "task", source_id: "same"}), workKey({source: "mission", source_id: "same"}));
});
test("action success is distinct from goal confirmation and unknown states", () => {
  assert.match(workStatus("ACTION_SUCCEEDED"), /목표 확인 대기/);
  assert.equal(workStatus("GOAL_CONFIRMED"), "목표 확인 완료");
  assert.equal(workStatus("new-state"), "상태 확인 필요");
  assert.equal(workStatus("REQUESTED"), "요청 접수");
  assert.equal(workStatus("UNKNOWN"), "실행 결과 미확인");
  assert.equal(workStatus("CLAIMED"), "사건 인수");
  assert.equal(workStatus("CLOSED"), "사건 종료");
});
test("D-763 8: a row reads the server's visible state, a wait first, the ledger status only as a fallback", () => {
  const row = {source: "trip", device_id: "rosy_01", status: "running", visible_state: "in_progress"};
  assert.equal(workLine(row), "운행 · rosy_01 · 진행 중");
  assert.equal(workLine({...row, visible_state: "waiting", wait: {reason: "signal", waiting: true}}), "운행 · rosy_01 · 대기 · 신호");
  assert.equal(workLine({...row, wait: {reason: "authority", waiting: false, over_bound: true}}), "운행 · rosy_01 · 대기 상한 넘음 · 통행권");
  assert.equal(workLine({source: "cell_job", device_id: "omx", status: "PROPOSED", visible_state: "approval_pending"}), "팔레트 적재 · omx · 승인 대기");
  assert.equal(workLine({source: "task", device_id: "rosy_02", status: "RUNNING"}), "주행 · rosy_02 · 실행 중");
  assert.equal(workStatus("running"), "운행 요청 처리 중");
  assert.equal(workStatus("started"), "운행 요청 접수");
  assert.equal(workLine({...row, status: "arrived", visible_state: "ended", wait: {reason: "signal", waiting: true}}), "운행 · rosy_01 · 끝남");
  assert.equal(workStatus("arrived"), "도착");
  assert.notEqual(workKey({source: "trip", source_id: "same"}), workKey({source: "cell_job", source_id: "same"}));
});
test("two same-device rows become distinguishable by the identifier tail and workspace/time tail when colliding", () => {
  const id = "550e8400-e29b-41d4-a716-446655440000";
  const base = {source: "trip", device_id: "rosy_45", status: "intervention", visible_state: "intervention"};
  const a = workLine({...base, source_id: `${id}`}, true);
  const b = workLine({...base, source_id: "TRIP-20261124-0042"}, true);
  assert.notEqual(a, b);  // 운행 · rosy_45 · 개입 필요 꼬리가 겹치는 두 행을 갈라 놓는다
  assert.match(a, /44665544/);
  assert.match(b, /0042/);
  assert.match(workLine({...base, source_id: id, workcell_id: "cell_ab"}, true), /cell_ab/);
  assert.match(workLine({...base, source_id: id, updated_at: "2026-11-24T12:49:00+00:00"}, true), /\d{1,2}:\d{2}/);
  assert.equal(workLine({...base, source_id: id}), "운행 · rosy_45 · 개입 필요");
});

// D-865 P3 — 승인 범위 판정·문구는 순수 함수다. 범위 밖·상한 소진·비활성은 배지 없음(사람 승인).
const scopePolicy = {scope: {enabled: true, robots: ["rosy_01"], step_approval_kinds: ["one_person"],
  max_admits: 5, valid_until: null, scope_revision: "rev-7"}, admits_remaining: 3, reason: null};
const waiting = {source: "mission", status: "PROPOSED", approval: "one_person", device_id: "rosy_01"};

test("D-865 P3: an enabled scope covers only waiting one_person rows of its robots with budget left", () => {
  assert.equal(autoAdmitScope(waiting, scopePolicy).member, true);
  assert.equal(autoAdmitScope(waiting, scopePolicy).remaining, 3);
  assert.equal(autoAdmitScope(waiting, scopePolicy).revision, "rev-7");
  assert.equal(autoAdmitScope({...waiting, device_id: "rosy_02"}, scopePolicy).member, false);  // robot outside the scope
  assert.equal(autoAdmitScope({...waiting, approval: "two_person"}, scopePolicy).member, false);  // arm steps stay human
  assert.equal(autoAdmitScope({...waiting, status: "READY"}, scopePolicy).member, false);  // only approval-waiting rows
  assert.equal(autoAdmitScope(waiting, {...scopePolicy, admits_remaining: 0}).exhausted, true);  // budget spent: no reset
  assert.equal(autoAdmitScope(waiting, {...scopePolicy, scope: {...scopePolicy.scope, enabled: false}}).member, false);
  assert.equal(autoAdmitScope(waiting, null).member, false);  // fail closed without a readback
});

test("D-865 P3: the detail line separates in-scope from human approval", () => {
  assert.equal(autoAdmitDetail(waiting, scopePolicy), "범위 안 · 잔여 3회 · 범위 rev-7");
  assert.equal(autoAdmitDetail({...waiting, device_id: "rosy_02"}, scopePolicy), "범위 밖 · 사람 승인");
  assert.equal(autoAdmitDetail(waiting, {...scopePolicy, scope: {...scopePolicy.scope, enabled: false}}), "꺼짐 · 사람 승인");
  assert.equal(autoAdmitDetail({...waiting, status: "RUNNING"}, scopePolicy), null);  // only waiting rows carry the line
});

test("D-960: FleetR relays arm jobs without admitting them locally; owning cell admits", () => {
  assert.equal(canAdmitWorkHere(waiting, null), true);
  assert.equal(canAdmitWorkHere(waiting, { role: "cell", arms: true, children: false }), true);
  assert.equal(canAdmitWorkHere(waiting, { role: "root", drive: true, arms: true, children: true }), false);
  assert.equal(canAdmitWorkHere(waiting, { role: "cell", drive: true, arms: false, children: false }), false);
  assert.equal(canAdmitWorkHere({ ...waiting, status: "RUNNING" }, null), false);
});

test("formatWorkTime handles Unix epoch seconds, ms, and ISO strings without 1970 dates", () => {
  for (const sample of [1795524570.123, 1795524570123, "2026-11-24T12:49:30.123+00:00"]) {
    assert.match(formatWorkTime(sample), /2026/);
    assert.doesNotMatch(formatWorkTime(sample), /1970/);
  }
  for (const empty of [null, undefined, "", 0, -1, Number.NaN, "not-a-date"]) {
    assert.equal(formatWorkTime(empty), "미확인");
  }
});

test("a 403 on channel-requests says the permission line and pauses polling; 404 and server faults do not", () => {
  assert.equal(requestsNotice(403), "대화 요청을 보려면 기명 운영자로 로그인해야 합니다.");
  assert.equal(requestsNotice(404), "대화 요청 접수가 설정되지 않았습니다.");
  assert.equal(requestsNotice(401), "기명 운영자 접속이 필요합니다.");
  assert.equal(requestsNotice(500), "대화 요청 조회 실패");
  assert.equal(requestsPause(403), true);
  assert.equal(requestsPause(404), false);
  assert.equal(requestsPause(401), false);
  assert.equal(requestsPause(500), false);
});

test("summarizeWorkCounts aggregates total, pending, active(in_progress+waiting), and intervention counts", () => {
  assert.deepEqual(summarizeWorkCounts([]), { total: 0, pending: 0, active: 0, intervention: 0 });
  const sample = [
    { visible_state: "approval_pending" },
    { visible_state: "in_progress" },
    { visible_state: "waiting" },
    { visible_state: "intervention" },
    { visible_state: "ended" },
    { visible_state: "approval_pending" },
    {},
  ];
  assert.deepEqual(summarizeWorkCounts(sample), { total: 7, pending: 2, active: 2, intervention: 1 });
});
