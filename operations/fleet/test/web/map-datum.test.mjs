import test from "node:test";
import assert from "node:assert/strict";

import {drawMapDatum} from "../../../../applications/fleet/web/map/map-datum.js";

globalThis.window = {RosyPalette: {canvasFont: () => "16px monospace"}};

function fakeCtx() {
  return {
    canvas: {width: 800, height: 600},
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {}, fill() {},
    fillRect() {}, strokeRect() {}, setTransform() {}, fillText() {},
    getTransform() { return {a: 1, b: 0, transformPoint: (point) => point}; },
  };
}

const css = () => "black";
const identity = (x, y) => ({x, y});

test("the 0,0 label is present only when the frame contains the origin, anchored at bottom-left", () => {
  const inside = drawMapDatum(fakeCtx(), identity, {min_x: -1, max_x: 2, min_y: -1, max_y: 2}, {css});
  assert.ok(inside.some((item) => item.text === "0,0"));
  assert.ok(inside.every((item) => item.x < 300 && item.y > 450), JSON.stringify(inside));
  const outside = drawMapDatum(fakeCtx(), identity, {min_x: 1, max_x: 3, min_y: 1, max_y: 3}, {css});
  assert.equal(outside.some((item) => item.text === "0,0"), false);
  assert.deepEqual(outside.map((item) => item.text).sort(), ["x", "y"]);
  assert.ok(outside.every((item) => item.x < 300 && item.y > 450), JSON.stringify(outside));
});

test("rotated projection keeps x and y arrows inside the bottom-left datum box", () => {
  const rotated90 = (x, y) => ({x: 400 - y * 100, y: 300 + x * 100});
  const labels = drawMapDatum(fakeCtx(), rotated90, {min_x: -1, max_x: 2, min_y: -1, max_y: 2}, {
    css,
    hoverWorld: {x: 0.42, y: -0.15},
  });
  const xLabel = labels.find((item) => item.text === "x");
  const yLabel = labels.find((item) => item.text === "y");
  assert.ok(labels.every((item) => item.x >= 8 && item.x < 300 && item.y > 450 && item.y < 600), JSON.stringify(labels));
  assert.ok(yLabel.x < xLabel.x, "rotated +y points left while +x stays vertically downward");
  assert.ok(xLabel.y > yLabel.y, "rotated +x points down on screen");
});
