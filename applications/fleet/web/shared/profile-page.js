import {createFleetClient} from '/common/fleet-client.js';
import {loginHref, loginReturn} from '/console/assets/login-return.js';
import {roleLabel} from '/console/assets/fleet-header.js';
import {CAPABILITIES} from '/console/assets/account-permissions.js';

const request = createFleetClient();
const $ = id => document.getElementById(id);
const back = loginReturn(new URLSearchParams(location.search).get('return'), location.origin);
$('profile-back').href = back.startsWith('/console/profile') ? '/console' : back;
$('profile-login').href = loginHref(location);
let busy = false, owner = null;

function status(message, state) {
  $('profile-status').textContent = message;
  $('profile-status').setAttribute('state', state);
}
function lock(value) {
  busy = value;
  for (const id of ['profile-name-save', 'profile-password-save', 'profile-reload']) {
    $(id).disabled = value;
    $(id).setAttribute('reason', value ? '계정 처리 결과 확인 중' : '');
  }
  for (const id of ['profile-name', 'profile-current', 'profile-new', 'profile-confirm']) $(id).readOnly = value;
}
async function readProfile(expected = null) {
  const profile = await request('/api/fleet/auth/profile');
  if (!profile.login || !profile.principal_id || !profile.role || typeof profile.display_name !== 'string') {
    throw new Error('Profile not verified');
  }
  if (expected && profile.principal_id !== expected) {
    const error = new Error('Profile account changed'); error.code = 'PROFILE_ACCOUNT_CHANGED'; throw error;
  }
  return profile;
}
function renderGrants(profile) {
  $('profile-role').textContent = roleLabel(profile.role);
  const grants = profile.grants;
  $('profile-grants').hidden = !Array.isArray(grants);
  $('profile-grant-list').replaceChildren();
  if (!Array.isArray(grants)) return;
  for (const grant of grants) {
    const item = document.createElement('li');
    const labels = CAPABILITIES[grant.resource.split(':')[0]] || {};
    item.textContent = `${grant.resource} · ${grant.capabilities.map(code => labels[code] || code).join(', ')}`;
    $('profile-grant-list').append(item);
  }
  if (!grants.length) {
    const item = document.createElement('li'); item.textContent = '부여된 서비스 권한 없음';
    $('profile-grant-list').append(item);
  }
}
async function load(expected = null) {
  const profile = await readProfile(expected);
  owner = profile.principal_id;
  $('profile-id').textContent = profile.login;
  $('profile-email').textContent = profile.email || '등록된 이메일 없음';
  $('profile-role').textContent = roleLabel(profile.role);
  $('profile-name').value = profile.display_name;
  renderGrants(profile);
  $('profile-content').hidden = false;
  $('profile-login').hidden = true;
  return profile;
}
function failure(error) {
  $('profile-grants').hidden = true;
  $('profile-grant-list').replaceChildren();
  if (error.code === 'PROFILE_ACCOUNT_CHANGED') {
    for (const id of ['profile-current', 'profile-new', 'profile-confirm']) $(id).value = '';
    $('profile-content').hidden = true;
    status('로그인 계정이 바뀌었습니다. 계정 상태 다시 확인을 눌러 현재 계정을 확인한 뒤 편집하세요.', 'warning');
  } else if (error.status === 401 || error.code === 'PASSWORD_CHANGE_REQUIRED') {
    for (const id of ['profile-current', 'profile-new', 'profile-confirm']) $(id).value = '';
    $('profile-content').hidden = true;
    $('profile-login').hidden = false;
    $('profile-login').textContent = error.code === 'PASSWORD_CHANGE_REQUIRED' ? '첫 로그인 비밀번호 변경' : '로그인';
    status('로그인과 첫 비밀번호 변경을 완료한 뒤 내 계정을 사용할 수 있습니다.', 'warning');
    $('profile-login').focus();
  } else if (error.code === 'CURRENT_PASSWORD_INCORRECT') {
    status('현재 비밀번호가 맞지 않습니다. 다시 확인하세요.', 'warning');
  } else if (error.status === 422 || error.status === 400) {
    status('입력 조건을 확인하세요. 표시 이름은 1~80자, 새 비밀번호는 8자 이상이며 ID·현재 비밀번호와 달라야 합니다.', 'warning');
  } else if (error.status === 403) {
    for (const id of ['profile-current', 'profile-new', 'profile-confirm']) $(id).value = '';
    $('profile-content').hidden = true;
    $('profile-login').hidden = false;
    status('내 계정은 사람 계정 로그인으로 사용할 수 있습니다.', 'warning');
  } else status('처리 결과를 확인할 수 없습니다. 연결을 확인한 뒤 계정 상태 다시 확인을 누르세요.', 'error');
}
async function reload() {
  if (busy) return;
  lock(true); status('저장된 계정 상태를 확인하고 있습니다.', 'pending');
  try { await load(); status('본인 계정 정보입니다. 표시 이름과 비밀번호를 관리할 수 있습니다.', 'ready'); }
  catch (error) { failure(error); }
  finally { lock(false); }
}
async function saveName(event) {
  event.preventDefault();
  if (busy || !$('profile-name-form').reportValidity()) return;
  const name = $('profile-name').value.trim();
  lock(true); status('표시 이름 저장 결과를 확인하고 있습니다.', 'pending');
  try {
    await readProfile(owner);
    await request('/api/fleet/auth/profile', {method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({display_name: name})});
    const profile = await load(owner);
    if (profile.display_name !== name) throw new Error('Name not verified');
    status('표시 이름을 저장하고 다시 확인했습니다.', 'ready');
  } catch (error) { failure(error); }
  finally { lock(false); }
}
async function changePassword(event) {
  event.preventDefault();
  if (busy || !$('profile-password-form').reportValidity()) return;
  const fields = ['profile-current', 'profile-new', 'profile-confirm'].map($);
  const [current, next, confirmation] = fields;
  try {
    if (next.value !== confirmation.value) {
      status('새 비밀번호와 확인 입력이 일치하지 않습니다.', 'warning'); return;
    }
    lock(true); status('비밀번호 변경과 새 로그인 상태를 확인하고 있습니다.', 'pending');
    await readProfile(owner);
    await request('/api/fleet/auth/change-password', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({current_password: current.value, password: next.value})});
    const session = await request('/api/fleet/auth/session');
    if (session.via !== 'cookie' || session.password_change_required !== false) throw new Error('Change not verified');
    await load(owner);
    status('비밀번호를 변경하고 새 로그인 상태를 확인했습니다. 이전 로그인 세션은 종료됐습니다.', 'ready');
  } catch (error) { failure(error); }
  finally { for (const field of fields) field.value = ''; lock(false); }
}
$('profile-name-form').addEventListener('submit', saveName);
$('profile-name-save').addEventListener('click', saveName);
$('profile-name').addEventListener('keydown', event => { if (event.key === 'Enter') saveName(event); });
$('profile-password-form').addEventListener('submit', changePassword);
$('profile-password-save').addEventListener('click', changePassword);
for (const id of ['profile-current', 'profile-new', 'profile-confirm']) {
  $(id).addEventListener('keydown', event => { if (event.key === 'Enter') changePassword(event); });
}
$('profile-reload').addEventListener('click', reload);
window.addEventListener('focus', async () => {
  if (busy || !owner || $('profile-content').hidden) return;
  lock(true);
  try { renderGrants(await readProfile(owner)); }
  catch (error) { failure(error); }
  finally { lock(false); }
});
reload();
