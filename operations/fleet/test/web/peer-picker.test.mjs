import test from 'node:test';
import assert from 'node:assert/strict';
import {peerOwnerAction, peerStateText, createPeerPicker} from '../../fleet/server/web/peer-picker.js';

const approved = {role: 'robot', peer_id: 'pinky / one', approval: 'approved',
  freshness: 'unavailable', readiness: 'unknown', hostname: 'untrusted.local', address: '192.168.1.9'};

test('selection uses existing owner identity, never an advertised endpoint', () => {
  assert.equal(peerOwnerAction(approved, {robots: ['pinky / one']}).href,
               '/console?robot=pinky%20%2F%20one');
  assert.equal(peerOwnerAction(approved, {robots: []}), null);
  assert.equal(peerOwnerAction({...approved, approval: 'unapproved'}, {robots: ['pinky / one']}), null);
  assert.equal(peerOwnerAction({...approved, freshness: 'conflict'}, {robots: ['pinky / one']}), null);
  assert.equal(peerOwnerAction({...approved, freshness: 'expired'}, {robots: ['pinky / one']}), null);
});

test('Cam routes only an existing approved Vision source; other roles do not invent owner actions', () => {
  assert.deepEqual(peerOwnerAction({...approved, role: 'cam', peer_id: 'north'}, {sources: ['north']}),
                   {source: 'north', label: '카메라 보기'});
  assert.equal(peerOwnerAction({...approved, role: 'cam', peer_id: 'north'}, {sources: []}), null);
  for (const role of ['fleet', 'overhead-camera', 'dock', 'signal', 'model-host', 'pilot']) {
    assert.equal(peerOwnerAction({...approved, role}, {robots: ['pinky / one']}), null);
  }
});

test('metadata does not claim connection or permission, and stale/conflict is explicit', () => {
  assert.equal(peerStateText(approved), '승인됨 · 상태 미확인');
  assert.equal(peerStateText({...approved, approval: 'unapproved'}), '승인 필요');
  assert.equal(peerStateText({...approved, freshness: 'expired'}), '검색 정보 만료');
  assert.equal(peerStateText({...approved, freshness: 'conflict'}), '장비 정보 충돌 · 확인 필요');
});

test('retry reason follows current work and stale epochs cannot clear a newer request', async t => {
  const previous = globalThis.document;
  t.after(() => { globalThis.document = previous; });
  const node = () => ({value: '', dataset: {}, attrs: new Map(),
    append() {}, replaceChildren() {},
    setAttribute(name, value) { this.attrs.set(name, value); },
    removeAttribute(name) { this.attrs.delete(name); }});
  globalThis.document = {createElement: node, activeElement: null};
  const elements = new Map();
  const el = name => {
    if (!elements.has(name)) elements.set(name, node());
    return elements.get(name);
  };
  let epoch = 0;
  const scope = {listen() {}, onDispose() {}, capture() {
    const captured = epoch;
    return {current: () => captured === epoch, check() {
      if (captured !== epoch) throw new DOMException('Stale view', 'AbortError');
    }};
  }};
  const reads = [];
  const picker = createPeerPicker({scope, el, isLocked: () => false, isActive: () => true,
    sources: () => [], onCamera() {}, call: url => new Promise((resolve, reject) => {
      reads.push({url, resolve, reject});
    })});
  const retry = el('peer-retry');
  const first = picker.refresh();
  assert.equal(retry.attrs.has('disabled'), true);
  assert.equal(retry.attrs.get('reason'), '장비 목록을 확인하는 동안 기다려 주세요.');
  await picker.refresh();
  assert.equal(reads.length, 2, 'pending refresh is coalesced');
  epoch++; picker.reset();
  assert.equal(retry.attrs.has('disabled'), false);
  assert.equal(retry.attrs.has('reason'), false);
  const current = picker.refresh();
  reads[0].resolve({peers: [], scanner_state: 'online'});
  reads[1].resolve({robots: []});
  await first;
  assert.equal(retry.attrs.has('disabled'), true, 'old finally cannot unlock current work');
  assert.equal(retry.attrs.has('reason'), true, 'old finally cannot remove current reason');
  reads[2].resolve({peers: [], scanner_state: 'online'});
  reads[3].resolve({robots: []});
  await current;
  assert.equal(retry.attrs.has('disabled'), false);
  assert.equal(retry.attrs.has('reason'), false);
  const failed = picker.refresh();
  reads[4].reject(Object.assign(new Error('Read failed'), {status: 503}));
  reads[5].resolve({robots: []});
  await failed;
  assert.equal(retry.attrs.has('disabled'), false);
  assert.equal(retry.attrs.has('reason'), false, 'current failure releases reason too');
});
