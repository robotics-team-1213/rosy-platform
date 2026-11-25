import { evidenceAgeText } from "/common/core_ui_logic.js";

// D-1057 refusals of claim/complete, said as the evidence that was missing.
const REFUSAL_TEXT = {
  AMR_BRAKE_BED_VELOCITY_UNMEASURED: '핑키 정지·정차 위치·적재함 확인 중 측정되지 않은 것이 있습니다',
  OMX_OWNER_EVIDENCE_UNAVAILABLE: '팔 셀이 보낸 완료 증거가 없습니다',
  OMX_OWNER_EVIDENCE_MISMATCH: '완료 보고가 팔 셀이 보낸 증거와 다릅니다',
  UNVERIFIED_CELL_COMPLETION: '카메라 위치 확인·홈 복귀·적재 층 중 확인되지 않은 것이 있습니다',
  OWNER_PRINCIPAL_NOT_REGISTERED: '증거를 보낸 계정이 이 셀의 주인으로 등록되지 않았습니다',
  HUMAN_HOLD_ACTIVE: '사람 감지로 멈춘 상태입니다',
  CELL_BUSY_OR_HELD: '셀이 다른 작업 중이거나 보류 중입니다',
  PREVIOUS_TIER_NOT_VERIFIED: '아래층 적재가 아직 확인되지 않았습니다',
  CELL_AB_EVIDENCE_NOT_ENABLED: '셀 A/B 완료 확인(깊이 측정)이 아직 켜지지 않았습니다',
  BED_CONFIRMATION_INVALID: '적재함 확인이 무효가 되었습니다 (핑키 이동 또는 지도 변경). 핑키가 멈춘 상태에서 적재함을 다시 확인하세요',
  PRESENCE_CONFIRMATION_REQUIRED: 'ACT 정책 구동은 이름 있는 운영자의 입회 표시가 필요합니다 (D-911)',
};

// Field names of the server's AMR evidence (pipeline_evidence.amr_evidence), when a refusal lists the missing ones.
const AMR_EVIDENCE_TEXT = {wheel_brake_locked: '정지', v_cmd_mps: '정지', pose: '정차 위치', bed_ready: '적재함 확인', observed_at: '측정 시각'};

export function refusalText(refusal) {
  if (!refusal?.code) return '';
  const missing = [...new Set((Array.isArray(refusal.missing) ? refusal.missing : []).map(k => AMR_EVIDENCE_TEXT[k] || k))];
  const text = missing.length ? `측정되지 않음: ${missing.join(', ')}` : REFUSAL_TEXT[refusal.code] || `사유 확인 필요 (${refusal.code})`;
  return `${refusal.op === 'complete' ? '완료 거부' : '시작 거부'} · ${text}`;
}

export function fieldStatus(body, tasks, cellId, armIds) {
  const liveJointArms = new Set(body.live_joint_arms || []);
  const cells = body?.cells || {};
  const states = body?.arm_live_states || {};
  const arms = armIds.map(id => {
    const arm = states[id];
    if (liveJointArms.has(id)) {
      return `${id} 마지막 화면 갱신 시 관절 관측${arm?.fresh === true ? '' : ' · 작업 상태 갱신 필요'}`;
    }
    if (!arm?.observed) return `${id} 관절 상태 미수신`;
    if (arm.fresh !== true) {
      const seconds = arm.age_s;
      const age = !Number.isFinite(seconds) ? '' : seconds >= 3600
        ? ` (${Math.floor(seconds / 3600)}시간 ${Math.floor(seconds % 3600 / 60)}분 전)`
        : seconds >= 60 ? ` (${Math.floor(seconds / 60)}분 전)` : evidenceAgeText(Math.floor(seconds));
      return `${id} 작업 관절 기록 갱신 필요${age}`;
    }
    return `${id} 작업 관절 기록 있음`;
  });
  const cellTasks = tasks.filter(task => task.cell_id === cellId);
  const pending = cellTasks.filter(task => task.status === 'PROPOSED').length;
  const queued = cellTasks.filter(task => task.status === 'QUEUED');
  const waiting = queued[0];
  const refused = waiting?.last_refusal ? waiting
    : cellTasks.findLast(task => task.status === 'RUNNING' && task.last_refusal);
  const refusal = refused?.last_refusal;
  const station = cells[cellId]?.station?.station_place;
  return {
    arms: arms.join(' · '),
    queue: `승인 대기 ${pending}건 · 실행 대기 ${queued.length}건`,
    refusal: refusalText(refusal),
    next: refused === waiting && refusal?.code === 'AMR_BRAKE_BED_VELOCITY_UNMEASURED'
      ? [refused.robot_id, station, '정차 및 적재함 확인 상태를 확인하세요.'].filter(Boolean).join(' ') : '',
  };
}
