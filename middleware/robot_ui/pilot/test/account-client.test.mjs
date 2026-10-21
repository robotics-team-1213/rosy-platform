import test from 'node:test';
import assert from 'node:assert/strict';
import {register} from 'node:module';

// Node cannot resolve the browser's absolute /common/ imports; map them to shared/web.
const shared = new URL('../../../../shared/web/', import.meta.url).href;
register('data:text/javascript,' + encodeURIComponent(`export async function resolve(specifier, context, next) {
  return next(specifier.startsWith('/common/') ? new URL(specifier.slice(8), ${JSON.stringify(shared)}).href : specifier, context);
}`));
const client = await import('../client.js');

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

  // A delayed session/profile read must not restore an account after local logout.
  let finishSession;
  globalThis.fetch = async () => ({ok:true,json:()=>new Promise(resolve=>{finishSession=resolve;})});
  const restoring = client.restoreAccount();
  await new Promise(resolve=>setImmediate(resolve));
  client.clearToken();
  finishSession({enabled:true,authenticated:true,account_id:'one',profile:{display_name:'old'}});
  await restoring;
  assert.equal(client.account, null);
  assert.equal(client.authenticated(), false);
});
