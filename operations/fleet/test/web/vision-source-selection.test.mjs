import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

const { createVisionView, FRAME_LATE_MS } = await import("../../../../applications/fleet/web/shared/vision-view.js");

// Model the select's browser behavior: replacing options selects the first option.
function harness(isActive = () => false) {
  const elements = new Map();
  const listeners = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value: "", dataset: {}, textContent: "", hidden: false,
      querySelectorAll: () => [], setAttribute() {}, toggleAttribute() {},
      getBoundingClientRect: () => ({ width: 480, height: 270 }),
      replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ""; },
    });
    return elements.get(id);
  };
  let sources = [];
  const scope = {
    capture: () => ({ check() {}, current: () => true, signal: new AbortController().signal }),
    listen: (target, type, fn) => listeners.set(`${type}:${[...elements].find(([, node]) => node === target)?.[0]}`, fn),
    onDispose() {}, subscribe() {},
    timeout(fn, delay) { const id = setTimeout(fn, delay); return () => clearTimeout(id); },
  };
  const view = createVisionView({ scope, el, isActive,
    call: async (path) => path.endsWith("/sources") ? { sources } : { frame_path: "/frame", lease: "lease" } });
  return { view, el, refresh: async (names) => { sources = names; await view.refreshSources(); },
    choose: (source) => { el("vision-source").value = source; listeners.get("change:vision-source")(); } };
}

globalThis.window = {};
globalThis.document = { createElement: () => ({}) };
globalThis.localStorage = { getItem: () => null };

test("a 429 delays frame requests and reports stale video before a long retry", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 60000 });
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    new Response(null, { status: 429, headers: { "Retry-After": "8" } }));
  const h = harness(() => true);
  const frames = [];
  h.view.onFrame((frame) => frames.push(frame.state));
  await h.refresh(["north"]);
  await h.view.refreshFrame();
  assert.equal(fetch.mock.callCount(), 1);
  assert.match(h.el("vision-state").textContent, /요청 제한/);
  t.mock.timers.tick(FRAME_LATE_MS);
  assert.equal(h.el("vision-frame").dataset.state, "warn");
  assert.equal(frames.at(-1), "stale");
  t.mock.timers.tick(7999 - FRAME_LATE_MS);
  await h.view.refreshFrame();
  assert.equal(fetch.mock.callCount(), 1);
  t.mock.timers.tick(1);
  await h.view.refreshFrame();
  assert.equal(fetch.mock.callCount(), 2);
});

test("selected camera stays selected through disconnect, empty list, reorder and reconnect", async () => {
  const h = harness();
  await h.refresh(["north", "south"]);
  h.choose("south");
  await h.refresh(["north"]);
  assert.equal(h.view.currentSource(), "south");
  assert.match(h.el("vision-message").textContent, /south/);
  assert.equal(h.el("vision-image").hidden, true);
  assert.deepEqual(await h.view.fetchPlane(), { state: "no-source" });
  await assert.rejects(h.view.fetchFieldProposal(), /연결된 카메라/);
  await h.refresh([]);
  assert.equal(h.view.currentSource(), "south");
  await h.refresh(["east", "north", "south"]);
  assert.equal(h.view.currentSource(), "south");
});

test("an unchanged source refresh keeps the current lease/profile and operator can select another source", async () => {
  const h = harness();
  await h.refresh(["north", "south"]);
  h.el("vision-adjustment-state").textContent = "operator draft";
  await h.refresh(["south", "north"]);
  assert.equal(h.view.currentSource(), "north");
  assert.equal(h.el("vision-adjustment-state").textContent, "operator draft");
  h.choose("south");
  assert.equal(h.view.currentSource(), "south");
});

test("invalidating page scope while refreshFrame awaits refreshSources resolves cleanly without AbortError", async () => {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, {
      value: "", dataset: {}, textContent: "", hidden: false,
      querySelectorAll: () => [], setAttribute() {}, toggleAttribute() {},
      getBoundingClientRect: () => ({ width: 480, height: 270 }),
      replaceChildren(...options) { this.options = options; this.value = options[0]?.value || ""; },
    });
    return elements.get(id);
  };
  let current = true;
  let calls = 0;
  const scope = {
    capture: () => ({
      signal: new AbortController().signal,
      current: () => current,
      check() { if (!current) throw new DOMException("Page operation is no longer current", "AbortError"); },
    }),
    listen() {}, onDispose() {}, subscribe() {},
  };
  const view = createVisionView({
    scope, el, isActive: () => true,
    call: async (path) => {
      calls += 1;
      if (path === "/api/fleet/vision/sources") {
        current = false;  // pageScope.invalidate() while refreshSources is in flight
        return { sources: ["north"] };
      }
      throw new Error(`unexpected call after invalidation: ${path}`);
    },
  });
  await assert.doesNotReject(view.refreshFrame());
  assert.equal(calls, 1);
  current = false;
  await assert.doesNotReject(view.refreshSources());
  await assert.doesNotReject(view.refreshFrame());
  assert.equal(calls, 1);
});
