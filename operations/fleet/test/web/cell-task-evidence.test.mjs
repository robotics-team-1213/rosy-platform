import test from "node:test";
import assert from "node:assert/strict";

import {
  BED_CONFIRM_TTL_S,
  bedConfirmPath,
  bedConfirmState,
  cellTaskRows,
  dstSiteOptions,
  presenceConfirmPath,
  presenceConfirmState,
  refusalText,
  visualCardSpecs,
} from "../../../../applications/fleet/web/cell/cell-real2sim-specs.js";
import {createCellActions} from "../../../../applications/fleet/web/cell/cell-real2sim-actions.js";

const queued = (extra = {}) => ({task_id: "t1", cell_id: "cell_s", arm_id: "arm_s", robot_id: "rosy_46",
  src_site: "pinky", dst_site: "belt", status: "QUEUED", ...extra});

test("bed confirmation states come from the row's server age", () => {
  assert.equal(bedConfirmPath("a b"), "/api/fleet/pipeline/cell-tasks/a%20b/bed-confirm");
  assert.equal(bedConfirmState(queued()).state, "none");
  const valid = bedConfirmState(queued({bed_confirmation: {age_s: 30.4, invalid: false}}), 0);
  assert.equal(valid.state, "valid");
  assert.equal(valid.remaining_s, BED_CONFIRM_TTL_S - 31);
  assert.match(valid.text, /89초 남음/);
  assert.equal(bedConfirmState(queued({bed_confirmation: {age_s: 121}})).state, "expired");
  assert.equal(bedConfirmState(queued({bed_confirmation: {age_s: 5, invalid: true}})).state, "voided");
});

test("card bed button targets the cell's first queued task and says its state", () => {
  const tasks = [
    {...queued({task_id: "done", status: "COMPLETED"})},
    queued({bed_confirmation: {age_s: 5, invalid: true}}),
    queued({task_id: "t2"}),
  ];
  const [cellS, cellAb] = visualCardSpecs({tasks});
  const bed = cellS.buttons.filter(b => b.bedConfirmTaskId);
  assert.equal(bed.length, 1);
  assert.equal(bed[0].bedConfirmTaskId, "t1");
  assert.equal(bed[0].robot_id, "rosy_46");
  assert.equal(bed[0].bedState, "voided");
  assert.match(bed[0].label, /무효.*다시 확인/);
  assert.ok(!cellAb.buttons.some(b => b.bedConfirmTaskId), "no queued task, no bed button");
  const presence = cellS.buttons.filter(b => b.presenceConfirmTaskId);
  assert.equal(presence.length, 1);
  assert.equal(presence[0].presenceConfirmTaskId, "t1");
  assert.equal(presence[0].presenceState, "none");
  assert.match(presence[0].label, /^입회 표시 \(t1 · rosy_46\)$/);
  assert.equal(cellS.buttons.indexOf(presence[0]), cellS.buttons.indexOf(bed[0]) + 1, "presence sits next to bed");
  assert.ok(!cellAb.buttons.some(b => b.presenceConfirmTaskId));
  const running = visualCardSpecs({tasks: [queued({status: "RUNNING"})]})[0];
  assert.ok(!running.buttons.some(b => b.bedConfirmTaskId));
});

test("presence mark has the bed confirmation's states", () => {
  assert.equal(presenceConfirmPath("t1"), "/api/fleet/pipeline/cell-tasks/t1/presence-confirm");
  assert.equal(presenceConfirmState(queued()).state, "none");
  const valid = presenceConfirmState(queued({presence_confirmation: {age_s: 20}}), 0);
  assert.equal(valid.state, "valid");
  assert.match(valid.text, /^입회 표시됨 · 100초 남음/);
  assert.equal(presenceConfirmState(queued({presence_confirmation: {age_s: 200}})).text, "입회 표시 만료");
  assert.equal(presenceConfirmState(queued({presence_confirmation: {age_s: 1, invalid: true}})).state, "voided");
  const rows = cellTaskRows({tasks: [queued({presence_confirmation: {age_s: 20}})]});
  assert.match(rows[0][5], /입회 표시됨/);
});

test("refusal codes are said as the missing evidence", () => {
  assert.equal(refusalText(null), "");
  assert.match(refusalText({code: "AMR_BRAKE_BED_VELOCITY_UNMEASURED", op: "claim"}), /^시작 거부 · 핑키 정지·정차 위치·적재함 확인/);
  assert.equal(refusalText({code: "AMR_BRAKE_BED_VELOCITY_UNMEASURED", op: "claim", missing: ["wheel_brake_locked", "v_cmd_mps", "bed_ready"]}),
    "시작 거부 · 측정되지 않음: 정지, 적재함 확인");
  assert.match(refusalText({code: "OMX_OWNER_EVIDENCE_UNAVAILABLE", op: "complete"}), /^완료 거부 · 팔 셀이 보낸 완료 증거가 없습니다/);
  assert.match(refusalText({code: "UNVERIFIED_CELL_COMPLETION", op: "complete"}), /확인되지 않은/);
  assert.match(refusalText({code: "OWNER_PRINCIPAL_NOT_REGISTERED", op: "complete"}), /주인으로 등록되지 않았습니다/);
  assert.match(refusalText({code: "REVIEW_REQUIRED", op: "claim"}), /^시작 거부 · 검토 필요 · .*입회 표시가 필요합니다/);
  assert.match(refusalText({code: "SOMETHING_NEW", op: "claim"}), /사유 확인 필요 \(SOMETHING_NEW\)/);
  const rows = cellTaskRows({tasks: [queued({last_refusal: {code: "OMX_OWNER_EVIDENCE_UNAVAILABLE", op: "complete"}, status: "RUNNING"})]});
  assert.match(rows[0][5], /완료 거부/);
  const [card] = visualCardSpecs({tasks: [queued({last_refusal: {code: "AMR_BRAKE_BED_VELOCITY_UNMEASURED", op: "claim"}})]});
  assert.match(card.folded_state, /시작 거부/);
});

test("destinations come only from the server's presets and export stations for the cell", () => {
  const body = {
    presets: [
      {cell_id: "cell_s", dst_site: "belt", tier: 1},
      {cell_id: "cell_ab", dst_site: "pallet-l0", tier: 1},
      {cell_id: "cell_ab", dst_site: "pallet-l1", tier: 2},
    ],
    station_zones: {export_stations: [{id: "EXP_X", cell_id: "cell_ab", dst_site: "pallet-l1", tier: 2}]},
  };
  assert.deepEqual(dstSiteOptions(body, "cell_s", 1), ["belt"]);
  assert.deepEqual(dstSiteOptions(body, "cell_ab", "2"), ["pallet-l1"]);
  assert.deepEqual(dstSiteOptions(null, "cell_s", 1), []);
});

function button() {
  const attrs = {};
  return {dataset: {}, disabled: false, listeners: {}, attrs,
    setAttribute(k, v) { attrs[k] = v; }, addEventListener(k, fn) { this.listeners[k] = fn; }};
}

test("bed button is off without a named operator and posts the robot when on", async () => {
  const calls = [];
  const els = {};
  let reason = "이름 있는 운영자 로그인이 필요합니다";
  let gen = 0;
  let fail = null;
  const ctx = {
    request: async (path, opts) => {
      calls.push([path, opts]);
      if (fail) throw fail;
      return {ok: true, renewed: true, expires_in_s: 120};
    },
    $: id => (els[id] ??= {textContent: ""}),
    namedReason: () => reason,
    bump: () => ++gen, gen: () => gen,
    refreshCellTasks: async () => {},
  };
  const actions = createCellActions(ctx);
  const off = button();
  actions.bindActionButton(off, {bedConfirmTaskId: "t1", robot_id: "rosy_46"});
  assert.equal(off.disabled, true);
  assert.equal(off.attrs.reason, reason);
  reason = "";
  const on = button();
  actions.bindActionButton(on, {bedConfirmTaskId: "t1", robot_id: "rosy_46"});
  assert.equal(on.disabled, false);
  await actions.confirmBed("t1", "rosy_46");
  assert.equal(calls[0][0], "/api/fleet/pipeline/cell-tasks/t1/bed-confirm");
  assert.deepEqual(JSON.parse(calls[0][1].body), {robot_id: "rosy_46"});
  assert.match(els["cell-tasks-status"].textContent, /120초 동안 유효/);
  fail = Object.assign(new Error("x"), {status: 409, code: "BED_CONFIRM_POSE_UNAVAILABLE"});
  await actions.confirmBed("t1", "rosy_46");
  assert.match(els["cell-tasks-status"].textContent, /핑키 위치를 확인하지 못했습니다/);
  fail = Object.assign(new Error("Not Found"), {status: 404});
  await actions.confirmBed("t1", "rosy_46");
  assert.match(els["cell-tasks-status"].textContent, /기능이 아직 없습니다/);
  fail = null;
  const presenceOff = button();
  reason = "운영자 권한이 필요합니다";
  actions.bindActionButton(presenceOff, {presenceConfirmTaskId: "t1", robot_id: "rosy_46"});
  assert.equal(presenceOff.disabled, true);
  assert.equal(presenceOff.dataset.presenceConfirmTaskId, "t1");
  await actions.confirmPresence("t1", "rosy_46");
  assert.equal(calls.at(-1)[0], "/api/fleet/pipeline/cell-tasks/t1/presence-confirm");
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), {robot_id: "rosy_46"});
  assert.equal(els["cell-tasks-status"].textContent, "태스크(t1) 입회 표시 완료 · 120초 동안 유효");
});
