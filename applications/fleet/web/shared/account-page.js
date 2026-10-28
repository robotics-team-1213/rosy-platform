import {createFleetClient} from '/common/fleet-client.js';
import {canManageAccounts, canViewAccountSetup, CAPABILITIES} from '/console/assets/account-permissions.js';

const rawRequest = createFleetClient(), $ = id => document.getElementById(id), endpoint = '/api/fleet/auth/accounts';
let owner = null, rows = [], selected = null, busy = false;
const lifetime = new AbortController();
let invalidated = false;
function changed() { return Object.assign(new Error(), {code:'ACCOUNT_CHANGED'}); }
window.addEventListener('storage', event => {
  if (event.key === 'rosy.fleet.account.identity' && (!owner || event.newValue !== owner)) {
    invalidated = true; lifetime.abort(); fail(changed());
  }
});
async function request(path, init = {}) {
  if (invalidated) throw changed();
  const held = owner;
  const result = await rawRequest(path, {...init, signal:lifetime.signal,
    headers:{...init.headers, 'X-Rosy-Session':owner.split(':')[1]}});
  await identity();
  if (invalidated || owner !== held) throw changed();
  return result;
}
function status(text, state = 'ready') {
  $('account-status').textContent = text; $('account-status').setAttribute('state', state);
}
function clearSecrets() { $('account-password').value = ''; $('account-reset-password').value = ''; }
function fail(error) {
  clearSecrets();
  $('account-setup').hidden = true; $('account-clients').replaceChildren();
  $('account-setup-state').textContent = '';
  if ([401, 403].includes(error.status) || error.code === 'ACCOUNT_CHANGED') {
    $('account-content').hidden = true; $('account-login').hidden = false;
    $('account-grants').replaceChildren(); $('account-list').replaceChildren(); selected = null;
    status('로그인 계정 또는 관리 권한이 변경되었습니다. 다시 로그인한 뒤 확인하세요.', 'warning');
  } else if (error.status === 409) {
    $('account-actions').hidden = true;
    status('다른 관리자가 변경했습니다. 현재 상태를 다시 조회하고 수정 내용을 확인하세요.', 'warning');
  } else status(error.status === 422 ? '입력값을 확인하세요. 마지막 관리자와 비밀번호 조건도 확인하세요.'
    : '처리 결과를 확인하지 못했습니다. 현재 상태를 다시 조회하세요.', 'warning');
}
async function identity() {
  if (invalidated) throw changed();
  const session = await rawRequest('/api/fleet/auth/session', {signal:lifetime.signal});
  if (!canManageAccounts(session)) throw Object.assign(new Error(), {status: 403});
  const current = `${session.account_id}:${session.session_family}:${session.revision}`;
  if (invalidated || (owner && owner !== current)) throw changed();
  owner = current; return session;
}
async function perform(fn) {
  if (busy) return;
  busy = true;
  for (const button of document.querySelectorAll('ui-button, button')) {
    button.disabled = true; button.setAttribute('reason', '처리 결과 확인 중');
  }
  try { await identity(); await fn(); } catch (error) { fail(error); }
  finally {
    busy = false;
    for (const button of document.querySelectorAll('ui-button, button')) {
      button.disabled = invalidated; if (!invalidated) button.removeAttribute('reason');
    }
  }
}
function grantRow(grant = null) {
  const group = document.createElement('fieldset'), legend = document.createElement('legend');
  legend.textContent = '대상 자원'; group.append(legend);
  const kindLabel = document.createElement('label'), kind = document.createElement('select');
  kindLabel.textContent = '자원 종류 '; kind.className = 'ui-field'; kind.dataset.grant = 'kind';
  for (const [value, label] of [['site', '현장'], ['robot', '로봇'], ['project', '프로젝트']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = label; kind.append(option);
  }
  kindLabel.append(kind); group.append(kindLabel);
  const idLabel = document.createElement('label'), id = document.createElement('input');
  idLabel.textContent = ' 식별자 '; id.className = 'ui-field'; id.required = true;
  id.pattern = '[A-Za-z0-9._-]{1,96}'; id.dataset.grant = 'id'; idLabel.append(id); group.append(idLabel);
  const choices = document.createElement('div'); group.append(choices);
  const draw = (selectedCaps = []) => {
    choices.replaceChildren();
    for (const [value, label] of Object.entries(CAPABILITIES[kind.value])) {
      const wrapper = document.createElement('label'), input = document.createElement('input');
      wrapper.className = 'ui-check'; input.type = 'checkbox'; input.className = 'ui-field'; input.value = value; input.checked = selectedCaps.includes(value);
      wrapper.append(input, document.createTextNode(label + ' ')); choices.append(wrapper);
    }
  };
  if (grant) { [kind.value, id.value] = grant.resource.split(':'); }
  draw(grant?.capabilities); kind.addEventListener('change', () => draw());
  const remove = document.createElement('ui-button'); remove.setAttribute('kind', 'quiet');
  remove.setAttribute('type', 'button'); remove.textContent = '자원 제거';
  remove.addEventListener('click', () => group.remove()); group.append(remove); $('account-grants').append(group);
}
function edit(row = null) {
  selected = row; clearSecrets();
  $('account-heading').textContent = row ? `${row.login} 계정 수정` : '새 계정';
  for (const [id, key] of [['account-name', 'login'], ['account-principal', 'principal_id']]) {
    $(id).value = row?.[key] || ''; $(id).readOnly = !!row;
  }
  $('account-role').value = row?.role || 'viewer'; $('account-enabled').checked = row?.enabled ?? true;
  $('account-enabled').closest('label').hidden = !row; $('account-initial-password').hidden = !!row;
  $('account-password').required = !row; $('account-actions').hidden = !row;
  $('account-grants').replaceChildren(); for (const grant of row?.grants || []) grantRow(grant);
}
async function load() {
  rows = await request(endpoint); $('account-list').replaceChildren();
  for (const row of rows) {
    const item = document.createElement('li'), button = document.createElement('ui-button');
    button.setAttribute('kind', 'quiet'); button.setAttribute('type', 'button');
    button.textContent = `${row.login} · ${row.enabled ? '사용 중' : '정지됨'}`;
    button.addEventListener('click', () => edit(row)); item.append(button); $('account-list').append(item);
  }
  $('account-content').hidden = false; $('account-login').hidden = true; edit();
}
function grants() {
  return [...$('account-grants').children].map(group => ({
    resource: group.querySelector('[data-grant=kind]').value + ':' + group.querySelector('[data-grant=id]').value,
    capabilities: [...group.querySelectorAll('input[type=checkbox]:checked')].map(input => input.value),
  }));
}
$('account-new').addEventListener('click', () => edit());
$('account-add-grant').addEventListener('click', () => grantRow());
$('account-reload').addEventListener('click', () => perform(async () => { await load(); status('최신 계정 상태입니다.'); }));
$('account-save').addEventListener('click', () => {
  if (!$('account-form').reportValidity()) return;
  const target = selected, body = {role: $('account-role').value, grants: grants()};
  if (target) Object.assign(body, {revision: target.revision, enabled: $('account-enabled').checked});
  else Object.assign(body, {login: $('account-name').value, principal_id: $('account-principal').value,
    password: $('account-password').value});
  clearSecrets();
  perform(async () => {
    await request(endpoint + (target ? '/' + target.account_id : ''), {method: target ? 'PATCH' : 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    await load(); status('계정을 저장했습니다. 대상 계정의 이전 세션은 종료되었습니다.');
  });
});
for (const [id, action] of [['account-reset', 'reset-password'], ['account-revoke', 'revoke-sessions']]) {
  $(id).addEventListener('click', () => {
    if (!selected) return;
    const target = selected, body = {revision: target.revision};
    if (action === 'reset-password') {
      const password = $('account-reset-password');
      if (!password.value || !password.reportValidity()) return;
      body.password = password.value;
    }
    clearSecrets();
    perform(async () => {
      await request(`${endpoint}/${target.account_id}/${action}`, {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      await load(); status('처리했습니다. 대상 계정의 모든 로그인 세션이 종료되었습니다.');
    });
  });
}
$('account-form').addEventListener('submit', event => { event.preventDefault(); $('account-save').click(); });
async function setup() {
  $('account-setup').hidden = true; $('account-clients').replaceChildren();
  try {
    const before = await rawRequest('/api/fleet/auth/session', {signal:lifetime.signal});
    if (!canViewAccountSetup(before)) throw Object.assign(new Error(), {status:403});
    const result = await rawRequest('/api/fleet/auth/setup', {signal:lifetime.signal});
    const after = await rawRequest('/api/fleet/auth/session', {signal:lifetime.signal});
    if (invalidated || JSON.stringify(before) !== JSON.stringify(after)) throw changed();
    $('account-setup-state').textContent = result.configured
      ? `통합 로그인 설정 적용됨 · ${result.issuer}`
      : '통합 로그인이 아직 설정되지 않았습니다. 서버 설치 안내에 따라 활성화하세요.';
    for (const client of result.clients) {
      const item = document.createElement('li');
      item.textContent = `${client.client_id} · ${client.resources.join(', ')} · 복귀 주소: ${client.redirect_uris.join(', ')}`;
      $('account-clients').append(item);
    }
    $('account-setup').hidden = false; $('account-login').hidden = true;
    if (canManageAccounts(after)) {
      await perform(async () => { await load(); status('관리할 계정을 선택하거나 새 계정을 만드세요.'); });
    } else {
      $('account-content').hidden = true;
      status('최초 서버 설정을 마친 뒤 지정된 계정 관리자로 다시 로그인하세요.', 'warning');
    }
  } catch (error) { fail(error); }
}
$('account-setup-reload').addEventListener('click', setup);
setup();
