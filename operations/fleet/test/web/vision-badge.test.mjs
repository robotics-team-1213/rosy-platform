import test from "node:test";
import assert from "node:assert/strict";

import { FRAME_LATE_MS, frameBadge } from "../../fleet/server/web/vision-view.js";

test("a fresh frame reads live, never an auth-waiting label", () => {
  const raw = frameBadge({ ok: true, status: 200, ageMs: "244", rectified: false });
  assert.deepEqual([raw.state, raw.label, raw.kind], ["live", "원본 최신 프레임", "good"]);
  const rect = frameBadge({ ok: true, status: 200, ageMs: "80", rectified: true });
  assert.equal(rect.label, "화면 보정 미리보기");
  assert.notEqual(raw.label, "인증 대기");
});

test("an auto-rectified frame names the field calibration (D-484)", () => {
  const auto = frameBadge({ ok: true, status: 200, ageMs: "80", rectified: "auto" });
  assert.deepEqual([auto.state, auto.label, auto.kind], ["live", "자동 보정 미리보기", "good"]);
  const waiting = frameBadge({ ok: true, status: 200, ageMs: "80", rectified: false,
    frameState: "field-unavailable" });
  assert.deepEqual([waiting.state, waiting.label], ["live", "자동 보정 대기"]);
});

test("an old frame that still arrives reads late, not live", () => {
  const late = frameBadge({ ok: true, status: 200, ageMs: String(FRAME_LATE_MS + 1) });
  assert.deepEqual([late.state, late.kind], ["stale", "warn"]);
  assert.equal(frameBadge({ ok: true, status: 200, ageMs: null }).state, "live");
});

test("Vision's stale header reads stopped", () => {
  const stale = frameBadge({ ok: false, status: 503, frameState: "stale" });
  assert.deepEqual([stale.state, stale.label], ["stale", "영상 정지"]);
});

test("a rejected lease reads unauthorized", () => {
  for (const status of [401, 403]) {
    assert.equal(frameBadge({ ok: false, status }).state, "unauthorized");
  }
});

test("no frame yet and a bad rectification are told apart", () => {
  assert.equal(frameBadge({ ok: false, status: 404 }).state, "no-frame");
  assert.equal(frameBadge({ ok: false, status: 422 }).state, "invalid");
});
