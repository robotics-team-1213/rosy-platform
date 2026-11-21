import {test} from "node:test";
import assert from "node:assert/strict";
import {skillState, SKILL_LIFECYCLES} from "../skill-state.js";
import {armAiCaseProblems, isSample, SAMPLE_LABEL} from "../sample-data.js";

const text = lifecycle => skillState({lifecycle, executor: "ik_chunk", measured: "verify_placed"}).text;

test("all nine lifecycles read the design's state-table words", () => {
  assert.equal(SKILL_LIFECYCLES.length, 9);
  assert.deepEqual(SKILL_LIFECYCLES.map(text), ["승인 대기", "승인 대기", "승인됨 · 시작 대기", "실행 중", "측정 성공", "측정 실패", "정지 · HOLD", "시간 초과 · HOLD", "대체 제안됨 · 승인 필요"]);
  assert.equal(skillState({lifecycle: "running", step: {n: 3, of: 5}}).text, "실행 중 3/5");
});

test("tags follow the table: quiet normal states, caution, danger only for a stop or a lock", () => {
  const tag = (lifecycle, rest = {}) => skillState({lifecycle, executor: "ik_chunk", measured: "verify_placed", ...rest}).tag;
  for (const lifecycle of ["approved", "running", "measured_success"]) assert.equal(tag(lifecycle), null, lifecycle);
  assert.equal(tag("proposed"), null);
  assert.deepEqual(tag("waiting_approval", {blocking: true}), {state: "caution"});
  for (const lifecycle of ["timed_out", "fallback_proposed", "measured_failure"]) assert.deepEqual(tag(lifecycle), {state: "caution"}, lifecycle);
  assert.deepEqual(tag("measured_failure", {guard: "loaded"}), {state: "danger", icon: "safety"});
  assert.deepEqual(tag("stopped", {guard: "estop"}), {state: "danger", icon: "estop"});
  assert.deepEqual(tag("stopped", {guard: "hold"}), {state: "danger", icon: "safety"});
});

test("an unknown lifecycle is unavailable, and a success without a measurement is never shown as success", () => {
  for (const input of [{lifecycle: "dreaming"}, {}, {lifecycle: undefined}, {lifecycle: "measured_success"}, {lifecycle: "measured_success", measured: ""}, {lifecycle: "measured_success", measured: "model"}]) {
    assert.deepEqual(skillState(input), {text: "정보 없음", tag: {state: "unknown"}, readout: []}, JSON.stringify(input));
  }
});

test("the readout names the executor, shows the policy only for a learned one and the guard only when it is not ok", () => {
  const act = skillState({lifecycle: "running", executor: "act", policyId: "act-pick", version: "0123456789abcdef", step: {n: 3, of: 5}, guard: "ok", leaseS: 12, ageS: 2});
  assert.deepEqual(act.readout, [{label: "실행기", value: "학습 정책"}, {label: "정책", value: "act-pick@01234567"}, {label: "단계", value: "3/5"}, {label: "리스 잔여", value: "12초"}, {label: "관측", value: "2초 전"}]);
  const script = skillState({lifecycle: "running", executor: "ik_chunk", policyId: "ignored", step: {n: 2, of: 5}});
  assert.deepEqual(script.readout.map(item => item.label), ["실행기", "단계"]);
  assert.equal(skillState({lifecycle: "running", executor: "mystery"}).readout[0].value, "정보 없음");
  assert.deepEqual(skillState({lifecycle: "stopped", executor: "act", guard: "estop"}).readout.at(-1), {label: "가드", value: "E-stop"});
});

const good = () => ({id: "c1", sample: true, title: "t", lifecycle: "approved", requested_by: "op", evidence: [{label: "x", value: "1", source: "ledger"}], candidates: [{id: "a", label: "A", reason: "r"}]});

test("the sample contract accepts a valid case and rejects fakes, coordinates, joints and unmeasured success", () => {
  assert.deepEqual(armAiCaseProblems(good()), []);
  assert.ok(isSample(good()) && !isSample({sample: "true"}) && SAMPLE_LABEL === "샘플 데이터");
  const bad = patch => armAiCaseProblems({...good(), ...patch}).join(" | ");
  assert.match(bad({sample: false}), /sample must be true/);
  assert.match(bad({lifecycle: "done"}), /lifecycle/);
  assert.match(bad({lifecycle: "measured_success"}), /measurement/);
  assert.match(bad({executor: "gpt"}), /executor/);
  assert.match(bad({evidence: [{label: "x", value: "1", source: "vibes"}]}), /evidence\[0\]\.source/);
  assert.match(bad({candidates: [{id: "a", label: "A", reason: "r", pose: {x: 1}}]}), /coordinates, joints/);
  assert.match(bad({joints: [1, 2]}), /case\.joints/);
});

test("a proposer approving their own proposal is a contract problem; a refused attempt is the valid sample", () => {
  const attempt = result => armAiCaseProblems({...good(), approval_attempt: {by: "op", result, reason: "제안자는 승인할 수 없습니다"}}).join(" | ");
  assert.equal(attempt("refused"), "");
  assert.match(attempt("accepted"), /own proposal/);
  assert.match(attempt("maybe"), /refused\|accepted/);
});

test("an approval attempt must name who tried", () => {
  assert.match(armAiCaseProblems({...good(), approval_attempt: {result: "refused"}}).join("|"), /must be a name/);
});
