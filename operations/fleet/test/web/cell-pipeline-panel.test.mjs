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
        tasks: [],
      },
      {robot_layer: {robots: [{robot_id: "rosy_77"}]}},
      {batch_id: "u-1", completed: 0, expected: 1, ready: false, reasons: ["UNLOAD_IN_PROGRESS"]},
    );
    const panelEl = root.children[0];
    registerIds(panelEl);
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
    const panel2 = createPipelinePanel({
      $: id => byId[id] || null,
      state,
      namedReason: () => "",
      invokeRecoveryTool: p => invCalls.push(p),
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
