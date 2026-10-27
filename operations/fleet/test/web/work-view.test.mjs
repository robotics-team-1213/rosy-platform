import test from "node:test";
import assert from "node:assert/strict";
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { workKey, workLine, workStatus, autoAdmitScope, policyScopeText, autoAdmitDetail } = await import("../../../../applications/fleet/web/work/work-view.js");

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
  assert.equal(workLine({source: "cell_job", device_id: "omx", status: "PROPOSED", visible_state: "approval_pending"}), "Cell 적재 · omx · 승인 대기");
  assert.equal(workLine({source: "task", device_id: "rosy_02", status: "RUNNING"}), "주행 · rosy_02 · 실행 중");
  assert.equal(workStatus("arrived"), "도착");
  assert.notEqual(workKey({source: "trip", source_id: "same"}), workKey({source: "cell_job", source_id: "same"}));
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

test("D-865 P3: the readback line carries robots, kinds, budget and revision; disabled states the reason", () => {
  assert.match(policyScopeText(scopePolicy), /켜짐/);
  assert.match(policyScopeText(scopePolicy), /로봇 rosy_01/);
  assert.match(policyScopeText(scopePolicy), /1인 승인/);
  assert.match(policyScopeText(scopePolicy), /잔여 3\/5회/);
  assert.match(policyScopeText(scopePolicy), /rev-7/);
  assert.match(policyScopeText({...scopePolicy, scope: {...scopePolicy.scope, enabled: false}, reason: "BUDGET_EXHAUSTED"}),
    /꺼짐 · BUDGET_EXHAUSTED/);
  assert.equal(policyScopeText(null), null);
});

test("D-865 P3: the detail line separates in-scope from human approval", () => {
  assert.equal(autoAdmitDetail(waiting, scopePolicy), "범위 안 · 잔여 3회 · 범위 rev-7");
  assert.equal(autoAdmitDetail({...waiting, device_id: "rosy_02"}, scopePolicy), "범위 밖 · 사람 승인");
  assert.equal(autoAdmitDetail(waiting, {...scopePolicy, scope: {...scopePolicy.scope, enabled: false}}), "꺼짐 · 사람 승인");
  assert.equal(autoAdmitDetail({...waiting, status: "RUNNING"}, scopePolicy), null);  // only waiting rows carry the line
});
