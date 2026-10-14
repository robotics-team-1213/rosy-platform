import {renderAccountProfile} from '/common/account-profile.js';
// Fence responses and drafts when another tab replaces the browser identity.
let managed = false, owner = '', invalidated = false, ready, initialized = false, loggingOut = false;
const key = 'rosy.learning.identity';
function invalidate() {
  invalidated = true;
  renderAccountProfile(null);
  document.body.hidden = true;
  location.reload();
  throw new Error('계정이 변경되었습니다.');
}
async function identity() {
  try {
    const response = await fetch('/api/accounts/session', {cache:'no-store', signal:AbortSignal.timeout(5000)});
    if (response.status >= 500) throw new Error('계정 연결을 확인하세요.');
    const session = response.ok ? await response.json() : null;
    const current = session?.account_session || '';
    renderAccountProfile(current && !invalidated && !loggingOut && (!initialized || current === owner)
      ? {...session, authenticated:true} : null);
    return current;
  } catch (error) { renderAccountProfile(null); throw error; }
}
function initialize() {
  return ready ??= (async () => {
  const response = await fetch('/api/accounts/options', {cache:'no-store', signal:AbortSignal.timeout(5000)});
  if (!response.ok) throw new Error('계정 설정을 확인하세요.');
  managed = (await response.json()).rosy_account === true;
  if (managed) {
    owner = await identity();
    localStorage.setItem(key, owner);
  }
  initialized = true;
  })().catch(error => { ready = undefined; managed = false; throw error; });
}
addEventListener('storage', event => {
  if (initialized && managed && event.key === key && event.newValue !== owner) invalidate();
});
setInterval(async () => {
  if (!initialized || !managed || invalidated) return;
  try { if (await identity() !== owner) invalidate(); } catch (_) { /* Keep drafts during outages. */ }
}, 10000);
export async function accountFetch(path, options) {
  await initialize();
  if (invalidated) throw new Error('계정이 변경되었습니다.');
  if (path === '/api/accounts/logout') { loggingOut = true; renderAccountProfile(null); }
  const response = await fetch(path, options);
  if (!managed) return response;
  const body = await response.text();
  if (path === '/api/accounts/logout') {
    localStorage.setItem(key, ''); owner = '';
  } else if (await identity() !== owner || invalidated) {
    invalidate();
  }
  return new Response(body, {status:response.status, statusText:response.statusText, headers:response.headers});
}
