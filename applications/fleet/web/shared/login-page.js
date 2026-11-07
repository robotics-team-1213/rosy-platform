import {createPasswordLogin} from '/console/assets/password-login.js';
import {loginReturn} from '/console/assets/login-return.js';

const query = new URLSearchParams(location.search);
const back = loginReturn(query.get('return'), location.origin);
document.getElementById('login-site').textContent = `접속 서버: ${location.host}`;
const failures = new Map([
  ['access_denied', ['forbidden', '현재 로그인 상태 또는 프로젝트 권한을 확인해야 합니다. 내 계정에서 권한을 확인하고, 필요한 권한은 관리자에게 요청하세요. 다른 계정으로도 로그인할 수 있습니다.']],
  ['invalid_request', ['error', '로그인 요청을 확인할 수 없습니다. 원래 앱에서 로그인을 다시 시작하세요.']],
  ['service_unavailable', ['unavailable', '로그인 서비스에 연결할 수 없습니다. 잠시 후 접근을 다시 확인하세요.']],
]);
const failure = failures.get(query.get('error'));
const central = back.startsWith('/api/fleet/auth/authorize?');
const account = central || document.documentElement.dataset.app === 'account';
if (account) {
  document.title = 'Rosy Account — 로그인';
  document.getElementById('login-title').textContent = 'Rosy Account 로그인';
  document.querySelector('ui-brand b').textContent = 'Rosy Account';
  document.querySelector('ui-brand small').textContent = '공용 계정';
  const home = document.querySelector('ui-brand a');
  if (central) home.href = location.href;
  home.setAttribute('aria-label', 'Rosy Account 로그인');
  document.querySelector('link[rel="icon"]').href = '/common/brand/mark.svg';
  document.getElementById('login-intro').textContent = central
    ? 'Rosy Account로 로그인해 원래 앱의 작업을 이어가세요.'
    : 'Rosy Account로 로그인해 내 계정과 권한을 확인하세요.';
  document.getElementById('login-support').textContent = '계정이 없거나 비밀번호를 잊었다면 계정 관리자에게 문의하세요.';
}
if (failure) {
  document.getElementById('login-recovery').hidden = false;
  const status = document.getElementById('login-recovery-status');
  status.setAttribute('state', failure[0]); status.textContent = failure[1];
  document.getElementById('login-profile').href = '/console/profile?return=' + encodeURIComponent(back);
  document.getElementById('login-retry').href = back;
}
document.getElementById('login-back').href = back;
document.getElementById('login-back').hidden = account || !!failure;
if (query.get('draft') === '1') {
  document.getElementById('login-context').hidden = false;
  document.getElementById('login-context').textContent =
    '편집 중이던 탭의 초안은 그대로 남습니다. 로그인 뒤 원래 탭으로 돌아가 현재 상태를 다시 조회하세요.';
}
const login = createPasswordLogin(document.getElementById('password-login'), {
  standalone: true, autoContinue: !failure,
  onChange: authenticated => { if (authenticated) location.assign(back); },
});
if (account) document.querySelector('[data-login=form]').setAttribute('aria-label', 'Rosy Account 로그인');
if (failure) document.querySelector('[data-login=submit]').textContent = '다른 계정으로 로그인';
login.refresh(true);

// D-993: a person without an account, or without a grant for the app they opened, asks the administrator.
if (account) {
  const $ = id => document.getElementById(id);
  const resource = central ? new URLSearchParams(back.split('?')[1]).get('scope') || '' : '';
  let signedIn = null;
  const open = async () => {
    $('access-request').hidden = false; $('access-request-open').hidden = true;
    try {
      const response = await fetch('/api/fleet/auth/session', {credentials: 'same-origin'});
      const session = response.ok ? await response.json() : null;
      signedIn = session?.account_id && !session.password_change_required ? session : null;
    } catch { signedIn = null; }
    $('access-request-person').hidden = !!signedIn;
    for (const id of ['access-request-name', 'access-request-username']) $(id).required = !signedIn;
    $('access-request-intro').textContent = signedIn
      ? `${signedIn.principal_id} 계정으로 이 앱을 쓸 수 있게 관리자에게 요청합니다. 관리자가 승인해야 권한이 생깁니다.`
      : '이름과 희망 로그인 ID를 보내면 관리자가 확인합니다. 승인되면 관리자가 알려 주는 임시 비밀번호로 로그인하고 첫 로그인에서 바꿉니다.';
    $('access-request-resource').hidden = !resource;
    $('access-request-resource').textContent = `요청 대상: ${resource}`;
    $('access-request-send').scrollIntoView?.({block: 'nearest'});
  };
  $('access-request-open').hidden = false;
  $('access-request-open').addEventListener('click', open);
  if (failure && query.get('error') === 'access_denied') {
    $('access-request-denied').hidden = false; $('access-request-denied').addEventListener('click', open);
  }
  const say = (text, state) => {
    $('access-request-status').hidden = false; $('access-request-status').textContent = text;
    $('access-request-status').setAttribute('state', state);
  };
  $('access-request-send').addEventListener('click', async () => {
    const form = $('access-request-form'), send = $('access-request-send');
    if (!form.reportValidity()) return;
    const body = {note: $('access-request-note').value, resource};
    if (!signedIn) Object.assign(body, {name: $('access-request-name').value, username: $('access-request-username').value});
    send.disabled = true; send.setAttribute('reason', '요청을 보내는 중');
    try {
      const response = await fetch('/api/fleet/auth/access-requests', {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      if (response.status === 202) {
        form.hidden = true;
        say('요청을 보냈습니다. 관리자가 처리하면 로그인하거나 앱에 다시 접근할 수 있습니다.', 'ready');
      } else say(response.status === 422 ? '입력값을 확인하세요.' : response.status === 429
        ? '요청이 많아 지금은 받을 수 없습니다. 나중에 다시 보내거나 관리자에게 직접 문의하세요.'
        : '요청을 보내지 못했습니다. 잠시 후 다시 시도하세요.', 'warning');
    } catch { say('요청을 보내지 못했습니다. 연결을 확인하세요.', 'warning'); }
    finally { send.disabled = false; send.removeAttribute('reason'); }
  });
  $('access-request-form').addEventListener('submit', event => { event.preventDefault(); $('access-request-send').click(); });
}
