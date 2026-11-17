// D-991 /console/maintenance: PC 상태·조치·이력. 해도 되는지는 그 PC의 도우미가 판단한다.
import {createFleetClient} from '/common/fleet-client.js';
import {createPollGate} from '/console/assets/poll-gate.js';
import {confirmIrreversible} from '/common/ui.js';
import {bindEstop, bindTopbarToggle, showSession, showSignedOut, tickClock, watchFleet} from '/console/assets/fleet-header.js';
import {createPasswordLogin} from '/console/assets/password-login.js';
import {createHostServices} from '/console/assets/host-services.js';
import {createDbMaintenance} from '/console/assets/db-maintenance.js';

// A development or token session lives in this tab's storage, not a cookie (same as the other work pages).
let token = sessionStorage.getItem('rosy-console-token') || '';
const tokenInput = document.getElementById('console-token');
if (tokenInput) tokenInput.value = token;
const request = createFleetClient({credential: () => token, origin: location.origin});
bindEstop(request);
bindTopbarToggle();
tickClock();
setInterval(tickClock, 1000);
watchFleet(request);

const call = (url, options) => request(url, options && {
  method: options.method,
  headers: {...(options.headers || {}), ...(options.body !== undefined ? {'Content-Type': 'application/json'} : {})},
  ...(options.body !== undefined ? {body: typeof options.body === 'string' ? options.body : JSON.stringify(options.body)} : {}),
});
const view = createHostServices({root: document.getElementById('host-services'), call, confirmIrreversible});
const dbRoot = document.getElementById('db-maintenance');
const dbView = dbRoot ? createDbMaintenance({root: dbRoot, call}) : null;
const loginLink = document.getElementById('maintenance-login');
let authenticated = false;
let connectSeq = 0;
const gate = createPollGate();

function showConnectFailure(error) {
  const forbidden = error?.status === 403;
  const label = forbidden ? '권한 필요' : error?.status ? `연결 실패 (${error.status})` : '연결 실패';
  const tone = forbidden ? 'neutral' : 'warn';
  const message = forbidden ? '이 세션으로는 PC 정비 정보를 읽을 수 없습니다.' : '연결 실패 · 서버 세션을 확인하지 못했습니다.';
  view.clear(label, tone, message);
  dbView?.clear(label, tone, message);
}

async function connect(credentialChange = false) {
  const seq = ++connectSeq;
  try {
    const session = await request('/api/fleet/auth/session');
    if (seq !== connectSeq) return;
    authenticated = true;
    if (loginLink) loginLink.hidden = true;
    tokenInput?.removeAttribute('aria-invalid');
    showSession(session, {credentialChange});
    await loginForm.refresh(false).catch(() => {});
  } catch (error) {
    if (seq !== connectSeq) return;
    authenticated = false;
    if (error?.status === 401) {
      if (loginLink) loginLink.hidden = false;
      if (token) tokenInput?.setAttribute('aria-invalid', 'true');
      showSignedOut();
      await loginForm.refresh(true).catch(() => {});
    } else {
      showConnectFailure(error);
    }
    return;
  }
  gate.reset();
  await Promise.allSettled([view.refresh(), dbView ? dbView.refresh() : Promise.resolve()]);
}

function saveToken() {
  token = tokenInput?.value.trim() || '';
  if (token) sessionStorage.setItem('rosy-console-token', token);
  else sessionStorage.removeItem('rosy-console-token');
  void connect(true).catch(() => {});
}

document.getElementById('token-save')?.addEventListener('click', saveToken);
tokenInput?.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') saveToken();
});
const loginForm = createPasswordLogin(document.getElementById('password-login'), {
  onChange: () => {
    token = '';
    if (tokenInput) tokenInput.value = '';
    sessionStorage.removeItem('rosy-console-token');
    void connect(true).catch(() => {});
  },
});

async function start() {
  await connect(false);
  setInterval(() => {
    if (!document.hidden && authenticated && gate.due()) {
      view.refresh().then(gate.ok, (error) => gate.fail(error?.status, error?.code));
      if (dbView) dbView.refresh().catch(() => {});
    }
  }, 30000);
}
start();
