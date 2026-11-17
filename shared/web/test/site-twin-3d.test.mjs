import { test } from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
const loaderSource = `
export async function resolve(specifier, context, next) {
  if (specifier === "./ui.js" && context.parentURL?.includes("/shared/web/")) {
    return { url: "data:text/javascript,export const readColour = () => [0, 0, 0, 0];", shortCircuit: true };
  }
  return next(specifier, context);
}
`;
register(`data:text/javascript,${encodeURIComponent(loaderSource)}`);

const {
  siteBoundsCenter,
  rayPlaneIntersection,
  orbitEyePosition,
  twinPresetOrbit,
  createSiteTwin3d,
} = await import("../site-twin-3d.js");

test("siteBoundsCenter computes center, extent, and bounding radius and rejects invalid bounds", () => {
  const c = siteBoundsCenter({ min_x: -1.4, max_x: 1.4, min_y: -0.6, max_y: 0.6 });
  assert.ok(Math.abs(c.x) < 1e-12 && Math.abs(c.y) < 1e-12);
  assert.ok(Math.abs(c.width - 2.8) < 1e-12 && Math.abs(c.height - 1.2) < 1e-12);
  assert.ok(Math.abs(c.radius - Math.hypot(2.8, 1.2) / 2) < 1e-12);

  assert.equal(siteBoundsCenter(null), null);
  assert.equal(siteBoundsCenter({ min_x: 1, max_x: 0, min_y: 0, max_y: 1 }), null);
  assert.equal(siteBoundsCenter({ min_x: 0, max_x: 1, min_y: Number.NaN, max_y: 1 }), null);
});

test("rayPlaneIntersection intersects z-planes and rejects parallel or backward rays", () => {
  const hit = rayPlaneIntersection([1, 2, 4], [0, 0, -1], 0);
  assert.deepEqual(hit, { x: 1, y: 2, z: 0, t: 4 });

  const angled = rayPlaneIntersection({ x: 0, y: 0, z: 2 }, { x: 1, y: -0.5, z: -1 }, 0.5);
  assert.ok(Math.abs(angled.t - 1.5) < 1e-12);
  assert.ok(Math.abs(angled.x - 1.5) < 1e-12);
  assert.ok(Math.abs(angled.y + 0.75) < 1e-12);
  assert.equal(angled.z, 0.5);

  assert.equal(rayPlaneIntersection([0, 0, 2], [1, 0, 0], 0), null); // parallel to z=0
  assert.equal(rayPlaneIntersection([0, 0, 2], [0, 0, 1], 0), null); // pointing away
});

test("orbitEyePosition and twinPresetOrbit produce top (+Y up), iso, and reset views aligned with turnDeg", () => {
  const bounds = { min_x: -1.4, max_x: 1.4, min_y: -0.63, max_y: 0.63 };
  const iso = twinPresetOrbit(bounds, "iso");
  const top = twinPresetOrbit(bounds, "top");
  const reset = twinPresetOrbit(bounds, "reset");
  assert.deepEqual(iso.target, [0, 0, 0]);
  assert.deepEqual(reset, iso);
  assert.ok(top.el > 1.5 && Math.abs(top.az + Math.PI / 2) < 1e-9);

  const top90 = twinPresetOrbit(bounds, "top", 90);
  const iso90 = twinPresetOrbit(bounds, "iso", 90);
  const reset90 = twinPresetOrbit(bounds, "reset", 90);
  assert.ok(Math.abs(top90.az - 0) < 1e-9, `expected top az=0 for turnDeg=90, got ${top90.az}`);
  assert.ok(Math.abs(iso90.az - (-Math.PI * 0.35 + Math.PI / 2)) < 1e-9);
  assert.deepEqual(reset90, iso90);
  assert.deepEqual(twinPresetOrbit("top", bounds, 90), top90);

  const eyeIso = orbitEyePosition(iso.target, iso);
  assert.ok(eyeIso[2] > 1.0 && eyeIso[1] < 0);
  const eyeTop = orbitEyePosition([0.5, -0.2, 0], { az: 0, el: Math.PI / 2, dist: 3 });
  assert.ok(Math.abs(eyeTop[0] - 0.5) < 1e-9 && Math.abs(eyeTop[1] + 0.2) < 1e-9 && Math.abs(eyeTop[2] - 3) < 1e-9);
  assert.throws(() => twinPresetOrbit(bounds, "unknown"), RangeError);
});

test("createSiteTwin3d calls onUnavailable cleanly without a canvas and resolves ready=false", async () => {
  let err = null;
  const twin = createSiteTwin3d({
    canvas: null,
    onUnavailable: (e) => { err = e; },
  });
  const ok = await twin.ready;
  assert.equal(ok, false);
  assert.ok(err instanceof Error);
  twin.dispose();
});
