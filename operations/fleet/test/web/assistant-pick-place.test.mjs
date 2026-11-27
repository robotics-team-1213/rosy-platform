import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { register } from "node:module";

globalThis.crypto ??= webcrypto;
register("./resolve-console-assets.mjs", import.meta.url);

const { OBJECT_STALE_MS } = await import("/console/assets/cell-cam-objects.js");
const { flattenCatalogObjects, renderObjectPickPlaceCard } = await import("/console/assets/assistant-pick-place.js");

function makeEl(tag) {
  const attrs = {};
  const listeners = new Map();
  const children = [];
  const el = {
    tagName: tag.toUpperCase(),
    children,
    textContent: "",
    value: "",
    disabled: false,
    dataset: {},
    setAttribute(k, v) {
      attrs[k] = String(v);
      if (k === "disabled") el.disabled = true;
      if (k.startsWith("data-")) {
        const camel = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        el.dataset[camel] = String(v);
      }
    },
    getAttribute: (k) => attrs[k] ?? null,
    hasAttribute: (k) => Object.hasOwn(attrs, k),
    removeAttribute(k) { delete attrs[k]; if (k === "disabled") el.disabled = false; },
    append(...nodes) { for (const n of nodes) if (n) children.push(n); },
    addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn); },
    dispatch(type) { for (const fn of listeners.get(type) || []) fn({ target: el }); },
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

function installDom(t) {
  const prev = globalThis.document;
  globalThis.document = { createElement: (tag) => makeEl(tag) };
  t.after(() => { globalThis.document = prev; });
}

const sampleObjects = (nowMs) => ({
  schema: "rosy.cell-detected-objects.v1",
  fetchedAtMs: nowMs,
  cells: {
    cell_s: {
      cell_id: "cell_s",
      cell_state_gen: 9,
      arms: {
        arm_s: {
          arm_id: "arm_s",
          source_seq: 31,
          observed_at: 1000.0,
          ttl_s: 15.0,
          cell_state_gen: 9,
          stale: false,
          objects: [
            { object_ref: "det:31:0", catalog_id: "container-1", site: "pinky", centre_mm: [12, 5], pickable: true, bind_tol_mm: 13.5 },
            { object_ref: "det:31:1", catalog_id: "unmatched", site: "pinky", centre_mm: [0, 0], pickable: true },
            { object_ref: "det:31:2", catalog_id: "container-2", site: "belt", centre_mm: [80, 10], pickable: false, veto_reason: "blocked" },
          ],
        },
      },
    },
  },
});

const answeredRow = {
  request_id: "req-1",
  state: "ANSWERED",
  kind: "STATUS",
  facts: [{ ref: "cell_objects:cell_s", text: "cell_s 카탈로그 객체: container-1@pinky(1개, 선택가능)", observed_at: 1000 }],
};

test("flattenCatalogObjects excludes unmatched and expired snapshots", () => {
  const fresh = sampleObjects(Date.now());
  const rows = flattenCatalogObjects(fresh, fresh.fetchedAtMs + 500);
  assert.equal(rows.length, 2);
  assert.equal(rows.some((r) => r.object.catalog_id === "unmatched"), false);
  assert.equal(flattenCatalogObjects(fresh, fresh.fetchedAtMs + OBJECT_STALE_MS + 100).length, 0);
});

test("renderObjectPickPlaceCard syncs highlight, builds one-shot payload, and locks on 5s click-time expiry", (t) => {
  installDom(t);
  let now = 300_000;
  t.mock.method(Date, "now", () => now);
  const data = sampleObjects(now);
  let hl = null;
  let draft = null;
  let submitted = null;

  const card = renderObjectPickPlaceCard({
    row: answeredRow,
    cellObjects: data,
    highlightedRef: "det:31:0",
    executionEnabled: true,
    available: true,
    identity: "alice",
    onHighlightObject: (ref) => { hl = ref; },
    onDraftChange: (d) => { draft = d; },
    onSubmit: (payload) => { submitted = payload; },
  });
  const chips = card.querySelectorAll((e) => Boolean(e.dataset.assistantObjChip));
  assert.equal(chips.length, 2);
  assert.equal(chips[0].getAttribute("aria-pressed"), "true");
  assert.equal(chips[1].disabled, true);

  chips[0].dispatch("click");
  assert.equal(hl, "det:31:0");
  assert.equal(draft.objectRef, "det:31:0");

  const submitBtn = card.querySelectorAll((e) => e.dataset.assistantObjSubmit === "true")[0];
  assert.equal(submitBtn.hasAttribute("disabled"), false);
  submitBtn.dispatch("click");
  const body = submitted.buildTaskBody();
  assert.equal(body.propose, false);
  assert.equal(body.target_object.catalog_id, "container-1");
  assert.equal(body.target_object.expected_cell_state_gen, 9);

  // Advance clock past 5s without re-render -> click-time lockout must refuse dispatch
  submitted = null;
  now += OBJECT_STALE_MS + 100;
  submitBtn.dispatch("click");
  assert.equal(submitted, null);
  assert.equal(Boolean(submitBtn.disabled), true);

  const receiptCard = renderObjectPickPlaceCard({
    row: answeredRow,
    receipt: { task: { task_id: "ct-9", arm_id: "arm_s", status: "QUEUED" } },
  });
  assert.ok(receiptCard.querySelectorAll((e) => e.tagName === "A" && (e.href || e.getAttribute("href")) === "/console/cell").length === 1);
});
