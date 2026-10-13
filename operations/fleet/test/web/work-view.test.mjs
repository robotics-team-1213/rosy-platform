import test from "node:test";
import assert from "node:assert/strict";
import {workKey, workStatus} from "../../../site_ui/console/work-view.js";

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
