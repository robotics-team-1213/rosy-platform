// 2026-11-14 요청 — 영상이 끊겨도 마지막 좋은 프레임을 지도·썸네일에 두고 낡음만 표시한다.
// keepFrame(유지 판단)·staleStamp(시각 글자)·bindCamera(끊김 표시 흐름)을 가린다.
import assert from "node:assert/strict";
import test from "node:test";
import { createCameraBackdrop, keepFrame, staleStamp } from "../../../../applications/fleet/web/map/camera-backdrop.js";

const frame = { state: "live", seq: 7, source: "ceiling_north", ageMs: 200, url: "blob:frame" };

test("keepFrame: only a live+fresh incoming frame replaces the kept picture", () => {
  const next = { ...frame, seq: 8 };
  assert.equal(keepFrame(frame, next), next);                            // 새 live 프레임은 바꾼다
  for (const bad of [{ state: "stale" }, { ageMs: 3001 }, { ageMs: NaN }, null]) {
    assert.equal(keepFrame(frame, bad), frame);                          // 끊김·안 신선함은 유지
  }
  assert.equal(keepFrame(null, { ...frame, state: "stale" }), null);     // 없던 그림은 지어내지 않는다
});

test("staleStamp: live는 찍은 시각만, 끊기면 나이를 붙인다", () => {
  const t = new Date(2026, 10, 14, 9, 8, 7).getTime();
  assert.equal(staleStamp(t, t + 500), "카메라 09:08:07");
  assert.equal(staleStamp(t, t + 45300, true), "카메라 09:08:07 · 45초 전");
  assert.equal(staleStamp(t, t + 940, true), "카메라 09:08:07 · 1초 전");
  assert.equal(staleStamp(t, t - 40000, true), "카메라 09:08:07 · 0초 전"); // 시계가 뒤로 가도 음수 없음
  assert.equal(staleStamp(NaN, 0, true), "");
});

test("feed drop keeps the last frame marked stale; the next live frame clears the mark", () => {
  const stage = { dataset: {} }, stamp = { hidden: true, textContent: "" }, birdseye = { hidden: true, src: "" };
  const elements = {
    "map-stage": stage, "map-camera-stamp": stamp, "map-birdseye": birdseye,
    "birdseye-toggle": { disabled: false, setAttribute() {}, removeAttribute() {} },
    "map-display-mode": { value: "camera" }, "camera-comparison": { open: false },
  };
  let handler = null;
  const timers = [];
  const scope = {
    listen: () => {}, guard: (fn) => fn, interval: () => {},
    timeout: (fn) => { const t = { fn, live: true }; timers.push(t); return () => { t.live = false; }; },
    subscribe: (start) => start(), onDispose: () => {},
  };
  const visionView = { onFrame: (cb) => { handler = cb; }, fetchPlane: async () => ({ state: "plane-unavailable" }) };
  const backdrop = createCameraBackdrop({
    scope, el: (id) => elements[id] || null,
    view: { siteMap: { maps: [] }, displayMode: "overlay" }, draw: () => {},
  });
  backdrop.bindCamera(visionView);

  handler(frame);                                   // live 프레임 — 표시 없음
  assert.equal(stamp.hidden, false);
  assert.match(stamp.textContent, /^카메라 \d\d:\d\d:\d\d$/);
  assert.ok(!("cameraStale" in stage.dataset));
  assert.equal(birdseye.hidden, false);

  handler({ state: "stale" });                      // 끊김 — 지우지 않고 낡음 표시
  assert.equal(stage.dataset.cameraStale, "true");
  assert.match(stamp.textContent, / · \d+초 전$/);
  assert.equal(birdseye.hidden, false);             // 썸네일도 그대로

  handler({ ...frame, ageMs: 4000 });               // 안 신선한 프레임이 와도 유지
  assert.equal(stage.dataset.cameraStale, "true");

  handler({ ...frame, seq: 8, ageMs: 100 });        // 살아 돌아오면 낡음 표시가 지워진다
  assert.ok(!("cameraStale" in stage.dataset));
  assert.match(stamp.textContent, /^카메라 \d\d:\d\d:\d\d$/);

  handler({ ...frame, seq: 9, ageMs: 100 });        // 마지막 살아 있는 프레임 뒤 3초 만료 타이머
  const armed = timers.filter((t) => t.live).at(-1);
  armed.fn();
  assert.equal(stage.dataset.cameraStale, "true");
  assert.match(stamp.textContent, / · \d+초 전$/);
});

test("coordinates mode skips plane warp requests while letting watch-ceiling toggle receive live frames", () => {
  const stage = { dataset: {} }, stamp = { hidden: true, textContent: "" }, birdseye = { hidden: true, src: "" };
  const mode = { value: "coordinates" };
  const elements = {
    "map-stage": stage, "map-camera-stamp": stamp, "map-birdseye": birdseye,
    "birdseye-toggle": { disabled: false, setAttribute() {}, removeAttribute() {} },
    "map-display-mode": mode, "camera-comparison": { open: false },
  };
  let handler = null;
  let planeCalls = 0;
  const scope = {
    listen: () => {}, guard: (fn) => fn, interval: () => {},
    timeout: () => () => {},
    subscribe: (start) => start(), onDispose: () => {},
  };
  const visionView = {
    onFrame: (cb) => { handler = cb; },
    fetchPlane: async () => { planeCalls += 1; return { state: "plane-unavailable" }; },
  };
  const view = { siteMap: { maps: [{ map_id: "track", sources: ["ceiling_north"] }] } };
  const backdrop = createCameraBackdrop({ scope, el: (id) => elements[id] || null, view, draw: () => {} });
  backdrop.setCalibrations([{
    map_id: "track", source_id: "ceiling_north", approved_by: "op",
    plane_ready: true, calibration_revision: "rev-1",
  }]);
  backdrop.bindCamera(visionView);

  handler(frame);
  assert.equal(view.displayMode, "coordinates");
  assert.equal(planeCalls, 0);
  assert.equal(birdseye.hidden, false);
  assert.match(stamp.textContent, /^카메라 \d\d:\d\d:\d\d$/);
});

async function replay(run) {
  const original = {Image: globalThis.Image, document: globalThis.document, now: Date.now};
  const start = new Date(2026, 10, 14, 9, 8, 8).getTime();
  let now = start;
  const context = (paints) => ({
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {},
    clip() {}, transform() {}, setTransform() {}, scale() {},
    drawImage(image) { paints.push({image, alpha: this.globalAlpha}); },
  });
  const paints = [], corrected = [], warps = [];
  const correctedContext = context(corrected);
  let resizes = 0;
  const canvas = {getContext: () => correctedContext, set width(value) { this.w = value; resizes++; },
    get width() { return this.w; }};
  const label = () => ({
    text: "", writes: 0,
    get textContent() { return this.text; },
    set textContent(value) { this.text = value; this.writes++; },
  });
  const stamp = label(), status = label(), correctedStatus = label();
  const comparison = {open: false};
  const stage = {dataset: {}}, mode = {value: "overlay"};
  const elements = {
    "map-stage": stage, "map-display-mode": mode, "map-birdseye": {},
    "birdseye-toggle": {setAttribute() {}, removeAttribute() {}},
    "map-camera-stamp": stamp, "map-display-status": status,
    "camera-comparison": comparison, "camera-corrected": canvas, "camera-corrected-status": correctedStatus,
  };
  const callbacks = new Map(), timers = [];
  let tick;
  const scope = {
    listen: (el, event, fn) => callbacks.set(el, fn), guard: (fn) => fn,
    interval(fn) { tick = fn; },
    timeout(fn, ms) {
      const timer = {fn, at: now + ms};
      timers.push(timer);
      return () => { timer.cancelled = true; };
    },
    subscribe: (start) => start(), onDispose() {}, capture: () => ({current: () => true}),
  };
  const record = {map_id: "track", source_id: frame.source, calibration_revision: "rev",
    image: {width: 200, height: 100}, map_to_image: [1, 0, 0, 0, 1, 0, 0, 0, 1]};
  const map = {map_id: "track", polygon_m: [[0, 0], [2, 1]]}, otherMap = {map_id: "other"};
  const view = {siteMap: {maps: [map, otherMap]}, activeSiteMap: {map}};
  const ctx = context(paints);
  const draw = () => {
    const calibration = backdrop.calibration();
    if (view.displayMode !== "overlay" || !calibration) return;
    backdrop.drawTopDown(ctx, calibration,
      {min_x: 0, min_y: 0, max_x: 2, max_y: 1}, (x, y) => ({x, y: -y}), 200, 100, 1, 0);
  };
  const rows = [record, {...record, map_id: "other"}, {...record, source_id: "new-camera"}];
  const backdrop = createCameraBackdrop({scope, el: (id) => elements[id], view, draw});
  const plane = (seq, overrides) => ({state: "live", source: frame.source, seq, calibrationRevision: "rev",
    ageMs: 1000, observedFraction: 0.73, ...overrides,
    plane: {min_x: 0, min_y: 0, max_x: 2, max_y: 1, ppm: 100}, blob: new Blob(["x"])});
  let send, finish;
  const resolve = async (result) => {
    assert.ok(finish, "a plane request is pending");
    const pending = finish;
    finish = null;
    pending(result);
    await new Promise(setImmediate);
  };
  const advance = (ms) => {
    const target = now + ms;
    for (const timer of timers.filter((entry) => entry.at <= target).sort((a, b) => a.at - b.at)) {
      if (timer.cancelled) continue;
      timer.cancelled = true;
      now = timer.at;
      timer.fn();
    }
    now = target;
  };
  try {
    Date.now = () => now;
    globalThis.Image = class { naturalWidth = 200; naturalHeight = 100; async decode() {} };
    globalThis.document = {createElement: () => {
      const offscreen = {getContext: () => context([])};
      warps.push(offscreen);
      return offscreen;
    }};
    backdrop.setCalibrations(rows);
    backdrop.bindCamera({onFrame: (fn) => { send = fn; },
      fetchPlane: () => new Promise((resolvePlane) => { finish = resolvePlane; })});
    const raw = (seq, overrides) => send({...frame, image: new Image(), seq, ...overrides});
    raw(7, {ageMs: 0});
    await resolve(plane(7));
    await run({start, stamp, status, correctedStatus, comparison, canvas, paints, corrected, warps, view, map, otherMap,
      rows, backdrop, advance, raw, resolve, plane, tick: () => tick(), resizes: () => resizes,
      toggleComparison: () => callbacks.get(comparison)(),
      setMode(value) { mode.value = value; callbacks.get(mode)(); }});
  } finally {
    Date.now = original.now;
    globalThis.Image = original.Image;
    globalThis.document = original.document;
  }
}

test("the stamp follows the plane through 429, recovery, and explicit 409 fallback", () => replay(async ({
  stamp, status, paints, warps, advance, raw, resolve, plane, tick,
}) => {
  const first = paints.at(-1);
  const initialWarps = warps.length;
  assert.equal(first.alpha, 1);
  assert.equal(stamp.textContent, "카메라 09:08:07");
  advance(1000);
  raw(8);
  advance(1300);
  assert.deepEqual(paints.at(-1), {...first, alpha: 0.5});
  assert.equal(stamp.textContent, "평면 영상 지연 09:08:07 · 3초 전");
  await resolve({state: "rate-limited"});
  advance(300);
  raw(9);
  assert.deepEqual(paints.at(-1), {...first, alpha: 0.5});
  assert.equal(warps.length, initialWarps);
  assert.equal(stamp.textContent, "평면 영상 지연 09:08:07 · 4초 전");
  const writes = stamp.writes;
  tick();
  assert.equal(stamp.writes, writes);
  await resolve(plane(9, {ageMs: 600, observedFraction: 0.82}));
  assert.notEqual(paints.at(-1).image, first.image);
  assert.equal(paints.at(-1).alpha, 1);
  assert.equal(stamp.textContent, "카메라 09:08:10");
  assert.equal(stamp.writes, writes + 1);
  assert.match(status.textContent, /82%$/);
  advance(1400);
  raw(10);
  await resolve({state: "plane-unavailable"});
  assert.equal(paints.at(-1).image, warps.at(-1));
  assert.equal(paints.at(-1).alpha, 1);
  assert.equal(stamp.textContent, "카메라 09:08:11");
}));

test("the stamp tick drops a plane older than 30 seconds while raw is live", () => replay(({
  stamp, paints, warps, advance, raw, tick, backdrop,
}) => {
  const first = paints.at(-1);
  for (let seq = 8; seq <= 21; seq++) {
    advance(2000);
    raw(seq);
  }
  advance(1000);
  tick();
  assert.deepEqual(paints.at(-1), {...first, alpha: 0.5});
  assert.equal(stamp.textContent, "평면 영상 지연 09:08:07 · 30초 전");
  advance(1);
  tick();
  assert.equal(backdrop.usesPlane(), false);
  assert.equal(paints.at(-1).image, warps.at(-1));
  assert.equal(paints.at(-1).alpha, 1);
  assert.equal(stamp.textContent, "카메라 09:08:35");
}));

test("a whole-camera outage keeps its last compatible plane past 30 seconds", () => replay(({
  stamp, paints, advance, tick, backdrop,
}) => {
  const first = paints.at(-1);
  advance(35_000);
  tick();
  assert.equal(backdrop.usesPlane(), true);
  assert.deepEqual(paints.at(-1), {...first, alpha: 0.5});
  assert.equal(stamp.textContent, "평면 영상 지연 09:08:07 · 36초 전");
}));

test("comparison draws once per image, opacity, or bounds change and clears only once", () => replay(async ({
  status, correctedStatus, comparison, canvas, corrected, map, rows, backdrop, resizes,
  toggleComparison, advance, raw, resolve, plane,
}) => {
  comparison.open = true;
  toggleComparison();
  const counts = () => [resizes(), corrected.length, status.writes, correctedStatus.writes];
  const initial = counts();
  backdrop.setCalibrations(rows);
  backdrop.setCalibrations(rows);
  assert.deepEqual(counts(), initial);
  advance(1000);
  raw(8);
  await resolve(plane(8)); // Same bounds, calibration, opacity and coverage, different image.
  assert.deepEqual(counts(), [initial[0] + 1, initial[1] + 1, initial[2], initial[3]]);
  advance(2000);
  assert.equal(corrected.at(-1).alpha, 0.5);
  map.polygon_m = [[0, 0], [3, 1]];
  backdrop.setCalibrations(rows);
  assert.deepEqual(counts(), [initial[0] + 3, initial[1] + 3, initial[2], initial[3]]);
  backdrop.setCalibrations([]);
  assert.equal(canvas.hidden, true);
  const cleared = counts();
  assert.equal(cleared[0], initial[0] + 4);
  backdrop.setCalibrations([]);
  assert.deepEqual(counts(), cleared);
}));

test("map, calibration, source and mode changes invalidate the plane and reject pending replies", () => replay(async ({
  stamp, paints, warps, view, otherMap, rows, backdrop, advance, raw, resolve, plane, setMode,
}) => {
  const original = paints.at(-1).image;
  advance(1000);
  raw(8);
  view.activeSiteMap = {map: otherMap};
  backdrop.setCalibrations(rows);
  assert.equal(stamp.textContent, "카메라 09:08:08");
  assert.equal(paints.at(-1).image, warps.at(-1));
  await resolve(plane(8)); // Same source and revision, but requested for the previous map.
  assert.equal(backdrop.usesPlane(), false);
  assert.equal(stamp.textContent, "카메라 09:08:08");
  raw(9);
  await resolve(plane(9));
  assert.equal(backdrop.usesPlane(), true);
  raw(10);
  const newRows = rows.map((row) => ({...row, calibration_revision: "rev-2"}));
  backdrop.setCalibrations(newRows);
  assert.equal(backdrop.usesPlane(), false);
  await resolve(plane(10));
  assert.equal(backdrop.usesPlane(), false);
  raw(11);
  await resolve(plane(11, {calibrationRevision: "rev-2"}));
  assert.equal(backdrop.usesPlane(), true);
  raw(12, {source: "new-camera"});
  assert.equal(backdrop.usesPlane(), false);
  assert.equal(stamp.hidden, true);
  setMode("coordinates");
  assert.equal(stamp.hidden, false);
  assert.equal(stamp.textContent, "카메라 09:08:08");
  setMode("overlay");
  assert.equal(stamp.hidden, true);
  assert.equal(paints.slice(3).filter(({image}) => image === original).length, 0);
}));
