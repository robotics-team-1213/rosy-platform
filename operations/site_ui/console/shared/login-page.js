import {createPasswordLogin} from '/console/assets/password-login.js';
import {loginReturn} from '/console/assets/login-return.js';

const query = new URLSearchParams(location.search);
const back = loginReturn(query.get('return'), location.origin);
const failures = new Map([
  ['access_denied', ['forbidden', '현재 로그인 상태 또는 프로젝트 권한을 확인해야 합니다. 내 계정에서 권한을 확인하고, 필요한 권한은 관리자에게 요청하세요. 다른 계정으로도 로그인할 수 있습니다.']],
  ['invalid_request', ['error', '로그인 요청을 확인할 수 없습니다. 원래 앱에서 로그인을 다시 시작하세요.']],
  ['service_unavailable', ['unavailable', '로그인 서비스에 연결할 수 없습니다. 잠시 후 접근을 다시 확인하세요.']],
]);
const failure = failures.get(query.get('error'));
if (back.startsWith('/api/fleet/auth/authorize?')) {
  document.title = 'Rosy Account — 로그인';
  document.getElementById('login-title').textContent = 'Rosy Account 로그인';
}
if (failure) {
  document.getElementById('login-recovery').hidden = false;
  const status = document.getElementById('login-recovery-status');
  status.setAttribute('state', failure[0]); status.textContent = failure[1];
  document.getElementById('login-profile').href = '/console/profile?return=' + encodeURIComponent(back);
  document.getElementById('login-retry').href = back;
}
document.getElementById('login-back').href = back;
document.getElementById('login-back').hidden = !!failure;
if (query.get('draft') === '1') document.getElementById('login-context').textContent =
  '편집 중이던 탭의 초안은 그대로 남습니다. 로그인 뒤 원래 탭으로 돌아가 현재 상태를 다시 조회하세요.';
const login = createPasswordLogin(document.getElementById('password-login'), {
  standalone: true, autoContinue: !failure,
  onChange: authenticated => { if (authenticated) location.assign(back); },
});
if (failure) document.querySelector('[data-login=submit]').textContent = '다른 계정으로 로그인';
login.refresh(true);
