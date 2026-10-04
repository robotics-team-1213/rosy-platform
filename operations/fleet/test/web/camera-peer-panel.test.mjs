import test from 'node:test';
import assert from 'node:assert/strict';
import { approvalBody, relationshipText } from '../../fleet/server/web/camera-peer.js';

test('approval requires named receiver owner, pending revision and selected source', () => {
  const row = {state:'pending',revision:2};
  assert.equal(approvalBody(row,'ceiling_north',true,{role:'viewer',principal_id:'named'}),null);
  assert.equal(approvalBody(row,'ceiling_north',true,{role:'operator'}),null);
  assert.equal(approvalBody({...row,state:'expired'},'ceiling_north',true,{role:'operator',principal_id:'named'}),null);
  assert.deepEqual(approvalBody(row,'ceiling_north',true,{role:'operator',principal_id:'named'}),
    {action:'approve',revision:2,source_id:'ceiling_north',persist_requested:true});
});

test('offline or short credential expiry does not claim relationship erased', () => {
  assert.match(relationshipText({state:'approved',persistent:true,authorization_available:true}),/기억/);
  assert.match(relationshipText({state:'approved',persistent:true,authorization_available:false}),/갱신할 수 없음/);
  assert.match(relationshipText({state:'revoked'}),/연결 해제/);
});
