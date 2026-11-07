import {renderAccountApps, renderAccountProfile} from '/common/account-profile.js';
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
    const shown = current && !invalidated && !loggingOut && (!initialized || current === owner)
      ? {...session, authenticated:true} : null;
    renderAccountProfile(shown);
    // Most Learning pages have no profile link; the topbar still offers the other apps.
    if (!document.querySelector('[data-account-profile]')) renderAccountApps(shown, document.querySelector('ui-topbar [data-spacer]'));
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
// A failed save or action says what happened, that the screen was kept, and what to do next, never a raw fetch or HTML error.
const NO_SERVER = '서버에 연결하지 못했습니다. 방금 요청은 처리되지 않았고 화면의 내용은 그대로입니다. 네트워크를 확인한 뒤 다시 시도하세요.';
const SLOW_SERVER = '서버 응답이 너무 늦어 기다리지 못했습니다. 반영됐는지 확실하지 않고 화면의 내용은 그대로입니다. 다시 불러와 확인한 뒤 다시 시도하세요.';
async function reach(path, options) {
  try { return await fetch(path, options); }
  catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new Error(error?.name === 'TimeoutError' ? SLOW_SERVER : NO_SERVER);
  }
}
function plainFailure(response, body) {
  let known = false;
  if (response.status >= 500) { try { known = typeof JSON.parse(body)?.error === 'string'; } catch (_) { /* an HTML error page */ } }
  if (response.status < 500 || known) return new Response(body, {status:response.status, statusText:response.statusText, headers:response.headers});
  const text = `서버가 요청을 끝내지 못했습니다(HTTP ${response.status}). 화면의 내용은 그대로 남아 있습니다. 잠시 뒤 다시 시도하고, 반복되면 다시 불러와 반영 여부를 확인하세요.`;
  return new Response(JSON.stringify({error:text}), {status:response.status, headers:{'Content-Type':'application/json'}});
}
export async function accountFetch(path, options) {
  await initialize();
  if (invalidated) throw new Error('계정이 변경되었습니다.');
  if (path === '/api/accounts/logout') { loggingOut = true; renderAccountProfile(null); }
  const response = await reach(path, options);
  if (!managed) return response.status >= 500 ? plainFailure(response, await response.text()) : response;
  const body = await response.text();
  if (path === '/api/accounts/logout') {
    localStorage.setItem(key, ''); owner = '';
  } else if (await identity() !== owner || invalidated) {
    invalidate();
  }
  return plainFailure(response, body);
}
