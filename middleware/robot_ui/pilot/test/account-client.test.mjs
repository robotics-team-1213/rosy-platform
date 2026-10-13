import test from 'node:test';
import assert from 'node:assert/strict';
import * as client from '../client.js';

test('Account session restores without putting credentials into browser storage', async () => {
  const values = new Map();
  globalThis.sessionStorage = {getItem: key => values.get(key), setItem: (key,value) => values.set(key,value), removeItem:key=>values.delete(key)};
  globalThis.document = {documentElement:{dataset:{}}};
  globalThis.fetch = async () => ({ok:true,json:async()=>({enabled:true,authenticated:true,account_id:'one',capabilities:['robot.read']})});
  await client.restoreAccount();
  assert.equal(client.authenticated(), true);
  assert.equal(client.token(), '');
  assert.deepEqual(client.authHeaders(), {});
  assert.equal(values.size, 0);
  let release;
  globalThis.fetch = async () => ({ok:true,status:200,json:()=>new Promise(resolve=>{release=resolve;})});
  const pending = client.api('/api/v1/robot/state');
  await new Promise(resolve=>setImmediate(resolve));
  client.clearToken();
  release({private:'previous-account'});
  await assert.rejects(pending, /계정이 변경/);
});
