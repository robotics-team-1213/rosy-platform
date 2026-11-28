import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { register } from "node:module";

globalThis.crypto ??= webcrypto;
register("./resolve-console-assets.mjs", import.meta.url);

const { createCellObjectStager, createArmCommandSection } = await import("/console/assets/arm-cell-controls.js");

function makeNode(tag) {
  const attrs = {};
  const listeners = new Map();
  const children = [];
  const el = {
    tagName: tag.toUpperCase(),
    children,
    textContent: "",
    value: "",
    disabled: false,
    checked: false,
    dataset: {},
    setAttribute(k, v) {
      attrs[k] = String(v);
      if (k === "disabled") el.disabled = true;
      if (k.startsWith("data-")) el.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(v);
    },
    getAttribute: (k) => attrs[k] ?? null,
    hasAttribute: (k) => Object.hasOwn(attrs, k),
    removeAttribute(k) { delete attrs[k]; if (k === "disabled") el.disabled = false; },
    append(...nodes) { for (const n of nodes) if (n) children.push(typeof n === "string" ? { nodeType: 3, textContent: n } : n); },
    replaceChildren(...nodes) { children.length = 0; el.append(...nodes); },
    addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn); },
    dispatch(type) { for (const fn of listeners.get(type) || []) fn({ target: el, stopPropagation() {}, preventDefault() {} }); },
    querySelectorAll(pred) {
      const out = [];
      for (const ch of children) {
        if (pred(ch)) out.push(ch);
        if (ch.querySelectorAll) out.push(...ch.querySelectorAll(pred));
      }
      return out;
    },
  };
  Object.defineProperty(el, "className", { get: () => attrs.class || "", set: (v) => el.setAttribute("class", v) });
  return el;
}

test("createCellObjectStager syncs objectHighlight and dispatches 1-shot bound pick-place", async (t) => {
  const prevDoc = globalThis.document;
  globalThis.document = { createElement: (tag) => makeNode(tag) };
  t.after(() => { globalThis.document = prevDoc; });

  let hl = null;
  const subs = [];
  const objectHighlight = {
    get: () => hl,
    set: (v) => { hl = v; subs.forEach((fn) => fn(v)); },
    subscribe: (fn) => { subs.push(fn); return () => {}; },
  };
  const calls = [];
  let confirmedMsg = "";
  const stager = createCellObjectStager({
    scope: { onDispose() {} },
    call: async (path, opts) => { calls.push({ path, body: JSON.parse(opts.body) }); return { task: { task_id: "ct-1" } }; },
    auth: { locked: false },
    objectHighlight,
    confirmedAction: { run: async ({ message, request }) => { confirmedMsg = message; await request(); } },
    isOperator: () => true,
  });

  const cam = { id: "arm_s_top", source: "arm_s_top" };
  const opts = stager.overlayOpts(cam, false);
  const obj = { object_ref: "det:9:0", catalog_id: "container-1", site: "pinky", centre_mm: [10, 20], pickable: true, bind_tol_mm: 13.5 };
  opts.onSelectObject(obj);
  assert.equal(hl, "det:9:0");

  const snapHost = makeNode("div");
  const data = {
    schema: "rosy.cell-detected-objects.v1",
    fetchedAtMs: Date.now(),
    cells: { cell_s: { cell_id: "cell_s", cell_state_gen: 3, arms: { arm_s: { arm_id: "arm_s", source_seq: 9, observed_at: 1000, ttl_s: 15, stale: false, cell_state_gen: 3, objects: [obj] } } } },
  };
  stager.renderStagingBar(snapHost, [cam], data);
  const dispatchBtn = snapHost.querySelectorAll((e) => e.dataset?.objDispatch === "true")[0];
  assert.equal(Boolean(dispatchBtn.disabled), false);
  dispatchBtn.dispatch("click");
  await new Promise((r) => setTimeout(r, 0));
  assert.match(confirmedMsg, /할까요\?$/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/fleet/pipeline/cell-tasks");
  assert.equal(calls[0].body.propose, false);
  assert.equal(calls[0].body.target_object.catalog_id, "container-1");
});

test("createArmCommandSection renders arm presets & incident clear with named-operator lockouts", async (t) => {
  const prevDoc = globalThis.document;
  globalThis.document = { createElement: (tag) => makeNode(tag) };
  t.after(() => { globalThis.document = prevDoc; });

  const calls = [];
  let isOp = false;
  const sec = createArmCommandSection({
    call: async (path, opts) => { calls.push({ path, body: JSON.parse(opts.body) }); return { task: { task_id: "arm-cmd-1" } }; },
    confirmedAction: { run: async ({ request }) => request() },
    isOperator: () => isOp,
  });
  const obsArm = {
    id: "arm_s", sourceId: "arm_s",
    openIncidents: [{ incident_id: "inc-1", decision: { reason: "a person checks the arm (jaws)" } }],
  };
  const root = sec.sync("arm_s", obsArm);
  const shuttleBtn = root.querySelectorAll((e) => e.dataset?.armPreset === "s3_shuttle")[0];
  assert.equal(Boolean(shuttleBtn.disabled), true);
  assert.ok(shuttleBtn.getAttribute("reason"));

  isOp = true;
  sec.sync("arm_s", obsArm);
  const enabledShuttle = root.querySelectorAll((e) => e.dataset?.armPreset === "s3_shuttle")[0];
  assert.equal(Boolean(enabledShuttle.disabled), false);
  enabledShuttle.dispatch("click");
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(calls[0].body.preset, "s3_shuttle");
  assert.equal(calls[0].body.propose, false);
});
