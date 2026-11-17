import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { createSelection } = await import("../../../../shared/web/selection.js");
const { shownRobot, createDeviceWatch } = await import("../../../../applications/fleet/web/device-watch.js");

test("the watch follows the open card, then the armed robot, then a sole robot", () => {
  const one = { robot_id: "rosy_26" };
  const two = { robot_id: "rosy_60" };
  assert.equal(shownRobot({ robots: [one, two], robotSelection: createSelection("rosy_60"), selected: "rosy_26" }).robot_id, "rosy_60");
  assert.equal(shownRobot({ robots: [one, two], robotSelection: createSelection(null), selected: "rosy_26" }).robot_id, "rosy_26");
  assert.equal(shownRobot({ robots: [one], robotSelection: createSelection(null), selected: null }).robot_id, "rosy_26");
  assert.equal(shownRobot({ robots: [one, two], robotSelection: createSelection("missing"), selected: null }), null);
  assert.equal(shownRobot({ robots: [] }), null);
});

test("device-watch hides #watch-ceiling in overlay, camera, and twin3d modes and shows it in coordinates with live birdseye", () => {
  const nodes = new Map();
  const makeNode = () => {
    const attrs = new Map();
    const listeners = new Map();
    return {
      hidden: false,
      disabled: false,
      dataset: {},
      setAttribute(k, v) { attrs.set(k, String(v)); },
      getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
      removeAttribute(k) { attrs.delete(k); },
      addEventListener(type, fn) { listeners.set(type, fn); },
      click() { listeners.get("click")?.(); },
    };
  };
  const el = (id) => {
    if (!nodes.has(id)) nodes.set(id, makeNode());
    return nodes.get(id);
  };
  el("map-stage").dataset.watch = "pip";
  el("map-birdseye").hidden = false;
  el("watch-front").hidden = true;
  const view = { robots: [], displayMode: "coordinates" };
  const scope = { listen: (node, type, fn) => node.addEventListener(type, fn) };
  const watch = createDeviceWatch({ scope, el, view });

  watch.render();
  assert.equal(el("watch-ceiling").hidden, false);
  assert.equal(el("device-watch").hidden, false);
  assert.equal(el("watch-ceiling").disabled, false);

  view.displayMode = "overlay";
  watch.render();
  assert.equal(el("watch-ceiling").hidden, true);
  assert.equal(el("device-watch").hidden, true);

  view.displayMode = "camera";
  watch.render();
  assert.equal(el("watch-ceiling").hidden, true);
  assert.equal(el("device-watch").hidden, true);

  view.displayMode = "coordinates";
  el("map-stage").dataset.displayMode = "twin3d";
  watch.render();
  assert.equal(el("watch-ceiling").hidden, true);
  assert.equal(el("device-watch").hidden, true);

  delete el("map-stage").dataset.displayMode;
  el("map-stage").dataset.view = "camera";
  watch.render();
  assert.equal(el("watch-ceiling").hidden, true);

  el("map-stage").dataset.view = "map";
  el("map-birdseye").hidden = true;
  watch.render();
  assert.equal(el("watch-ceiling").hidden, true);
  assert.equal(el("watch-ceiling").disabled, true);

  el("map-birdseye").hidden = false;
  watch.render();
  assert.equal(el("watch-ceiling").hidden, false);
  assert.equal(el("watch-ceiling").getAttribute("aria-pressed"), "true");
  el("watch-ceiling").click();
  assert.equal(el("map-stage").dataset.watch, "off");
  assert.equal(el("watch-ceiling").getAttribute("aria-pressed"), "false");
});
