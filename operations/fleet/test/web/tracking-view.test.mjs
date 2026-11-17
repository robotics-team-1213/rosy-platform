import test from "node:test";
import assert from "node:assert/strict";
import { createTrackingView } from "../../../../applications/fleet/web/tracking-view.js";
import { createMapOverlays } from "../../../../applications/fleet/web/map/map-overlays.js";

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

test("expireOnly lease expiration preserves unknownFloor while explicit null or reset clears it", async () => {
  const nodes = new Map();
  const el = (id) => {
    if (!nodes.has(id)) nodes.set(id, { hidden: true, dataset: {},
      replaceChildren(...rows) { this.rows = rows; } });
    return nodes.get(id);
  };
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: () => ({ children: [], append(child) { this.children.push(child); } }) };
  try {
    let expire;
    const body = {
      lease_s: 1,
      sources: [{ source_id: "north", status: "OK", age_ms: 0, unknown_floor: [{ x: 1.5, y: 2.5, radius_m: 0.16 }] }],
      robots: [{ robot_id: "rosy_01", status: "MARKER", camera: { x: 1.25, y: 2.5 } }],
      unknown: [{ x: 3.0, y: 4.0 }],
    };
    const view = {};
    const auth = { locked: false };
    const tracking = createTrackingView({ el, view, auth, call: async () => body,
      scope: { capture: () => ({ check() {}, signal: new AbortController().signal }),
        timeout: (fn) => { expire = fn; return () => {}; } } });
    await tracking.refresh();
    assert.deepEqual(view.cameraTracking.unknownFloor, [{ x: 1.5, y: 2.5, radiusM: 0.16 }]);
    expire();
    assert.deepEqual(view.cameraTracking.robots, []);
    assert.deepEqual(view.cameraTracking.unknown, []);
    assert.deepEqual(view.cameraTracking.unknownFloor, [{ x: 1.5, y: 2.5, radiusM: 0.16 }]);
    auth.locked = true;
    await tracking.refresh();
    assert.equal(view.cameraTracking.unknownFloor, undefined);
    auth.locked = false;
    await tracking.refresh();
    assert.deepEqual(view.cameraTracking.unknownFloor, [{ x: 1.5, y: 2.5, radiusM: 0.16 }]);
    tracking.reset();
    assert.equal(view.cameraTracking.unknownFloor, undefined);
  } finally {
    globalThis.document = previousDocument;
  }
});

test("drawCameraTracking suppresses unknownFloor and unmarked unknown near known robots while keeping isolated and ArUco markers", () => {
  const previousWindow = globalThis.window;
  globalThis.window = { RosyPalette: { canvasTextSize: () => 12 } };
  try {
    const arcs = [];
    const clips = [];
    const fills = [];
    const ctx = {
      canvas: { width: 800, height: 600, getBoundingClientRect: () => ({ width: 800, height: 600 }) },
      save() {},
      restore() {},
      setLineDash() {},
      beginPath() {},
      moveTo() {},
      lineTo() {},
      stroke() {},
      arc(x, y, r) { arcs.push({ x, y, r }); },
      clip() { clips.push(arcs.at(-1)); },
      fill() { fills.push(arcs.at(-1)); },
      getTransform: () => ({ transformPoint: (p) => p }),
      setTransform() {},
      measureText: (text) => ({ width: text.length * 6 }),
      fillRect() {},
      strokeRect() {},
      fillText() {},
    };
    const view = {
      robots: [{ robot_id: "r1", pose: { x: 1.0, y: 1.0 } }],
      guide: { robots: [{ robot_id: "r2", pose: { x: 2.0, y: 2.0 } }] },
      sightings: [{ robot_id: "r3", x: 3.0, y: 3.0, state: "fresh", age_ms: 50 }],
      cameraTracking: {
        robots: [{ robotId: "r4", camera: { x: 4.0, y: 4.0 }, pose: { x: 4.0, y: 4.0 }, offsetM: 0, warn: false, verified: true }],
        unknownFloor: [
          { x: 1.05, y: 1.0, radiusM: 0.16 },
          { x: 4.05, y: 4.0, radiusM: 0.16 },
          { x: 5.5, y: 5.5, radiusM: 0.16 },
        ],
        unknown: [
          { x: 1.05, y: 1.05 },
          { x: 2.05, y: 2.0 },
          { x: 3.05, y: 3.0 },
          { x: 1.02, y: 1.0, markerId: 41 },
          { x: 6.5, y: 6.5 },
        ],
      },
    };
    const overlays = createMapOverlays({
      view,
      css: (token) => token,
      font: () => "12px var(--body)",
      layerOn: () => true,
      worldToCell: () => ({ col: 0, row: 0 }),
      colorOf: () => "--series-primary",
    });
    overlays.resetChips();
    overlays.drawCameraTracking(ctx, (x, y) => ({ x, y }), 10, 2);
    assert.deepEqual(clips.map((c) => [c.x, c.y]), [[5.5, 5.5]]);
    assert.deepEqual(fills.map((c) => [c.x, c.y]), [[1.02, 1.0], [6.5, 6.5]]);
    assert.ok(globalThis.window.__mapChips.some((c) => c.text === "ArUco 41 · 미등록"));
  } finally {
    globalThis.window = previousWindow;
  }
});
