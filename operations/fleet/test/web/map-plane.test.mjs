// D-560 S2: Vision map-plane header, pixel↔map formula, and the two screens' placement of the plane.
import assert from "node:assert/strict";
import test from "node:test";
import {
  createPlaneFeed, mapToPlane, parsePlaneHeader, planeCalibration, planeFitsImage, planeToMap,
} from "../../fleet/server/web/shared/vision-view.js";
import { planeAffine } from "../../fleet/server/web/camera-backdrop.js";
import { fitTransform, project, quarterTurn } from "../../fleet/server/web/site-layer.js";
import { planeView } from "../../fleet/server/web/shared/site-map-model.js";

const PLANE = { min_x: -0.15, min_y: -0.15, max_x: 6.55, max_y: 3.75, ppm: 400 };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

test("X-Frame-Plane parses five finite numbers with min < max and px_per_m > 0, nothing else", () => {
  assert.deepEqual(parsePlaneHeader("-0.15,-0.15,6.55,3.75,400"), PLANE);
  assert.deepEqual(parsePlaneHeader(" -0.15, -0.15 ,6.55,3.75, 400 "), PLANE);
  for (const bad of [null, undefined, "", "1,2,3,4", "0,0,1,1,400,5", "0,,1,1,400", "0,0,1,1,abc",
    "0,0,1,1,Infinity", "NaN,0,1,1,400", "1,0,1,1,400", "0,1,1,1,400", "2,0,1,1,400",
    "0,0,1,1,0", "0,0,1,1,-400"]) {
    assert.equal(parsePlaneHeader(bad), null, String(bad));
  }
});

test("plane pixel ↔ map follows x = min_x + u/ppm, y = max_y − v/ppm both ways", () => {
  assert.deepEqual(planeToMap(PLANE, 0, 0), { x: -0.15, y: 3.75 });
  const corner = planeToMap(PLANE, 2680, 1560);
  close(corner.x, 6.55); close(corner.y, -0.15);
  for (const [x, y] of [[0, 0], [3.2, 1.8], [6.4, 3.6], [-0.1, 3.7]]) {
    const { u, v } = mapToPlane(PLANE, x, y);
    const back = planeToMap(PLANE, u, v);
    close(back.x, x); close(back.y, y);
  }
});

test("the console lays plane pixels where toPx puts the same map point, with and without a view turn", () => {
  const bounds = { min_x: -0.4, min_y: -0.4, max_x: 6.8, max_y: 4.0 };
  for (const rot of [0, 90, 180, 270]) {
    const side = rot === 90 || rot === 270;
    const fw = side ? 700 : 1200, fh = side ? 1200 : 700;
    const t = fitTransform(bounds, fw, fh, 32);
    const turn = quarterTurn(rot, fw, fh);
    const toPx = (x, y) => { const p = project(t, x, y); return turn.point(p.px, p.py); };
    const [a, b, c, d, e, f] = planeAffine(PLANE, 2680, 1560, toPx);
    for (const [x, y] of [[0, 0], [6.4, 3.6], [1.25, 2.5]]) {
      const { u, v } = mapToPlane(PLANE, x, y);
      const want = toPx(x, y);
      close(a * u + c * v + e, want.x, 1e-6); close(b * u + d * v + f, want.y, 1e-6);
    }
  }
});

test("the site-map tab's view over the plane rectangle picks x = min_x + u/ppm, y = max_y − v/ppm at any turn", () => {
  for (const rot of [0, 90, 180, 270]) {
    const { view, field } = planeView(PLANE, 800, 480, rot);
    const cx = field.x + field.width / 2, cy = field.y + field.height / 2;
    const q = rot * Math.PI / 180, c = Math.round(Math.cos(q)), s = Math.round(Math.sin(q));
    for (const [u, v] of [[0, 0], [2680, 1560], [500, 1000]]) {
      // The SVG image is drawn unturned over ``field`` then rotated by ``rot`` about its centre.
      const fx = field.x + u * field.width / 2680 - cx, fy = field.y + v * field.height / 1560 - cy;
      const [x, y] = view.toMap(cx + fx * c - fy * s, cy + fx * s + fy * c);
      const want = planeToMap(PLANE, u, v);
      close(x, want.x); close(y, want.y);
    }
  }
});

test("a plane whose rectangle is not its picture (more than 1 px off) is not used", () => {
  assert.ok(planeFitsImage(PLANE, 2680, 1560));
  assert.ok(planeFitsImage(PLANE, 2681, 1559));
  assert.ok(!planeFitsImage(PLANE, 2682, 1560));
  assert.ok(!planeFitsImage(PLANE, 2680, 1500));
});

test("the console uses a plane only while fresh and of an approved calibration on this site map", () => {
  const cal = { source_id: "ceiling_north", map_id: "map_v2_fleet", calibration_revision: "paint-7b2" };
  const siteMap = { maps: [{ map_id: "map_v2_fleet" }] };
  const frame = { source: "ceiling_north", calibrationRevision: "paint-7b2", ageMs: 100, plane: PLANE };
  assert.equal(planeCalibration(frame, [cal], siteMap), cal);
  for (const changed of [{ ageMs: 3001 }, { ageMs: NaN }, { ageMs: -1 }, { source: "other" },
    { calibrationRevision: "paint-old" }, { calibrationRevision: null }]) {
    assert.equal(planeCalibration({ ...frame, ...changed }, [cal], siteMap), null);
  }
  assert.equal(planeCalibration(frame, [cal], { maps: [{ map_id: "other" }] }), null);
  assert.equal(planeCalibration(null, [cal], siteMap), null);
  // Fleet's site lanes ({maps: [{map_id}]}) name the maps on the install page.
  assert.equal(planeCalibration(frame, [cal], { maps: [{ map_id: "map_v2_fleet", source_ids: [] }] }), cal);
});

function feedHarness(answers) {
  const timers = [];
  let clock = 1000, changes = 0, fetches = 0;
  const scope = {
    capture: () => ({ current: () => true }),
    timeout: (fn, ms) => { const t = { at: clock + ms, fn, live: true }; timers.push(t); return () => { t.live = false; }; },
    onDispose: () => {},
  };
  const visionView = { fetchPlane: async () => { fetches += 1; return answers.shift(); } };
  const feed = createPlaneFeed({ scope, visionView, onChange: () => { changes += 1; }, now: () => clock });
  return {
    feed, fetches: () => fetches, changes: () => changes,
    advance(ms) {
      clock += ms;
      for (const t of timers) if (t.live && t.at <= clock) { t.live = false; t.fn(); }
    },
  };
}
const live = (extra = {}) => ({ state: "live", source: "ceiling_north", plane: { ...PLANE, max_x: PLANE.min_x + 2, max_y: PLANE.min_y + 1, ppm: 100 },
  calibrationRevision: "paint-7b2", ageMs: 1000, blob: new Blob(["x"]), ...extra });

test("the plane feed drops a frame at 3000 ms age and backs off after errors and plane-unavailable", async (t) => {
  const OldImage = globalThis.Image;
  globalThis.Image = class { constructor() { this.naturalWidth = 200; this.naturalHeight = 100; } decode() { return Promise.resolve(); } };
  t.after(() => { globalThis.Image = OldImage; });
  const h = feedHarness([live(), { state: "error", status: 503 }, live(), { state: "plane-unavailable" }]);
  await h.feed.refresh();
  assert.equal(h.feed.current().calibrationRevision, "paint-7b2");
  h.advance(1000);
  await h.feed.refresh();                       // transient error: the fresh frame stays
  assert.ok(h.feed.current());
  await h.feed.refresh();                       // within the 5 s error backoff: no request
  assert.equal(h.fetches(), 2);
  h.advance(1000);                              // 3000 ms after capture: dropped
  assert.equal(h.feed.current(), null);
  h.advance(3000);
  await h.feed.refresh();                       // still inside the error backoff
  assert.equal(h.fetches(), 2);
  h.advance(1000);
  await h.feed.refresh();
  assert.ok(h.feed.current());
  await h.feed.refresh();                       // not busy, not backing off: asks and gets 409
  assert.equal(h.feed.current(), null);
  h.advance(29000);
  await h.feed.refresh();                       // 30 s plane-unavailable backoff
  assert.equal(h.fetches(), 4);
  await h.feed.refresh(false);
  assert.equal(h.fetches(), 4);
});

test("the plane feed rejects a picture that does not match its rectangle", async (t) => {
  const OldImage = globalThis.Image;
  globalThis.Image = class { constructor() { this.naturalWidth = 300; this.naturalHeight = 100; } decode() { return Promise.resolve(); } };
  t.after(() => { globalThis.Image = OldImage; });
  const h = feedHarness([live()]);
  await h.feed.refresh();
  assert.equal(h.feed.current(), null);
});
