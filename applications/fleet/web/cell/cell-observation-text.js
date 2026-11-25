import {jointLabel} from '/common/motor-health.js';

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
