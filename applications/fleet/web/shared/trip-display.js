// Fleet trip display vocabulary and explanations; no DOM, geometry or requests.

export const ACTION_LABEL = {straight: '직진', left: '좌회전', right: '우회전', uturn: '회차', stop: '정지'};
/** D-517 5 (M4) Fleet resolver decisions for a wait cycle. */
export const RESOLVER_DECISION_LABEL = {replan: '다른 길 계획', wait: '다른 로봇 대기', human: '운영자 판단'};
/** D-577 3 AI PC fact kinds (shadow: shown, never acted on here). */
export const AI_FACT_LABEL = {
  trip_route_check: 'AI 경로 편차 확인',
  wait_cycle_confirmed: '교착 확인 (모두 멈춤)', wait_cycle_stale_input: '낡은 입력의 교착일 수 있음',
  waiting_but_moving: '대기인데 움직임', livelock: '움직이지만 진행 없음', stalled: '권한이 있는데 멈춤',
  unknown_occupancy_long: '위치 불명 점유 30초 넘음', rear_blocked: '뒤가 막힘', path_blocked_by_robot: '앞에 로봇',
  incident_context: '사건 원인 초안',
};

export const TRIP_ERROR_LABEL = {
  TRIP_PROPOSAL_NOT_FOUND: '해당 이송 제안을 찾을 수 없습니다 · 제안 식별자를 확인하세요',
  TRIP_PROPOSAL_FORBIDDEN: '이 이송 제안을 읽거나 승인할 권한이 없습니다 · 제안자와 다른 기명 운영자가 승인해야 합니다',
  TRIP_PROPOSAL_CONFLICT: '이송 제안이나 실행 세대가 바뀌었습니다 · 원본을 다시 조회하세요',
  TRIP_PROPOSAL_UNAVAILABLE: '이송 제안 API를 쓸 수 없습니다 · 시뮬레이션 설치와 연결 상태를 확인하세요',
  TRIP_START_CANCELED: '출발 준비 중 정지 요청을 받았습니다 · 상태를 확인한 뒤 다시 시작하세요',
  TRIP_START_PLACE_MISMATCH: '선택한 출발 장소에 로봇이 없습니다 · 실제 위치를 확인하세요',
  TRIP_START_PLACE_MOVED: '그 장소에서는 안전하게 정지할 수 없습니다 · 다른 장소를 고르세요',
  TRIP_BODY_UNKNOWN: '로봇 차체 폭을 확인할 수 없어 출발할 수 없습니다',
  TRIP_START_BODY_OUTSIDE_ROUTE: '로봇 차체가 첫 차로 경계를 넘었습니다 · 위치를 조정하세요',
  TRIP_START_OFF_MAP: '로봇이 차로 위에 없습니다',
  TRIP_HEADING_CONFLICT: '로봇이 차로 반대 방향을 보고 있습니다 · Pilot으로 돌려 세우세요',
  TRIP_OFF_MAP: '찍은 점에서 차로 폭 두 배 안에 차로가 없습니다',
  TRIP_UNKNOWN_PLACE: '없는 주소입니다',
  TRIP_UNKNOWN_EDGE: '지도에 없는 차로입니다',
  TRIP_NO_ROUTE: '갈 수 있는 길이 없습니다',
  TRIP_ARRIVE_YAW_UNREACHABLE: '그 방향으로 도착하는 차로가 없습니다',
  TRIP_NO_ACTIVE_MAP: '활성 지도가 없습니다',
  TRIP_POSE_UNTRUSTED: '현장 지도 위치를 확인할 수 없습니다 · 위치와 관측 갱신을 확인하세요',
  TRIP_PLAN_FAILED: '이 지도에서 경로 계산이 실패했습니다 · 관리자에게 알리세요',
  TRIP_JOB_NOT_FOUND: '해당하는 이송 작업이 없습니다 · 접수 키와 권한을 확인하세요',
  UNKNOWN_ROBOT: '등록되지 않은 로봇입니다',
  // D-494 5 trip start / control
  TRIP_PLAN_UNKNOWN: '저장된 경로가 없습니다 · 다시 계산하세요',
  TRIP_PLAN_EXPIRED: '계산한 지 30초가 지났습니다 · 다시 계산하세요',
  TRIP_MAP_CHANGED: '계산 뒤 활성 지도가 바뀌었습니다 · 다시 계산하세요',
  TRIP_ROBOT_CAPS_UNKNOWN: '로봇이 주행 능력(종류·주행 방식)을 알리지 않습니다 · 새 이미지가 필요합니다',
  TRIP_MODE_UNSUPPORTED: '이 로봇의 주행 방식으로 갈 수 없는 차로가 경로에 있습니다',
  TRIP_SITE_FLOOR_MISMATCH: '로봇의 현장 바닥 선언이 활성 지도와 다릅니다 · 로봇 설정을 확인하세요',
  // D-601: 꺼져 있으면 관제가 출발 때 카메라 차선 주행을 켠다; 남는 거절은 IR 차선 주행이나 모르는 상태
  TRIP_LINE_FOLLOW_NOT_ACTIVE: '로봇이 IR 차선 주행 중이거나 차선 주행 상태를 알 수 없습니다 · 차선 주행을 끈 뒤 다시 출발하세요',
  TRIP_LANE_CAMERA_UNAVAILABLE: '로봇 앞 카메라 영상이 들어오지 않아 차선 주행을 할 수 없습니다 · 카메라를 확인하세요',
  TRIP_START_HEADING_MISMATCH: '로봇이 첫 차로 방향과 다르게 서 있습니다 · 차로 방향으로 돌려 세우세요',
  TRIP_START_OFF_LANE: '로봇이 첫 차로 밖에 있습니다 · 차로 위로 옮기세요',
  TRIP_LINE_FOLLOW_START_FAILED: '로봇이 카메라 차선 주행을 켜지 못해 운행을 멈췄습니다',
  // D-603 출발 자동 정렬
  TRIP_ALIGN_REFUSED: '로봇이 제자리 회전을 거절했습니다 · 주변을 비우거나 직접 돌려 세우세요',
  TRIP_ALIGN_ABORTED: '제자리 회전이 중간에 멈췄습니다 · 로봇 주변을 확인하세요',
  TRIP_BUSY: '이 로봇은 이미 운행 중입니다', TRIP_OWNER_KIND_INVALID: '운행을 요청한 작업을 확인할 수 없습니다',
  TRIP_LOOP_FULL: '고리 수용 한도를 넘어 출발할 수 없습니다',
  // D-517 9 M3 대열
  TRIP_CONVOY_SELF: '자기 자신을 리더로 고를 수 없습니다',
  TRIP_CONVOY_LEADER_NOT_RUNNING: '리더가 반복 운행 중이 아닙니다 · 리더를 먼저 출발시키세요',
  TRIP_CONVOY_LEADER_IS_FOLLOWER: '고른 리더도 다른 로봇을 따라갑니다 · 대열의 맨 앞 로봇을 고르세요',
  TRIP_CONVOY_OTHER_LOOP: '리더와 다른 고리입니다 · 같은 출발 자리 순환으로 다시 하세요',
  TRIP_CONVOY_NO_AUTHORITY: '이 로봇은 통행권(CORE)을 받지 않아 대열에 들 수 없습니다',
  TRIP_CONVOY_LOOP_FULL: '대열을 더하면 고리 수용 한도를 넘습니다',
  TRIP_CONVOY_NOT_BEHIND: '리더 뒤 같은 고리에 있지 않습니다 · 리더 뒤에 세운 뒤 다시 하세요',
  // D-517 4 통행권: 현장 설정과 로봇 CORE 설정이 맞아야 출발한다
  TRIP_AUTHORITY_SITE_OFF: '이 로봇 CORE는 통행권이 있어야 움직이는데 현장 통행권이 꺼져 있습니다 · 현장 설정을 켜거나 로봇의 통행권 필수를 끄세요',
  TRIP_AUTHORITY_NOT_REQUIRED: '현장은 통행권을 보내는데 이 로봇 CORE는 통행권 없이 움직입니다 · 로봇 설정에서 통행권 필수를 켜세요',
  // D-525 가상 신호
  TRIP_SIGNAL_START_IN_ZONE: '신호 교차로 안에서는 출발할 수 없습니다 · 교차로 밖으로 옮긴 뒤 다시 하세요',
  // D-517 3: 구역 안에서는 서지 않는다
  TRIP_STOP_IN_ZONE: '경로 위에 구역(교차로) 밖에 설 장소가 없습니다 · 다른 목적지를 고르세요',
  TRIP_REGULATION_CAPS_MISSING: '경로가 횡단보도나 신호 교차로를 지나는데 이 로봇의 CORE에 그 규칙(횡단보도 게이트·교차로 신호)이 꺼져 있다고 알립니다',
  TRIP_SIGNAL_NEEDS_AUTHORITY: '경로가 신호 교차로를 지나는데 이 로봇은 통행권(CORE)을 받지 않습니다 · 적색에서 선다는 보장이 없습니다',
  TRIP_ROBOT_BUSY: '이 로봇은 운행 중입니다 · 운행을 먼저 취소하세요',
  TRIP_CANDIDATES_BUSY: '후보 로봇이 모두 사용 중입니다 · 현재 작업 상태를 확인하세요',
  TRIP_REQUEST_CONFLICT: '같은 요청 번호에 다른 내용이 있습니다 · 기존 요청 내용을 확인하세요',
  TRIP_ALREADY_STARTED: '이미 출발시킨 경로입니다',
  TRIP_NOT_RUNNING: '진행 중인 운행이 아닙니다',
  TRIP_UNKNOWN: '없는 운행입니다',
  TRIP_NO_REPLAN: '확인할 바뀐 경로가 없습니다',
  TRIP_REPLAN_FAILED: '다시 계산한 경로가 없습니다 · 운행을 취소하세요',
  TRIP_EXECUTION_NOT_AVAILABLE: '출발은 운행 시작 버튼으로 따로 합니다',
  // D-541 7 trip lease: CORE가 운행 중 로봇을 쥐게 한다
  TRIP_LEASE_UNSUPPORTED: '이 로봇 CORE는 운행 점유(trip lease)를 모릅니다 · 현장이 점유를 요구합니다 · 새 이미지가 필요합니다',
  TRIP_ROBOT_LEASED: '다른 운행이 이 로봇을 쥐고 있습니다 · 그 운행이 끝난 뒤 다시 하세요',
  TRIP_LEASED: '다른 운행이 이 로봇을 쥐고 있습니다',  // CORE's code (D-541 2), as Fleet's TRIP_ROBOT_LEASED
  TRIP_ROBOT_MANUAL: '로봇이 수동(MANUAL) 모드입니다 · 로봇을 멈춤(IDLE)으로 둔 뒤 다시 출발하세요',
  CALIBRATION_ACTIVE: '로봇이 보정 중입니다 · 보정이 끝난 뒤 다시 출발하세요',
  TRIP_LEASE_REFUSED: '로봇 CORE가 운행 점유를 거절했습니다(비상 정지·도킹 등) · 로봇 상태를 확인하세요',
  TRIP_ROBOT_UNREACHABLE: '로봇에 지시를 보내지 못했습니다',
};
/** D-541 5/7: why CORE ended the trip lease (``detail.lease_reason``). */
const LEASE_END_LABEL = {
  taken_over: '로봇 화면·Pilot에서 넘겨받음', expired: '점유가 만료됨(관제 연결이 끊겼던 듯)',
  mode_left: '로봇이 운행 모드를 떠남(멈춤·수동·도킹·막힘 중단)', estop: '비상 정지', released: '점유를 놓음',
  core_restarted: '로봇 CORE가 다시 시작됨', leased: '다른 운행이 로봇을 쥠', renew_timeout: '점유 갱신 응답이 없음',
};
export const TRIP_STATE_LABEL = {
  started: '출발 대기', running: '운행 중', arrived: '도착', stopped: '멈춤', failed: '실패', canceled: '취소됨', link_wait: '연결 대기',
};
const TRIP_POSE_STATE_LABEL = {LOCALIZED: '위치 확정', DEGRADED: '위치 정확도 저하', UNKNOWN: '위치 확인 불가'};
export const TRIP_REASON_LABEL = {
  pose: '위치를 믿을 수 없어 멈췄습니다',
  junction: '로봇이 교차로 동작을 마치지 못해 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  JUNCTION_ODOM_STALE: '로봇 odom이 낡아 교차로 지시를 다음 주기에 다시 보냅니다',
  junction_unexpected: '지도에 없는 자리에서 교차로를 봐 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  junction_corner_hold: '지시한 교차로 바로 앞에서 차선 모서리로 돌지 않게 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  junction_no_window: '교차로 위치를 확인할 기대 창이 없어 좌·우 회전 지시를 보내지 않고 멈췄습니다 · 차선 주행을 껐습니다',
  stall: '경로를 따라 나아가지 않아 멈췄습니다 · 현장을 확인하세요',
  lane_arc: '회전교차로 호를 달리던 로봇이 멈췄습니다 · 차선 주행을 껐습니다 · 현장을 확인하세요',
  TRIP_LOOP_ERROR: '관제 운행 처리에 오류가 나 멈췄습니다 · 로봇 정지를 확인하고 관리자에게 알리세요',
  restart: '관제 서버가 다시 시작돼 멈췄습니다 · 자동으로 다시 출발하지 않습니다',
  TRIP_ROBOT_JUNCTION_UNSUPPORTED: '로봇 CORE가 교차로 지시를 모릅니다 · 새 이미지가 필요합니다',
  TRIP_ROBOT_UNREACHABLE: '로봇에 지시를 보내지 못했습니다',
  TRIP_GOAL_REFUSED: '로봇이 목적지 지시를 거절해 멈췄습니다 · 현장을 확인하세요',
  LINE_FOLLOW_NOT_ACTIVE: '로봇의 차선 주행이 켜져 있지 않습니다',
  lease_lost: '운행 끝 · 다시 몰려면 새 운행을 시작하세요',
  TRIP_LINE_FOLLOW_START_FAILED: '로봇이 카메라 차선 주행을 켜지 못해 운행을 멈췄습니다',
};

const WAIT_LABEL = {signal: '신호', authority: '통행권', link_wait: '연결', crosswalk_look: '횡단보도', crosswalk_wait: '횡단보도', crosswalk_held: '횡단보도'};

/** D-601 D: "출발 가능" / "방향 반대(178°)" / "차선 밖 5 cm" from a plan's ``start_check``. */
export function startCheckText(check) {
  if (!check?.code) return '출발 가능';
  if (check.auto_align) return `${startCheckText({...check, auto_align: false})} · 출발 때 자동 정렬`;
  if (check.code === 'TRIP_START_OFF_LANE') return `차선 밖 ${Math.round((check.off_lane_m || 0) * 100)} cm`;
  const err = Math.abs(check.heading_err_deg ?? NaN);
  if (!Number.isFinite(err)) return '방향 모름';
  return `${err > 90 ? '방향 반대' : '방향 어긋남'}(${err.toFixed(0)}°)`;
}

export function tripErrorText(code, detail = {}) {
  const base = TRIP_ERROR_LABEL[code] || `경로 계획 거절 (${code || '알 수 없음'})`;
  if (/HEADING_CONFLICT|START_HEADING_MISMATCH/.test(code || '') && detail?.heading_err_deg != null)
    return `${base} · ${startCheckText({...detail, code: 'heading'})}`;
  if (/START_OFF_(LANE|MAP)/.test(code || '') && detail?.off_lane_m != null)
    return `${base} · ${startCheckText({...detail, code: 'TRIP_START_OFF_LANE'})}`;
  if (code?.endsWith('LOOP_FULL') && Number.isInteger(detail.robots) && Number.isInteger(detail.capacity))
    return `${base} · 고리 ${detail.robots}/${detail.capacity}대`;  // robots counts this one too
  if (code === 'TRIP_UNKNOWN_EDGE' && typeof detail.edge === 'string' && detail.edge)
    return `${base} · ${detail.edge}`;
  if (code !== 'TRIP_NO_ROUTE') return base;
  const leg = Number.isInteger(detail.segment) ? ` · ${detail.segment + 1}번째 구간` : '';
  return base + leg + (detail.unblock_would_help ? ' · 막은 차로를 풀면 길이 있습니다' : '');
}

/** D-541 7: e.g. "로봇 화면·Pilot에서 넘겨받음(kim-tablet)". */
function leaseEndText(trip) {
  const why = LEASE_END_LABEL[trip.detail?.lease_reason] || trip.detail?.lease_reason || '점유를 잃음';
  return trip.detail?.lease_by ? `${why}(${trip.detail.lease_by})` : why;
}

/** D-540 (d): why a trip stopped or failed, for the card line and the queue; '' for any other state. */
export function tripEndText(trip) {
  if (trip?.state !== 'stopped' && trip?.state !== 'failed') return '';
  const why = trip.reason === 'lease_lost' ? leaseEndText(trip) : TRIP_REASON_LABEL[trip.reason] || trip.reason;
  return [`운행 ${TRIP_STATE_LABEL[trip.state]}`, why].filter(Boolean).join(' · ');
}

export function tripWaitText(trip, wait = trip?.wait) {  // D-763 8 (v1.231): Fleet's one waiting predicate; past its bound, D-622 (rev 2 Q7)
  return wait?.waiting || wait?.over_bound ? `${wait.waiting ? '대기' : '대기 상한 넘음'} · ${WAIT_LABEL[wait.reason] || wait.reason}` : '';
}

/** One line for the trip panel: state, current lane, next place and action, pose source. */
export function tripStatusText(trip, map) {
  if (!trip) return '진행 중인 운행 없음';
  const names = new Map((map?.places || []).map(place => [place.id, place.name]));
  const parts = [`${TRIP_STATE_LABEL[trip.state] || trip.state} · ${trip.robot_id}`];
  if (trip.current_edge) parts.push(`차로 ${trip.current_edge}`);
  if (trip.next_place) parts.push(`다음 ${names.get(trip.next_place) || trip.next_place} ${ACTION_LABEL[trip.next_action] || trip.next_action || ''}`.trim());
  if (trip.pose) parts.push(`자세 ${TRIP_POSE_STATE_LABEL[trip.pose.state] || trip.pose.state} · ${trip.pose.source === 'sighting' ? 'Rosy Cam' : trip.pose.source === 'bridged' ? 'odom 다리' : trip.pose.source}`);
  if (trip.hold) parts.push('바뀐 경로 확인 대기 · 장소에서 서 있음');
  if (['started', 'running', 'link_wait'].includes(trip.state) && tripWaitText(trip)) parts.push(tripWaitText(trip));  // open only
  if (trip.stop_moved) {  // D-517 3 (2026-10-09 "다음 지점까지 가서 섬"): never stands inside a zone
    const {from, to} = trip.stop_moved;
    parts.push(`목적지 ${names.get(from) || from || '좌표'} → ${names.get(to) || to} · 교차로 안에 서지 않도록 다음 지점에서 섭니다`);
  }
  if (trip.reason === 'stall' && Number.isFinite(trip.detail?.stall_s)) {
    parts.push(`${trip.detail.stall_s}초 넘게 ${TRIP_REASON_LABEL.stall}`);
  } else if (trip.reason) {
    parts.push(TRIP_REASON_LABEL[trip.reason] || trip.reason);
  }
  if (trip.reason === 'lease_lost') parts.push(leaseEndText(trip));
  else if (trip.lease?.state === 'held') parts.push('CORE 점유 중');
  if (trip.detail?.junction_retry) parts.push(TRIP_REASON_LABEL[trip.detail.junction_retry] || trip.detail.junction_retry);
  if (trip.detail?.junction_fields_dropped) parts.push('활성 지도가 바뀌어 교차로 기대 값을 보내지 않았습니다');
  if (trip.reason === 'lane_arc' && trip.detail?.arc_reason) parts.push(`사유 ${trip.detail.arc_reason}`);  // D-520 2
  if (trip.detail?.junction_reason === 'arc_mismatch') parts.push('호 끝 장소와 다른 장소의 지시라 로봇이 버렸습니다');
  if (trip.detail?.arc_end_unarmed) parts.push('호 끝에 다음 지시가 없어 로봇이 일반 차선 추종으로 돌아갔습니다');
  if (trip.reason === 'junction_unexpected') {  // D-507 3: where it stopped and why CORE held
    const {x, y} = trip.pose || {};
    if (Number.isFinite(x) && Number.isFinite(y)) parts.push(`지도 자세 (${x.toFixed(2)}, ${y.toFixed(2)})`);
    const why = trip.detail?.junction_reason || trip.detail?.line_reason;
    if (why) parts.push(`사유 ${why}`);
  }
  return parts.join(' · ');
}
