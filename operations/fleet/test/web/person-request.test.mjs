import test from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';

const gate = new URL('../../../../applications/fleet/web/shared/poll-gate.js', import.meta.url).href;
register('data:text/javascript,' + encodeURIComponent(
  `export async function resolve(s, c, next) { return s === '/console/assets/poll-gate.js' ? { url: '${gate}', shortCircuit: true } : next(s, c); }`));
const { personHeadline, personView, deliveryText, requestsFor, NO_MOTION_LINE } =
  await import('../../../../applications/fleet/web/person-request.js');

const ask = { id: 'a1', robot_id: 'rosy_46', kind: 'unplug_charger', text: '충전기를 뽑아 주세요',
  why: '주행을 시작해야 합니다', state: 'open', created_at: 2, delivery: { state: 'delivered', age_s: 1 } };

test('the queue sentence names the kind, what to do and why', () => {
  assert.equal(personHeadline(ask), ': 사람 부탁(충전기 분리) — 충전기를 뽑아 주세요 · 이유: 주행을 시작해야 합니다');
  assert.equal(personHeadline({ ...ask, why: '' }), ': 사람 부탁(충전기 분리) — 충전기를 뽑아 주세요');
});

test('the opened row always says an answer moves nothing', () => {
  const spec = personView(ask, { operator: true });
  assert.ok(spec.lines.includes(NO_MOTION_LINE));
  assert.match(NO_MOTION_LINE, /움직이거나 비상 정지를 풀지 않습니다/);
  assert.equal(spec.lock, '');
});

test('a viewer, a busy answer or an unnamed login locks the buttons with a reason', () => {
  assert.equal(personView(ask, { operator: false }).lock, '운영자 권한이 필요합니다');
  assert.equal(personView(ask, { operator: true, busy: true }).lock, '답을 보내는 중');
  assert.equal(personView(ask, { operator: true, named: '이름 있는 계정 필요' }).lock, '이름 있는 계정 필요');
});

test('shown means read back from the robot lately; an old or missing read-back is unknown, not shown', () => {
  assert.equal(deliveryText({ delivery: { state: 'delivered', age_s: 4.2 } }), '로봇 화면에도 표시 중 (4초 전 확인)');
  assert.match(deliveryText({ delivery: { state: 'delivered', age_s: 120 } }), /확인 불가/);
  assert.match(deliveryText({ delivery: { state: 'delivered' } }), /확인 불가/);
  assert.match(deliveryText({ delivery: { state: 'waiting', age_s: 1 } }), /아직 로봇 화면에 없음/);
  assert.match(deliveryText({ delivery: { state: 'not_delivered' } }), /전달하지 못함/);
  assert.match(deliveryText({ delivery: { state: 'not_sent' } }), /보내지 않음/);
  assert.match(deliveryText({}), /보내지 않음/);
});

test('only open requests of that robot are listed, oldest first', () => {
  const view = { personRequests: [{ ...ask, id: 'b', created_at: 5 }, ask, { ...ask, id: 'c', state: 'done' },
    { ...ask, id: 'd', robot_id: 'other' }] };
  assert.deepEqual(requestsFor(view, 'rosy_46').map((r) => r.id), ['a1', 'b']);
  assert.deepEqual(requestsFor({}, 'rosy_46'), []);
});
