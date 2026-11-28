const WAIT_LABEL = {
  peer_pre_dispatch: '안전거리 확인 · 주행 명령 전송 전', peer_clearance: '통행 안전거리 확인',
  fleet_hold_unconfirmed: '일시정지 · 기체 정지 응답 확인 중', fleet_hold: '일시정지 · 정지 확인됨',
  route_replan_hold: '변경 경로 확인', traffic_hold: '앞 기체 비킬 때까지 정지 위치에서 대기', signal: '신호', authority: '통행권', link_wait: '연결', crosswalk_look: '횡단보도', crosswalk_wait: '횡단보도', crosswalk_held: '횡단보도'};

const DOCK_PREREQUISITE = {
  CHARGE_BAY_TARGET_NOT_TAUGHT: '도킹 위치 미등록', CHARGE_BAY_REAR_TYPE_REQUIRED: '후진 도킹 유형 확인 필요',
  CHARGE_BAY_SCOPED_CANCEL_UNSUPPORTED: '작업별 정지 미지원', CHARGE_BAY_DOCK_OWNER_BUSY: '기존 도킹 작업 있음',
  CHARGE_BAY_DOCK_OWNER_UNVERIFIED: '도킹 작업 상태 미확인', CHARGE_BAY_OWNER_UNAVAILABLE: '기체 연결 미확인',
  CHARGE_BAY_STATUS_READ_UNAVAILABLE: '도킹 상태 조회 불가', CHARGE_BAY_TARGET_READ_UNAVAILABLE: '도킹 위치 조회 불가',
  CHARGE_BAY_OWNER_CHANGED: '도킹 연결 변경'};

export function dockPlanIssues(parking) {
  const reasons = parking?.plan_prerequisites?.reasons;
  return reasons?.length ? ` · 계획 시 ${parking.bay_id} 도킹 확인 결과 · ${reasons.map(r => DOCK_PREREQUISITE[r] || r).join(' · ')}` : '';
}

const PEER_REASON_LABEL = {
  YIELDING: '경로 앞 정차 기체 대기', ROUTE_CONFLICT: '경로 겹침 대기',
  LOCALIZATION_UNTRUSTED: '상대 위치 확인 대기', MAP_FRAME_MISMATCH: '지도 좌표계 확인 대기'};
const WAIT_PREFIX_STATE = {
  dispatched: '대기 지점 이동 중', at_wait_place: '대기 지점 정차 중',
  waiting_stop_confirmation: '대기 지점 정지 확인 중'};

export function tripWaitText(trip, wait = trip?.wait) {  // D-763 8 (v1.231): Fleet's one waiting predicate; past its bound, D-622 (rev 2 Q7)
  if (trip?.hold?.reason === 'fleet_hold') {
    return trip.hold.stop?.confirmed ? '일시정지 · 정지 확인됨' : '일시정지 · 기체 정지 응답 확인 중';
  }
  const parking = trip?.detail?.parking_handoff;
  if (parking?.phase === "waiting_for_commission")
    return `${parking.staging_place_id} 대기 · ${parking.bay_id} 도킹 보정 필요 (${parking.reason})`;
  if (parking?.phase === "waiting_for_clearance") return `${parking.staging_place_id} 대기 · ${parking.bay_id} 진입 확인 (${parking.reason})`;
  if (parking?.phase === "submitting") return `${parking.bay_id} 후진 주차 명령 전송 중`;
  if (parking?.phase === "docking") return `${parking.bay_id} 후진 주차 명령 접수`;
  const peer = trip?.detail?.peer_wait;
  if (peer) {
    const ids = peer.waiting_on?.length ? peer.waiting_on : [peer.blocked_by].filter(Boolean);
    const stage = peer.stage === 'pre_dispatch_peer_check' && peer.dispatch_attempted === false ? ' · 주행 명령 전송 전' : '';
    const reason = peer.reason ? ` · ${PEER_REASON_LABEL[peer.reason] || peer.reason}` : '';
    const wp = trip?.detail?.wait_prefix;
    const wpText = wp?.place && WAIT_PREFIX_STATE[wp.state] ? ` · ${wp.place} ${WAIT_PREFIX_STATE[wp.state]}` : '';
    return `통행 대기${stage} · 명령 대상 ${trip.robot_id}${ids.length ? ' · 안전거리 확인 대상 ' + ids.join(', ') : ''}${reason}${wpText} · 자동 재확인 중` + dockPlanIssues(parking);
  }
  const prob = trip?.detail?.nav2_problem;
  if (prob?.state === 'retry_wait') {
    return `Nav2 경로 재시도 대기 (${prob.attempt}/${prob.max_retries}) · 자동 재확인 중`;
  }
  if (prob?.state === 'held' || trip?.hold?.reason === 'nav2_problem') {
    return `Nav2 주행 문제 정지 · 확인 후 재개 대기${prob?.code ? ` (${prob.code})` : ''}`;
  }
  return wait?.waiting || wait?.over_bound ? `${wait.waiting ? '대기' : '대기 상한 넘음'} · ${WAIT_LABEL[wait.reason] || wait.reason}` : '';
}

export function tripExecutionText(trip) {
  const execution = trip?.execution;
  if (!execution || execution.phase === 'terminal') return '';
  const wait = tripWaitText(trip);
  let label = wait || {received: '운행 요청 접수', dispatched: '주행 명령 전달 · 이동 확인 대기',
    moving: '실제 이동 중', stationary: '주행 명령 전달 · 현재 정지',
    pre_dispatch_wait: '통행 대기 · 주행 명령 전송 전', goal_wait: '주행 명령 대기', paused: '일시정지'}[execution.phase];
  if (!label) return '';
  if (!trip.detail?.peer_wait && execution.waiting_on?.length) label += ' · 안전거리 확인 대상 ' + execution.waiting_on.join(', ');
  if (execution.motion === 'moving' && (wait || execution.phase !== 'moving')) return label + ' · 실제 이동 중';
  if (execution.motion === 'stationary' && (wait || execution.phase !== 'stationary')) return label + ' · 현재 정지';
  return label;
}
