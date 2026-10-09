// D-540 (d): the one trip path the site map and the 관제 robot card share (plan, start, cancel, texts).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  cancelTrip, planSummaryText, planTrip, repeatTripReason, startTrip, tripRefusalText,
} from '../../fleet/server/web/shared/site-map-model.js';

const ACTIVE = {version: 4, map: {places: [{id: 'A', kind: 'start'}, {id: 'B', kind: 'start'}, {id: 'X', kind: 'junction'}]}};

test('plan, start and cancel call the D-494 routes with the escaped id', async () => {
  const calls = [];
  const request = async (path, init) => { calls.push([path, init.method, init.body]); return {}; };
  await planTrip(request, 'rosy 01', {to: 'B'});
  await startTrip(request, 'p/1');
  await cancelTrip(request, 't1');
  assert.deepEqual(calls, [
    ['/api/fleet/robots/rosy%2001/trip', 'POST', '{"to":"B"}'],
    ['/api/fleet/trips/p%2F1/start', 'POST', undefined],
    ['/api/fleet/trips/t1/cancel', 'POST', undefined],
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
