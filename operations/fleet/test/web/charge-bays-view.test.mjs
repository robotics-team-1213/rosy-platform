import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = new URL('../../../../applications/fleet/web/charge-bays-view.js', import.meta.url);
const gate = new URL('../../../../applications/fleet/web/shared/poll-gate.js', import.meta.url);
const code = (await readFile(source, 'utf8')).replace('/console/assets/poll-gate.js', gate.href);
const { chargeBayRows } = await import(`data:text/javascript,${encodeURIComponent(code)}`);

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
  assert.equal(rows.bays[0].text, '확인 불가 · 비어 있다고 볼 수 없음 · rosy_45');
  assert.equal(rows.bays[0].status, 'warn');
  assert.equal(rows.actions[0].text, '칸에 머무름 · 로봇 위치를 확인할 수 없음 · 칸을 직접 확인');
});

test('an empty bay that cannot be called free says so', () => {
  const rows = chargeBayRows({ bays: [{ bay: 'C2', state: 'unknown', robot_id: null }],
    actions: [{ robot_id: 'low', action: 'wait', reason: 'bay_unknown' }] });
  assert.equal(rows.bays[0].text, '확인 불가 · 비어 있다고 볼 수 없음');
  assert.match(rows.actions[0].text, /칸이 비었는지 확인 불가/);
});

test('centerline docking evaluation and misaligned reseat render in Korean', () => {
  const rows = chargeBayRows({
    bays: [{ bay: 'C1', state: 'arrived', robot_id: 'rosy_60' }],
    actions: [{
      robot_id: 'rosy_60', action: 'reseat', bay: 'C1', arrived_percent: 14,
      reason: 'misaligned_on_bay',
      docking: { verdict: 'RETRY_FROM_P', offset_m: 0.034, yaw_err_deg: 11.2 },
    }],
  });
  assert.match(rows.actions[0].text, /중심선 정렬 불량 · 전진 후 재접안 필요/);
  assert.match(rows.actions[0].text, /이탈 · 재정렬 필요 34mm 11\.2°/);
});

test('OMX cell gates and cell-blocked actions render in Korean', () => {
  const rows = chargeBayRows({
    actions: [{ robot_id: 'rosy_60', action: 'wait', reason: 'locked_by_cell',
      blocked_by_cell: true, cell_id: 'cell_s' }],
    omx_cells: {
      cell_s: { station: { station_place: 'S3' }, gate: {
        phase: 'ARM_IN_BED_ZONE', robot_id: 'rosy_60', amr_motion_inhibited: true,
      } },
      cell_ab: { station: { station_place: 'S5' }, gate: { phase: 'IDLE' } },
    },
  });
  assert.deepEqual(rows.cells, [
    { id: 'cell_s', text: 'OMX 작업 중 · AMR 잠금 · S3 · rosy_60', status: 'active' },
    { id: 'cell_ab', text: '대기 중 · S5', status: 'neutral' },
  ]);
  assert.match(rows.actions[0].text, /OMX 셀 작업 중 구동 잠금/);
  assert.match(rows.actions[0].text, /OMX 셀\(cell_s\) 잠금/);
});

test('pipeline cards carry cell telemetry and one-click robot actions without changing legacy rows', () => {
  const rows = chargeBayRows({
    ...plan,
    omx_cells: {
      cell_s: {gate: {phase: 'ARM_IN_BED_ZONE'}},
      cell_ab: {gate: {phase: 'IDLE'}},
    },
    omx_cell_tasks: [
      {task_id: 'old', cell_id: 'cell_s', status: 'COMPLETED', created_at: 1},
      {task_id: 'new', cell_id: 'cell_s', status: 'RUNNING', created_at: 2, arm_id: 'arm_s'},
    ],
  });
  assert.equal(rows.bays.length, 3);
  assert.equal(rows.actions.length, 2);
  assert.equal(rows.cells.length, 2);
  assert.match(rows.summary, /15%/);
  assert.equal(rows.cards[0].cameraUrl, '/api/fleet/pipeline/cell-camera/cell_s');
  assert.equal(rows.cards[0].title, 'cell_s · S3 하역 셔틀 (arm_s)');
  assert.equal(rows.cards[0].phase, 'ARM_IN_BED_ZONE');
  assert.equal(rows.cards[0].task.task_id, 'new');
  assert.deepEqual(rows.cards[0].buttons.map(b => b.preset),
    ['s3_shuttle', 's3_recover_belt_far', 's3_recover_floor_front']);
  assert.equal(rows.cards[1].title, 'cell_ab · S5 팔레트 적재 (arm_a·arm_b)');
  assert.deepEqual(rows.cards[1].buttons.map(b => b.preset),
    ['s5_tier1_arm_a', 's5_tier2_arm_b', 's5_tier3_arm_a', 'full_s3_to_s5_pipeline']);
  assert.equal(rows.cards[2].cameraUrl, '/api/fleet/pipeline/cell-camera/pinky');
  assert.equal(rows.cards[2].robot_id, 'rosy_60');
  assert.deepEqual(rows.cards[2].buttons.map(b => b.pinkyAction),
    ['dock_and_unload_s3', 'dock_s3', 'charge_c1', 'depart_s1']);
  assert.equal(rows.cards[0].quickControls[0].decisionSubject, 'cell_s');
  assert.equal(rows.cards[0].quickControls[1].humanSafetyCell, 'cell_s');
  assert.equal(rows.cards[0].quickControls[2].zoneId, 'EXP_S3_BELT');
  assert.equal(rows.cards[2].quickControls[0].decisionSubject, 'rosy_60');
  assert.equal(rows.cards[2].quickControls[1].zoneId, 'STG_C2');
  assert.deepEqual(chargeBayRows({}).cards.filter(c => c.robot_id).map(c => c.robot_id),
    ['rosy_42', 'rosy_45', 'rosy_46']);
});
