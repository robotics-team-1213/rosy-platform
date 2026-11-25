import {jointLabel} from '/common/motor-health.js';
import {isHomeRecovery} from '/console/assets/cell-obs-model.js';

const STATE_LABEL = {open: '열림 · 사람 확인 필요', explained: '열림 · AI 설명 있음', cleared: '해제됨'};
export const when = seconds => new Date(seconds * 1000).toLocaleString('ko-KR');

export function incidentHeading(incident) {
  const status = isHomeRecovery(incident) ? (incident.state === 'cleared' ? '홈 복구 보류 해제' : '홈 복구 대기') : STATE_LABEL[incident.state] || incident.state;
  return `${status} · ${when(incident.reported_at)}`;
}

// A second joint lagging with the stopped one points at an outside restraint, not that motor (arm_a, 2026-11-01).
const LAGGING_DEG = 1;
export function faultLine(fault) {
  const stopped = fault.motors.filter(motor => motor.fault);
  const lagging = fault.motors.filter(motor => !motor.fault && motor.error_deg >= LAGGING_DEG);
  return [
    ...stopped.map(motor => `${jointLabel(motor.joint)}(ID ${motor.id}) 정지 · 오차 ${motor.error_deg.toFixed(1)}° ` +
      `(목표 ${Math.round(motor.command_raw)} / 현재 ${Math.round(motor.present_raw)} tick, PWM ${Math.round(motor.pwm)}/${Math.round(motor.pwm_limit)})`),
    fault.stop_reasons.join(', '),
    lagging.length ? `함께 뒤처진 관절: ${lagging.map(motor => `${jointLabel(motor.joint)} ${motor.error_deg.toFixed(1)}°`).join(', ')}` : '',
  ].filter(Boolean).join(' · ');
}

// D-971: what the control PC measured, as plain lines (text only, never markup)
export const incidentLines = incident => {
  const {facts = {}, decision = {}, recovery = null} = incident;
  const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const latched = facts.latched === undefined ? {} : facts.latched, flagged = facts.flagged === undefined ? [] : facts.flagged;
  const measured = ['latched', 'flagged', 'folded', 'torque_after', 'windup_hits'].some(key => key in facts)
    && record(latched) && Object.values(latched).every(latch => record(latch)
      && typeof latch.hw_error === 'number'
      && (latch.bits === undefined || (Array.isArray(latch.bits) && latch.bits.every(bit => typeof bit === 'string'))))
    && Array.isArray(flagged) && flagged.every(row => record(row) && typeof row.command === 'string'
      && ['error', 'fault'].every(key => row[key] == null || typeof row[key] === 'string'))
    && (facts.folded === undefined || typeof facts.folded === 'boolean')
    && (facts.windup_hits === undefined || Array.isArray(facts.windup_hits));
  const measurements = measured ? [
    Object.entries(facts.latched || {}).map(([id, latch]) => `ID ${id} 오류 ${latch.hw_error} (${(latch.bits || []).join('/')})`).join(', '),
    facts.folded === undefined ? '' : `홈 접힘 ${facts.folded ? '예' : '아니오'} · 종료 후 토크 ${JSON.stringify(facts.torque_after || {})}`,
    (facts.windup_hits || []).length ? `출력 상승 감지 ${facts.windup_hits.length}건` : '',
    (facts.flagged || []).map(row => `실행기: ${row.command} ${row.error || row.fault || ''}`).join(' · '),
  ].filter(Boolean) : [];
  return [
    typeof decision.reason === 'string' ? decision.reason : JSON.stringify(decision.reason),
    ...(measurements.length ? measurements : [Object.keys(facts).length ? JSON.stringify(facts) : '']),
    recovery ? `장치 안전 재부팅: ${JSON.stringify(recovery).slice(0, 300)}` : '',
  ].filter(Boolean);
};
