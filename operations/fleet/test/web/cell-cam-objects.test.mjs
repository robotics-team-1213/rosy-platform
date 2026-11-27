import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

const {
  OBJECT_STALE_MS, cellIdForCamView, armIdForCamView, isObjectSnapshotFresh,
  objectsForCamView, buildCamObjectsSvg, syncCamObjectsOverlay,
} = await import("/console/assets/cell-cam-objects.js");
const { buildInspectorStagingBar } = await import("/console/assets/cell-pick-place-staging.js");

function makeNode(tag, ns = "") {
  const attrs = {};
  const listeners = new Map();
  const children = [];
  const classSet = new Set();
  const el = {
    tagName: tag.toUpperCase(),
    namespaceURI: ns,
    children,
    textContent: "",
    dataset: {},
    classList: {
      contains: (c) => classSet.has(c),
      toggle: (c, force) => (force === undefined ? (classSet.has(c) ? classSet.delete(c) : classSet.add(c)) : (force ? classSet.add(c) : classSet.delete(c))),
    },
    setAttribute(k, v) {
      attrs[k] = String(v);
      if (k === "class") {
        classSet.clear();
        for (const c of String(v).split(/\s+/).filter(Boolean)) classSet.add(c);
      }
      if (k.startsWith("data-")) {
        const key = k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        el.dataset[key] = String(v);
      }
    },
    getAttribute: (k) => attrs[k] ?? null,
    hasAttribute: (k) => Object.hasOwn(attrs, k),
    removeAttribute: (k) => { delete attrs[k]; },
    append(...nodes) { for (const n of nodes) if (n) { n.parentElement = el; children.push(n); } },
    addEventListener(type, fn) { if (!listeners.has(type)) listeners.set(type, []); listeners.get(type).push(fn); },
    dispatch(type, ev = {}) {
      const event = { target: el, stopPropagation() { event.stopped = true; }, preventDefault() { event.defaultPrevented = true; }, ...ev };
      for (const fn of listeners.get(type) || []) fn(event);
      return event;
    },
    querySelector(sel) {
      const cls = sel.startsWith(".") ? sel.slice(1) : null;
      for (const ch of children) {
        if (cls && ch.classList?.contains(cls)) return ch;
        const deep = ch.querySelector?.(sel);
        if (deep) return deep;
      }
      return null;
    },
    querySelectorAll(sel) {
      const cls = sel.startsWith(".") ? sel.slice(1) : null;
      const out = [];
      for (const ch of children) {
        if (cls && ch.classList?.contains(cls)) out.push(ch);
        if (ch.querySelectorAll) out.push(...ch.querySelectorAll(sel));
      }
      return out;
    },
    remove() {
      if (!el.parentElement) return;
      const arr = el.parentElement.children;
      const idx = arr.indexOf(el);
      if (idx >= 0) arr.splice(idx, 1);
      el.parentElement = null;
    },
  };
  Object.defineProperty(el, "className", {
    get: () => attrs.class || "",
    set: (v) => el.setAttribute("class", v),
  });
  return el;
}

function installDom(t) {
  const prev = globalThis.document;
  globalThis.document = {
    createElement: (tag) => makeNode(tag),
    createElementNS: (ns, tag) => makeNode(tag, ns),
  };
  t.after(() => { globalThis.document = prev; });
}

const sampleObjects = (nowMs = Date.now()) => ({
  schema: "rosy.cell-detected-objects.v1",
  fetchedAtMs: nowMs,
  cells: {
    cell_s: {
      cell_id: "cell_s",
      cell_state_gen: 4,
      arms: {
        arm_s: {
          arm_id: "arm_s",
          source_seq: 19,
          observed_at: 1000.0,
          ttl_s: 15.0,
          cell_state_gen: 4,
          stale: false,
          objects: [
            { object_ref: "det:19:0", catalog_id: "container-1", site: "pinky", centre_mm: [10, 20], centre_px: [300, 220], corners_px: [[280, 200], [320, 200], [320, 240], [280, 240]], pickable: true, bind_tol_mm: 13.5 },
            { object_ref: "det:19:1", catalog_id: "unmatched", site: "pinky", centre_mm: [0, 0], pickable: true },
            { object_ref: "det:19:2", catalog_id: "container-2", site: "belt", centre_mm: [80, 10], centre_px: [420, 260], pickable: false, veto_reason: "no finger room" },
          ],
        },
      },
    },
  },
  by_arm: {},
});

test("cellIdForCamView excludes wrist/side/depth cameras and maps top cameras only", () => {
  assert.equal(cellIdForCamView({ id: "arm_s_top", label: "상단" }), "cell_s");
  assert.equal(cellIdForCamView({ id: "arm_s_wrist", label: "손목" }), null);
  assert.equal(cellIdForCamView({ id: "top", stream: "depth" }), null);
  assert.equal(cellIdForCamView({ source_id: "omx_overhead", role: "overhead" }), "cell_ab");
  assert.equal(armIdForCamView({ id: "arm_s_top" }), "arm_s");
});

test("buildCamObjectsSvg filters unmatched, exposes pickable only, enforces 5s stale lock, and supports AI highlight", (t) => {
  installDom(t);
  const now = 50_000;
  const data = sampleObjects(now);
  const cam = { id: "arm_s_top", source: "arm_s_top" };
  let picked = null;
  const svg = buildCamObjectsSvg(cam, data, {
    selectedRef: "det:19:0", aiHighlightRef: "det:19:0", zoomed: true, nowMs: now + 1000,
    onSelectObject: (o) => { picked = o; },
  });
  assert.equal(svg.getAttribute("data-stale"), "false");
  assert.equal(svg.getAttribute("preserveAspectRatio"), "xMidYMid meet");
  const pickNodes = svg.querySelectorAll(".omx-cam-obj-node");
  const vetoNodes = svg.querySelectorAll(".omx-cam-obj-veto");
  assert.equal(pickNodes.length, 1);
  assert.equal(vetoNodes.length, 1);
  assert.equal(pickNodes[0].getAttribute("data-catalog-id"), "container-1");
  const ev = pickNodes[0].dispatch("click");
  assert.equal(ev.stopped, true);
  assert.equal(picked.object_ref, "det:19:0");

  // Past 5s stale threshold locks clicks and tabindex
  const staleSvg = buildCamObjectsSvg(cam, data, { nowMs: now + OBJECT_STALE_MS + 100 });
  assert.equal(staleSvg.getAttribute("data-stale"), "true");
  assert.equal(staleSvg.querySelectorAll(".omx-cam-obj-node")[0].getAttribute("tabindex"), "-1");
  assert.equal(isObjectSnapshotFresh(objectsForCamView(cam, data).snap, now + OBJECT_STALE_MS + 100), false);
});

test("syncCamObjectsOverlay and buildInspectorStagingBar wire destination, lockouts, and dispatch", (t) => {
  installDom(t);
  const now = 90_000;
  const data = sampleObjects(now);
  const cam = { id: "arm_s_top", source: "arm_s_top" };
  const frameEl = makeNode("div");
  syncCamObjectsOverlay(frameEl, cam, data, { nowMs: now });
  assert.equal(frameEl.querySelectorAll(".omx-cam-objects-overlay").length, 1);

  let dispatched = null;
  const barFresh = buildInspectorStagingBar(cam, data, {
    selectedRef: "det:19:0", selectedDest: "belt-in", nowMs: now + 500,
    onDispatch: (p) => { dispatched = p; },
  });
  const btn = barFresh.children[1].children[1];
  assert.equal(Boolean(btn.disabled), false);
  btn.dispatch("click");
  assert.equal(dispatched.object.catalog_id, "container-1");
  assert.equal(dispatched.destSite, "belt-in");
  const body = dispatched.buildTaskBody("rosy_01");
  assert.equal(body.robot_id, "rosy_01");
  assert.equal(body.propose, false);
  assert.equal(body.target_object.object_ref, "det:19:0");
  assert.equal(body.target_object.expected_cell_state_gen, 4);

  // Stale bar locks button via setOffBy
  const barStale = buildInspectorStagingBar(cam, data, {
    selectedRef: "det:19:0", nowMs: now + OBJECT_STALE_MS + 500,
  });
  const staleBtn = barStale.children[1].children[1];
  assert.equal(staleBtn.disabled, true);
  assert.match(staleBtn.getAttribute("reason"), /관측 만료/);

  // Click-time freshness lockout when wall-clock advances past 5s without re-render
  let fakeNow = 200_000;
  t.mock.method(Date, "now", () => fakeNow);
  const realSnap = sampleObjects(fakeNow);
  let realPicked = null;
  let realDispatched = null;
  const realSvg = buildCamObjectsSvg(cam, realSnap, { onSelectObject: (o) => { realPicked = o; } });
  const realBar = buildInspectorStagingBar(cam, realSnap, { selectedRef: "det:19:0", onDispatch: (p) => { realDispatched = p; } });
  fakeNow += OBJECT_STALE_MS + 100;
  realSvg.querySelectorAll(".omx-cam-obj-node")[0].dispatch("click");
  realBar.children[1].children[1].dispatch("click");
  assert.equal(realPicked, null);
  assert.equal(realDispatched, null);
  assert.equal(realSvg.getAttribute("data-stale"), "true");
  assert.equal(realBar.children[1].children[1].disabled, true);
});
