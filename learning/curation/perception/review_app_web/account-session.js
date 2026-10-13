// Fence responses and drafts when another tab replaces the browser identity.
let managed = false, owner = '', invalidated = false, ready, initialized = false;
const key = 'rosy.learning.identity';
function invalidate() {
  invalidated = true;
  document.body.hidden = true;
  location.reload();
  throw new Error('계정이 변경되었습니다.');
}
async function identity() {
  const response = await fetch('/api/accounts/session', {cache:'no-store', signal:AbortSignal.timeout(5000)});
  if (response.status >= 500) throw new Error('계정 연결을 확인하세요.');
  if (!response.ok) return '';
  return (await response.json()).account_session || '';
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
