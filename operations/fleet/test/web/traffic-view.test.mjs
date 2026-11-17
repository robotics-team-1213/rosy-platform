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
    assert.deepEqual(chips, ['yard · 점유 1/2 · 대기 1']);
    assert.ok(elements['map-traffic-status'].rows.some(row => row.textContent.includes('yard · 점유 1/2 · 대기 1')));
    drawTraffic(ctx, (x, y) => ({x, y}), 100, {...options, on: false});
    assert.deepEqual(chips, ['yard · 점유 1/2 · 대기 1']);
  } finally {globalThis.document = previous; globalThis.window = previousWindow;}
});

test('hatch pattern is cached by warn color and status DOM updates only when summary changes', () => {
  let hatchCanvases = 0;
  let createPatternCalls = 0;
  let replaceCalls = 0;
  const ctx = new Proxy({canvas: {width: 800, height: 600}}, {get(target, key) {
    if (key in target) return target[key];
    if (key === 'createPattern') return () => { createPatternCalls += 1; return 'pat'; };
    if (key === 'getTransform') return () => ({a: 1, b: 0, c: 0, d: 1, e: 0, f: 0});
    return () => {};
  }});
  const statusEl = {replaceChildren(...rows) { replaceCalls += 1; this.rows = rows; }};
  const elements = {'legend-traffic': {}, 'map-traffic-status': statusEl};
  const previous = globalThis.document;
  const previousWindow = globalThis.window;
  globalThis.window = {};
  globalThis.document = {
    createElement(tag) {
      if (tag === 'canvas') hatchCanvases += 1;
      return {
        width: 0,
        height: 0,
        getContext: () => new Proxy({}, {get(_t, k) { return k === 'clearRect' ? () => {} : () => {}; }}),
      };
    },
  };
  try {
    let warnToken = 'warn-a';
    const options = {
      view: {
        activeSiteMap: {version: 5, map: {edges: [{id: 'east', polyline: [[0, 0], [1, 0]]}]}},
        traffic: {map_version: 5, block_length_m: {east: 1}, units: [{id: 'east#0', state: 'UNKNOWN', holders: ['rosy_40']}]},
      },
      el: (id) => elements[id],
      css: (token) => (token === '--status-warn' ? warnToken : token),
      colorOf: () => 'col',
      drawChip: null,
      on: true,
    };
    const project = (x, y) => ({x: x * 100, y: y * 100});
    drawTraffic(ctx, project, 100, options);
    assert.equal(replaceCalls, 1);
    assert.equal(createPatternCalls, 1);
    const canvasesAfterFirst = hatchCanvases;

    drawTraffic(ctx, project, 100, options);
    assert.equal(replaceCalls, 1, 'identical summary should not call replaceChildren again');
    assert.equal(createPatternCalls, 1, 'identical warn color + ctx should reuse CanvasPattern');
    assert.equal(hatchCanvases - canvasesAfterFirst, 0, 'both hatch and outline canvases are reused across calls');

    warnToken = 'warn-b';
    drawTraffic(ctx, project, 100, options);
    assert.equal(createPatternCalls, 2, 'warn color change should rebuild hatch CanvasPattern');
    assert.equal(hatchCanvases, canvasesAfterFirst, 'warn color change should not allocate extra canvases');
  } finally {
    globalThis.document = previous;
    globalThis.window = previousWindow;
  }
});

test('outline canvas is allocated once per document and only resized when canvas grows', () => {
  const createdCanvases = [];
  let widthAssignments = 0;
  let heightAssignments = 0;
  const backing = {width: 800, height: 600};
  const ctx = new Proxy({canvas: backing}, {get(target, key) {
    if (key in target) return target[key];
    if (key === 'getTransform') return () => ({a: 1, b: 0, c: 0, d: 1, e: 0, f: 0});
    return () => {};
  }});
  const elements = {'legend-traffic': {}, 'map-traffic-status': {replaceChildren() {}}};
  const previous = globalThis.document;
  const previousWindow = globalThis.window;
  globalThis.window = {};
  globalThis.document = {
    createElement(tag) {
      let _w = 0;
      let _h = 0;
      const canvas = {
        get width() { return _w; },
        set width(v) { widthAssignments += 1; _w = v; },
        get height() { return _h; },
        set height(v) { heightAssignments += 1; _h = v; },
        getContext: () => new Proxy({}, {get() { return () => {}; }}),
      };
      if (tag === 'canvas') createdCanvases.push(canvas);
      return canvas;
    },
  };
  try {
    const options = {
      view: {
        activeSiteMap: {version: 5, map: {edges: [
          {id: 'east', polyline: [[0, 0], [1, 0]]},
          {id: 'west', polyline: [[0, 1], [1, 1]]},
        ]}},
        traffic: {
          map_version: 5,
          block_length_m: {east: 1, west: 1},
          units: [
            {id: 'yard_a', zone: true, state: 'FREE', capacity: 2, holders: ['rosy_01'], waiting: []},
            {id: 'yard_b', zone: true, state: 'FREE', capacity: 2, holders: [], waiting: []},
            {id: 'east#0', state: 'GRANTED', holders: ['rosy_01']},
            {id: 'west#0', state: 'GRANTED', holders: ['rosy_02']},
          ],
          signals: [{signal_id: 'sig_1', approaches: [{approach: 'east:fwd', lamp: 'green', stop_line: {x: 0.2, y: 0.3, yaw: 0}}]}],
        },
      },
      el: (id) => elements[id],
      css: (token) => token,
      colorOf: () => 'col',
      drawChip: null,
      on: true,
    };
    const project = (x, y) => ({x: x * 100, y: y * 100});
    drawTraffic(ctx, project, 100, options);
    drawSignalLamps(ctx, project, options);
    assert.equal(createdCanvases.length, 1, 'only one outline canvas allocated across all zones and bands');
    const widthsAfterFirst = widthAssignments;
    const heightsAfterFirst = heightAssignments;

    // Repeated draw at same or smaller dimensions reuses outlineCanvas without resizing
    backing.width = 640;
    backing.height = 480;
    drawTraffic(ctx, project, 100, options);
    drawSignalLamps(ctx, project, options);
    assert.equal(createdCanvases.length, 1);
    assert.equal(widthAssignments, widthsAfterFirst);
    assert.equal(heightAssignments, heightsAfterFirst);

    // Growing dimensions resizes outlineCanvas once without creating a new element
    backing.width = 1024;
    backing.height = 768;
    drawTraffic(ctx, project, 100, options);
    assert.equal(createdCanvases.length, 1);
    assert.equal(widthAssignments, widthsAfterFirst + 1);
    assert.equal(heightAssignments, heightsAfterFirst + 1);
  } finally {
    globalThis.document = previous;
    globalThis.window = previousWindow;
  }
});
