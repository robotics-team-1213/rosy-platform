import test from "node:test";
import assert from "node:assert/strict";
import { createTrackingView } from "../../../../applications/fleet/web/tracking-view.js";

test("expired or missing observations clear coordinates without hiding the coordinate table", async () => {
  const nodes = new Map();
  const el = (id) => {
    if (!nodes.has(id)) nodes.set(id, { hidden: true, dataset: {},
      replaceChildren(...rows) { this.rows = rows; } });
    return nodes.get(id);
  };
  globalThis.document = { createElement: () => ({ children: [], append(child) { this.children.push(child); } }) };
  let expire;
  let body = { lease_s: 1, sources: [{ source_id: "north", status: "OK", age_ms: 0 }],
    robots: [{ robot_id: "rosy_01", status: "MARKER", camera: { x: 1.25, y: 2.5 } }] };
  const view = {};
  const tracking = createTrackingView({ el, view, auth: { locked: false }, call: async () => body,
    scope: { capture: () => ({ check() {}, signal: new AbortController().signal }),
      timeout: (fn) => { expire = fn; return () => {}; } } });
  await tracking.refresh();
  assert.equal(el("tracking-positions").hidden, false);
  assert.equal(el("tracking-position-rows").rows[0].children[1].textContent, "1.25");
  expire();
  assert.equal(el("tracking-positions").hidden, false);
  assert.deepEqual(view.cameraTracking.robots, []);
  assert.equal(el("tracking-position-rows").rows[0].children[1].textContent, "—");
  body = { sources: [{ source_id: "north", status: "LEARNING" }], robots: [] };
  await tracking.refresh();
  assert.equal(el("tracking-positions").hidden, false);
  tracking.reset();
  assert.equal(el("tracking-positions").hidden, true);
});
