import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);

const {
  hasPendingCorrection,
  correctionPayload,
  custodyView,
  correctionView,
  createNamedStopActions,
} = await import("../../../../applications/fleet/web/map/named-stop-actions.js");

const RUN_ID = "11111111-2222-3333-4444-555555555555";
const MAP_SHA = "a".repeat(64);

function makeTrip(extra = {}) {
  return {
    trip_id: "trip-1",
    robot_id: "pinky_1",
    hold: null,
    detail: {
      named_stop_operation: { run_id: RUN_ID },
      named_stop_dispatch: { place: "S3", map_sha256: MAP_SHA },
      named_stop_precision: { decision: "HOLD", reason: "camera_disagrees_with_pose", forward_m: 0.04, site_end: [0.745, -0.207] },
    },
    ...extra,
  };
}

function makeDoc() {
  const slots = {};
  const mk = (tag = "DIV") => {
    const el = {
      tagName: String(tag).toUpperCase(),
      className: "",
      type: "",
      value: "",
      placeholder: "",
      textContent: "",
      checked: false,
      selected: false,
      disabled: false,
      open: false,
      dataset: {},
      attributes: new Map(),
      listeners: {},
      children: [],
      get firstElementChild() { return el.children[0] || null; },
      setAttribute(k, v) { el.attributes.set(k, String(v)); },
      getAttribute(k) { return el.attributes.get(k) ?? null; },
      hasAttribute(k) { return el.attributes.has(k); },
      removeAttribute(k) { el.attributes.delete(k); },
      addEventListener(type, fn) { (el.listeners[type] ??= []).push(fn); },
      append(...nodes) {
        for (const n of nodes) if (typeof n !== "string") { n.parentElement = el; el.children.push(n); }
      },
      replaceChildren(...nodes) { el.children = []; el.append(...nodes); },
      contains(target) {
        if (target === el) return true;
        return el.children.some((c) => c.contains?.(target));
      },
      querySelector(sel) {
        const m = sel.match(/^\[([a-z0-9-]+)="([^"]+)"\]$/i);
        for (const c of el.children) {
          if (m) {
            const attr = m[1];
            const val = m[2];
            if (c.getAttribute(attr) === val || c.dataset[attr.replace(/^data-/, "").replace(/-([a-z])/g, (_, x) => x.toUpperCase())] === val) return c;
          }
          const hit = c.querySelector?.(sel);
          if (hit) return hit;
        }
        return null;
      },
      querySelectorAll(sel) {
        const out = [];
        const walk = (n) => {
          for (const c of n.children || []) {
            if (sel === "ui-button" && c.tagName === "UI-BUTTON") out.push(c);
            else if (sel === "input" && c.tagName === "INPUT") out.push(c);
            walk(c);
          }
        };
        walk(el);
        return out;
      },
      focus() {},
    };
    return el;
  };
  return {
    slots,
    doc: {
      activeElement: null,
      createElement: mk,
      querySelector(sel) {
        const m = sel.match(/^\[data-decision-slot="([^"]+)"\]$/);
        return m ? slots[m[1]] || null : null;
      },
    },
    ensureSlot(key) {
      return (slots[key] ??= mk("DIV"));
    },
  };
}

test("hasPendingCorrection and correctionPayload match precision_correction_routes schema", () => {
  const trip = makeTrip();
  assert.equal(hasPendingCorrection(trip), true);
  assert.deepEqual(correctionPayload(trip, true), {
    nav_run_id: RUN_ID,
    map_sha256: MAP_SHA,
    forward_m: 0.04,
    site_end: [0.745, -0.207],
    cable_and_path_clear: true,
  });
  assert.equal(hasPendingCorrection(makeTrip({ hold: { reason: "replan" } })), false);
  assert.equal(hasPendingCorrection(makeTrip({
    detail: { ...trip.detail, named_stop_precision: { decision: "IN_TOLERANCE", forward_m: 0.0, site_end: [0, 0] } },
  })), false);
});

test("custodyView and correctionView validate operator, reason, checkbox, and isolation evidence", () => {
  const robot = {
    robot_id: "pinky_1",
    named_stop_custody: { reservation_id: "res-1", missing_proof: "CORE standstill", operator_action: "현장 확인" },
  };
  assert.equal(custodyView(robot, { operator: false, reasonText: "ok!" }).releaseReason, "운영자 권한이 필요합니다");
  assert.equal(custodyView(robot, { operator: true, reasonText: "ab" }).releaseReason, "해제 사유를 3자 이상 입력하세요");
  assert.equal(custodyView(robot, { operator: true, reasonText: "확인함", isolated: true, isolationEvidence: "12" }).releaseReason, "물리 격리 근거를 3자 이상 입력하세요");
  assert.equal(custodyView(robot, { operator: true, reasonText: "확인함", isolated: true, isolationEvidence: "전원 차단 확인" }).releaseReason, "");

  const trip = makeTrip();
  assert.equal(correctionView(trip, { operator: true, cableClear: false }).confirmReason, "케이블·경로 이상 없음 확인을 체크하세요");
  assert.equal(correctionView(trip, { operator: true, cableClear: true }).confirmReason, "");
  assert.equal(correctionView(trip, { operator: true, cableClear: false }).cancelReason, "");
});

test("createNamedStopActions gates custody release and correction clearance behind confirm and records failures cleanly", async (t) => {
  const prevDoc = globalThis.document;
  const prevCss = globalThis.CSS;
  const { doc, ensureSlot } = makeDoc();
  globalThis.document = doc;
  globalThis.CSS = { escape: (s) => String(s) };
  t.after(() => { globalThis.document = prevDoc; globalThis.CSS = prevCss; });

  const slotCustody = ensureSlot("pinky_1|custody");
  const slotCorr = ensureSlot("pinky_1|correction");
  const posts = [];
  let allowConfirm = false;
  let answerError = null;
  const logs = [];
  const view = {
    stateUnavailable: false,
    robots: [{
      robot_id: "pinky_1",
      named_stop_custody: { reservation_id: "res-1", missing_proof: "velocity", operator_action: "점유 해제" },
    }],
    trafficTrips: [makeTrip()],
  };
  const actions = createNamedStopActions({
    scope: { capture: () => ({ check() {}, current: () => true, signal: undefined }), guard: (fn) => fn },
    view,
    call: async (path, opts) => {
      posts.push({ path, body: opts?.body ? JSON.parse(opts.body) : null });
      if (answerError) throw answerError;
      return { ok: true };
    },
    log: (text, kind) => logs.push({ text, kind }),
    isOperator: () => true,
    namedReason: () => "",
    confirmedAction: {
      run: async ({ message, eligible, request, onError }) => {
        assert.equal(eligible(), true, message);
        if (!allowConfirm) return;
        try {
          await request({ check() {}, signal: undefined });
        } catch (err) {
          onError(err);
        }
      },
    },
  });

  actions.render();
  const relBtn = slotCustody.querySelector('[data-named-stop-action="release"]');
  assert.equal(relBtn.disabled, false);
  await relBtn.listeners.click[0]();
  assert.equal(posts.length, 0, "canceled confirm posts nothing");

  allowConfirm = true;
  await relBtn.listeners.click[0]();
  assert.deepEqual(posts[0], {
    path: "/api/fleet/robots/pinky_1/named-stop-custody/release",
    body: { reservation_id: "res-1", reason: "현장 정지 확인 완료" },
  });

  // Correction requires cableClear checkbox before button unlocks; 409 shows alert without claiming success.
  const corrBtn = slotCorr.querySelector('[data-named-stop-action="correction"]');
  const cancelBtn = slotCorr.querySelector('[data-named-stop-action="cancel"]');
  assert.equal(corrBtn.disabled, true);
  const checkbox = slotCorr.querySelector('[data-named-stop-clear="check"]');
  checkbox.checked = true;
  checkbox.listeners.change[0]();
  assert.equal(corrBtn.disabled, false);

  answerError = Object.assign(new Error("scope changed"), { detail: { code: "NAMED_STOP_CORRECTION_SCOPE_CHANGED" } });
  await corrBtn.listeners.click[0]();
  assert.equal(posts[1].path, "/api/fleet/trips/trip-1/correction-clearance");
  assert.equal(logs.at(-1).kind, "bad");

  answerError = null;
  await cancelBtn.listeners.click[0]();
  assert.equal(posts[2].path, "/api/fleet/trips/trip-1/cancel");
  assert.equal(posts[2].body, null);
});

test("queues attentionItems emit crit decision rows for custody reservation and pending correction", async () => {
  const { createQueues } = await import("../../../../applications/fleet/web/queues.js");
  const view = {
    robots: [],
    formation: null,
    stateUnavailable: false,
    receivedAtMs: Date.now(),
    trafficTrips: [makeTrip()],
    endedTrips: [],
  };
  const { attentionItems } = createQueues({
    scope: { guard: (f) => f },
    el: () => ({}),
    view,
    render: () => {},
    streamEvidence: () => null,
  });
  const items = attentionItems({
    robot_id: "pinky_1",
    online: true,
    state: { safety: { estop: false } },
    named_stop_custody: { reservation_id: "res-1", missing_proof: "CORE standstill" },
  });
  assert.deepEqual(
    items.map((i) => [i.severity, i.decision]),
    [["crit", "correction"], ["crit", "custody"]]
  );
  const partial = attentionItems({
    robot_id: "rosy_46",
    online: true,
    state: { safety: { estop: false } },
    named_stop_custody: { motion_refused_site_wide: true, operator_action: "점유 해제 필요" },
  });
  assert.deepEqual(partial.map((i) => [i.severity, i.decision]), [["warn", undefined]]);
});
