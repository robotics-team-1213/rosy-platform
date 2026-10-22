import test from 'node:test';
import assert from 'node:assert/strict';
import {createPageScope} from '../../../../shared/web/scope.js';
import {createCameraPeerPanel} from '../../../../applications/fleet/web/installation/camera-peer.js';

function node(tag = '') {
  return {
    tagName: tag.toUpperCase(), children: [], listeners: {}, textContent: '', value: '', hidden: false,
    append(...children) {
      this.children.push(...children);
      if (this.tagName === 'SELECT' && !this.value) this.value = children[0]?.value || '';
    },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this[name] = value; },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    removeEventListener(type) { delete this.listeners[type]; },
  };
}

function setup(t) {
  const saved = {document: globalThis.document, location: globalThis.location, fetch: globalThis.fetch};
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, node()); return elements.get(id); };
  globalThis.document = {getElementById: get, createElement: node, visibilityState: 'visible',
    createTextNode: value => Object.assign(node('#text'), {textContent: value})};
  globalThis.location = {origin: 'https://fleet.example'};
  const scope = createPageScope({events: new EventTarget(), clock: {setInterval() {}, clearInterval() {}}});
  const calls = [];
  let token = 'first', locked = false, failStatus = 0, errorReads = 0, unauthorized = 0;
  let postResponse = () => new Response('{}');
  const pending = {request_id: 'request', state: 'pending', revision: 2, label: 'camera',
    display_code: 'ABCD', client_key_sha256: 'test-client-key'};
  globalThis.fetch = async (url, init = {}) => {
    calls.push({url, init});
    if (init.method === 'POST') return postResponse();
    if (failStatus) return {status: failStatus, ok: false,
      json: () => { errorReads++; return new Promise(resolve => setTimeout(() => resolve({}), 20)); }};
    const path = new URL(url, location.origin).pathname;
    const body = path.endsWith('/identity') ? {tls_ca_sha256: 'a'.repeat(64)}
      : path.endsWith('/relationships') ? []
      : path.includes('/v2/') ? [pending] : {paired_sources: [{source_id: 'ceiling', has_credential: false}]};
    return new Response(JSON.stringify(body));
  };
  const panel = createCameraPeerPanel({scope,
    headers: () => ({Authorization: `Bearer ${token}`, 'X-Trace': 'session'}),
    identity: () => ({role: 'operator', principal_id: 'named'}), locked: () => locked,
    dialogs: {confirmIrreversible: async () => true},
    onUnauthorized: () => { unauthorized++; locked = true; }});
  t.after(() => { scope.dispose(); Object.assign(globalThis, saved); });
  const descendants = element => [element, ...element.children.flatMap(descendants)];
  return {panel, scope, get, calls,
    fail: status => { failStatus = status; },
    token: value => { token = value; locked = false; },
    post: fn => { postResponse = fn; },
    approve: () => descendants(get('camera-peer-requests')).find(row => row.textContent === '연결 승인').listeners.click({}),
    errorReads: () => errorReads, unauthorized: () => unauthorized};
}

for (const status of [401, 403, 404]) {
  test(`camera peer denies ${status} before reading a delayed body and stops the same owner`, async t => {
    const env = setup(t);
    await env.panel.refresh();
    assert.equal(env.get('camera-peer-requests').children.length, 1);
    env.fail(status);
    await env.panel.refresh();
    assert.equal(env.get('camera-peer-requests').children.length, 0);
    assert.equal(env.errorReads(), 0);
    assert.equal(env.unauthorized() > 0, status === 401);
    const count = env.calls.length;
    await env.panel.refresh();
    assert.equal(env.calls.length, count);
    assert.equal(env.calls.filter(row => row.init.method === 'POST').length, 0);
  });
}

for (const [status, body] of [[200, 'not JSON'], [200, ''], [204, null]]) {
  test(`camera peer cannot report approval after invalid ${status}/${body}`, async t => {
    const env = setup(t);
    await env.panel.refresh();
    env.post(() => new Response(body, {status}));
    await env.approve();
    assert.equal(env.calls.filter(row => row.init.method === 'POST').length, 1);
    assert.doesNotMatch(env.get('camera-peer-status').textContent, /연결을 승인했습니다/);
  });
}

test('camera peer ignores approval body that completes after disposal', async t => {
  const env = setup(t);
  await env.panel.refresh();
  let finish, received;
  const reading = new Promise(resolve => { received = resolve; });
  env.post(() => ({status: 200, ok: true, json: () => {
    received(); return new Promise(resolve => { finish = resolve; });
  }}));
  const submitting = env.approve();
  await reading;
  env.scope.dispose();
  env.get('camera-peer-status').textContent = 'new page';
  finish({});
  await submitting;
  assert.equal(env.get('camera-peer-status').textContent, 'new page');
  assert.equal(env.calls.filter(row => row.init.method === 'POST').length, 1);
});

test('camera peer ignores a denied response whose headers arrive after disposal', async t => {
  const env = setup(t);
  await env.panel.refresh();
  const responses = [];
  globalThis.fetch = () => new Promise(resolve => { responses.push(resolve); });
  const refreshing = env.panel.refresh();
  assert.equal(responses.length, 3);
  env.scope.dispose();
  env.get('camera-peer-fingerprint').textContent = 'new device';
  const replacement = node('li');
  env.get('camera-peer-requests').append(replacement);
  for (const finish of responses) finish({status: 401, ok: false,
    json: () => { throw new Error('disposed response body must not be read'); }});
  await refreshing;
  assert.equal(env.unauthorized(), 0);
  assert.equal(env.get('camera-peer-fingerprint').textContent, 'new device');
  assert.deepEqual(env.get('camera-peer-requests').children, [replacement]);
});

test('camera peer sends current credentials through the scoped transport and approves once', async t => {
  const env = setup(t);
  await env.panel.refresh();
  env.token('second');
  await env.approve();
  const writes = env.calls.filter(row => row.init.method === 'POST');
  assert.equal(writes.length, 1);
  assert.deepEqual(JSON.parse(writes[0].init.body),
    {action: 'approve', revision: 2, source_id: 'ceiling', persist_requested: true});
  assert.equal(new Headers(writes[0].init.headers).get('Authorization'), 'Bearer second');
  for (const {url, init} of env.calls) {
    assert.equal(new URL(url, location.origin).origin, location.origin);
    assert.equal(new Headers(init.headers).get('X-Trace'), 'session');
    assert.equal(init.credentials, 'same-origin');
    assert.equal(init.redirect, 'error');
    assert.equal(init.cache, 'no-store');
  }
  assert.match(env.get('camera-peer-status').textContent, /연결을 승인했습니다/);
});
