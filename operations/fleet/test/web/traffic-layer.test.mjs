import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  loopCapacityText, repeatTripBody, routePoint, tripErrorText, tripStartReason, trafficAttention, trafficCardLine, trafficClock, trafficDrawing, unitParts,
} from '../../fleet/server/web/shared/site-map-model.js';

// A square loop: east (0,0)->(2,0) cut in 3 blocks, ring (2,0)->(2,1) one zone, west (2,1)->(0,1)->(0,0).
const ACTIVE = {version: 7, map: {edges: [
  {id: 'east', polyline: [[0, 0], [2, 0]]},
  {id: 'ring', polyline: [[2, 0], [2, 1]]},
  {id: 'west', polyline: [[2, 1], [0, 1], [0, 0]]},
]}};
const TRAFFIC = {
  map_version: 7,
  block_length_m: {east: 2 / 3, ring: 1, west: 1.5},
  units: [
    {id: 'east#0', capacity: 1, zone: false, two_way: false, state: 'FREE', holders: [], waiting: []},
    {id: 'east#1', capacity: 1, zone: false, two_way: false, state: 'OCCUPIED', holders: ['rosy_01'], waiting: []},
    {id: 'east#2', capacity: 1, zone: false, two_way: false, state: 'GRANTED', holders: ['rosy_01'], waiting: []},
    {id: 'ring_zone', capacity: 1, zone: true, two_way: false, state: 'OCCUPIED', holders: ['rosy_03'], waiting: ['rosy_02']},
    {id: 'west#0', capacity: 1, zone: false, two_way: false, state: 'UNKNOWN', holders: ['rosy_04'], waiting: []},
    {id: 'west#1', capacity: 1, zone: false, two_way: false, state: 'FREE', holders: [], waiting: []},
  ],
  robots: [
    {robot_id: 'rosy_01', authority_end_m: 1.9, waiting_for: [], lap: 3, trip_state: 'running'},
    {robot_id: 'rosy_02', authority_end_m: 2.0, waiting_for: ['rosy_03'], lap: 1, trip_state: 'running'},
    {robot_id: 'rosy_05', authority_end_m: null, waiting_for: ['rosy_01'], lap: null, trip_state: 'running'},
  ],
  loop_capacity: [{edges: ['east', 'ring', 'west'], capacity: 3, robots: ['rosy_01', 'rosy_02']}],
  wait_cycle: null,
};
const TRIPS = [{robot_id: 'rosy_01', plan: {segments: [{edge_id: 'east', forward: true, s_from: 0.2, s_to: 2},
  {edge_id: 'ring', forward: true, s_from: 0, s_to: 1}]}}];

test('block units map to their stretch of the edge; a zone takes the edges without units', () => {
  assert.deepEqual(unitParts('east#1', TRAFFIC), [['east', 2 / 3, 4 / 3]]);
  assert.deepEqual(unitParts('lane:ab', TRAFFIC), [['ab', 0, Infinity]]);
  assert.deepEqual(unitParts('ring_zone', TRAFFIC), [['ring', 0, Infinity]]);
  // two zones: /traffic does not say which edges belong to which, so nothing is drawn
  const two = {...TRAFFIC, units: [...TRAFFIC.units, {id: 'other', zone: true, capacity: 1}]};
  assert.deepEqual(unitParts('ring_zone', two), []);
});

test('the drawing skips FREE blocks, keeps the closed state vocabulary and labels the zone', () => {
  const drawing = trafficDrawing(TRAFFIC, ACTIVE, TRIPS);
  assert.deepEqual(drawing.bands.map(b => [b.unit, b.state, b.robot]), [
    ['east#1', 'OCCUPIED', 'rosy_01'], ['east#2', 'GRANTED', 'rosy_01'],
    ['ring_zone', 'OCCUPIED', 'rosy_03'], ['west#0', 'UNKNOWN', 'rosy_04']]);
  const [a, b] = [drawing.bands[0].points[0], drawing.bands[0].points.at(-1)];
  assert.ok(Math.abs(a[0] - (2 / 3 + 0.03)) < 1e-9 && Math.abs(b[0] - (4 / 3 - 0.03)) < 1e-9);  // gap between blocks
  assert.deepEqual(drawing.zones.map(z => [z.unit, z.label]), [['ring_zone', '점유 1/1 · 대기 1']]);
  // the authority end is in route metres along the trip plan: 1.9 m is on east at x = 1.9
  assert.equal(drawing.ticks.length, 1);
  assert.equal(drawing.ticks[0].robot, 'rosy_01');
  assert.ok(Math.abs(drawing.ticks[0].x - 1.9) < 1e-9 && drawing.ticks[0].y === 0);
  assert.equal(trafficDrawing(TRAFFIC, {...ACTIVE, version: 8}, TRIPS), null);  // another map version
});

test('route metres continue on the next arc after the full length of the previous one', () => {
  const edges = new Map(ACTIVE.map.edges.map(e => [e.id, e]));
  const at = routePoint(TRIPS[0].plan.segments, edges, 2.5);
  assert.ok(Math.abs(at.x - 2) < 1e-9 && Math.abs(at.y - 0.5) < 1e-9);
  assert.equal(routePoint(TRIPS[0].plan.segments, edges, 9), null);
});

test('one card line per trip robot', () => {
  assert.equal(trafficCardLine(TRAFFIC, 'rosy_01'), '반복 운행 3바퀴째');
  assert.equal(trafficCardLine(TRAFFIC, 'rosy_02'), '반복 운행 1바퀴째 · 교차로 대기 · rosy_03 통과 중');
  assert.equal(trafficCardLine(TRAFFIC, 'rosy_05'), '앞 블록 대기 · rosy_01');
  assert.equal(trafficCardLine(TRAFFIC, 'rosy_09'), '');
  const advice = (row) => ({ robots: [{ robot_id: 'r', trip_state: 'running', advice: row }], units: [] });
  assert.equal(trafficCardLine(advice({ signal: true, sent_seq: 4, accepted: true }), 'r'), '운행 중 · 신호 참고 전송 · seq 4');
  assert.equal(trafficCardLine(advice({ signal: true, sent_seq: 0, accepted: false, reason: 'stale' }), 'r'), '운행 중 · 신호 참고 전송 · seq 0 · stale');
  assert.equal(trafficCardLine(advice({ signal: false, sent_seq: 5, accepted: true }), 'r'), '운행 중');  // cleared: no line
  const unknown = {...TRAFFIC, robots: [{robot_id: 'rosy_04', waiting_for: [], lap: null, trip_state: 'running'}]};
  assert.equal(trafficCardLine(unknown, 'rosy_04'), '위치 불명 · 블록 유지');
});

test('queue rows: wait cycle and 30 s UNKNOWN are critical, a long merge wait and an over-full loop warn', () => {
  let clock = trafficClock(null, TRAFFIC, 1000);
  assert.deepEqual(clock, {merge: {rosy_02: 1000}});
  clock = trafficClock(clock, TRAFFIC, 5000);  // the first sighting time stays
  assert.equal(clock.merge.rosy_02, 1000);
  assert.deepEqual(trafficAttention(TRAFFIC, 'rosy_02', clock, 15000), []);  // a block wait is normal
  assert.deepEqual(trafficAttention(TRAFFIC, 'rosy_02', clock, 22000),
    [{severity: 'warn', text: ': 합류 대기 21초 — 구역 ring_zone 입구'}]);
  assert.deepEqual(trafficAttention(TRAFFIC, 'rosy_04', clock, 32000), []);  // D-517 M4: Fleet's resolver says when
  const lost = {...TRAFFIC, resolver: [{robot_id: 'rosy_04', trigger: 'unknown', decision: 'human', since: 1}]};
  assert.deepEqual(trafficAttention(lost, 'rosy_04', clock, 0),
    [{severity: 'crit', text: ': 위치 불명 30초 넘음 — 블록을 풀지 않습니다 · 로봇 위치를 확인하세요'}]);
  const cycle = {...TRAFFIC, wait_cycle: ['rosy_01', 'rosy_05']};
  assert.deepEqual(trafficAttention(cycle, 'rosy_05', {}, 0),
    [{severity: 'crit', text: ': 교착 — rosy_01 → rosy_05 → rosy_01 서로 기다림 · 운영자 판단 필요'}]);
  const resolved = {...cycle, resolver: [
    {robot_id: 'rosy_01', trigger: 'wait_cycle', decision: 'wait', cycle: ['rosy_01', 'rosy_05']},
    {robot_id: 'rosy_05', trigger: 'wait_cycle', decision: 'replan', cycle: ['rosy_01', 'rosy_05'], blocked_edges: ['ring_n']}]};
  assert.equal(trafficAttention(resolved, 'rosy_05', {}, 0)[0].text,
    ': 교착 — rosy_01 → rosy_05 → rosy_01 서로 기다림 · 해결기: 다른 길 계획 · 다음 장소에서 운영자 확인');
  assert.equal(trafficAttention(resolved, 'rosy_01', {}, 0)[0].text,
    ': 교착 — rosy_01 → rosy_05 → rosy_01 서로 기다림 · 해결기: rosy_05 다른 길 대기');
  const card = {...resolved, robots: [{robot_id: 'rosy_05', waiting_for: [], lap: null, trip_state: 'running'}]};
  assert.equal(trafficCardLine(card, 'rosy_05'), '교착 · 다른 길 계획');
  const full = {...TRAFFIC, loop_capacity: [{edges: [], capacity: 1, robots: ['rosy_01', 'rosy_02']}]};
  assert.deepEqual(trafficAttention(full, 'rosy_01', {}, 0), [{severity: 'warn', text: ': 고리 수용 초과 — 고리 2/1대'}]);
  assert.deepEqual(trafficAttention(null, 'rosy_01', {}, 0), []);
});

test('loop capacity reads 고리 n/m대', () => {
  assert.equal(loopCapacityText(TRAFFIC), '고리 2/3대');
  assert.equal(loopCapacityText({loop_capacity: []}), '');
});

test('a repeat start pairs the robot with its start place and laps over every start place', () => {
  const map = {places: [{id: 'n', kind: 'start'}, {id: 'j', kind: 'junction'}, {id: 's', kind: 'start'}, {id: 'w', kind: 'start'}]};
  assert.deepEqual(repeatTripBody(map, 's'), {to: 's', via: ['w', 'n'], repeat: true});
  assert.throws(() => repeatTripBody(map, 'j'), /출발 자리를 고르세요/);
  assert.throws(() => repeatTripBody({places: [{id: 'n', kind: 'start'}]}, 'n'), /두 곳 이상/);
});

test('TRIP_BUSY is per robot and TRIP_LOOP_FULL names robots and capacity', () => {
  assert.equal(tripErrorText('TRIP_BUSY', {trip_id: 'a'}), '이 로봇은 이미 운행 중입니다');
  assert.equal(tripErrorText('TRIP_LOOP_FULL', {robots: 4, capacity: 3, held_per_robot: 3}),
    '고리 수용 한도를 넘어 출발할 수 없습니다 · 고리 4/3대');
  assert.equal(tripStartReason({role: 'operator', plan: {}, running: {trip_id: 'a'}}), '이 로봇은 이미 운행 중입니다');
});
