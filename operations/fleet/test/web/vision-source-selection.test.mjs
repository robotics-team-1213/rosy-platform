import test from "node:test";
import assert from "node:assert/strict";
import { createVisionView } from "../../../../applications/fleet/web/shared/vision-view.js";

// Model the select's browser behavior: replacing options selects the first option.
function harness() {
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
  };
  const view = createVisionView({ scope, el, isActive: () => false,
    call: async () => ({ sources }) });
  return { view, el, refresh: async (names) => { sources = names; await view.refreshSources(); },
    choose: (source) => { el("vision-source").value = source; listeners.get("change:vision-source")(); } };
}

globalThis.window = {};
globalThis.document = { createElement: () => ({}) };
globalThis.localStorage = { getItem: () => null };

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
