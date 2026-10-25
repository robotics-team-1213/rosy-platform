import {test} from 'node:test';
import assert from 'node:assert/strict';
import {splitRoad, joinRoads} from '/console/assets/map-topology.js';

const map = () => ({map_id: 'any-floor', places: [
  {id: 'a', name: 'A', x: 0, y: 0}, {id: 'b', name: 'B', x: 2, y: 0}, {id: 'c', name: 'C', x: 4, y: 0}],
  edges: [{id: 'ab', from: 'a', to: 'b', polyline: [[0, 0], [1, 0], [2, 0]], width_m: .2,
    direction: 'one_way', speed_cap_mps: .1, drive_mode: 'lane'},
  {id: 'bc', from: 'b', to: 'c', polyline: [[2, 0], [4, 0]], width_m: .2,
    direction: 'one_way', speed_cap_mps: .1, drive_mode: 'lane'}], survey: {revision: 'r', reviewed: true}});

test('explicit road split and join preserve policy and reset review atomically', () => {
  const original = map(), before = JSON.stringify(original);
  const split = splitRoad(original, 'ab', 1, 'mid', 'second');
  assert.equal(split.edges.length, 3);
  assert.equal(split.places.length, 4);
  assert.equal(split.edges.find(e => e.id === 'second').speed_cap_mps, .1);
  assert.equal(split.survey.reviewed, false);
  const joined = joinRoads(split, 'ab', 'second');
  assert.equal(joined.edges.length, 2);
  assert.deepEqual(joined.edges.find(e => e.id === 'ab').polyline, [[0, 0], [1, 0], [2, 0]]);
  assert.equal(JSON.stringify(original), before);
  assert.throws(() => splitRoad(original, 'ab', 0, 'mid', 'second'));
  assert.throws(() => splitRoad(original, 'ab', 1, 'a', 'second'));
  assert.throws(() => joinRoads(original, 'bc', 'ab'));
});

test('road references and differing policies require explicit review instead of silent rewrites', () => {
  for (const referenced of [
    {...map(), turn_bans: [{at: 'b', from_edge: 'ab', to_edge: 'bc'}]},
    {...map(), facilities: [{approaches: [{edge_id: 'ab'}]}]},
    {...map(), crosswalks: [{lanes: ['ab']}]},
  ]) {
    assert.throws(() => splitRoad(referenced, 'ab', 1, 'mid', 'second'), /참조/);
    assert.throws(() => joinRoads(referenced, 'ab', 'bc'), /참조/);
  }
  const mixed = map(); mixed.edges[1].width_m = .3;
  assert.throws(() => joinRoads(mixed, 'ab', 'bc'), /속성/);
  const branch = map(); branch.edges.push({...branch.edges[1], id: 'branch'});
  assert.throws(() => joinRoads(branch, 'ab', 'bc'), /연결/);
  const evidence = map();
  evidence.edges[0].evidence = {source: 'operator', note: 'first'};
  evidence.edges[1].evidence = {source: 'camera', note: 'second'};
  const joined = joinRoads(evidence, 'ab', 'bc');
  assert.match(joined.edges[0].evidence.note, /first\nsecond/);
  assert.match(joined.edges[0].evidence.note, /camera/);
  evidence.edges[1].evidence.note = 'x'.repeat(1000);
  assert.throws(() => joinRoads(evidence, 'ab', 'bc'), /1000/);
});
