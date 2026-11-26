import test from "node:test";
import assert from "node:assert/strict";

import {axisOrientation, drawMapDatum, gridCellOf} from "../../../../applications/fleet/web/map/map-datum.js";
import {fitBox} from "../../../../applications/fleet/web/shared/site-map-model.js";

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
test("cells are half-open in map metres on both sides of the ROS origin", () => {
  assert.deepEqual(gridCellOf(-0.001, 0.5), { col: -1, row: 1, x0: -0.5, x1: 0, y0: 0.5, y1: 1, label: "X-1·Y1" });
  assert.equal(gridCellOf(-0.5, -0.501).label, "X-1·Y-2");
  assert.equal(gridCellOf(0, 0).label, "X0·Y0");
});

test("metre ticks and cell labels keep their projected positions through all four turns", () => {
  const bounds = {min_x: -1, max_x: 2, min_y: -1, max_y: 2};
  const orientations = ["+X → · +Y ↑", "+X ↓ · +Y →", "+X ← · +Y ↓", "+X ↑ · +Y ←"];
  for (const [index, rot] of [0, 90, 180, 270].entries()) {
    const fit = fitBox(bounds, 300, 300, 0, rot);
    const project = (x, y) => { const [px, py] = fit.toPx(x, y); return {x: px, y: py}; };
    const labels = drawMapDatum(fakeCtx(), project, bounds, {css});
    const horizontalAxis = rot % 180 === 0 ? "X" : "Y";
    assert.equal(axisOrientation(rot), orientations[index]);
    assert.equal(labels.filter((item) => item.text === "0").length, 2);
    assert.equal(labels.find((item) => item.text === horizontalAxis + "0").x,
      project(0.25, 0.25).x);
    assert.ok(labels.every((item) => item.text !== "0,0"));
  }
  const outside = drawMapDatum(fakeCtx(), (x, y) => ({x: 100 * x, y: -100 * y}),
    {min_x: 1, max_x: 3, min_y: 1, max_y: 3}, {css});
  assert.ok(!outside.some((item) => item.text === "0"));
});
