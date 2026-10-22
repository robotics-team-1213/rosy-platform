import {accountFetch} from '/account-session.js';
import {openLiveDialog} from '/common/ui.js';

const returnKey = 'rosy.learning.connection-return';
const loginReturnKey = 'rosy.learning.login-return';
const requiredScopes = ['read-repos', 'write-repos', 'manage-repos'];

export function learningReturn(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\x00-\x20]/.test(value)) return null;
  try {
    const url = new URL(value, location.origin);
    const path = decodeURIComponent(url.pathname);
    if (url.origin !== location.origin || /[\\\x00-\x20]/.test(path) || path.startsWith('//')) return null;
    if (!['/', '/pixels', '/catalog', '/accounts', '/learning'].includes(path) && !path.startsWith('/learning/')) return null;
    return url.pathname + url.search + url.hash;
  } catch (_) { return null; }
}

export function currentLearningTask() {
  return (location.pathname === '/accounts' && learningReturn(new URLSearchParams(location.search).get('return')))
    || learningReturn(location.pathname + location.search + location.hash) || '/learning';
}

export function readyConnection(session) {
  return session?.connections?.find(connection => connection.active !== false
    && (connection.expires_at == null || connection.expires_at * 1000 > Date.now())
    && requiredScopes.every(scope => connection.scopes?.includes(scope)));
}

export function rememberLearningLogin() {
  try { sessionStorage.setItem(loginReturnKey, currentLearningTask()); }
  catch (_) { throw new Error('작업 복귀 경로를 보관할 수 없습니다. 브라우저 저장 설정을 확인하세요.'); }
}

export function restoreLearningTask(session) {
  if (location.pathname !== '/accounts' || new URLSearchParams(location.search).has('error') || !session) return;
  let target;
  try {
    target = learningReturn(sessionStorage.getItem(loginReturnKey));
    sessionStorage.removeItem(loginReturnKey);
    if (target) sessionStorage.removeItem(returnKey);
    else if (readyConnection(session)) {
      target = learningReturn(sessionStorage.getItem(returnKey)); sessionStorage.removeItem(returnKey);
    }
  }
  catch (_) { return; }
  if (target && new URL(target, location.origin).pathname !== '/accounts') location.replace(target);
}

export async function connectHuggingFace(session) {
  const response = await accountFetch('/api/accounts/oauth', {
    method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-Pinky-Token':session.token},
    body:JSON.stringify({purpose:'link'}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '연결을 시작하지 못했습니다. 다시 시도하세요.');
  const url = new URL(result.url, location.origin);
  if (url.username || url.password || (url.origin !== 'https://huggingface.co' && url.origin !== location.origin)) throw new Error('연결 주소를 확인할 수 없습니다. 다시 시도하세요.');
  const target = currentLearningTask();
  try { sessionStorage.setItem(returnKey, target); }
  catch (_) { throw new Error('작업 복귀 경로를 보관할 수 없습니다. 브라우저 저장 설정을 확인하세요.'); }
  location.assign(url.href);
}

let serial = 0;
class LearningConnections extends HTMLElement {
  connectedCallback() {
    if (this.trigger) return;
    if (!document.querySelector('link[href="/learning-connections.css"]')) {
      const style = document.createElement('link'); style.rel = 'stylesheet'; style.href = '/learning-connections.css';
      document.head.append(style);
    }
    this.innerHTML = '<ui-button kind="quiet" data-action-icon="account" aria-label="계정과 Hugging Face 연결" aria-haspopup="dialog">연결 확인 중</ui-button>';
    this.trigger = this.querySelector('ui-button');
    this.trigger.addEventListener('click', () => this.open());
    this.refresh();
  }

  async refresh() {
    this.failure = ''; this.denied = false;
    try {
      const optionsResponse = await accountFetch('/api/accounts/options', {credentials:'same-origin', cache:'no-store'});
      const options = await optionsResponse.json();
      if (!optionsResponse.ok) throw new Error('계정 설정을 확인할 수 없습니다. 다시 시도하세요.');
      this.options = options;
      this.hidden = !this.options.enabled;
      if (this.hidden) return;
      const response = await accountFetch('/api/accounts/session', {credentials:'same-origin', cache:'no-store'});
      const result = await response.json();
      this.session = response.ok ? result : null;
      this.denied = response.status === 403;
      if (!response.ok && response.status !== 401) {
        throw new Error(result.error || '계정 상태를 확인할 수 없습니다. 다시 시도하세요.');
      }
      restoreLearningTask(this.session);
    } catch (error) { this.session = null; this.failure = error.message; }
    this.trigger.textContent = this.failure ? '연결 확인 필요' : !this.session ? '로그인' : readyConnection(this.session) ? '연결됨' : 'HF 연결 필요';
    if (this.dialog?.open) this.render();
  }

  open() {
    if (this.dialog?.open || this.hidden) return;
    const titleId = `learning-connections-title-${++serial}`;
    this.dialog = document.createElement('dialog');
    this.dialog.className = 'learning-connections-dialog';
    this.dialog.setAttribute('aria-labelledby', titleId);
    this.dialog.innerHTML = `<div class="ui-workspace-bar"><h2 id="${titleId}" class="ui-section-heading">계정과 연결</h2><span data-spacer></span><ui-button kind="quiet" data-icon-only data-action-icon="close" aria-label="닫기"></ui-button></div><div data-connection-content></div>`;
    this.dialog.querySelector('[aria-label="닫기"]').addEventListener('click', () => this.closeDialog());
    this.render();
    this.closeDialog = openLiveDialog(this.dialog, {opener:this.trigger});
    this.refresh();
  }

  render() {
    const content = this.dialog.querySelector('[data-connection-content]');
    content.replaceChildren();
    const line = (text, tag = 'p') => {
      const node = document.createElement(tag); node.textContent = text; content.append(node); return node;
    };
    const actions = document.createElement('ui-actions');
    const action = (label, handler, kind = 'quiet') => {
      const button = document.createElement('ui-button'); button.textContent = label; button.setAttribute('kind', kind);
      button.addEventListener('click', async () => {
        button.disabled = true;
        try { await handler(); }
        catch (error) { this.failure = error.message; this.render(); }
        finally { button.disabled = false; }
      });
      actions.append(button);
    };
    if (this.failure) {
      const status = line(this.failure, 'ui-status'); status.setAttribute('state', this.denied ? 'forbidden' : 'unavailable'); status.setAttribute('role', 'alert');
      action('다시 확인', () => this.refresh());
    }
    if (!this.session) {
      if (!this.failure) line('Rosy Account로 로그인해 작업을 이어가세요.');
      const login = document.createElement('a'); login.textContent = 'Rosy Account로 로그인';
      login.href = '/api/account/login?return=/accounts';
      login.addEventListener('click', event => {
        try { rememberLearningLogin(); }
        catch (error) { event.preventDefault(); this.failure = error.message; this.render(); }
      });
      actions.append(login);
    } else {
      line(this.session.profile?.display_name || this.session.user_id);
      const ready = readyConnection(this.session);
      const hasConnections = this.session.connections?.length > 0;
      const state = line(ready ? '읽기 · 쓰기 · 저장소 관리 가능' : hasConnections ? 'Hugging Face 재연결 필요' : 'Hugging Face 연결 필요', 'ui-status');
      state.setAttribute('state', ready ? 'ready' : 'empty'); state.setAttribute('role', 'status');
      if (ready) line(ready.username || ready.subject);
      if (!this.session.capabilities?.includes('import')) line('자료 가져오기 권한이 필요합니다. 계정 관리자에게 권한을 요청하세요.');
      else if (this.options?.oauth) action(hasConnections ? 'Hugging Face 다시 연결' : 'Hugging Face 연결', () => connectHuggingFace(this.session), ready ? 'quiet' : 'primary');
      else line('Hugging Face 연결을 사용할 수 없습니다. 계정과 자료에서 연결을 확인하세요.');
      const accounts = document.createElement('a'); accounts.href = '/accounts'; accounts.textContent = '계정과 자료 관리'; actions.append(accounts);
      action('로그아웃', async () => {
        const response = await accountFetch('/api/accounts/logout', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-Pinky-Token':this.session.token}, body:'{}'});
        if (!response.ok) throw new Error('로그아웃하지 못했습니다. 다시 시도하세요.');
        this.closeDialog(); location.reload();
      });
    }
    content.append(actions);
  }
}
customElements.define('learning-connections', LearningConnections);
