import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  startCheckText, tripErrorText, tripEndText, tripWaitText, tripStatusText,
} from '../../../../applications/fleet/web/shared/trip-display.js';

test('trip display loads without a DOM and preserves refusal detail and unknown codes', () => {
  assert.equal(tripErrorText('FUTURE_REFUSAL'), '경로 계획 거절 (FUTURE_REFUSAL)');
  assert.equal(tripErrorText('TRIP_JOB_NOT_FOUND'), '해당하는 이송 작업이 없습니다 · 접수 키와 권한을 확인하세요');
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
test('pre-dispatch peer wait and operator pause take precedence over the open trip state', () => {
  const trip = {robot_id:'rosy_42',state:'running',detail:{peer_wait:{
    stage:'pre_dispatch_peer_check',dispatch_attempted:false,waiting_on:['rosy_45']}}};
  assert.match(tripStatusText(trip), /^통행 대기 · 주행 명령 전송 전/);
  assert.doesNotMatch(tripStatusText(trip), /운행 중/);
  const paused = {...trip, hold:{reason:'fleet_hold',stop:{confirmed:false}}};
  assert.match(tripStatusText(paused), /^일시정지 · 기체 정지 응답 확인 중/);
  assert.doesNotMatch(tripStatusText(paused), /자동 재확인/);
  assert.doesNotMatch(tripStatusText({...trip, state:'arrived'}), /통행 대기/);
});

test("receipt and measured motion remain distinct when waiting and stopped", () => {
  const trip = {state: "running", robot_id: "rosy_42", detail: {peer_wait: {
    stage: "pre_dispatch_peer_check", dispatch_attempted: false, waiting_on: ["rosy_45"]}}};
  const show = (phase, motion) => tripStatusText({...trip, execution: {phase, motion}});
  assert.match(show("pre_dispatch_wait", "moving"), /전송 전.*실제 이동 중/);
  assert.match(show("pre_dispatch_wait", "stationary"), /전송 전.*현재 정지/);
  assert.doesNotMatch(show("pre_dispatch_wait", "unknown"), /현재 정지|실제 이동 중/);
});

test('parking reports request and device receipt separately from observed motion', () => {
  const parking = {phase: 'submitting', bay_id: 'C2'};
  const trip = {state: 'running', robot_id: 'rosy_42', detail: {parking_handoff: parking},
    execution: {phase: 'received', motion: 'unknown'}};
  assert.match(tripStatusText(trip), /C2 후진 주차 명령 전송 중/);
  parking.phase = 'docking';
  trip.execution = {phase: 'stationary', motion: 'stationary'};
  assert.match(tripStatusText(trip), /C2 후진 주차 명령 접수 · 현재 정지/);
});

test('a peer-held parking trip also shows the time-scoped independent dock diagnostics', () => {
  const trip = {state: 'running', robot_id: 'rosy_42', detail: {
    peer_wait: {stage: 'pre_dispatch_peer_check', dispatch_attempted: false, waiting_on: ['rosy_45']},
    parking_handoff: {bay_id: 'C1', phase: 'approaching', plan_prerequisites: {
      reasons: ['CHARGE_BAY_TARGET_NOT_TAUGHT', 'CHARGE_BAY_SCOPED_CANCEL_UNSUPPORTED']}}}};
  assert.match(tripWaitText(trip), /통행 대기.*명령 대상 rosy_42.*rosy_45.*계획 시 C1.*도킹 위치 미등록.*작업별 정지 미지원/);
});

test('peer_wait reason, wait_prefix, nav2_problem, and approved_slam source render clearly', () => {
  const yieldingTrip = {state: 'running', robot_id: 'rosy_45', detail: {
    peer_wait: {stage: 'pre_dispatch_peer_check', dispatch_attempted: false, reason: 'YIELDING', waiting_on: ['rosy_46']},
    wait_prefix: {place: 'S2', state: 'at_wait_place'}}};
  const waitText = tripWaitText(yieldingTrip);
  assert.match(waitText, /경로 앞 정차 기체 대기/);
  assert.match(waitText, /S2 대기 지점 정차 중/);

  const retryTrip = {state: 'running', robot_id: 'rosy_45', detail: {
    nav2_problem: {state: 'retry_wait', attempt: 1, max_retries: 2}}};
  assert.match(tripWaitText(retryTrip), /Nav2 경로 재시도 대기 \(1\/2\)/);

  const heldTrip = {state: 'running', robot_id: 'rosy_45',
    hold: {reason: 'nav2_problem', code: 'NAV2_FAILED'},
    pose: {state: 'LOCALIZED', source: 'approved_slam'},
    detail: {nav2_problem: {state: 'held', code: 'NAV2_FAILED'}}};
  const statusText = tripStatusText(heldTrip);
  assert.match(statusText, /Nav2 주행 문제 정지.*NAV2_FAILED/);
  assert.match(statusText, /위치 확정 · SLAM/);
  assert.doesNotMatch(statusText, /바뀐 경로 확인 대기/);
});
