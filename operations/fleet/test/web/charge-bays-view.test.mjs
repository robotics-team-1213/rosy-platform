import test from 'node:test';
import assert from 'node:assert/strict';
import { chargeBayRows } from '../../../../applications/fleet/web/charge-bays-view.js';

const plan = {
  thresholds: { go_percent: 15, leave_percent: 80, rate_pct_per_min: null },
  bays: [
    { bay: 'C1', x: -0.414, y: 0.47, state: 'charging', robot_id: 'rosy_40' },
    { bay: 'C2', x: -0.19, y: 0.47, state: 'planned', robot_id: 'rosy_60' },
    { bay: 'C3', x: 0.032, y: 0.47, state: 'free', robot_id: null },
  ],
  actions: [
    { robot_id: 'rosy_60', action: 'go', bay: 'C2', reason: 'low_battery' },
    { robot_id: 'rosy_40', action: 'stay', bay: 'C1', arrived_percent: 12.4, reason: 'charge_rate_not_measured' },
  ],
  dispatch: false,
};

test('bays and actions read as plain Korean rows, and the plan is marked view-only', () => {
  const rows = chargeBayRows(plan);
  assert.deepEqual(rows.bays.map((b) => [b.id, b.text, b.status]), [
    ['C1', '충전 중 · rosy_40', 'active'], ['C2', '배정됨 · rosy_60', 'warn'], ['C3', '비어 있음', 'neutral']]);
  assert.deepEqual(rows.actions.map((a) => a.text), [
    '충전 칸으로 · C2 · 배터리 낮음', '칸에 머무름 · 도착 12% · 충전 속도 미측정']);
  assert.match(rows.summary, /15% 이하면 충전 · 80%면 나감 · 충전 속도 미측정 · 보기 전용/);
});

test('an estimate wins over the arrival percent, and unknown codes are shown as given', () => {
  const rows = chargeBayRows({ bays: [{ bay: 'C9', state: 'new_state' }],
    actions: [{ robot_id: 'a', action: 'leave', arrived_percent: 14, estimated_percent: 80, reason: 'charged' },
      { robot_id: 'b', action: 'later', reason: 'why' }] });
  assert.equal(rows.bays[0].text, '알 수 없음');
  assert.deepEqual(rows.actions.map((a) => a.text), ['충전 끝 · 나가도 됨 · 추정 80% · 목표 충전 도달', 'later · why']);
});

test('a bay whose robot lost its pose reads as unknown, never as empty', () => {
  const rows = chargeBayRows({ bays: [{ bay: 'C1', state: 'unknown', robot_id: 'rosy_45' }],
    actions: [{ robot_id: 'rosy_45', action: 'stay', bay: 'C1', reason: 'pose_unknown' }] });
  assert.equal(rows.bays[0].text, '위치 확인 불가 · 사용 중으로 봄 · rosy_45');
  assert.equal(rows.bays[0].status, 'warn');
  assert.equal(rows.actions[0].text, '칸에 머무름 · 로봇 위치를 확인할 수 없음 · 직접 확인 필요');
});
