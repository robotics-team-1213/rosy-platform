import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
globalThis.crypto ??= webcrypto;
const { register } = await import('node:module');
register('./resolve-console-assets.mjs', import.meta.url);
const { createDialogue } = await import('../../../../operations/site_ui/console/assistant/panel.js');

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
