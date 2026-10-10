import assert from "node:assert/strict";
import test from "node:test";
import { cameraMapCalibration, createCameraBackdrop } from "../../fleet/server/web/camera-backdrop.js";

const frame = { state: "live", rectified: false, source: "ceiling_north",
  ageMs: 100, image: { naturalWidth: 1280, naturalHeight: 720 },
  lens: { kind: "wide", focal_mm: 2.2, hfov_deg: 104.1 } };
const calibration = { source_id: "ceiling_north", map_id: "map_v2_fleet",
  image: { width: 1280, height: 720 }, lens: { kind: "wide", focal_mm: 2.2, hfov_deg: 104.1 },
  map_to_image: [1, 0, 0, 0, 1, 0, 0, 0, 1] };
const siteMap = { maps: [{ map_id: "map_v2_fleet" }] };

test("new frames on the same img refresh the warped backdrop; map redraw alone reuses it", (t) => {
  const previousDocument = globalThis.document;
  let canvases = 0;
  const context = new Proxy({}, { get: () => () => {} });
  globalThis.document = { createElement: () => {
    canvases += 1;
    return { getContext: () => context };
  } };
  t.after(() => { globalThis.document = previousDocument; });
  const backdrop = createCameraBackdrop({ scope: {}, el: () => null, view: { siteMap }, draw: () => {} });
  const draw = () => backdrop.drawTopDown(context, calibration,
    { min_x: 0, min_y: 0, max_x: 1, max_y: 1 }, (x, y) => ({ x, y }), 100, 100, 1, 0);
  backdrop.setCameraFrame({ ...frame, seq: 1 });
  draw(); draw();
  assert.equal(canvases, 1);
  backdrop.setCameraFrame({ ...frame, seq: 2 });
  draw();
  assert.equal(canvases, 2);
});

test("camera map accepts only a fresh raw frame with matching source, map, lens and size", () => {
  assert.equal(cameraMapCalibration(frame, [calibration], siteMap), calibration);
  for (const changed of [
    { state: "stale" }, { rectified: true }, { source: "other" },
    { ageMs: NaN }, { ageMs: 3001 }, { ageMs: -1 },
    { lens: { kind: "standard" } }, { lens: { ...frame.lens, focal_mm: 3 } },
    { image: { naturalWidth: 640, naturalHeight: 360 } },
  ]) assert.equal(cameraMapCalibration({ ...frame, ...changed }, [calibration], siteMap), null);
  assert.equal(cameraMapCalibration(frame, [calibration], { maps: [{ map_id: "wrong" }] }), null);
  // D-457: Vision voids a lens-less record once the frame reports a lens; the map must not draw it.
  const lensless = { ...calibration, lens: null };
  assert.equal(cameraMapCalibration(frame, [lensless], siteMap), null);
  assert.equal(cameraMapCalibration({ ...frame, lens: null }, [lensless], siteMap), lensless);
  // header rounding (6 significant digits) still matches
  assert.equal(cameraMapCalibration({ ...frame, lens: { ...frame.lens, hfov_deg: 104.10001 } },
    [calibration], siteMap), calibration);
});
