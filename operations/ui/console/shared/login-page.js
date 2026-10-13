import {createPasswordLogin} from '/console/assets/password-login.js';
import {loginReturn} from '/console/assets/login-return.js';

const query = new URLSearchParams(location.search);
const back = loginReturn(query.get('return'), location.origin);
document.getElementById('login-back').href = back;
if (query.get('draft') === '1') document.getElementById('login-context').textContent =
  '편집 중이던 탭의 초안은 그대로 남습니다. 로그인 뒤 원래 탭으로 돌아가 현재 상태를 다시 조회하세요.';
const login = createPasswordLogin(document.getElementById('password-login'), {
  standalone: true, onChange: authenticated => { if (authenticated) location.assign(back); },
});
login.refresh(true);
