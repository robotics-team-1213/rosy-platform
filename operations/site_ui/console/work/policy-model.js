// D-793 학습 정책 승인 화면의 순수 판단. DOM이 없고 node 시험이 덮는다.
// 서버가 규칙의 단일 출처다. 여기서는 서버가 거절할 조작을 미리 잠그고 사유를 보인다.

export const STAGE_LABELS = {
  L0: 'L0 학습됨 · 오프라인 재생만', L1: 'L1 오프라인 통과', L2: 'L2 shadow · 명령 없음',
  L3: 'L3 입회 시험', LIMITED: '제한 사용',
};
export const WINDOW_LABELS = {shadow: 'shadow (명령 없음)', supervised: '입회 시험', limited: '제한 사용'};
export const REASON_LABELS = {
  new_policy: '처음 쓰는 모델', revision_mismatch: 'rig·보정 revision 다름',
  environment_out_of_range: '환경이 지원 범위 밖', policy_output_rejected: '정책 출력 거부',
  target_not_reached: '목표에 도달하지 않음', timing_budget_exceeded: '시간 예산 초과',
  owner_fault: 'owner fault·모터 오류', owner_hold: 'owner HOLD', other: '기타',
};
export const RESOLUTION_LABELS = {resume: '재개', abort: '중단', send_to_learning: '학습으로 되돌림'};
export const TWO_PERSON_REASON = '제안한 사람과 다른 관리자가 승인해야 합니다';
export const ADMIN_REASON = '정책 관리자 권한이 필요합니다';
export const OPERATOR_REASON = '이름 있는 운영자 로그인이 필요합니다';

function permits(session, capability, legacyRoles) {
  if (!session) return false;
  if (session.account_id) {
    return (session.grants || []).some(grant => grant.resource === session.site_resource
      && (grant.capabilities || []).includes(capability));
  }
  return legacyRoles.includes(session.role) || (capability === 'fleet.policy' && session.policy_admin === true);
}

export function roles(session) {
  const operator = permits(session, 'fleet.operate', ['operator'])
    && !!session.principal_id && session.principal_id !== 'site-console';
  return {me: session?.principal_id || '', admin: permits(session, 'fleet.policy', ['policy-admin']), operator};
}

export function nextStage(rules, stage) {
  const stages = rules.stages;
  if (!stage) return stages[0];
  const index = stages.indexOf(stage);
  return index >= 0 && index < stages.length - 1 ? stages[index + 1] : null;
}

export function remaining(expiresNs, nowNs) {
  const seconds = Math.max(0, Math.floor((expiresNs - nowNs) / 1e9));
  return `${Math.floor(seconds / 60)}분 ${String(seconds % 60).padStart(2, '0')}초`;
}

// 실물 실행이 지금 가능한지 한 줄로. 막는 이유가 여럿이면 가장 강한 것 하나를 말한다.
export function executionVerdict(state) {
  const incidents = state.incidents.filter(item => item.cleared_ns === null);
  if (incidents.length) return {state: 'error', text: `사고 잠금 ${incidents.length}건 — 다른 관리자가 해제하기 전까지 학습 정책은 실행되지 않습니다.`};
  const open = state.confirmations.filter(item => item.resolution === null);
  if (open.length) return {state: 'warning', text: `확인 요청 ${open.length}건 — 해결하기 전까지 실행 lease를 발급하지 않습니다.`};
  const active = state.windows.find(item => item.active);
  if (!active) return {state: 'ready', text: '열린 승인 창이 없습니다. 학습 정책은 실물을 움직이지 않습니다.'};
  const left = remaining(active.expires_ns, state.now_ns);
  if (active.kind === 'shadow') return {state: 'ready', text: `shadow 승인 창 ${left} 남음 — 추론만 하고 명령은 보내지 않습니다.`};
  return {state: 'warning', text: `${WINDOW_LABELS[active.kind]} 승인 창 ${left} 남음 — ${active.policy_revision}이(가) 1–2초 lease로 실행될 수 있습니다.`};
}

// 서버가 거절할 승인을 미리 잠그는 사유. 빈 글이면 누를 수 있다.
export function proposalLock(proposal, rules, who) {
  if (!who.admin) return ADMIN_REASON;
  if (rules.two_person_stages.includes(proposal.to_stage) && proposal.proposed_by === who.me) return TWO_PERSON_REASON;
  return '';
}

export function windowLock(window, rules, who) {
  if (!who.admin) return ADMIN_REASON;
  if (rules.windows[window.kind].two_person && window.requested_by === who.me) return TWO_PERSON_REASON;
  return '';
}

export function incidentLock(incident, who) {
  if (!who.admin) return ADMIN_REASON;
  return incident.reported_by === who.me ? '신고한 사람과 다른 관리자가 해제해야 합니다' : '';
}

export function errorText(error) {
  const known = {
    STAGE_SKIP_REFUSED: '단계는 하나씩만 올릴 수 있습니다.',
    APPROVER_MUST_DIFFER_FROM_PROPOSER: TWO_PERSON_REASON,
    INCIDENT_OPEN: '사고 잠금 중에는 실물 단계를 승인하거나 승인 창을 열 수 없습니다.',
    REVISION_CHANGED_REAPPROVAL_REQUIRED: 'rig·보정 revision이 승인 때와 다릅니다. 다시 등록하고 승인받아야 합니다.',
    REVISION_CHANGED_REREGISTER_REQUIRED: 'rig·보정 revision이 승인 때와 다릅니다. 다시 등록하고 승인받아야 합니다.',
    STAGE_TOO_LOW: '이 승인 창을 열기에는 정책 단계가 낮습니다.',
    ANOTHER_WINDOW_ACTIVE: '이미 열린 승인 창이 있습니다. 먼저 닫으세요.',
    WINDOW_TOO_LONG: '승인 창 길이가 허용 범위를 넘습니다.',
    PROPOSAL_ALREADY_PENDING: '이미 결정을 기다리는 제안이 있습니다.',
  };
  return known[error?.code] || error?.message || '처리 결과를 확인하지 못했습니다. 현재 상태를 다시 조회하세요.';
}
