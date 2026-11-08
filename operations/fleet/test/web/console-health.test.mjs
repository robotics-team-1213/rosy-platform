import test from 'node:test';
import assert from 'node:assert/strict';
import { powerHealthView } from '../../../../applications/fleet/web/power-health-view.js';

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
  assert.equal(fresh.safetyRelease, '로봇 안전 확인 후: 로봇 등록 목록 → 비상정지 해제… → 그 로봇 정지 화면의 Release code');
  assert.equal(powerHealthView(robot({ charging_state: 'unconfirmed' }), 1000, 1000).charging,
    '충전 미확인');
  const held = powerHealthView(robot({ shown_percent: 72.2, percent: 100 }), 1000, 1000);
  assert.equal(held.battery, '72%');
  assert.equal(held.charging, '충전 확인 · 72%');
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

test('a missing or late Fleet read is unknown without an attention problem; robot evidence is', () => {
  const noRead = powerHealthView({ ...robot(), power_health: null, power_health_age_s: null }, 1000, 1000);
  assert.equal(noRead.battery, '확인 불가');
  assert.equal(noRead.problem, '');
  assert.equal(powerHealthView(robot(), 1000, 7000).problem, '');
  assert.equal(powerHealthView(robot({ sample_age_s: 4.9 }), 1000, 1200).problem, '');
  const missing = powerHealthView(robot({ evidence: 'missing' }), 1000, 1000);
  assert.equal(missing.problem, '배터리 값 없음 — 배터리 센서 서비스 확인');
  assert.equal(missing.note, '');
  // A frozen value is told apart from none; the age is in the note, not the grouped problem text.
  const frozen = powerHealthView(robot({ evidence: 'stale', sample_age_s: 48960 }), 1000, 1000);
  assert.equal(frozen.problem, '배터리 값 멈춤 — 센서 연결 확인');
  assert.equal(frozen.note, '값 멈춤 (13.6시간 전)');
  assert.equal(frozen.battery, '확인 불가');
  assert.equal(powerHealthView(robot({ evidence: 'stale', sample_age_s: 48000 }), 1000, 1000).problem, frozen.problem);
});
