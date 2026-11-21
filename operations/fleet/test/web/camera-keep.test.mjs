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
    "map-display-mode": { value: "overlay" }, "camera-comparison": { open: false },
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
});

test("a compatible plane stays visible through refresh, 429 and expiry, falls back on explicit 409, and clears with its map or mode", async (t) => {
  const oldImage = globalThis.Image, oldNow = Date.now;
  let now = 1_700_000_000_000;
  Date.now = () => now;
  globalThis.Image = class { naturalWidth = 200; naturalHeight = 100; async decode() {} };
  t.after(() => { globalThis.Image = oldImage; Date.now = oldNow; });
  const stage = {dataset: {}}, mode = {value: "overlay"};
  const elements = {
    "map-stage": stage, "map-display-mode": mode, "map-birdseye": {},
    "birdseye-toggle": {setAttribute() {}, removeAttribute() {}},
    "camera-comparison": {open: false},
  };
  const callbacks = new Map(), timers = [];
  const scope = {
    listen: (el, event, fn) => callbacks.set(el, fn), guard: (fn) => fn, interval() {},
    timeout(fn, ms) { const timer = {fn, ms}; timers.push(timer); return () => { timer.cancelled = true; }; },
    subscribe: (start) => start(), onDispose() {}, capture: () => ({current: () => true}),
  };
  const record = {map_id: "track", source_id: frame.source, calibration_revision: "rev",
    image: {width: 200, height: 100}, map_to_image: [1, 0, 0, 0, 1, 0, 0, 0, 1]};
  const map = {map_id: "track"}, otherMap = {map_id: "other"};
  const view = {siteMap: {maps: [map, otherMap]}, activeSiteMap: {map}};
  const backdrop = createCameraBackdrop({scope, el: (id) => elements[id], view, draw() {}});
  backdrop.setCalibrations([record, {...record, map_id: "other"}, {...record, source_id: "new-camera"}]);
  const plane = (seq) => ({state: "live", source: frame.source, seq, calibrationRevision: "rev", ageMs: 1000,
    plane: {min_x: 0, min_y: 0, max_x: 2, max_y: 1, ppm: 100}, blob: new Blob(["x"])});
  let send, finish;
  backdrop.bindCamera({onFrame: (fn) => { send = fn; }, fetchPlane: () => new Promise((resolve) => { finish = resolve; })});
  const raw = {...frame, image: new Image()};
  const flush = () => new Promise(setImmediate);
  send(raw);
  finish(plane(raw.seq));
  await flush();
  const paints = [];
  const ctx = {save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {}, clip() {}, transform() {},
    drawImage(image) { paints.push({image, alpha: this.globalAlpha}); }};
  const paint = () => backdrop.drawTopDown(ctx, backdrop.calibration(),
    {min_x: 0, min_y: 0, max_x: 2, max_y: 1}, (x, y) => ({x, y: -y}), 200, 100, 1, 0);
  paint();
  assert.equal(paints[0].alpha, 1);
  send({...raw, seq: 8});
  paint();
  assert.deepEqual(paints[1], paints[0]);
  timers.find((timer) => !timer.cancelled && timer.ms <= 2000).fn();
  paint();
  assert.deepEqual(paints[2], {...paints[0], alpha: 0.5});
  finish({state: "rate-limited"});  // transient 429 backoff keeps the last compatible plane
  await flush();
  paint();
  assert.deepEqual(paints[3], paints[2]);
  assert.equal(backdrop.usesPlane(), true);
  now += 300;
  send({...raw, seq: 9});
  finish({state: "plane-unavailable"});  // explicit 409 clears keptPlane -> D-515 fallback
  await flush();
  assert.equal(backdrop.usesPlane(), false);
  now += 30_000;
  send({...raw, seq: 10});
  finish(plane(10));  // fresh plane restores overlay after 409 backoff expires
  await flush();
  assert.equal(backdrop.usesPlane(), true);
  view.activeSiteMap = {map: otherMap};
  assert.equal(backdrop.usesPlane(), false);
  view.activeSiteMap = {map};
  send({...raw, seq: 11});
  mode.value = "coordinates";
  callbacks.get(mode)();
  assert.equal(backdrop.usesPlane(), false);
  mode.value = "overlay";
  callbacks.get(mode)();
  assert.equal(backdrop.usesPlane(), false);
});
