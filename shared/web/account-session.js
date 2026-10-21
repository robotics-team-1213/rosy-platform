// D-757 browser half of a Rosy Account app: one session probe and one identity per origin.
// The server still authorizes every request; this keeps tabs and the profile link consistent.
const KEY = 'rosy.account.identity';
export const UNREVOKED = '이 앱에서 로그아웃했습니다. 전체 세션 회수는 연결 복구 후 완료됩니다.';

export function accountKey(account) {
  return account?.authenticated ? `${account.account_id}:${account.session_family}:${account.revision}` : '';
}

function publish(value) {
  globalThis.dispatchEvent?.(new CustomEvent('rosy:account-profile', {detail: value}));
}

function announce(key) {
  try { localStorage.setItem(KEY, key); } catch { /* storage may be unavailable; the poll still fences */ }
}

// current(): the app's account value. apply(value): store a fresh read and drop app-local
// credentials. changed(): another identity took this origin; clear and reload.
// failed(): optional, the probe could not confirm a session. poll: 0 leaves polling to the app.
export function createAccountSession({current, apply, changed, failed = () => {}, poll = 10000}) {
  let read = 0;
  async function restore() {
    const mine = ++read, previous = accountKey(current());
    try {
      const response = await fetch('/api/account/session', {cache: 'no-store', signal: AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error('Account unavailable');
      const value = await response.json();
      if (mine !== read) return current();
      apply(value);
      publish(value);
      const key = accountKey(value);
      if (key) announce(key);
      if (previous && previous !== key) changed();
    } catch {
      // A failed probe never opens a fallback login path.
      if (mine === read) { publish(null); failed(); }
    }
    return current();
  }
  // Drops reads still in flight, e.g. after a local logout.
  function invalidate() { read++; publish(null); }
  async function logout(reset, options = {}) {
    const response = await fetch('/api/account/logout', {method: 'POST', ...options});
    reset();
    announce('');
    if (!response.ok) throw new Error(UNREVOKED);
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('storage', event => {
      if (event.key === KEY && current()?.authenticated && event.newValue !== accountKey(current())) changed();
    });
    if (poll) window.setInterval(() => { if (current()?.enabled) restore(); }, poll);
  }
  return {restore, invalidate, logout};
}
