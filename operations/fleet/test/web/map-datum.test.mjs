import test from "node:test";
import assert from "node:assert/strict";

import {drawMapDatum} from "../../../../applications/fleet/web/map/map-datum.js";

globalThis.window = {RosyPalette: {canvasFont: () => "16px monospace"}};

function fakeCtx() {
  return {
    canvas: {width: 800, height: 600},
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {}, fill() {},
    setTransform() {}, fillText() {},
    getTransform() { return {a: 1, b: 0, transformPoint: (point) => point}; },
  };
}

const css = () => "black";
const identity = (x, y) => ({x, y});

test("the 0,0 label is present only when the frame contains the origin", () => {
  const inside = drawMapDatum(fakeCtx(), identity, {min_x: -1, max_x: 2, min_y: -1, max_y: 2}, {css});
  assert.ok(inside.some((item) => item.text === "0,0"));
  const outside = drawMapDatum(fakeCtx(), identity, {min_x: 1, max_x: 3, min_y: 1, max_y: 3}, {css});
  assert.equal(outside.some((item) => item.text === "0,0"), false);
  assert.deepEqual(outside.map((item) => item.text).sort(), ["x", "y"]);
});
