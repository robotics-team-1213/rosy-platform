import test from 'node:test';
import assert from 'node:assert/strict';
import { createMapView } from '../../../../applications/fleet/web/map/map-view.js';

test('an active camera map keeps its coordinate view when a robot starts serving a grid', async () => {
  const ctx = new Proxy({}, { get: (_, key) => key === 'measureText' ? () => ({ width: 10 }) : () => {} });
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
  globalThis.document = {createElement: () => ({}), getElementById: () => null};
  globalThis.window = { devicePixelRatio: 1, RosyPalette: {
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
    el('map-traffic-status').rows = [{textContent: 'green'}];
    view.siteMap = null;
    map.draw();
    assert.equal(el('map-traffic-status').rows[0].textContent, '교통 상태 대기');
  } finally { globalThis.window = previous; globalThis.document = previousDocument; }
});
