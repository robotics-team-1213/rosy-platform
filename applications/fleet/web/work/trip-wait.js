const WAIT_LABEL = {
  peer_pre_dispatch: '안전거리 확인 · 주행 명령 전송 전', peer_clearance: '통행 안전거리 확인',
  fleet_hold_unconfirmed: '일시정지 · 기체 정지 응답 확인 중', fleet_hold: '일시정지 · 정지 확인됨',
  route_replan_hold: '변경 경로 확인', signal: '신호', authority: '통행권', link_wait: '연결', crosswalk_look: '횡단보도', crosswalk_wait: '횡단보도', crosswalk_held: '횡단보도'};

export function tripWaitText(trip, wait = trip?.wait) {  // D-763 8 (v1.231): Fleet's one waiting predicate; past its bound, D-622 (rev 2 Q7)
  if (trip?.hold?.reason === 'fleet_hold') {
    return trip.hold.stop?.confirmed ? '일시정지 · 정지 확인됨' : '일시정지 · 기체 정지 응답 확인 중';
  }
  const parking = trip?.detail?.parking_handoff;
  if (parking?.phase === "waiting_for_commission")
    return `${parking.staging_place_id} 대기 · ${parking.bay_id} 도킹 보정 필요 (${parking.reason})`;
  if (parking?.phase === "waiting_for_clearance") return `${parking.staging_place_id} 대기 · ${parking.bay_id} 진입 확인 (${parking.reason})`;
  if (parking?.phase === "docking" || parking?.phase === "submitting") return `${parking.bay_id} 후진 주차 중`;
  const peer = trip?.detail?.peer_wait;
  if (peer) {
    const ids = peer.waiting_on?.length ? peer.waiting_on : [peer.blocked_by].filter(Boolean);
    const stage = peer.stage === 'pre_dispatch_peer_check' && peer.dispatch_attempted === false ? ' · 주행 명령 전송 전' : '';
    return `통행 대기${stage} · 명령 대상 ${trip.robot_id}${ids.length ? ' · 안전거리 확인 대상 ' + ids.join(', ') : ''} · 자동 재확인 중`;
  }
  return wait?.waiting || wait?.over_bound ? `${wait.waiting ? '대기' : '대기 상한 넘음'} · ${WAIT_LABEL[wait.reason] || wait.reason}` : '';
}

export function tripExecutionText(trip) {
  const execution = trip?.execution;
  if (!execution || execution.phase === 'terminal') return '';
  const wait = tripWaitText(trip);
  const label = wait || {received: '운행 요청 접수', dispatched: '주행 명령 전달 · 이동 확인 대기',
    moving: '실제 이동 중', stationary: '주행 명령 전달 · 현재 정지',
    pre_dispatch_wait: '통행 대기 · 주행 명령 전송 전', goal_wait: '주행 명령 대기', paused: '일시정지'}[execution.phase];
  if (!label) return '';
  if (execution.motion === 'moving' && execution.phase !== 'moving') return label + ' · 실제 이동 중';
  if (execution.motion === 'stationary' && execution.phase !== 'stationary') return label + ' · 현재 정지';
  return label;
}
