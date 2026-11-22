import test from "node:test";
import assert from "node:assert/strict";
import { createMapPolling } from "../../../../applications/fleet/web/map/map-polling.js";

test("invalidating page scope while refreshSiteMap awaits resolves cleanly without AbortError", async () => {
  const nodes = new Map();
  const el = (id) => {
    if (!nodes.has(id)) {
      const node = {
        hidden: false, textContent: "", tabIndex: 0, dataset: {},
        classList: { add() {}, remove() {} },
        setAttribute() {}, removeAttribute() {},
        querySelectorAll: () => [],
        getContext: () => ({ clearRect() {} }),
      };
      nodes.set(id, node);
    }
    return nodes.get(id);
  };
  let current = true;
  let calls = 0;
  const scope = {
    capture: () => ({
      signal: new AbortController().signal,
      current: () => current,
      check() { if (!current) throw new DOMException("Page operation is no longer current", "AbortError"); },
    }),
    listen() {},
    onDispose() {},
  };
  const polling = createMapPolling({
    scope,
    el,
    view: { siteMap: null, activeSiteMap: null, map: null, robots: [], sightings: [] },
    auth: { locked: false },
    camera: { setCalibrations() {} },
    draw() {},
    layerOn: () => false,
    onMapChanged() {},
    onMapUnavailable() {},
    onTrafficChanged() {},
    call: async (path) => {
      calls += 1;
      if (path === "/api/fleet/site-map") {
        current = false;  // pageScope.invalidate() while /api/fleet/site-map is in flight
        return { maps: [] };
      }
      throw new Error(`unexpected call after invalidation: ${path}`);
    },
  });
  await assert.doesNotReject(polling.refresh());
  assert.equal(calls, 1);
  current = false;
  await assert.doesNotReject(polling.refresh());
  assert.equal(calls, 1);
});
