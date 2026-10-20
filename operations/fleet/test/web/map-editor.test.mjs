import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createEditHistory} from '/console/assets/edit-history.js';
import {editSurveyElement} from '/console/assets/site-map-edit.js';
import {replaceVertex, removeVertex, mapPoint} from '/console/assets/geometry-edit.js';

test('geometry primitives know only finite points and preserve their input', () => {
  const line = [[-2000, 5], [0, 1], [3, 4]];
  assert.deepEqual(replaceVertex(line, 1, [7, 8]), [[-2000, 5], [7, 8], [3, 4]]);
  assert.deepEqual(line[1], [0, 1]);
  assert.deepEqual(removeVertex(line, 1, 2), [[-2000, 5], [3, 4]]);
  assert.throws(() => removeVertex(line, 1, 3));
  assert.throws(() => replaceVertex(line, 7, [0, 0]));
  assert.throws(() => replaceVertex(line, 0, [NaN, 0]));
  assert.throws(() => replaceVertex(line, 0, [0, Infinity]));
});

test('screen conversion delegates units and rotation to the supplied view', () => {
  const svg = {getScreenCTM: () => ({inverse: () => ({kind: 'inverse'})})};
  const point = {matrixTransform: matrix => { assert.equal(matrix.kind, 'inverse'); return {x: 20, y: 10}; }};
  const view = {toMap: (x, y) => [-y / 2, x / 2]};
  assert.deepEqual(mapPoint(svg, view, point), [-5, 10]);
});

test('undo_redo_preserves_original_and_clears_redo_on_new_edit', () => {
  const original = {places: [{id: 'a', x: 0}], edges: []};
  const history = createEditHistory(original);
  original.places[0].x = 99;
  const before = history.current();
  history.apply({...before, map_id: 'second'});
  assert.deepEqual(history.undo(), before);
  assert.equal(history.canRedo(), true);
  history.apply({...before, map_id: 'third'});
  assert.equal(history.canRedo(), false);
  const current = history.current();
  current.places[0].x = 100;
  assert.equal(history.current().places[0].x, 0);
  history.reset(before);
  assert.equal(history.canUndo(), false);
  assert.equal(history.canRedo(), false);
});

test('history_budget_is_bounded', () => {
  const history = createEditHistory({n: 0});
  for (let n = 1; n < 100; n++) history.apply({n});
  let undos = 0;
  while (history.canUndo()) { history.undo(); undos++; }
  assert.ok(undos <= 49);
  const large = createEditHistory({n: 0});
  for (let n = 1; n < 12; n++) large.apply({n, payload: 'x'.repeat(1024 * 1024)});
  let bytes = JSON.stringify(large.current()).length;
  while (large.canUndo()) bytes += JSON.stringify(large.undo()).length;
  assert.ok(bytes <= 8 * 1024 * 1024);
  assert.throws(() => large.apply({payload: 'x'.repeat(9 * 1024 * 1024)}));
});

test('vertex_edit_preserves_road_endpoints_and_facility_links', () => {
  const map = {places: [{id: 'a', name: 'A', x: 0, y: 0, kind: 'junction'},
                        {id: 'b', name: 'B', x: 2, y: 0, kind: 'park'}],
    edges: [{id: 'ab', name: '입구 도로', from: 'a', to: 'b', polyline: [[0, 0], [1, 1], [2, 0]],
             width_m: .2, direction: 'one_way', speed_cap_mps: .2, drive_mode: 'lane'}],
    facilities: [{id: 'light', name: '신호', kind: 'traffic_signal', geometry: [[1, 0]],
                  approaches: [{edge_id: 'ab', forward: true}], signal_id: 's', signal_kind: 'physical'}],
    survey: {revision: 'survey', reviewed: false}};
  const moved = editSurveyElement(map, {id: 'a', name: 'A', kind: 'junction', geometry: [[0, 1]]});
  assert.deepEqual(moved.edges[0].polyline[0], [0, 1]);
  assert.equal(moved.edges[0].name, '입구 도로');
  assert.deepEqual(moved.facilities, map.facilities);
  const road = editSurveyElement(map, {id: 'ab', name: '입구 도로', kind: 'road', from: 'a', to: 'b',
    geometry: [[0, 0], [1, 2], [2, 0]], width_m: .2, direction: 'one_way'});
  assert.equal(road.edges[0].name, '입구 도로');
  assert.deepEqual(road.edges[0].polyline[1], [1, 2]);
  assert.equal(road.edges[0].speed_cap_mps, .2);
});
