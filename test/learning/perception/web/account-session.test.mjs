import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const COMMON_SESSION_URL = new URL('../../../../shared/web/account-session.js', import.meta.url).href;

async function loadLearningSession(tag) {
  const raw = await readFile(new URL('../../../../learning/curation/perception/review_app_web/account-session.js', import.meta.url), 'utf8');
  const source = raw
    .replace(
      "import {renderAccountApps, renderAccountProfile} from '/common/account-profile.js';",
      'const renderAccountApps = () => {}; const renderAccountProfile = session => globalThis.renderedProfile = session;'
    )
    .replace(
      "import {announceIdentity, watchIdentity} from '/common/account-session.js';",
      `import {announceIdentity, watchIdentity} from '${COMMON_SESSION_URL}';`
    );
  return import('data:text/javascript;base64,' + Buffer.from(`${source}\n// ${tag}`).toString('base64'));
}

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
    const {accountFetch} = await loadLearningSession('delay');
    const pending = accountFetch('/api/workspace');
    await new Promise(resolve=>setImmediate(resolve));
    account = 'account-b'; release();
    await assert.rejects(pending,/계정이 변경/);
    assert.equal(reloaded,true);
    assert.equal(document.body.hidden,true);
  } finally { globalThis.setInterval = interval; }
});

test('initial authority outage can retry without discarding drafts', async () => {
  let offline = true, reloads = 0;
  globalThis.document = {body:{hidden:false}};
  globalThis.location = {reload:()=>{reloads++;}};
  globalThis.localStorage = {setItem:()=>{}};
  globalThis.addEventListener = ()=>{};
  const interval = globalThis.setInterval;
  globalThis.setInterval = ()=>0;
  globalThis.fetch = async path => {
    if(path.endsWith('/options')) return Response.json({rosy_account:true});
    if(path.endsWith('/session')) return offline ? Response.json({}, {status:503}) : Response.json({account_session:'a'});
    return Response.json({ok:true});
  };
  try {
    const {accountFetch} = await loadLearningSession('retry');
    await assert.rejects(accountFetch('/api/workspace'),/계정 연결/);
    offline = false;
    assert.deepEqual(await (await accountFetch('/api/workspace')).json(), {ok:true});
    assert.equal(reloads,0);
    assert.equal(document.body.hidden,false);
  } finally { globalThis.setInterval = interval; }
});


test('profile follows the existing session poll and clears on outage and logout', async () => {
  let poll, offline = false, name = 'First';
  globalThis.document = {body:{hidden:false}};
  globalThis.location = {reload:()=>{}};
  globalThis.localStorage = {setItem:()=>{}};
  globalThis.addEventListener = ()=>{};
  const interval = globalThis.setInterval;
  globalThis.setInterval = fn=>{poll=fn;return 0;};
  globalThis.fetch = async path => {
    if(path.endsWith('/options')) return Response.json({rosy_account:true});
    if(path.endsWith('/session')) return offline ? Response.json({}, {status:503}) : Response.json({
      account_session:'session-a',account_id:'a',profile:{account_id:'a',display_name:name}});
    return Response.json({ok:true});
  };
  try {
    const {accountFetch} = await loadLearningSession('profile');
    await accountFetch('/api/workspace');
    assert.equal(renderedProfile.authenticated,true);
    assert.equal(renderedProfile.profile.display_name,'First');
    name='Updated';await poll();
    assert.equal(renderedProfile.profile.display_name,'Updated');
    offline=true;await poll();assert.equal(renderedProfile,null);
    offline=false;await poll();assert.equal(renderedProfile.profile.display_name,'Updated');
    await accountFetch('/api/accounts/logout',{method:'POST'});
    assert.equal(renderedProfile,null);
    await poll();assert.equal(renderedProfile,null);
  } finally { globalThis.setInterval=interval; }
});
