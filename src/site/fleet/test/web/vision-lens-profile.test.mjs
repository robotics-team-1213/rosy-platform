import test from "node:test";
import assert from "node:assert/strict";

import { parseLensHeader, rectificationKey, resolveSavedProfile } from "../../fleet/server/web/vision-view.js";

function memoryStorage(entries = {}) {
  const map = new Map(Object.entries(entries));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    keys: () => [...map.keys()],
  };
}

const LEGACY = "rosy-camera-rectification:s21";
const PROFILE = JSON.stringify({ k1: -0.2 });

test("Vision's lens header parses; unknown or missing lens is null", () => {
  assert.deepEqual(parseLensHeader("kind=wide;focal_mm=2.2;hfov_deg=104.1"),
    { kind: "wide", focal_mm: 2.2, hfov_deg: 104.1 });
  assert.equal(parseLensHeader(null), null);
  assert.equal(parseLensHeader("kind=tele;focal_mm=9"), null);
});

test("the profile key is per source and lens; an app without lens keeps the old key", () => {
  assert.equal(rectificationKey("s21", "wide"), "rosy-camera-rectification:s21@wide");
  assert.equal(rectificationKey("s21", null), LEGACY);
});

test("an old profile is copied to the standard lens and kept for an old app", () => {
  const storage = memoryStorage({ [LEGACY]: PROFILE });
  assert.deepEqual(resolveSavedProfile(storage, "s21", "standard"), { saved: PROFILE, warning: null });
  assert.deepEqual(storage.keys().sort(), [LEGACY, "rosy-camera-rectification:s21@standard"]);
  // Downgrade to an app without lens: the old key still holds the profile.
  assert.deepEqual(resolveSavedProfile(storage, "s21", null), { saved: PROFILE, warning: null });
  // A later standard edit does not touch the old key.
  storage.setItem("rosy-camera-rectification:s21@standard", "{}");
  assert.equal(resolveSavedProfile(storage, "s21", "standard").saved, "{}");
  assert.equal(storage.getItem(LEGACY), PROFILE);
});

test("an old app without lens still reads the old profile untouched", () => {
  const storage = memoryStorage({ [LEGACY]: PROFILE });
  assert.deepEqual(resolveSavedProfile(storage, "s21", null), { saved: PROFILE, warning: null });
  assert.deepEqual(storage.keys(), [LEGACY]);
});

test("a standard-lens profile is not applied to the ultra-wide, and says so", () => {
  for (const entries of [{ [LEGACY]: PROFILE }, { "rosy-camera-rectification:s21@standard": PROFILE }]) {
    const result = resolveSavedProfile(memoryStorage(entries), "s21", "wide");
    assert.equal(result.saved, null);
    assert.match(result.warning, /기본 렌즈용/);
    assert.match(result.warning, /초광각/);
  }
});

test("each lens keeps its own profile", () => {
  const wide = JSON.stringify({ k1: -0.3 });
  const storage = memoryStorage({ "rosy-camera-rectification:s21@standard": PROFILE,
    "rosy-camera-rectification:s21@wide": wide });
  assert.equal(resolveSavedProfile(storage, "s21", "wide").saved, wide);
  assert.equal(resolveSavedProfile(storage, "s21", "standard").saved, PROFILE);
  assert.deepEqual(resolveSavedProfile(memoryStorage(), "s21", "wide"), { saved: null, warning: null });
});

test("inherited object names are not lens kinds", () => {
  assert.equal(parseLensHeader("kind=toString"), null);
  assert.equal(parseLensHeader("kind=__proto__"), null);
});
