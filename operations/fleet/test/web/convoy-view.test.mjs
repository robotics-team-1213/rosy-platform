// D-517 9 M3 / 10: the convoy line, the card line and the 운행 panel's leader choice.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  convoyLeaders, repeatTripBody, trafficCardLine, trafficDrawing, tripErrorText,
} from '../../fleet/server/web/shared/site-map-model.js';

const ACTIVE = {version: 7, map: {edges: [{id: 'east', polyline: [[0, 0], [4, 0]]}],
  places: [{id: 'start_n', kind: 'start'}, {id: 'start_s', kind: 'start'}, {id: 'X', kind: 'junction'}]}};
const plan = {segments: [{edge_id: 'east', forward: true, s_from: 0, s_to: 4}]};
const TRIPS = ['rosy_01', 'rosy_02', 'rosy_03'].map(robot_id => ({robot_id, plan}));
const TRAFFIC = {map_version: 7, block_length_m: {east: 1}, units: [], loop_capacity: [], wait_cycle: null, robots: [
  {robot_id: 'rosy_01', front_d_m: 3.0, authority_end_m: 3.5, waiting_for: [], lap: 2, trip_state: 'running', convoy: null},
  {robot_id: 'rosy_02', front_d_m: 2.3, authority_end_m: 2.5, waiting_for: ['rosy_01'], lap: 1, trip_state: 'running',
    convoy: {leader: 'rosy_01', follows: 'rosy_01', gap_m: 0.582}},
  {robot_id: 'rosy_03', front_d_m: 1.0, authority_end_m: null, waiting_for: ['rosy_02'], lap: 1, trip_state: 'running',
    convoy: {leader: 'rosy_01', follows: null, gap_m: null}},
]};

test('one thin line from the robot ahead (else the leader) to each follower', () => {
  const {convoys} = trafficDrawing(TRAFFIC, ACTIVE, TRIPS);
  assert.deepEqual(convoys.map(c => [c.robot, c.leader, c.from.x, c.to.x]),
    [['rosy_02', 'rosy_01', 3.0, 2.3], ['rosy_03', 'rosy_01', 3.0, 1.0]]);
  assert.deepEqual(trafficDrawing(TRAFFIC, ACTIVE, TRIPS.slice(0, 1)).convoys, []);  // no plan: no point
});

test('a follower card says whom it follows and how far behind', () => {
  assert.equal(trafficCardLine(TRAFFIC, 'rosy_02'), '반복 운행 1바퀴째 · 대열 · rosy_01 뒤 0.6 m');
  assert.equal(trafficCardLine(TRAFFIC, 'rosy_03'), '반복 운행 1바퀴째 · 대열 · rosy_01 위치 모름 · 고정 블록 · 앞 블록 대기 · rosy_02');
  assert.equal(trafficCardLine(TRAFFIC, 'rosy_01'), '반복 운행 2바퀴째 · 대열 리더 · rosy_02, rosy_03 따라옴');
});

test('the leader choice lists open repeat trips that follow nobody, and the body carries it', () => {
  const open = [{robot_id: 'rosy_01', repeat: true, convoy: null}, {robot_id: 'rosy_02', repeat: true,
    convoy: {leader: 'rosy_01'}}, {robot_id: 'rosy_04', repeat: false}];
  assert.deepEqual(convoyLeaders(open, 'rosy_05'), ['rosy_01']);
  assert.deepEqual(convoyLeaders(open, 'rosy_01'), []);
  assert.deepEqual(repeatTripBody(ACTIVE.map, 'start_s', 'rosy_01'),
    {to: 'start_s', via: ['start_n'], repeat: true, convoy: {leader: 'rosy_01'}});
  assert.equal('convoy' in repeatTripBody(ACTIVE.map, 'start_s', ''), false);
});

test('convoy refusals read as operator text', () => {
  assert.match(tripErrorText('TRIP_CONVOY_LEADER_NOT_RUNNING'), /리더를 먼저 출발/);
  assert.equal(tripErrorText('TRIP_CONVOY_LOOP_FULL', {robots: 4, capacity: 3}),
    '대열을 더하면 고리 수용 한도를 넘습니다 · 고리 4/3대');
});
