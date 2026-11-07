import test from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

// The browser's /console/assets/poll-gate.js is shared/poll-gate.js on disk.
const gate = new URL('../../../../applications/fleet/web/shared/poll-gate.js', import.meta.url).href;
register('data:text/javascript,' + encodeURIComponent(
  `export async function resolve(s, c, next) { return s === '/console/assets/poll-gate.js' ? { url: '${gate}', shortCircuit: true } : next(s, c); }`));
const { recoveryHeadline, recoveryReason, recoveryView, NO_MOTION } =
  await import('../../../../applications/fleet/web/station-recovery.js');

const ok = { robot_id: 'r1', request: true, bay: 'C1', reason: null, percent: 17.6, bays_unknown: 0 };

test('an actionable request names the bay and offers the approve button, with the no-motion line', () => {
  assert.equal(recoveryHeadline(ok), ': 스테이션 복구 요청 (배터리 18%) — 충전 칸 C1 후보 · 승인은 기록만, 아직 아무것도 움직이지 않음');
  assert.doesNotMatch(recoveryHeadline(ok), /보낼 수/);
  const spec = recoveryView(ok, { operator: true });
  assert.equal(spec.approve, true);
  assert.equal(spec.approveReason, '');
  assert.ok(spec.lines.includes(NO_MOTION));
});

test('a refused request shows its reason as a sentence and no approve button', () => {
  for (const reason of ['no_station', 'no_free_bay', 'position_unknown', 'already_stopped', 'busy', 'another_returning', 'state_unknown']) {
    const spec = recoveryView({ ...ok, bay: null, reason }, { operator: true });
    assert.equal(spec.approve, false, reason);
    assert.match(recoveryHeadline({ ...ok, bay: null, reason }), /스테이션 복구 요청/);
    assert.notEqual(recoveryReason({ ...ok, bay: null, reason }), '');
  }
  assert.match(recoveryReason({ ...ok, bay: null, reason: 'already_stopped' }), /정지를 풀지 않습니다/);
});

test('unknown stays unknown: unknown bays and unknown evidence read 확인 불가, and unknown codes are shown as given', () => {
  assert.equal(recoveryReason({ reason: 'no_free_bay', bays_unknown: 2 }), '빈 충전 칸 확인 불가');
  assert.match(recoveryReason({ reason: 'battery_evidence_missing' }), /확인 불가/);
  assert.match(recoveryReason({ reason: 'new_code' }), /확인 불가 \(new_code\)/);
});

test('unknown battery evidence is not a request row at all', () => {
  assert.equal(recoveryHeadline({ robot_id: 'r1', request: false, reason: 'battery_evidence_missing' }), '');
  assert.equal(recoveryHeadline(undefined), '');
});

test('a viewer or a busy answer locks the button with a reason instead of hiding it', () => {
  assert.equal(recoveryView(ok, { operator: false }).approveReason, '운영자 권한이 필요합니다');
  assert.equal(recoveryView(ok, { operator: true, busy: true }).approveReason, '답을 보내는 중');
  assert.equal(recoveryView(ok, { operator: true, named: '이름 있는 계정 필요' }).approveReason, '이름 있는 계정 필요');
});
