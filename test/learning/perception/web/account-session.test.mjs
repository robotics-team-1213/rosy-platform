import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('learning session rejects delayed old-account data and hides old drafts', async () => {
  let account = 'account-a', release, reloaded = false;
  const listeners = {};
  globalThis.document = {body:{hidden:false}};
  globalThis.location = {reload:()=>{reloaded=true;}};
  globalThis.localStorage = {setItem:()=>{}};
  globalThis.addEventListener = (name, fn)=>{listeners[name]=fn;};
  const interval = globalThis.setInterval;
  globalThis.setInterval = ()=>0;
  globalThis.fetch = async path => {
    if(path.endsWith('/options')) return Response.json({rosy_account:true});
    if(path.endsWith('/session')) return Response.json({account_session:account});
    return new Promise(resolve=>{release=()=>resolve(Response.json({private:'old-account'}));});
  };
  try {
    const source = await readFile(new URL('../../../../learning/curation/perception/review_app_web/account-session.js',import.meta.url),'utf8');
    const {accountFetch} = await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
    const pending = accountFetch('/api/workspace');
    await new Promise(resolve=>setImmediate(resolve));
    account = 'account-b'; release();
    await assert.rejects(pending,/계정이 변경/);
    assert.equal(reloaded,true);
    assert.equal(document.body.hidden,true);
  } finally { globalThis.setInterval = interval; }
});
