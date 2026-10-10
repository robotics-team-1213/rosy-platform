// D-540 (d): the one trip path the site map and the 관제 robot card share (plan, start, texts).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  oneLapBody, oneLapReason, planSummaryText, planTrip, repeatTripReason, startCheckText, startTrip,
  tripErrorText, tripRefusalText,
  tripStartReason,
} from '../../fleet/server/web/shared/site-map-model.js';

const ACTIVE = {version: 4, map: {places: [{id: 'A', kind: 'start'}, {id: 'B', kind: 'start'}, {id: 'X', kind: 'junction'}]}};

test('one lap uses a finite trip via a different stop and returns to its start', () => {
  const map = {places: [{id: 'W_mid', kind: 'stop'}, {id: 'E_mid', kind: 'stop'}]};
  assert.deepEqual(oneLapBody(map, 'W_mid', 'E_mid'),
    {to: 'W_mid', via: ['E_mid'], repeat: false, start_at: 'W_mid'});
  assert.equal(oneLapReason({active: {map}, running: null, start: 'W_mid', via: 'E_mid'}), '');
  assert.match(oneLapReason({active: {map}, running: null, start: 'W_mid', via: 'W_mid'}), /서로 다른/);
  assert.throws(() => oneLapBody(map, 'W_mid', 'W_mid'));
});

test('plan and start call the D-494 routes with the escaped id', async () => {
  const calls = [];
  const request = async (path, init) => { calls.push([path, init.method, init.body]); return {}; };
  await planTrip(request, 'rosy 01', {to: 'B'});
  await startTrip(request, 'p/1');
  assert.deepEqual(calls, [
    ['/api/fleet/robots/rosy%2001/trip', 'POST', '{"to":"B"}'],
    ['/api/fleet/trips/p%2F1/start', 'POST', undefined],
  ]);
});

test('plan summary and refusal text', () => {
  assert.equal(planSummaryText({segments: [1, 2, 3], length_m: 2.1, eta_s: 13.6, map_version: 4}),
    '3개 차로 · 2.10 m · 약 14 s · 지도 v4');
  assert.match(tripRefusalText({code: 'TRIP_CONVOY_SELF', detail: {}}), /./);
  assert.equal(tripRefusalText({status: 403, message: 'x'}), '운영자 권한이 필요합니다 · 계정을 확인하세요');
});

test('repeat reason: map, running trip, two start places, a chosen start', () => {
  assert.equal(repeatTripReason({active: null, running: null, start: 'A'}), '활성 지도가 없습니다');
  assert.equal(repeatTripReason({active: ACTIVE, running: {}, start: 'A'}), '이 로봇은 이미 운행 중입니다');
  const one = {version: 4, map: {places: [{id: 'A', kind: 'start'}]}};
  assert.equal(repeatTripReason({active: one, running: null, start: 'A'}), '반복 운행에는 출발 자리가 두 곳 이상 필요합니다');
  assert.equal(repeatTripReason({active: ACTIVE, running: null, start: ''}), '출발 자리를 고르세요');
  assert.equal(repeatTripReason({active: ACTIVE, running: null, start: 'A'}), '');
});

test('D-601 start check: 출발 가능, 방향 반대, 차선 밖, with numbers in refusals and on the start button', () => {
  assert.equal(startCheckText({code: null}), '출발 가능');
  assert.equal(startCheckText({code: 'TRIP_START_HEADING_MISMATCH', heading_err_deg: -178.2}), '방향 반대(178°)');
  assert.equal(startCheckText({code: 'TRIP_START_HEADING_MISMATCH', heading_err_deg: 35}), '방향 어긋남(35°)');
  assert.equal(startCheckText({code: 'TRIP_START_OFF_LANE', off_lane_m: 0.05}), '차선 밖 5 cm');
  const plan = {segments: [1], length_m: 1, eta_s: 3, map_version: 4, start_check: {code: null}};
  assert.equal(planSummaryText(plan), '1개 차로 · 1.00 m · 약 3 s · 지도 v4 · 출발 가능');
  assert.equal(tripStartReason({role: 'operator', plan, active: {version: 4}, running: null}), '');
  const away = {...plan, start_check: {code: 'TRIP_START_HEADING_MISMATCH', heading_err_deg: 178}};
  assert.match(tripStartReason({role: 'operator', plan: away, active: {version: 4}, running: null}), /^방향 반대\(178°\) · /);
  assert.match(tripErrorText('TRIP_HEADING_CONFLICT', {heading_err_deg: 178}), /방향 반대\(178°\)$/);
  assert.match(tripErrorText('TRIP_START_OFF_LANE', {off_lane_m: 0.12}), /차선 밖 12 cm$/);
  assert.match(tripErrorText('TRIP_LANE_CAMERA_UNAVAILABLE'), /카메라/);
  assert.doesNotMatch(tripErrorText('TRIP_LINE_FOLLOW_NOT_ACTIVE'), /카메라 또는 IR/);
});
