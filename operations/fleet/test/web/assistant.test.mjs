import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
globalThis.crypto ??= webcrypto;
const { register } = await import('node:module');
register('./resolve-console-assets.mjs', import.meta.url);
const { createDialogue } = await import('../../../../applications/fleet/web/assistant/panel.js');
const {
  KIND_META, buildNavigationPayload, controlRemainingS, formatNavigationError, isControlExpired,
} = await import('../../../../applications/fleet/web/assistant/assistant-command.js');

test('an account change discards old replies and creates a new conversation', () => {
  const state = createDialogue();
  state.setIdentity('alice');
  const first = state.begin('상태 알려줘', 'r1');
  state.setIdentity('bob');
  assert.equal(state.receive(first, {...first.message, state:'ANSWERED', response:'private'}), false);
  const second = state.begin('안녕');
  assert.notEqual(second.message.conversation_id, first.message.conversation_id);
  assert.equal(state.rows.length, 0);
});

test('a network retry reuses exactly the same intake, never a fresh execution key', () => {
  const state = createDialogue();
  state.setIdentity('alice');
  const ticket = state.begin('  상태\n알려줘  ', 'r1');
  state.failed(ticket);
  assert.deepEqual(state.retry().message, ticket.message);
  assert.equal(ticket.message.text, '  상태\n알려줘  ');
  assert.throws(() => state.begin('다른 요청'), /PENDING/);
});

test('out-of-order and foreign results cannot overwrite the current request', () => {
  const state = createDialogue();
  state.setIdentity('alice');
  const ticket = state.begin('안녕');
  assert.equal(state.receive(ticket, {...ticket.message, request_id:'foreign', state:'ANSWERED'}), false);
  assert.equal(state.receive(ticket, {...ticket.message, state:'PENDING'}), true);
  assert.equal(state.busy, true);
  assert.equal(state.receive(ticket, {...ticket.message, state:'UNKNOWN'}), true);
  assert.equal(state.busy, false);
  assert.equal(state.rows.length, 1);
});

test('signing out clears the draft request and prevents submission', () => {
  const state = createDialogue();
  state.setIdentity('alice');
  state.begin('안녕');
  state.setIdentity(null);
  assert.equal(state.rows.length, 0);
  assert.equal(state.retry(), null);
  assert.throws(() => state.begin('안녕'), /IDENTITY/);
});

test('dialogue preserves kind, selected_robot_id, and navState lifecycle', () => {
  const state = createDialogue();
  state.setIdentity('alice');
  const ticket = state.begin('r1을 충전소로 이동해줘', 'r1');
  assert.equal(state.receive(ticket, {
    ...ticket.message, state: 'ANSWERED', kind: 'CONTROL', response: '이동 명령 제안',
    created_at: 1000, completed_at: 1005,
  }), true);
  assert.equal(state.rows[0].kind, 'CONTROL');
  assert.equal(state.rows[0].selected_robot_id, 'r1');
  state.patchNav(ticket.message.request_id, { draft: { x: '1.5', y: '2.0', yaw: '0' } });
  assert.deepEqual(state.getNav(ticket.message.request_id).draft, { x: '1.5', y: '2.0', yaw: '0' });
  state.reset();
  assert.equal(state.getNav(ticket.message.request_id), null);
});

test('command handoff validates coordinates, expiry, kind labels, and errors', () => {
  assert.equal(KIND_META.CONTROL.label, '명령 제안');
  assert.deepEqual(buildNavigationPayload('r1', '1.5', '-2.25', '0.5'), { robot_id: 'r1', x: 1.5, y: -2.25, yaw: 0.5 });
  assert.equal(buildNavigationPayload('', '1', '2', '0'), null);
  assert.equal(buildNavigationPayload('r1', '', '2', '0'), null);
  assert.equal(buildNavigationPayload('r1', '100001', '2', '0'), null);
  assert.equal(buildNavigationPayload('r1', '1', '2', '4'), null);
  assert.equal(controlRemainingS({ completed_at: 1000 }, 1012), 18);
  assert.equal(controlRemainingS({ completed_at: 1010 }, 1000), 30);
  assert.equal(isControlExpired({ completed_at: 1010 }, 1000), false);
  assert.equal(isControlExpired({ completed_at: 1000 }, 1030), false);
  assert.equal(isControlExpired({ completed_at: 1000 }, 1031), true);
  assert.match(formatNavigationError({ status: 409 }), /30초/);
  assert.match(formatNavigationError({ status: 403 }), /권한/);
});
