import test from 'node:test';
import assert from 'node:assert/strict';
import {drawTraffic, drawSignalLamps} from '../../../../applications/fleet/web/map/traffic-view.js';

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
    options.view.activeSiteMap.map.edges = [{id: 'east', polyline: [[0, 0], [1, 0]]}];
    options.view.traffic = {map_version: 5, block_length_m: {east: 1},
      units: [{id: 'east#0', state: 'OCCUPIED', holders: ['rosy_40']}],
      robots: [{robot_id: 'rosy_40', authority_end_m: .8}]};
    options.view.trafficTrips = [{robot_id: 'rosy_40', plan: {segments: [{edge_id: 'east', forward: true, s_from: 0, s_to: 1}]}}];
    drawTraffic(ctx, project, 100, options);
    assert.ok(elements['map-traffic-status'].rows.some(row => row.textContent.includes('rosy_40') && row.textContent.includes('점유 중')));
    assert.ok(elements['map-traffic-status'].rows.some(row => row.textContent === '통행권 끝 · rosy_40'));
    drawTraffic(ctx, project, 100, {...options, on: false});
    assert.equal(elements['map-traffic-status'].rows[0].textContent, '교통 표시 꺼짐');
  } finally {globalThis.document = previous; globalThis.window = previousWindow;}
});

test('a zone occupancy sentence is a chip on the zone and stays in the list', () => {
  const chips = [];
  const ctx = new Proxy({canvas: {width: 800, height: 600}}, {get(target, key) {
    if (key in target) return target[key];
    return () => {};
  }});
  const elements = {'legend-traffic': {}, 'map-traffic-status': {replaceChildren(...rows) {this.rows = rows;}}};
  const previous = globalThis.document;
  const previousWindow = globalThis.window;
  globalThis.window = {};
  globalThis.document = {createElement: () => ({getContext: () => ctx})};
  try {
    const options = {view: {activeSiteMap: {version: 5, map: {edges: [{id: 'east', polyline: [[0, 0], [2, 0]]}]}}, traffic: {
      map_version: 5, block_length_m: {east: 1},
      units: [{id: 'yard', zone: true, state: 'FREE', capacity: 2, holders: ['rosy_01'], waiting: ['rosy_02']}],
    }}, el: id => elements[id], css: token => token, colorOf: () => '',
      drawChip: (_ctx, _grid, _x, _y, text) => chips.push(text), on: true};
    drawTraffic(ctx, (x, y) => ({x, y}), 100, options);
    assert.deepEqual(chips, ['점유 1/2 · 대기 1']);
    assert.ok(elements['map-traffic-status'].rows.some(row => row.textContent.includes('점유 1/2 · 대기 1')));
    drawTraffic(ctx, (x, y) => ({x, y}), 100, {...options, on: false});
    assert.deepEqual(chips, ['점유 1/2 · 대기 1']);
  } finally {globalThis.document = previous; globalThis.window = previousWindow;}
});
