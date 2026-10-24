import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  startCheckText, tripErrorText, tripEndText, tripWaitText, tripStatusText,
} from '../../../../applications/fleet/web/shared/trip-display.js';

test('trip display loads without a DOM and preserves refusal detail and unknown codes', () => {
  assert.equal(tripErrorText('FUTURE_REFUSAL'), '경로 계획 거절 (FUTURE_REFUSAL)');
  assert.equal(tripErrorText('TRIP_UNKNOWN_EDGE', {edge: 'lane-x'}), '지도에 없는 차로입니다 · lane-x');
  assert.equal(startCheckText({code: 'TRIP_START_HEADING_MISMATCH', heading_err_deg: -178.2}), '방향 반대(178°)');
  assert.match(tripErrorText('TRIP_START_OFF_LANE', {off_lane_m: 0.123}), /차선 밖 12 cm/);
});

test('wait and lease explanations keep server state and unknown reasons visible', () => {
  assert.equal(tripWaitText({wait: {waiting: true, reason: 'signal'}}), '대기 · 신호');
  assert.equal(tripWaitText({wait: {over_bound: true, reason: 'future_wait'}}), '대기 상한 넘음 · future_wait');
  assert.equal(tripWaitText(null), '');
  assert.equal(tripEndText({state: 'running', reason: 'stall'}), '');
  assert.equal(tripEndText({state: 'stopped', reason: 'lease_lost',
    detail: {lease_reason: 'future_reason', lease_by: 'operator-device'}}),
  '운행 멈춤 · future_reason(operator-device)');
});

test('trip status names places while keeping source and unknown state fallback', () => {
  assert.equal(tripStatusText(null), '진행 중인 운행 없음');
  const line = tripStatusText({state: 'future_state', robot_id: 'robot-a', next_place: 'B',
    next_action: 'future_action', pose: {state: 'LOCALIZED', source: 'bridged'}},
  {places: [{id: 'B', name: '하역 지점'}]});
  assert.match(line, /future_state · robot-a/);
  assert.match(line, /다음 하역 지점 future_action/);
  assert.match(line, /위치 확정 · odom 다리/);
});
