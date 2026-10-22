import test from 'node:test';
import assert from 'node:assert/strict';
import {createPageScope} from '../../../../shared/web/scope.js';
import {createEnrollmentPanel} from '../../../../applications/fleet/web/devices/enrollment.js';
import {createCameraPairingPanel} from '../../../../applications/fleet/web/devices/camera-pairing.js';

function node() {
  return {
    dataset: {}, listeners: {}, hidden: false, value: '', children: [],
    addEventListener(type, callback) { this.listeners[type] = callback; },
    removeEventListener(type) { delete this.listeners[type]; },
    setAttribute() {}, removeAttribute() {}, contains() { return false; },
    replaceChildren(...children) { this.children = children; },
    append(...children) { this.children.push(...children); },
    close() {},
  };
}

function panel(t, factory) {
  const originals = {document: globalThis.document, location: globalThis.location, fetch: globalThis.fetch};
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); };
  globalThis.document = {getElementById: get, createElement: node, activeElement: null};
  globalThis.location = {origin: 'https://fleet.example'};
  const scope = createPageScope({events: new EventTarget(), clock: {setInterval() {}, clearInterval() {}}});
  let token = 'first';
  const instance = factory({scope, headers: () => ({Authorization: `Bearer ${token}`, 'X-Rosy-Session': 'session'}),
    identity: () => ({role: 'operator', principal_id: 'named'}), locked: () => false,
    dialogs: {openLiveDialog() {}}});
  t.after(() => { scope.dispose(); Object.assign(globalThis, originals); });
  return {instance, scope, get, token: value => { token = value; }};
}

for (const factory of [createEnrollmentPanel, createCameraPairingPanel]) {
  test(`${factory.name}: common transport uses current credentials without replay`, async t => {
    const {instance, token} = panel(t, factory);
    const calls = [];
    globalThis.fetch = async (url, init) => {
      calls.push({url, init});
      return new Response(JSON.stringify({detail: {code: 'OPERATOR_IDENTITY_REQUIRED', reason: 'named'}}), {status: 403});
    };
    await instance.refresh();
    token('second'); instance.resetPolling();
    await instance.refresh();
    assert.equal(calls.length, 2);
    for (const [index, {url, init}] of calls.entries()) {
      assert.equal(new URL(url, location.origin).origin, 'https://fleet.example');
      assert.equal(new Headers(init.headers).get('Authorization'), `Bearer ${index ? 'second' : 'first'}`);
      assert.equal(new Headers(init.headers).get('X-Rosy-Session'), 'session');
      assert.equal(init.credentials, 'same-origin');
      assert.equal(init.redirect, 'error');
      assert.equal(init.cache, 'no-store');
    }
  });

  for (const status of [200, 204]) {
    test(`${factory.name}: empty ${status} preserves the existing null response`, async t => {
      const {instance} = panel(t, factory);
      globalThis.fetch = async () => new Response(null, {status});
      await instance.refresh();
    });
  }

  test(`${factory.name}: disposal during JSON parsing discards the response`, async t => {
    const {instance, scope, get} = panel(t, factory);
    let parsed, received;
    const waiting = new Promise(resolve => { received = resolve; });
    globalThis.fetch = async () => ({ok: true, status: 200, json: () => {
      received(); return new Promise(resolve => { parsed = resolve; });
    }});
    const reading = instance.refresh();
    await waiting;
    scope.dispose();
    get('enroll-controls').hidden = true;
    get('camera-link-controls').hidden = true;
    parsed({robots: [], requests: [], sources: [], credentials: []});
    await reading;
    assert.equal(get('enroll-controls').hidden, true);
    assert.equal(get('camera-link-controls').hidden, true);
  });
}

test('enrollment sends one POST and preserves server error detail', async t => {
  const {instance, get} = panel(t, createEnrollmentPanel);
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({url, init});
    return new Response(JSON.stringify({detail: {code: 'OPERATOR_IDENTITY_REQUIRED'}}), {status: 403});
  };
  instance.openMove('robot-one');
  get('enroll-code').value = '7KXMP3QA';
  await get('enroll-submit').listeners.click();
  assert.equal(calls.filter(({init}) => init.method === 'POST').length, 1);
  const post = calls.find(({init}) => init.method === 'POST');
  assert.deepEqual(JSON.parse(post.init.body), {code: '7KXMP3QA'});
  assert.equal(get('enroll-result').dataset.kind, 'bad');
  assert.match(get('enroll-result').children.map(child => child.textContent).join(' '), /운영자/);
});
