import test from 'node:test';
import assert from 'node:assert/strict';
import {peerOwnerAction, peerStateText} from '../../fleet/server/web/peer-picker.js';

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
