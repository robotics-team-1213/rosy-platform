import {createPageScope} from '../../../../shared/web/scope.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import { decisionBody, suggestionText, createUsbCameraPanel } from '../../../../applications/fleet/web/installation/usb-camera.js';

test('a decision carries only a valid role name, trimmed', () => {
  assert.deepEqual(decisionBody(' arm_b_wrist '), {role: 'arm_b_wrist'});
  for (const bad of ['', '1top', 'a b', '../x', 'x'.repeat(65), null, 7]) assert.equal(decisionBody(bad), null);
});

test('the suggestion says where it came from', () => {
  assert.equal(suggestionText({suggest: null, roles: ['a']}), '');
  assert.match(suggestionText({suggest: 'arm_a_wrist', hub_arm: 'arm_a', roles: []}), /같은 USB 허브의 팔/);
  assert.match(suggestionText({suggest: 'top', hub_arm: null, roles: ['top']}), /같은 모델이 빠진 역할/);
});

function node(tag = '') {
  return {tagName: tag.toUpperCase(), children: [], listeners: {}, textContent: '', value: '', hidden: true,
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this[name] = value; },
    addEventListener(type, callback) { this.listeners[type] = callback; }};
}

function setup(t, headers = {}) {
  const saved = {document: globalThis.document, location: globalThis.location, fetch: globalThis.fetch};
  const elements = new Map();
  const get = id => {if (!elements.has(id)) elements.set(id, node()); return elements.get(id);};
  globalThis.document = {getElementById: get, createElement: node, visibilityState: 'visible'};
  globalThis.location = {origin: 'https://fleet.example'};
  const scope = createPageScope({events: new EventTarget(), clock: {setInterval() {}, clearInterval() {}}});
  let principal = {role: 'operator', principal_id: 'named-human'}, locked = false;
  const calls = [];
  const candidate = {key: 'a'.repeat(32), usb_id: '0c45:6366', roles: ['top'], suggest: 'top', hub_arm: null};
  globalThis.fetch = async (url, init) => {
    calls.push({url, init});
    return new Response(JSON.stringify(init.method === 'POST' ? {key: candidate.key, role: 'top'}
      : {workcells: [{workcell_id: 'one', roles: ['top'], candidates: [candidate]}]}));
  };
  const panel = createUsbCameraPanel({scope, headers: () => headers, identity: () => principal,
    locked: () => locked, dialogs: {confirmIrreversible: async () => true}});
  t.after(() => {scope.dispose(); Object.assign(globalThis, saved);});
  const descendants = element => [element, ...element.children.flatMap(descendants)];
  return {panel, calls, get,
    identity: value => {principal = value;}, lock: () => {locked = true;},
    approve: () => descendants(get('usb-camera-list')).find(row => row.tagName === 'UI-BUTTON').listeners.click({})};
}

for (const headers of [{}, {Authorization: 'Bearer fixture-current'}]) {
  test(`named operator lists and approves with ${headers.Authorization ? 'Bearer' : 'cookie'} transport`, async t => {
    const env = setup(t, headers);
    await env.panel.refresh();
    assert.equal(env.get('usb-camera-panel').hidden, false);
    await env.approve();
    const writes = env.calls.filter(row => row.init.method === 'POST');
    assert.equal(writes.length, 1);
    assert.equal(new URL(writes[0].url).pathname,
      '/api/fleet/workcell-observations/one/usb-devices/' + 'a'.repeat(32) + '/decision');
    assert.deepEqual(JSON.parse(writes[0].init.body), {role: 'top'});
    for (const {url, init} of env.calls) {
      assert.equal(new URL(url).origin, location.origin);
      assert.equal(new Headers(init.headers).get('Authorization'), headers.Authorization || null);
      assert.equal(init.credentials, 'same-origin');
      assert.equal(init.redirect, 'error');
      assert.equal(init.cache, 'no-store');
    }
  });
}

for (const principal of [null, {role: 'viewer', principal_id: 'named-human'},
  {role: 'operator'}, {role: 'operator', principal_id: '   '}]) {
  test(`unverified or non-operator identity cannot expose USB approval: ${JSON.stringify(principal)}`, async t => {
    const env = setup(t, {Authorization: 'Bearer fixture-current'});
    env.identity(principal);
    await env.panel.refresh();
    assert.equal(env.get('usb-camera-panel').hidden, true);
    assert.equal(env.calls.length, 0);
  });
}

for (const change of [env => env.identity({role: 'viewer', principal_id: 'named-human'}), env => env.lock()]) {
  test('a previously rendered approval cannot submit after authority is lost', async t => {
    const env = setup(t);
    await env.panel.refresh();
    assert.equal(env.get('usb-camera-panel').hidden, false);
    change(env);
    await env.approve();
    assert.equal(env.calls.filter(row => row.init.method === 'POST').length, 0);
    await env.panel.refresh();
    assert.equal(env.get('usb-camera-panel').hidden, true);
  });
}
