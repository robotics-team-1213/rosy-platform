import test from 'node:test';
import assert from 'node:assert/strict';
import { powerHealthView } from '../../fleet/server/web/power-health-view.js';

function robot(battery = {}) {
  return { online: true, power_health_age_s: 0.2, power_health: {
    battery: { evidence: 'fresh', sample_age_s: 0.2, stale_after_s: 5,
      level: 'ok', percent: 63, charging_state: 'confirmed',
      charging_evidence_age_s: 0.2, ...battery },
    recommendation: 'normal_idle_policy',
  }, state: { safety: { estop: true } } };
}

test('charging requires fresh CORE evidence and never clears a safety stop', () => {
  const fresh = powerHealthView(robot(), 1000, 1000);
  assert.equal(fresh.battery, '63%');
  assert.equal(fresh.charging, '충전 확인');
  assert.equal(fresh.safetyRelease, '관리자: 로봇 안전 상태 확인 후 명시적으로 해제');
  assert.equal(powerHealthView(robot({ charging_state: 'unconfirmed' }), 1000, 1000).charging,
    '충전 미확인');
  assert.equal(powerHealthView(robot({ evidence: 'stale' }), 1000, 1000).battery, '확인 불가');
  assert.equal(powerHealthView(robot({ sample_age_s: 4.9 }), 1000, 1200).charging, '확인 불가');
  assert.equal(powerHealthView(robot({ charging_evidence_age_s: 4.9 }), 1000, 1200).charging, '확인 불가');
  assert.equal(powerHealthView(robot(), 1000, 7000).charging, '확인 불가');
  assert.equal(powerHealthView({ ...robot(), online: false }, 1000, 1000).battery, '확인 불가');
  assert.equal(powerHealthView({ ...robot(), power_health_age_s: NaN }, 1000, 1000).charging,
    '확인 불가');
});

test('battery warning and docked-unconfirmed state give different next checks', () => {
  assert.match(powerHealthView(robot({ level: 'warning' }), 1000, 1000).problem, /충전·절전/);
  const docked = robot({ charging_state: 'unconfirmed' });
  docked.state.docking = { state: 'DOCKED' };
  assert.match(powerHealthView(docked, 1000, 1000).problem, /도크·전압/);
});
