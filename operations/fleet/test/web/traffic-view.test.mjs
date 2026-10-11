import test from 'node:test';
import assert from 'node:assert/strict';
import {drawTraffic, drawSignalLamps} from '../../fleet/server/web/traffic-view.js';

test('signal and occupancy descriptions stay outside the floor plane', () => {
  const arcs = [];
  const ctx = new Proxy({canvas: {width: 800, height: 600}}, {get(target, key) {
    if (key in target) return target[key];
    if (key === 'fillText' || key === 'measureText') return () => assert.fail('traffic text painted on floor');
    if (key === 'arc') return (...args) => arcs.push(args);
    return () => {};
  }});
  const elements = {'legend-traffic': {}, 'map-traffic-status': {replaceChildren(...rows) {this.rows = rows;}}};
  const previous = globalThis.document;
  const previousWindow = globalThis.window;
  globalThis.window = {};
  globalThis.document = {createElement: () => ({getContext: () => ctx})};
  try {
    const options = {view: {activeSiteMap: {version: 5, map: {edges: []}}, traffic: {
      map_version: 5, units: [], signals: [{signal_id: 'sig_ring', approaches: [{
        approach: 'east:fwd', lamp: 'green', stop_line: {x: .2, y: .3, yaw: 0},
      }]}],
    }}, el: id => elements[id], css: token => token, colorOf: () => '',
      drawChip: () => assert.fail('traffic label painted on floor'), on: true};
    const project = (x, y) => ({x: x * 100, y: y * 100});
    drawTraffic(ctx, project, 100, options);
    drawSignalLamps(ctx, project, options);
    assert.ok(elements['map-traffic-status'].rows.some(row => row.textContent.includes('sig_ring') && row.textContent.includes('east:fwd')));
    assert.ok(arcs.length > 0 && arcs.every(arc => arc[2] <= 12));
    drawTraffic(ctx, project, 100, {...options, on: false});
    assert.equal(elements['map-traffic-status'].rows[0].textContent, '교통 표시 꺼짐');
  } finally {globalThis.document = previous; globalThis.window = previousWindow;}
});
