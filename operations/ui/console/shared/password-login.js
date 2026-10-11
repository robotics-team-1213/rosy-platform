// D-683: pages own authority and drafts; this component owns cookie login and verified logout.
import {createFleetClient} from '/common/fleet-client.js';
import {loginHref} from '/console/assets/login-return.js';

const cookieRequest = createFleetClient();
const sessionRequest = createFleetClient({credential: () => document.getElementById('console-token')?.value
  ?? sessionStorage.getItem('rosy-console-token') ?? ''});
const FORM = `
  <form class="password-login-form" data-login="form" aria-label="관제 로그인">
    <label for="fleet-login-name">아이디</label>
    <input id="fleet-login-name" class="ui-field password-login-field" data-login="login" autocomplete="username"
           autocapitalize="none" spellcheck="false" required>
    <label for="fleet-login-password">비밀번호</label>
    <input id="fleet-login-password" class="ui-field password-login-field" data-login="password" type="password"
           autocomplete="current-password" required>
    <label class="ui-check password-login-remember"><input class="ui-field" type="checkbox" data-login="remember"> 이 브라우저 기억(30일)</label>
    <ui-button kind="primary" type="button" data-login="submit">로그인</ui-button>
    <span class="password-login-error" data-login="error" role="alert" hidden></span>
  </form>`;
const WHO = `<div class="password-login-who" data-login="who">
  <span data-login="principal"></span>
  <ui-button kind="quiet" type="button" data-login="logout">로그아웃</ui-button>
  <span class="password-login-error" data-login="error" role="alert" hidden></span>
</div>`;

function failureText(error) {
  if (error?.status === 401) return '아이디 또는 비밀번호가 맞지 않습니다.';
  if (error?.status === 429) return '실패가 많아 잠시 막혔습니다. 1분 뒤 다시 시도하세요.';
  return '로그인 결과를 확인할 수 없습니다. 관제 PC 연결을 확인한 뒤 다시 확인하세요.';
}

export function createPasswordLogin(host, {onChange = () => {}, standalone = false} = {}) {
  host.innerHTML = standalone ? FORM : WHO;
  const part = name => host.querySelector(`[data-login="${name}"]`);
  let busy = false, cookie = false, cookiePrincipal = null, cookieRole = null;
  const link = document.getElementById('fleet-login');
  if (link) link.href = loginHref(location);
  if (link && ['/console/site-map', '/console/cell'].includes(location.pathname)) {
    link.target = '_blank'; link.rel = 'noopener'; link.href += '&draft=1';
    link.title = '새 탭에서 로그인 · 이 탭의 편집 내용 보존';
  }
  const errorText = message => {
    part('error').textContent = message;
    part('error').hidden = !message;
  };

  async function refresh(locked = true) {
    try {
      if (!standalone && locked) {
        try {
          const connection = await cookieRequest('/api/fleet/auth/connection');
          if (connection.mode === 'paired' && !connection.password_login) {
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
        availability.textContent = connection.mode === 'development'
          ? '현재 현장은 개발 연결 모드입니다. 원래 업무 화면에서 개발 접속 상태를 확인하세요.'
          : '이 현장에는 사람 로그인이 설정되지 않았습니다. 현장 관리자에게 계정 설정을 요청하세요.';
        if (!offered) return false;
      }
      const session = await (standalone ? cookieRequest : sessionRequest)('/api/fleet/auth/session');
      cookie = session.via === 'cookie';
      cookiePrincipal = cookie ? session.principal_id : null;
      cookieRole = cookie ? session.role : null;
      if (standalone) {
        if (cookie) onChange(true);
      } else {
        host.hidden = false;
        part('principal').textContent = `${session.principal_id} · ${session.role}`;
        part('logout').textContent = cookie ? '로그아웃' : '이 탭 접속 해제';
        part('logout').title = cookie ? '이 브라우저의 현장 로그인 종료' : '서버 토큰은 폐기하지 않습니다';
        part('logout').disabled = false;
      }
      return cookie;
    } catch (error) {
      if (error?.status === 401 || error?.status === 404) {
        cookie = false; cookiePrincipal = cookieRole = null;
        if (!standalone) host.hidden = true;
      } else if (standalone) {
        host.hidden = false;
        document.getElementById('login-availability').hidden = true;
        errorText(failureText(error));
      } else errorText('계정 상태 확인 불가 · 현재 상태를 다시 조회하세요.');
      return false;
    }
  }

  if (standalone) {
    async function submit(event) {
      event?.preventDefault();
      if (busy || !part('form').reportValidity()) return;
      busy = true; part('submit').disabled = true; errorText('');
      try {
        await cookieRequest('/api/fleet/auth/login', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({login: part('login').value.trim(), password: part('password').value,
            remember: part('remember').checked}),
        });
        sessionStorage.removeItem('rosy-console-token');
        const session = await cookieRequest('/api/fleet/auth/session');
        if (session.via !== 'cookie' || !session.principal_id || !session.role) throw new Error('Session not verified');
        onChange(true);
      } catch (error) { errorText(failureText(error)); }
      finally { part('password').value = ''; busy = false; part('submit').disabled = false; }
    }
    part('form').addEventListener('submit', submit);
    part('submit').addEventListener('click', submit);
    for (const name of ['login', 'password']) part(name).addEventListener('keydown', event => {
      if (event.key === 'Enter') submit(event);
    });
  } else {
    const account = document.getElementById('fleet-account');
    part('logout').disabled = true;
    account.addEventListener('keydown', event => {
      if (event.key === 'Escape') { account.open = false; account.querySelector('summary').focus(); }
    });
    window.addEventListener('focus', async () => {
      try {
        const session = await cookieRequest('/api/fleet/auth/session');
        if (session.via !== 'cookie') return;
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
        host.hidden = true;
        document.getElementById('fleet-account').open = false;
        onChange(false);
        link?.focus();
      } catch { errorText('로그아웃 결과 확인 불가 · 계정 메뉴에서 다시 확인하세요.'); }
      finally { busy = false; part('logout').disabled = false; }
    });
  }
  return {refresh};
}
