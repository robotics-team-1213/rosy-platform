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
