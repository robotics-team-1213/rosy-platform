import test from "node:test";
import assert from "node:assert/strict";

const {
  robotCameraSourceId,
  cameraTileViewModel,
  createRobotCameraPoller,
} = await import("../../../../applications/fleet/web/robot/robot-camera-tile.js");

test("robotCameraSourceId derives pinky_<N>_front from robot id without a map", () => {
  assert.equal(robotCameraSourceId("rosy_45"), "pinky_45_front");
  assert.equal(robotCameraSourceId("rosy_01"), "pinky_01_front");
  assert.equal(robotCameraSourceId("arm_a"), null);
  assert.equal(robotCameraSourceId(""), null);
});

test("cameraTileViewModel covers unregistered, fresh, and stale frames", () => {
  assert.deepEqual(cameraTileViewModel({ registered: false }, 10000), {
    state: "unregistered",
    text: "카메라 등록 안 됨",
    hasImage: false,
    url: null,
  });
  const kept = { state: "live", ageMs: 500, capturedAtMs: 9500, url: "blob:1" };
  assert.equal(cameraTileViewModel({ registered: true, keptFrame: kept, lastFrame: kept }, 10000).state, "live");
  assert.equal(cameraTileViewModel({ registered: true, keptFrame: kept, lastFrame: kept }, 10000).text, "최신 사진 · 1초 전");
  const stale = cameraTileViewModel({ registered: true, keptFrame: kept, lastFrame: { state: "stale", ageMs: 5000 } }, 15000);
  assert.equal(stale.state, "stale");
  assert.equal(stale.text, "최신 사진 · 6초 전");
  assert.equal(stale.url, "blob:1");
});

test("createRobotCameraPoller handles fresh, stale (keeps last frame), and unregistered", async () => {
  let nowMs = 100_000;
  let sources = ["pinky_45_front"];
  let frameResp = { ok: true, status: 200, ageMs: "1000", frameState: "live", size: 4 };
  const leased = [];
  const revoked = [];
  let seq = 0;
  const states = [];

  const poller = createRobotCameraPoller({
    robotId: "rosy_45",
    now: () => nowMs,
    createObjectURL: () => `blob:frame-${++seq}`,
    revokeObjectURL: (u) => revoked.push(u),
    call: async (path, opts) => {
      if (path === "/api/fleet/vision/sources") return { sources };
      if (path === "/api/fleet/vision/lease") {
        leased.push(JSON.parse(opts.body));
        return { lease: "tok-1", expires_in_s: 60, frame_path: "/api/vision/sources/pinky_45_front/frame" };
      }
      throw new Error(`unexpected call ${path}`);
    },
    fetchImpl: async () => ({
      ok: frameResp.ok,
      status: frameResp.status,
      headers: {
        get: (name) => (name === "X-Frame-Age-Ms" ? frameResp.ageMs : name === "X-Frame-State" ? frameResp.frameState : null),
      },
      blob: async () => ({ size: frameResp.size }),
    }),
    onChange: (vm) => states.push(vm),
  });

  await poller.step();
  assert.deepEqual(leased, [{ source_id: "pinky_45_front" }]);
  assert.equal(states.at(-1).state, "live");
  assert.equal(states.at(-1).text, "최신 사진 · 1초 전");
  assert.equal(states.at(-1).url, "blob:frame-1");

  // Stale update keeps the last live picture and advances age.
  nowMs += 4000;
  frameResp = { ok: true, status: 200, ageMs: "5000", frameState: "stale", size: 4 };
  await poller.step();
  assert.equal(states.at(-1).state, "stale");
  assert.equal(states.at(-1).text, "최신 사진 · 5초 전");
  assert.equal(states.at(-1).url, "blob:frame-1");

  // Unregistered source reports 카메라 등록 안 됨 without leasing.
  sources = [];
  const unreg = createRobotCameraPoller({
    robotId: "rosy_47",
    call: async (path) => (path === "/api/fleet/vision/sources" ? { sources } : (() => { throw new Error("should not lease"); })()),
    onChange: (vm) => states.push(vm),
  });
  await unreg.step();
  assert.equal(states.at(-1).state, "unregistered");
  assert.equal(states.at(-1).text, "카메라 등록 안 됨");
  poller.stop();
  assert.deepEqual(revoked, ["blob:frame-1"]);
});
