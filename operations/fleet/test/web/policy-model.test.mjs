import test from "node:test";
import assert from "node:assert/strict";

import {
  ADMIN_REASON, TWO_PERSON_REASON, executionVerdict, incidentLock, nextStage, policyFigures, proposalLock, remaining, roles, windowLock,
} from "../../../../applications/fleet/web/work/policy-model.js";

const RULES = {
  stages: ["L0", "L1", "L2", "L3", "LIMITED"], two_person_stages: ["L3", "LIMITED"],
  windows: {shadow: {two_person: false}, supervised: {two_person: true}, limited: {two_person: true}},
};
const empty = {incidents: [], confirmations: [], windows: [], now_ns: 0};

test("legacy and account sessions map to the same governance roles", () => {
  assert.deepEqual(roles({principal_id: "a", role: "policy-admin"}), {me: "a", admin: true, operator: false});
  assert.deepEqual(roles({principal_id: "site-console", role: "operator"}).operator, false);
  assert.deepEqual(roles({principal_id: "c", role: "operator", policy_admin: true}), {me: "c", admin: true, operator: true});
  assert.equal(roles({principal_id: "d", role: "operator", policy_admin: false}).admin, false);
  const account = {principal_id: "b", account_id: "x", site_resource: "site:s",
    grants: [{resource: "site:s", capabilities: ["fleet.read", "fleet.operate", "fleet.policy"]}]};
  assert.deepEqual(roles(account), {me: "b", admin: true, operator: true});
  assert.equal(roles({...account, grants: [{resource: "site:other", capabilities: ["fleet.policy"]}]}).admin, false);
});

test("the verdict names the strongest reason execution is blocked", () => {
  assert.match(executionVerdict(empty).text, /움직이지 않습니다/);
  const active = {active: true, kind: "supervised", expires_ns: 90e9, policy_revision: "r"};
  assert.equal(executionVerdict({...empty, windows: [active]}).state, "warning");
  assert.match(executionVerdict({...empty, windows: [active], confirmations: [{resolution: null}]}).text, /확인 요청 1건/);
  assert.equal(executionVerdict({...empty, windows: [active], incidents: [{cleared_ns: null}]}).state, "error");
  assert.match(executionVerdict({...empty, windows: [{...active, kind: "shadow"}]}).text, /명령은 보내지 않습니다/);
});

test("controls the server would refuse are locked with a reason", () => {
  const me = {me: "a", admin: true, operator: true};
  assert.equal(proposalLock({to_stage: "L3", proposed_by: "a"}, RULES, me), TWO_PERSON_REASON);
  assert.equal(proposalLock({to_stage: "L1", proposed_by: "a"}, RULES, me), "");
  assert.equal(proposalLock({to_stage: "L1", proposed_by: "b"}, RULES, {...me, admin: false}), ADMIN_REASON);
  assert.equal(windowLock({kind: "supervised", requested_by: "a"}, RULES, me), TWO_PERSON_REASON);
  assert.equal(windowLock({kind: "shadow", requested_by: "a"}, RULES, me), "");
  assert.notEqual(incidentLock({reported_by: "a"}, me), "");
});

test("stages advance one at a time and time left is readable", () => {
  assert.equal(nextStage(RULES, undefined), "L0");
  assert.equal(nextStage(RULES, "L2"), "L3");
  assert.equal(nextStage(RULES, "LIMITED"), null);
  assert.equal(remaining(75e9, 0), "1분 15초");
  assert.equal(remaining(0, 5e9), "0분 00초");
});

test("the figure strip only counts what the server returned", () => {
  const figures = Object.fromEntries(policyFigures({...empty, proposals: [], policies: []}).map(f => [f.id, f]));
  assert.equal(figures.incidents.value, "0"); assert.equal(figures.incidents.alert, false);
  assert.equal(figures.window.value, "없음"); assert.equal(figures.window.note, "실물 움직이지 않음");
  const busy = Object.fromEntries(policyFigures({
    incidents: [{cleared_ns: null}, {cleared_ns: 5}], confirmations: [{resolution: null}, {resolution: "abort"}],
    windows: [{active: true, kind: "supervised", expires_ns: 90e9}], now_ns: 0,
    proposals: [{state: "PENDING"}, {state: "APPROVED"}], policies: [{}, {}],
  }).map(f => [f.id, f]));
  assert.deepEqual([busy.incidents.value, busy.confirmations.value, busy.proposals.value], ["1", "1", "1"]);
  assert.equal(busy.incidents.alert, true);
  assert.equal(busy.window.value, "입회 시험"); assert.equal(busy.window.note, "1분 30초 남음"); assert.equal(busy.window.alert, true);
  assert.equal(busy.proposals.note, "등록 정책 2개");
  const shadow = policyFigures({...empty, windows: [{active: true, kind: "shadow", expires_ns: 60e9}]}).find(f => f.id === "window");
  assert.equal(shadow.alert, false);
});
