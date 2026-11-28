import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const liveUiUrl = `data:text/javascript,${encodeURIComponent(
  await readFile(new URL("../web/factory-live-ui.js", import.meta.url), "utf8"),
)}`;
const monitorCode = (await readFile(new URL("../web/world-monitor.js", import.meta.url), "utf8"))
  .replace("./factory-live-ui.js", liveUiUrl);
const { createWorldMonitor } = await import(`data:text/javascript,${encodeURIComponent(monitorCode)}`);

function makeFakeElement(tag) {
  const listeners = new Map();
  const attrs = new Map();
  const el = {
    tagName: String(tag).toUpperCase(),
    className: "",
    textContent: "",
    type: "",
    hidden: false,
    dataset: {},
    children: [],
    focusCount: 0,
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = [...nodes]; },
    setAttribute(k, v) { attrs.set(k, String(v)); },
    getAttribute(k) { return attrs.get(k) ?? null; },
    addEventListener(type, fn) { listeners.set(type, fn); },
    click() { listeners.get("click")?.(); },
    focus() { this.focusCount += 1; globalThis.document.activeElement = this; },
    closest(sel) { return sel === ".world-card" && this.className === "world-card" ? this : null; },
    contains(target) { return this.children.includes(target); },
  };
  return el;
}

test("createWorldMonitor reuses card buttons across polls and preserves focus on reorder", async (t) => {
  const beforeDocument = globalThis.document;
  const beforeFetch = globalThis.fetch;
  const beforeSetInterval = globalThis.setInterval;
  const beforeClearInterval = globalThis.clearInterval;
  let pollFn = null;
  t.after(() => {
    globalThis.document = beforeDocument;
    globalThis.fetch = beforeFetch;
    globalThis.setInterval = beforeSetInterval;
    globalThis.clearInterval = beforeClearInterval;
  });

  globalThis.setInterval = (fn) => { pollFn = fn; return 42; };
  globalThis.clearInterval = () => {};
  globalThis.document = {
    hidden: false,
    activeElement: null,
    createElement: (tag) => makeFakeElement(tag),
  };

  const worldsStripEl = makeFakeElement("div");
  let replaceCount = 0;
  const origReplace = worldsStripEl.replaceChildren.bind(worldsStripEl);
  worldsStripEl.replaceChildren = (...nodes) => {
    replaceCount += 1;
    origReplace(...nodes);
  };
  const parityEl = makeFakeElement("ui-status");
  const selectedEvents = [];

  const packets = [
    {
      schema: "rosy.world.registry.v1",
      worlds: [
        { world_id: "real-site", adapter: "real", status: "live", parity: { ok: true } },
        { world_id: "gazebo-sim", adapter: "gazebo", status: "live", parity: { ok: true }, training: { episode: 1, step: 10, reward: 1.5, sim_fps: 60 } },
      ],
    },
    {
      schema: "rosy.world.registry.v1",
      worlds: [
        { world_id: "real-site", adapter: "real", status: "live", parity: { ok: true } },
        { world_id: "gazebo-sim", adapter: "gazebo", status: "live", parity: { ok: true }, training: { episode: 2, step: 25, reward: 2.75, sim_fps: 58 } },
      ],
    },
    {
      schema: "rosy.world.registry.v1",
      worlds: [
        { world_id: "gazebo-sim", adapter: "gazebo", status: "live", parity: { ok: true }, training: { episode: 3, step: 40, reward: 3.1, sim_fps: 60 } },
        { world_id: "real-site", adapter: "real", status: "live", parity: { ok: true } },
      ],
    },
  ];
  let idx = 0;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => packets[Math.min(idx++, packets.length - 1)],
  });

  const monitor = createWorldMonitor({
    adaptersBarEl: null,
    worldsStripEl,
    parityEl,
    onSelectWorld: (ev) => selectedEvents.push(ev),
  });

  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
  monitor.start();
  await flush();
  assert.equal(replaceCount, 1);
  assert.equal(worldsStripEl.children.length, 2);
  const firstRealBtn = worldsStripEl.children[0];
  const firstSimBtn = worldsStripEl.children[1];
  firstSimBtn.focus();

  pollFn();
  await flush();
  assert.equal(replaceCount, 1, "steady-state poll must update cards in place without replaceChildren");
  assert.equal(worldsStripEl.children[0], firstRealBtn);
  assert.equal(worldsStripEl.children[1], firstSimBtn);
  assert.equal(globalThis.document.activeElement, firstSimBtn);
  assert.match(firstSimBtn.children[1].textContent, /Ep 2 · Step 25/);

  firstSimBtn.click();
  assert.equal(selectedEvents.at(-1)?.world?.training?.episode, 2);

  pollFn();
  await flush();
  assert.equal(replaceCount, 2, "reordered world list calls replaceChildren once");
  assert.equal(worldsStripEl.children[0], firstSimBtn);
  assert.equal(firstSimBtn.focusCount, 2, "focus is restored to the surviving focused card");
  monitor.stop();
});
