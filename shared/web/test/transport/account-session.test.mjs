import test from 'node:test';
import assert from 'node:assert/strict';
import {accountKey, createAccountSession, UNREVOKED} from '../../account-session.js';

const signedIn = (family) => ({enabled: true, authenticated: true, account_id: 'alice', session_family: family, revision: 1});

function harness() {
  const stored = new Map(), state = {account: null, changed: 0, failed: 0};
  globalThis.localStorage = {setItem: (key, value) => stored.set(key, value)};
  const kit = createAccountSession({
    current: () => state.account, apply: value => { state.account = value; },
    changed: () => { state.changed++; }, failed: () => { state.failed++; },
  });
  return {kit, state, stored};
}

test('a read that finishes after invalidate never restores the old account', async () => {
  const {kit, state} = harness();
  let release;
  globalThis.fetch = async () => ({ok: true, json: () => new Promise(resolve => { release = resolve; })});
  const restoring = kit.restore();
  await new Promise(resolve => setImmediate(resolve));
  kit.invalidate();
  release(signedIn('one'));
  await restoring;
  assert.equal(state.account, null);
});

test('a new identity on this origin is marked and reported as a change', async () => {
  const {kit, state, stored} = harness();
  globalThis.fetch = async () => ({ok: true, json: async () => signedIn('one')});
  await kit.restore();
  assert.equal(stored.get('rosy.account.identity'), accountKey(signedIn('one')));
  assert.equal(state.changed, 0);
  globalThis.fetch = async () => ({ok: true, json: async () => signedIn('two')});
  await kit.restore();
  assert.equal(state.changed, 1);
  assert.equal(stored.get('rosy.account.identity'), 'alice:two:1');
});

test('a failed probe reports failure and keeps the last value', async () => {
  const {kit, state} = harness();
  globalThis.fetch = async () => ({ok: false});
  await kit.restore();
  assert.equal(state.failed, 1);
  assert.equal(state.account, null);
});

test('logout clears locally even when central revocation is pending', async () => {
  const {kit, stored} = harness();
  let reset = false;
  globalThis.fetch = async (path, init) => {
    assert.equal(path, '/api/account/logout');
    assert.equal(init.method, 'POST');
    return {ok: false};
  };
  await assert.rejects(kit.logout(() => { reset = true; }), new RegExp(UNREVOKED));
  assert.equal(reset, true);
  assert.equal(stored.get('rosy.account.identity'), '');
});

test('an ended session clears the marker so other tabs follow at once', async () => {
  const {kit, state, stored} = harness();
  globalThis.fetch = async () => ({ok: true, json: async () => signedIn('one')});
  await kit.restore();
  globalThis.fetch = async () => ({ok: true, json: async () => ({enabled: true, authenticated: false})});
  await kit.restore();
  assert.equal(stored.get('rosy.account.identity'), '');
  assert.equal(state.changed, 1);
});

test('a first sign-in is not reported as a change', async () => {
  const {kit, state} = harness();
  globalThis.fetch = async () => ({ok: true, json: async () => signedIn('one')});
  await kit.restore();
  assert.equal(state.changed, 0);
});
