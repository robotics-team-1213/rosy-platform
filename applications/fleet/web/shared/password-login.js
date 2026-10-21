// D-683: pages own authority and drafts; this component owns cookie login and verified logout.
import {actionIcon} from '/common/ui.js';
import {createFleetClient} from '/common/fleet-client.js';
import {loginHref, loginReturn} from '/console/assets/login-return.js';
import {canViewAccountSetup} from '/console/assets/account-permissions.js';

const cookieRequest = createFleetClient();
const sessionRequest = createFleetClient({credential: () => document.getElementById('console-token')?.value
  ?? sessionStorage.getItem('rosy-console-token') ?? ''});
const FORM = `
  <form class="password-login-form ui-form" data-login="form" aria-label="관제 로그인">
    <label class="ui-field-label" for="fleet-login-name">아이디
    <input id="fleet-login-name" class="ui-field password-login-field" data-login="login" autocomplete="username"
           autocapitalize="none" spellcheck="false" required></label>
    <label class="ui-field-label" for="fleet-login-password">비밀번호
    <input id="fleet-login-password" class="ui-field password-login-field" data-login="password" type="password"
           autocomplete="current-password" required></label>
    <label class="ui-check password-login-remember"><input class="ui-field" type="checkbox" data-login="remember"> 이 브라우저 기억(30일)</label>
    <ui-button kind="primary" type="button" data-login="submit">로그인</ui-button>
    <ui-status state="error" data-login="error" role="alert" hidden></ui-status>
  </form>`;
const WHO = `<div class="password-login-who" data-login="who">
  <span data-login="principal"></span>
  <ui-button kind="quiet" type="button" data-login="logout" data-action-icon="logout">로그아웃</ui-button>
  <ui-status state="error" data-login="error" role="alert" hidden></ui-status>
</div>`;
const CHANGE = `
  <form class="password-login-form ui-form" data-login="form" aria-label="첫 로그인 비밀번호 변경">
    <p>첫 로그인입니다. 새 비밀번호를 설정해야 현장 업무를 사용할 수 있습니다.</p>
    <label class="ui-field-label" for="fleet-new-password">새 비밀번호 · 8자 이상, 아이디와 다르게
    <input id="fleet-new-password" class="ui-field password-login-field" data-login="password" type="password"
           autocomplete="new-password" minlength="8" maxlength="1024" required></label>
    <label class="ui-field-label" for="fleet-confirm-password">새 비밀번호 확인
    <input id="fleet-confirm-password" class="ui-field password-login-field" data-login="confirm" type="password"
           autocomplete="new-password" minlength="8" maxlength="1024" required></label>
    <ui-button kind="primary" type="button" data-login="submit">비밀번호 변경</ui-button>
    <ui-status state="error" data-login="error" role="alert" hidden></ui-status>
  </form>`;

function failureText(error) {
  if (error?.status === 401) return '아이디 또는 비밀번호가 맞지 않습니다.';
  if (error?.status === 429) return '실패가 많아 잠시 막혔습니다. 1분 뒤 다시 시도하세요.';
  return '로그인 결과를 확인할 수 없습니다. 관제 PC 연결을 확인한 뒤 다시 확인하세요.';
}

export function createPasswordLogin(host, {onChange = () => {}, standalone = false} = {}) {
  host.innerHTML = standalone ? FORM : WHO;
  const part = name => host.querySelector(`[data-login="${name}"]`);
  let busy = false, cookie = false, cookiePrincipal = null, cookieRole = null, changing = false;
  const link = document.getElementById('fleet-login');
  const profile = document.getElementById('fleet-profile');
  const accounts = profile ? document.createElement('a') : null;
  if (accounts) {
    accounts.id = 'fleet-accounts'; accounts.href = '/console/accounts';
    accounts.textContent = '계정 관리'; accounts.hidden = true; profile.after(accounts);
  }
  if (profile) {
    profile.href = '/console/profile?return=' + encodeURIComponent(loginReturn(location.href, location.origin));
    if (['/console/site-map', '/console/cell'].includes(location.pathname)) {
      profile.target = '_blank'; profile.rel = 'noopener'; profile.title = '새 탭에서 내 계정 · 편집 내용 보존';
    }
  }
  if (link) link.href = loginHref(location);
  if (link && ['/console/site-map', '/console/cell'].includes(location.pathname)) {
    link.target = '_blank'; link.rel = 'noopener'; link.href += '&draft=1';
    link.title = '새 탭에서 로그인 · 이 탭의 편집 내용 보존';
  }
  const errorText = message => {
    part('error').textContent = message;
    part('error').hidden = !message;
  };
  const paintLoginWords = text => {
    if (!link) return;
    link.textContent = text;
    const icon = link.getAttribute('data-action-icon');
    if (icon) actionIcon(link, icon);
  };
  const paintLogout = button => {
    button.textContent = cookie ? '로그아웃' : '이 탭 접속 해제';
    actionIcon(button, 'logout');
  };
  function verified(session) {
    if (session.via !== 'cookie' || !session.principal_id || !session.role) throw new Error('Session not verified');
    if (session.password_change_required === true) {
      if (!changing) {
        changing = true; host.innerHTML = CHANGE; bindForm(); part('password').focus();
      }
      return false;
    }
    if (session.account_id) {
      try { localStorage.setItem('rosy.fleet.account.identity', `${session.account_id}:${session.session_family}:${session.revision}`); } catch {}
    }
    onChange(true);
    return true;
  }

  async function refresh(locked = true) {
    try {
      if (!standalone && locked) {
        try {
          const connection = await cookieRequest('/api/fleet/auth/connection');
          if (connection.mode === 'paired' && !connection.password_login && !link?.hidden) {
            const token = document.getElementById('token-access');
            if (token) token.open = true;
          }
        } catch { /* Older sites retain the explicitly available advanced connection controls. */ }
      }
      if (standalone) {
        const connection = await cookieRequest('/api/fleet/auth/connection');
        const offered = connection.mode !== 'development' && connection.password_login === true;
        host.hidden = !offered;
        const availability = document.getElementById('login-availability');
        availability.hidden = offered;
        availability.setAttribute('state', 'unavailable');
        availability.textContent = connection.mode === 'development'
          ? '현재 현장은 개발 연결 모드입니다. 원래 업무 화면에서 개발 접속 상태를 확인하세요.'
          : '이 현장에는 사람 로그인이 설정되지 않았습니다. 현장 관리자에게 계정 설정을 요청하세요.';
        if (!offered) return false;
      }
      const session = await (standalone ? cookieRequest : sessionRequest)('/api/fleet/auth/session');
      cookie = session.via === 'cookie';
      cookiePrincipal = cookie ? session.principal_id : null;
      cookieRole = cookie ? session.role : null;
      if (profile) profile.hidden = !cookie || session.password_change_required === true;
      if (accounts) accounts.hidden = !canViewAccountSetup(session);
      if (standalone) {
        if (cookie) return verified(session);
      } else {
        if (cookie && session.password_change_required === true) {
          cookie = false; host.hidden = true;
          paintLoginWords('비밀번호 변경');
          return false;
        }
        paintLoginWords('로그인');
        host.hidden = false;
        part('principal').textContent = '';
        paintLogout(part('logout'));
        part('logout').title = cookie ? '이 브라우저의 현장 로그인 종료' : '서버 토큰은 폐기하지 않습니다';
        part('logout').disabled = false;
        part('logout').removeAttribute('reason');
      }
      return cookie;
    } catch (error) {
      if (error?.status === 401 || error?.status === 404) {
        cookie = false; cookiePrincipal = cookieRole = null;
        if (profile) profile.hidden = true;
        if (accounts) accounts.hidden = true;
        if (standalone && changing) {
          changing = false; host.innerHTML = FORM; bindForm(); part('login').focus();
          errorText('로그인이 만료됐습니다. 다시 로그인해 비밀번호 변경 상태를 확인하세요.');
        }
        if (!standalone) host.hidden = true;
      } else if (standalone) {
        host.hidden = false;
        document.getElementById('login-availability').hidden = true;
        errorText(failureText(error));
      } else errorText('계정 상태 확인 불가 · 현재 상태를 다시 조회하세요.');
      return false;
    }
  }

  function bindForm() {
    async function submit(event) {
      event?.preventDefault();
      if (busy || !part('form').reportValidity()) return;
      const password = part('password'), submitButton = part('submit');
      const confirmation = part('confirm');
      if (changing && password.value !== confirmation.value) {
        errorText('새 비밀번호와 확인 입력이 일치하지 않습니다.');
        password.value = confirmation.value = ''; return;
      }
      busy = true; submitButton.disabled = true;
      submitButton.setAttribute('reason', changing ? '비밀번호 변경 결과 확인 중' : '로그인 결과 확인 중');
      errorText('');
      try {
        await cookieRequest(changing ? '/api/fleet/auth/change-password' : '/api/fleet/auth/login', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(changing ? {password: password.value} : {
            login: part('login').value.trim(), password: password.value, remember: part('remember').checked}),
        });
        sessionStorage.removeItem('rosy-console-token');
        const session = await cookieRequest('/api/fleet/auth/session');
        if (changing && session.password_change_required !== false) throw new Error('Password change not verified');
        verified(session);
      } catch (error) {
        if (changing && error?.status === 401) {
          changing = false; host.innerHTML = FORM; bindForm(); part('login').focus();
          errorText('로그인이 만료됐습니다. 다시 로그인해 비밀번호 변경 상태를 확인하세요.');
        } else errorText(changing ? (error?.status === 422 || error?.status === 400
          ? '8자 이상이며 아이디와 다른 새 비밀번호를 입력하세요.'
          : '비밀번호 변경 결과를 확인할 수 없습니다. 연결을 확인한 뒤 화면을 새로고침해 계정 상태를 확인하세요.') : failureText(error));
      } finally {
        password.value = ''; if (confirmation) confirmation.value = '';
        busy = false; submitButton.disabled = false;
        submitButton.removeAttribute('reason');
      }
    }
    part('form').addEventListener('submit', submit);
    part('submit').addEventListener('click', submit);
    for (const name of ['login', 'password', 'confirm']) part(name)?.addEventListener('keydown', event => {
      if (event.key === 'Enter') submit(event);
    });
  }
  if (standalone) bindForm();
  else {
    part('logout').disabled = true;
    part('logout').setAttribute('reason', '계정 상태 확인 중');
    window.addEventListener('focus', async () => {
      try {
        const session = await cookieRequest('/api/fleet/auth/session');
        if (session.via !== 'cookie') return;
        if (session.password_change_required === true) {
          cookie = false; cookiePrincipal = cookieRole = null;
          paintLoginWords('비밀번호 변경');
          onChange(false); return;
        }
        if (cookie && cookiePrincipal === session.principal_id && cookieRole === session.role) return;
        cookie = true;
        cookiePrincipal = session.principal_id;
        cookieRole = session.role;
        sessionStorage.removeItem('rosy-console-token');
        onChange(true);
      } catch (error) {
        if (error?.status === 401 && cookie) {
          cookie = false; cookiePrincipal = cookieRole = null; onChange(false);
        }
      }
    });
    part('logout').addEventListener('click', async () => {
      if (busy) return;
      busy = true; part('logout').disabled = true; errorText('');
      part('logout').setAttribute('reason', '로그아웃 결과 확인 중');
      try {
        if (cookie) {
          await cookieRequest('/api/fleet/auth/logout', {method: 'POST'});
          try {
            await cookieRequest('/api/fleet/auth/session');
            throw new Error('Session still exists');
          } catch (error) { if (error?.status !== 401) throw error; }
        }
        sessionStorage.removeItem('rosy-console-token');
        cookie = false; cookiePrincipal = cookieRole = null;
        try { localStorage.setItem('rosy.fleet.account.identity', ''); } catch {}
        host.hidden = true;
        onChange(false);
        link?.focus();
      } catch { errorText('로그아웃 결과 확인 불가 · 계정 메뉴에서 다시 확인하세요.'); }
      finally {
        busy = false; part('logout').disabled = false;
        part('logout').removeAttribute('reason');
      }
    });
  }
  return {refresh};
}
