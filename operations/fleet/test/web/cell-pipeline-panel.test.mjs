import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const panelUrl = new URL("../../../../applications/fleet/web/cell/cell-pipeline-panel.js", import.meta.url);
const causeUrl = new URL("../../../../shared/web/cause-line.js", import.meta.url);
const code = (await readFile(panelUrl, "utf8")).replace("/common/cause-line.js", causeUrl.href);
const {
  discoverPinkyIds,
  formatPinkyTaskRow,
  createPipelinePanel,
} = await import(`data:text/javascript,${encodeURIComponent(code)}`);

function makeNode(tag = "div") {
  const attrs = new Map();
  const children = [];
  const el = {
    tagName: tag.toUpperCase(),
    id: "",
    className: "",
    dataset: {},
    value: "",
    selected: false,
    textContent: "",
    disabled: false,
    children,
    parentNode: null,
    listeners: {},
    setAttribute(k, v) { attrs.set(k, String(v)); if (k === "disabled") el.disabled = true; },
    removeAttribute(k) { attrs.delete(k); if (k === "disabled") el.disabled = false; },
    getAttribute(k) { return attrs.get(k) ?? null; },
    hasAttribute(k) { return attrs.has(k); },
    append(...items) {
      for (const item of items) {
        if (item && typeof item === "object") item.parentNode = el;
        children.push(item);
      }
    },
    insertBefore(newNode) {
      if (newNode && typeof newNode === "object") newNode.parentNode = el;
      children.unshift(newNode);
    },
    replaceChildren(...items) {
      children.length = 0;
      el.append(...items);
    },
    addEventListener(type, fn) {
      (el.listeners[type] ??= []).push(fn);
    },
    click() {
      for (const fn of el.listeners.click || []) fn({stopPropagation() {}});
    },
  };
  return el;
}

test("discoverPinkyIds prefers status and docked robots over defaults", () => {
  assert.deepEqual(discoverPinkyIds({}, {}), ["rosy_46", "rosy_45", "rosy_42"]);
  assert.deepEqual(
    discoverPinkyIds(
      {cells: {cell_s: {gate: {docked_robot: {robot_id: "rosy_77"}}}}, pinky_tasks: [{robot_id: "rosy_88"}]},
      {robot_layer: {robots: [{robot_id: "rosy_99"}]}},
    ),
    ["rosy_99", "rosy_77", "rosy_88"],
  );
  assert.deepEqual(
    formatPinkyTaskRow({task_id: "p1", robot_id: "rosy_99", action: "depart_s3", place_id: "S1", status: "REFUSED", reason: "ARM_NOT_HOME"}),
    ["p1", "rosy_99", "depart_s3", "S1", "REFUSED", "ARM_NOT_HOME", "—"],
  );
});

test("createPipelinePanel renders banner, depart gate, cancel and repark controls", () => {
  const prevDoc = globalThis.document;
  const root = makeNode("div");
  const cardsEl = makeNode("div");
  cardsEl.id = "cell-visual-cards";
  root.append(cardsEl);
  const byId = {"cell-visual-cards": cardsEl};
  const registerIds = (node) => {
    if (node?.id) byId[node.id] = node;
    for (const c of node?.children || []) if (c && typeof c === "object") registerIds(c);
  };
  globalThis.document = {
    createElement(tag) { return makeNode(tag); },
  };
  try {
    const calls = [];
    const state = {selectedRobotId: "rosy_77"};
    const panel = createPipelinePanel({
      $: id => byId[id] || null,
      state,
      namedReason: () => "",
      runPinkyQuickAction: (rid, act) => calls.push(["pinky", rid, act]),
      runQuickPreset: (p, rid) => calls.push(["preset", p, rid]),
      cancelPinkyTask: id => calls.push(["cancel_pinky", id]),
      closeRepark: (id, st) => calls.push(["repark", id, st]),
      cancelOrRetryTask: (id, op) => calls.push(["cell_op", id, op]),
    });
    panel.render(
      {
        pinky_dispatch_enabled: false,
        repark_requests: {rosy_77: {request_id: "rp-1", robot_id: "rosy_77", state: "REQUESTED", need_site_dxdy_m: [0.01, -0.02]}},
        pinky_tasks: [{task_id: "pt-1", robot_id: "rosy_77", action: "dock_s3", status: "QUEUED"}],
        calibration_origin: "https://cal.test:9449",
        tasks: [
          {task_id: "source", arm_id: "arm_s", status: "CANCELLED"},
          {task_id: "move", arm_id: "arm_a", status: "QUEUED", depends_on: "source"},
          {task_id: "ship", arm_id: "arm_b", status: "QUEUED", depends_on: "move",
            src_site: "tmp-b-2-l1", dst_site: "ship-h1r2-l0", cell_id: "cell_ab", src_site_id: "temp_b:r1-s2:l2", dst_site_id: "yard:r1-s1:l1"},
          {task_id: "supply:1", cell_id: "cell_s", arm_id: "arm_s", src_site: "pinky", dst_site: "belt"},
          {task_id: "invalid&1", cell_id: "cell_s", arm_id: "arm_s", src_site: "pinky", dst_site: "belt"},
          {task_id: "recovery", cell_id: "cell_s", arm_id: "arm_s", src_site: "pinky", dst_site: "belt", displaced_to: "belt_far"},
          {task_id: "legacy", cell_id: "cell_ab", arm_id: "arm_a", src_site: "belt", dst_site: "pallet-l0"},
          {task_id: "unrelated", arm_id: "arm_s", status: "FAILED"},
          {task_id: "orphan", arm_id: "arm_b", status: "QUEUED", depends_on: "missing"},
        ],
      },
      {robot_layer: {robots: [{robot_id: "rosy_77"}]}},
      {batch_id: "u-1", completed: 0, expected: 1, ready: false, reasons: ["UNLOAD_IN_PROGRESS"]},
    );
    const panelEl = root.children[0];
    registerIds(panelEl);
    const tables = panelEl.children.flatMap(node => node.children).filter(node => node.tagName === "TABLE");
    const chain = tables.find(table => table.children[0].textContent === "셀 작업과 경로 점검");
    const rows = chain.children[2].children.map(row => row.children.map(cell => cell.textContent));
    assert.deepEqual(rows.map(row => row[0]), ["source", "move", "ship", "supply:1", "orphan"]);
    assert.deepEqual(rows[1].slice(4, 6), ["source", "CANCELLED"]);
    assert.deepEqual(rows[2].slice(2, 6), ["tmp-b-2-l1 → ship-h1r2-l0", "QUEUED", "move", "QUEUED"]);
    assert.deepEqual(rows[4].slice(4, 6), ["missing", "상태 미확인"]);
    const actions = chain.children[2].children.map(row => row.children[6].children[0]);
    assert.equal(actions[0], undefined);
    const links = actions.filter(Boolean).map(link => new URL(link.href));
    assert.deepEqual(links.map(link => link.origin), ["https://cal.test:9449", "https://cal.test:9449"]);
    assert.deepEqual(links.map(link => link.hash), ["#route-arm_b", "#route-arm_s"]);
    assert.deepEqual(links.map(link => Object.fromEntries(link.searchParams)), [
      {arm: "arm_b", src_site: "tmp-b-2-l1", dst_site: "ship-h1r2-l0", task_id: "ship"},
      {arm: "arm_s", src_site: "pinky", dst_site: "belt", task_id: "supply:1"},
    ]);
    assert.equal(panelEl.id, "cell-pipeline-panel");
    const buttons = [];
    const walk = n => {
      if (n?.tagName === "UI-BUTTON") buttons.push(n);
      for (const c of n?.children || []) if (c && typeof c === "object") walk(c);
    };
    walk(panelEl);

    assert.match(panelEl.children[0].textContent, /ROSY_FLEET_PINKY_TASK_DISPATCH=1 미활성/);
    const departBtn = buttons.find(b => b.textContent.includes("depart_s3"));
    assert.equal(departBtn.disabled, true);
    assert.match(departBtn.getAttribute("reason"), /UNLOAD_IN_PROGRESS/);
    const cancelBtn = buttons.find(b => b.textContent === "취소");
    cancelBtn.click();
    const reparkDone = buttons.find(b => b.textContent === "재주차 완료(DONE)");
    reparkDone.click();
    assert.deepEqual(calls, [["cancel_pinky", "pt-1"], ["repark", "rp-1", "DONE"]]);

    // Recovery handoff renders unresolved failures, blocks repick on FOLD_READBACK_MISSING, and passes CAS sha.
    const invCalls = [];
    const admitCalls = [];
    const cancelCalls = [];
    const panel2 = createPipelinePanel({
      $: id => byId[id] || null,
      state,
      namedReason: () => "",
      invokeRecoveryTool: p => invCalls.push(p),
      admitCellPlan: p => admitCalls.push(p.plan_id),
      cancelCellPlan: p => cancelCalls.push(p.plan_id),
    });
    panel2.render(
      {
        pinky_tasks: [],
        tasks: [],
        recovery_handoff: {
          active_failures: [{
            root_task_id: "t-f1",
            trigger_code: "FOLD_READBACK_MISSING",
            arm_id: "arm_s",
            state: "READY",
            homing_stage: "IDLE",
            cameras_fresh: true,
            camera_sequences: {arm_s_top: 12, arm_s_wrist: 9},
            vetoes: ["OUT_OF_HOME_POSE"],
            context_sha256: "a".repeat(64),
            homing_strategies: {
              release_and_lift: {allowed: true, reason: null},
              guarded_slow_park: {allowed: false, reason: "VISUAL_CLEAR_CHECKPOINT_REQUIRED"},
              auto_fold: {allowed: true, reason: null},
              finalize_home_verify: {allowed: false, reason: "FINALIZE_HOME_VISUAL_REQUIRED"},
            },
            eligible_tools: {
              safe_fold_home: {allowed: true, reason: null},
              record_visual_checkpoint: {allowed: true, reason: null},
              enqueue_vla_act_fallback: {allowed: false, reason: "PLACEMENT_ALREADY_VERIFIED_HOME_ONLY"},
            },
          }],
          recent_invocations: [],
        },
      },
      {robot_layer: {robots: [{robot_id: "rosy_77"}]}},
      {ready: false, reasons: ["UNLOAD_ABORTED"]},
      {
        plans: [
          {
            plan_id: "plan-1",
            mode: "harbor_plan",
            order_source: "harbor",
            status: "PROPOSED",
            completed_steps: 0,
            total_steps: 2,
            hold_reason: null,
          },
          {
            plan_id: "plan-2",
            mode: "outbound",
            order_source: "rosy_r",
            status: "COMPLETED",
            completed_steps: 2,
            total_steps: 2,
            hold_reason: null,
          },
        ],
      },
    );
    const b2 = [];
    const collectBtns = n => {
      if (n?.tagName === "UI-BUTTON") b2.push(n);
      for (const ch of n?.children || []) if (ch && typeof ch === "object") collectBtns(ch);
    };
    collectBtns(panelEl);
    const actBtn = b2.find(b => b.textContent.includes("ACT 폴백"));
    assert.equal(actBtn.disabled, true);
    assert.equal(actBtn.getAttribute("reason"), "PLACEMENT_ALREADY_VERIFIED_HOME_ONLY");
    const slowParkBtn = b2.find(b => b.textContent === "가드 홈 복귀(park)");
    assert.equal(slowParkBtn.disabled, true);
    assert.equal(slowParkBtn.getAttribute("reason"), "VISUAL_CLEAR_CHECKPOINT_REQUIRED");
    const liftBtn = b2.find(b => b.textContent === "그리퍼 열기+상승");
    assert.equal(liftBtn.disabled, false);
    liftBtn.click();
    const visBtn = b2.find(b => b.textContent === "3카메라 이탈 확인");
    assert.equal(visBtn.disabled, false);
    visBtn.click();
    const admitPlanBtns = b2.filter(b => b.textContent === "일괄 승인");
    const cancelPlanBtns = b2.filter(b => b.textContent === "계획 취소");
    assert.equal(admitPlanBtns.length, 2);
    assert.equal(cancelPlanBtns.length, 2);
    // Rendered in reverse chronological order: plan-2 (COMPLETED, disabled) then plan-1 (PROPOSED, enabled).
    assert.equal(admitPlanBtns[0].disabled, true);
    assert.equal(cancelPlanBtns[0].disabled, true);
    assert.equal(admitPlanBtns[1].disabled, false);
    assert.equal(cancelPlanBtns[1].disabled, false);
    admitPlanBtns[1].click();
    cancelPlanBtns[1].click();
    assert.deepEqual(admitCalls, ["plan-1"]);
    assert.deepEqual(cancelCalls, ["plan-1"]);
    assert.equal(invCalls.length, 2);
    assert.equal(invCalls[0].tool_name, "safe_fold_home");
    assert.equal(invCalls[0].arguments.strategy, "release_and_lift");
    assert.equal(invCalls[0].expected_context_sha256, "a".repeat(64));
    assert.equal(invCalls[1].tool_name, "record_visual_checkpoint");
    assert.deepEqual(invCalls[1].arguments.cameras_checked, {arm_s_top: 12, arm_s_wrist: 9});
  } finally {
    globalThis.document = prevDoc;
  }
});
