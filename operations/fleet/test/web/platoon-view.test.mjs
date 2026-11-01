import test from 'node:test';
import assert from 'node:assert/strict';
import { platoonRows } from '../../../../applications/fleet/web/platoon-view.js';

test('each robot reads its leader, gap and state, and the loop is marked view-only', () => {
  const rows = platoonRows({
    loop: { edges: ['a', 'b', 'c', 'd'], perimeter_m: 4.424 }, target_gap_m: 0.6,
    speed: { stripes: [{ place: 'S5', s_m: 0 }, { place: 'S3', s_m: 0.611 }], curve_caps_measured: false },
    robots: [
      { robot_id: 'rosy_40', s_m: 1.2, off_m: 0.01, state: 'ok', leader: 'rosy_60', gap_m: 0.71 },
      { robot_id: 'rosy_60', s_m: 1.9, off_m: 0.02, state: 'too_close', leader: 'rosy_40', gap_m: 0.2 },
      { robot_id: 'rosy_42', s_m: null, off_m: 0.4, state: 'off_loop' },
    ],
  });
  assert.deepEqual(rows.robots.map((r) => [r.robot, r.text, r.status]), [
    ['rosy_40', '간격 정상 · 앞차 rosy_60 · 0.71 m', 'active'],
    ['rosy_60', '너무 가까움 · 앞차 rosy_40 · 0.20 m', 'crit'],
    ['rosy_42', '고리 밖 · 차선에서 0.40 m', 'neutral']]);
  assert.equal(rows.summary, '고리 4구간 · 4.42 m · 목표 간격 0.60 m · 감속 줄무늬 S5·S3 · 곡선 상한 미측정 · 보기 전용');
});

test('a lone robot has no leader and an unknown state is shown as unknown', () => {
  const rows = platoonRows({ robots: [{ robot_id: 'a', state: 'alone' }, { robot_id: 'b', state: 'new' }] });
  assert.deepEqual(rows.robots.map((r) => r.text), ['앞차 없음', '알 수 없음']);
  assert.equal(rows.summary, '');
});
