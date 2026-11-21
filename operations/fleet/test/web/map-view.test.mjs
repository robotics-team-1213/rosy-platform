import test from 'node:test';
import assert from 'node:assert/strict';
import { createMapView } from '../../../../applications/fleet/web/map/map-view.js';

async function verifyMapView(useCache) {
  let staticPaints = 0, clears = 0;
  const makeContext = (methods) => new Proxy(methods, {
    get: (target, key) => target[key] ?? (key === 'measureText' ? () => ({width: 10}) : () => {}),
  });
  const ctx = makeContext({clearRect: () => { clears += 1; }});
  const off = makeContext({stroke: () => { staticPaints += 1; }});
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, {
      dataset: {}, classList: { add() {}, remove() {} }, querySelectorAll: () => [],
      setAttribute() {}, removeAttribute() {}, getContext: () => ctx,
      replaceChildren(...rows) {this.rows = rows;},
      getBoundingClientRect: () => ({ width: 800, height: 600 }),
      clientWidth: 800, clientHeight: 600,
    });
    return elements.get(id);
  };
  const previous = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: () => useCache ? {getContext: () => off} : {},
    getElementById: () => null, documentElement: {dataset: {theme: 'dark'}},
  };
  const frames = [];
  globalThis.window = {devicePixelRatio: 1,
    requestAnimationFrame(fn) { frames.push(fn); return frames.length; }, RosyPalette: {
    cssColor: () => '#000', canvasFont: () => '12px sans-serif',
  } };
  try {
    const view = { robots: [], sightings: [], colors: ['#000'], layers: {}, map: null };
    const calls = [];
    const scope = { capture: () => ({ check() {}, current: () => true }), onDispose() {}, listen() {} };
    const map = createMapView({ scope, el, view, auth: { locked: false },
      onMapChanged() {}, onMapUnavailable() {}, call: async (path) => {
        calls.push(path);
        if (path === '/api/fleet/site-map') return { maps: [
          { map_id: 'track', polygon_m: [[0, 0], [2, 0], [2, 1], [0, 1]],
            bounds_m: { min_x: 0, min_y: 0, max_x: 2, max_y: 1 }, sources: [] },
        ] };
        if (path === '/api/fleet/site-map/active') return { version: 5, map: { map_id: 'track' } };
        if (path === '/api/fleet/calibrations') return { calibrations: [] };
        if (path === '/api/fleet/map') throw new Error('robot grid must not replace the active site map');
        throw new Error(path);
      } });
    await map.refresh();
    view.robots = [{ robot_id: 'r1', online: true, capabilities: { navigation: true }, state: {
      localization: { state: 'LOCALIZED', pose_frame: 'map' },
    } }];
    await map.refresh();
    assert.equal(el('map-stage').dataset.mapState, 'site');
    assert.equal(view.map, null);
    assert.ok(!calls.includes('/api/fleet/map'));
    while (frames.length) frames.shift()();
    const before = {staticPaints, clears};
    view.pointerWorld = {x: 0.2, y: 0.2};
    map.scheduleDraw();
    map.scheduleDraw();
    assert.equal(frames.length, 1);
    assert.equal(clears, before.clears);
    frames.shift()();
    assert.equal(clears, before.clears + 1);
    assert.equal(staticPaints, before.staticPaints);
    if (useCache) {
      assert.ok(staticPaints > 0);
      document.documentElement.dataset.theme = 'light';
      map.draw();
      assert.ok(staticPaints > before.staticPaints);
    }
    el('map-traffic-status').rows = [{textContent: 'green'}];
    view.siteMap = null;
    map.draw();
    assert.equal(el('map-traffic-status').rows[0].textContent, '교통 상태 대기');
  } finally { globalThis.window = previous; globalThis.document = previousDocument; }
}

test('an active camera map keeps its coordinate view with a stub canvas', () => verifyMapView(false));
test('the site map reuses its static layer and batches paints', () => verifyMapView(true));
