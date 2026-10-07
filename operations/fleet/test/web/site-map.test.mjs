import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  arrowMarks, editEdge, editPlace, fitView, planPolylines, segmentPoints, tripErrorText,
} from '../../fleet/server/web/site-map-model.js';

const MAP = {
  places: [{id: 'A', name: 'A', x: 0, y: 0, kind: 'junction'}, {id: 'B', name: 'B', x: 2, y: 0, kind: 'park'}],
  edges: [{id: 'ab', from: 'A', to: 'B', polyline: [[0, 0], [1, 0], [2, 0]], direction: 'one_way',
           width_m: 0.2, speed_cap_mps: 0.2, drive_mode: 'lane'}],
};

test('fitView flips y and round-trips map metres', () => {
  const view = fitView(MAP, 200, 100, 10);
  const [px, py] = view.toPx(2, 0);
  assert.deepEqual(view.toMap(px, py).map(v => Math.round(v * 1e6) / 1e6), [2, 0]);
  assert.ok(view.toPx(0, 1)[1] < view.toPx(0, 0)[1]);
});

test('one-way edges get one arrow, two-way edges two opposite ones', () => {
  assert.equal(arrowMarks(MAP.edges[0]).length, 1);
  assert.equal(arrowMarks(MAP.edges[0])[0].angle, 0);
  const both = arrowMarks({...MAP.edges[0], direction: 'two_way'});
  assert.equal(both.length, 2);
  assert.equal(Math.abs(both[1].angle), Math.PI);
});

test('segments slice the edge in driving order', () => {
  assert.deepEqual(segmentPoints(MAP.edges[0], true, 0.5, 1.5), [[0.5, 0], [1, 0], [1.5, 0]]);
  assert.deepEqual(segmentPoints(MAP.edges[0], false, 0, 0.5), [[2, 0], [1.5, 0]]);
  const plan = {segments: [{edge_id: 'ab', forward: true, s_from: 0, s_to: 2}, {edge_id: 'gone', forward: true}]};
  assert.equal(planPolylines(MAP, plan).length, 1);
});

test('edits copy the map and refuse bad values', () => {
  const named = editPlace(MAP, 'B', {name: ' 주차-1 ', kind: 'charge'});
  assert.equal(named.places[1].name, '주차-1');
  assert.equal(MAP.places[1].name, 'B');
  const edge = editEdge(MAP, 'ab', {direction: 'two_way', drive_mode: 'free', speed_cap_mps: '0.3'});
  assert.deepEqual([edge.edges[0].direction, edge.edges[0].drive_mode, edge.edges[0].speed_cap_mps],
    ['two_way', 'free', 0.3]);
  assert.throws(() => editEdge(MAP, 'ab', {speed_cap_mps: 0}));
  assert.throws(() => editPlace(MAP, 'A', {kind: 'garage'}));
});

test('trip errors read in Korean with the leg and the unblock hint', () => {
  assert.match(tripErrorText('TRIP_NO_ROUTE', {segment: 1, unblock_would_help: true}), /2번째 구간.*막은 차로/);
  assert.match(tripErrorText('NEW_CODE'), /NEW_CODE/);
});

test('actions read the address names and stale plans are refused', async () => {
  const {actionRows, planIsCurrent, siteMapErrorText} = await import('../../fleet/server/web/site-map-model.js');
  const map = {places: [{id: 'B', name: '충전'}]};
  const plan = {map_version: 2, actions: [{place_id: 'B', action: 'left'}, {place_id: null, action: 'stop'}]};
  assert.deepEqual(actionRows(plan, map), ['충전 · 좌회전', '찍은 좌표 · 정지']);
  assert.equal(planIsCurrent(plan, {version: 2}), true);
  assert.equal(planIsCurrent(plan, {version: 3}), false);
  assert.match(siteMapErrorText({code: 'SITE_MAP_ROUTE_ACTIVE'}), /진행 중/);
  assert.match(siteMapErrorText({status: 401}), /토큰을 확인하고 다시 접속/);
  assert.match(siteMapErrorText({status: 503, code: 'SITE_MAP_UNAVAILABLE'}), /잠시 뒤 다시 접속/);
  assert.match(siteMapErrorText(new TypeError('Failed to fetch')), /연결이 끊겼습니다/);
});

test('invalid draft errors list the fields', async () => {
  const {siteMapErrorText} = await import('../../fleet/server/web/site-map-model.js');
  const text = siteMapErrorText({code: 'SITE_MAP_INVALID',
    detail: {errors: [{loc: ['map', 'edges', '0', 'width_m'], msg: 'Input should be greater than 0'}]}});
  assert.match(text, /맞지 않는 값.*map\.edges\.0\.width_m: Input should be greater than 0/);
});

test('D-491 trip panel text and button reasons', async () => {
  const {tripStatusText, tripStartReason, tripCancelReason} = await import('../../fleet/server/web/site-map-model.js');
  assert.equal(tripStatusText(null, MAP), '진행 중인 운행 없음');
  const trip = {state: 'running', robot_id: 'r1', current_edge: 'ab', next_place: 'B', next_action: 'stop',
    pose: {state: 'LOCALIZED', source: 'bridged'}, hold: null, reason: null};
  assert.equal(tripStatusText(trip, MAP), '운행 중 · r1 · 차로 ab · 다음 B 정지 · 자세 LOCALIZED · odom 다리');
  assert.match(tripStatusText({...trip, state: 'stopped', reason: 'restart'}, MAP), /자동으로 다시 출발하지 않습니다/);
  const plan = {map_version: 1, expires_at: 100};
  const active = {version: 1};
  assert.equal(tripStartReason({role: 'operator', plan, active, running: null, now: 99}), '');
  assert.match(tripStartReason({role: 'operator', plan, active, running: null, now: 101}), /30초/);
  assert.match(tripStartReason({role: 'operator', plan, active, running: trip, now: 99}), /진행 중/);
  assert.match(tripStartReason({role: 'operator', plan, active: {version: 2}, running: null, now: 99}), /지도가 바뀌었습니다/);
  assert.match(tripStartReason({role: 'viewer', plan, active, running: null, now: 99}), /운영자/);
  assert.match(tripStartReason({role: 'operator', plan: null, active, running: null}), /경로를 계산/);
  assert.equal(tripCancelReason({role: 'operator', running: trip}), '');
  assert.match(tripCancelReason({role: 'operator', running: null}), /없습니다/);
});
