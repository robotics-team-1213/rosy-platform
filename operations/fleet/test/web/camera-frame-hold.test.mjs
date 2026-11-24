import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

const {
  formatDisconnectDuration,
  decodeImageUrl,
  createCameraFrameHold,
  paintCameraFrameHold,
} = await import("/common/camera-frame-hold.js");

test("formatDisconnectDuration formats seconds and minutes without '초 전'", () => {
  assert.equal(formatDisconnectDuration(-500), "0초간 끊어짐");
  assert.equal(formatDisconnectDuration(5200), "5초간 끊어짐");
  assert.equal(formatDisconnectDuration(60000), "1분간 끊어짐");
  assert.equal(formatDisconnectDuration(125000), "2분 5초간 끊어짐");
  for (const ms of [0, 1000, 59999, 60000, 125000]) {
    assert.doesNotMatch(formatDisconnectDuration(ms), /초 전/);
  }
});

test("createCameraFrameHold keeps never-live hidden and preserves last live frame across disconnects", () => {
  let clock = 10_000;
  const revoked = [];
  const hold = createCameraFrameHold({ now: () => clock, onRevoke: (u) => revoked.push(u) });

  // Never-live camera stays waiting with no frame
  hold.disconnect({ label: "카메라 송신기 미연결" });
  let snap = hold.snapshot();
  assert.equal(snap.phase, "waiting");
  assert.equal(snap.hasFrame, false);
  assert.equal(snap.url, null);

  // Live frame accepted
  hold.acceptFrame({ url: "blob:1", seq: "10", label: "원본 최신 프레임", detail: "#10" });
  snap = hold.snapshot();
  assert.equal(snap.phase, "live");
  assert.equal(snap.hasFrame, true);
  assert.equal(snap.url, "blob:1");
  assert.equal(snap.overlayText, "");

  // First disconnect starts elapsed timer and retains blob:1
  clock = 12_000;
  hold.disconnect({ label: "영상 연결 끊김" });
  clock = 15_400;
  // Repeated disconnect does not reset disconnectedAt
  hold.disconnect({ label: "영상 요청 한도 도달" });
  snap = hold.snapshot(17_200);
  assert.equal(snap.phase, "disconnected");
  assert.equal(snap.hasFrame, true);
  assert.equal(snap.url, "blob:1");
  assert.equal(snap.disconnectedMs, 5200);
  assert.equal(snap.overlayText, "끊어짐 · 5초간 끊어짐 · 영상 요청 한도 도달");
  assert.deepEqual(revoked, []);

  // Pause preserves last frame too
  hold.setPaused(true);
  snap = hold.snapshot();
  assert.equal(snap.phase, "paused");
  assert.equal(snap.hasFrame, true);
  assert.equal(snap.overlayText, "영상 일시정지 · 마지막 프레임 유지");
  hold.setPaused(false);
  assert.equal(hold.snapshot().phase, "disconnected");

  // New frame revokes old frame and resets disconnect state
  hold.acceptFrame({ url: "blob:2", seq: "11", label: "원본 최신 프레임", detail: "#11" });
  assert.deepEqual(revoked, ["blob:1"]);
  assert.equal(hold.snapshot().phase, "live");

  // dropFrame (401/403) clears and revokes
  hold.disconnect({ label: "영상 권한 없음", dropFrame: true });
  assert.deepEqual(revoked, ["blob:1", "blob:2"]);
  assert.equal(hold.snapshot().hasFrame, false);
  assert.equal(hold.snapshot().phase, "waiting");

  hold.dispose();
});

test("decodeImageUrl handles non-DOM fallback and mock Image.decode", async () => {
  assert.equal(await decodeImageUrl("blob:1", { ImageCtor: undefined }), true);
  assert.equal(await decodeImageUrl("blob:2", {
    ImageCtor: class { decode() { return Promise.resolve(); } },
  }), true);
  assert.equal(await decodeImageUrl("blob:bad", {
    ImageCtor: class { decode() { return Promise.reject(new Error("corrupt")); } },
  }), false);
});

test("paintCameraFrameHold updates dataset, img, and overlay minimally", () => {
  const frame = { dataset: {} };
  const img = { hidden: true, src: "", removeAttribute(k) { if (k === "src") this.src = ""; } };
  const overlay = { hidden: false, textContent: "" };

  paintCameraFrameHold(frame, img, overlay, { phase: "live", hasFrame: true, url: "blob:1", overlayText: "" });
  assert.equal(frame.dataset.camPhase, "live");
  assert.equal(frame.dataset.camHasFrame, "true");
  assert.equal(img.hidden, false);
  assert.equal(img.src, "blob:1");
  assert.equal(overlay.hidden, true);

  paintCameraFrameHold(frame, img, overlay, {
    phase: "disconnected", hasFrame: true, url: "blob:1", overlayText: "끊어짐 · 3초간 끊어짐",
  });
  assert.equal(frame.dataset.camPhase, "disconnected");
  assert.equal(img.hidden, false);
  assert.equal(img.src, "blob:1");
  assert.equal(overlay.hidden, false);
  assert.equal(overlay.textContent, "끊어짐 · 3초간 끊어짐");
});
