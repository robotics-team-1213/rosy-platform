import '/common/account-profile.js';
import {createAccountSession} from '/common/account-session.js';

const $ = id => document.getElementById(id);
const KIND = {measure: '측정', check: '확인'};
const VERDICT = {pass: '통과', fail: '실패', neither: '어느 쪽도 아님'};
let account = null;
let canOperate = false;
let loggingOut = false;
let selected = '';

function text(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}
function say(message, state = '') {
  const node = $('status');
  node.textContent = message;
  if (state) node.setAttribute('state', state); else node.removeAttribute('state');
}
const when = value => (value ? new Date(value).toLocaleString('ko-KR') : '');

async function api(path, options) {
  const response = await fetch('/api/calibration/v1/requests' + path, {cache: 'no-store', ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(body.error || '요청을 처리하지 못했습니다.'), {status: response.status});
  return body;
}

const session = createAccountSession({
  current: () => account,
  apply: value => {
    account = value;
    canOperate = value.can_operate === true;
    $('account-login').hidden = !value.enabled || value.authenticated;
    $('account-logout').hidden = !value.authenticated;
    $('mode-tag').textContent = !value.enabled ? '읽기 전용' : !value.authenticated ? '로그인 필요' : canOperate ? '답할 수 있음' : '보기만 가능';
    $('mode-tag').setAttribute('status', canOperate ? 'active' : 'neutral');
  },
  changed: () => { document.body.hidden = true; window.location.reload(); },
  failed: () => { canOperate = false; },
  poll: 0,
});
$('account-logout').addEventListener('click', async () => {
  loggingOut = true;
  session.invalidate();
  canOperate = false;
  try { await session.logout(() => { account = null; }, {signal: AbortSignal.timeout(5000)}); } catch (_) { say('중앙 로그아웃 처리가 지연 중입니다.', 'warning'); }
  loggingOut = false;
  await session.restore();
  await refresh();
});
setInterval(() => { if (!loggingOut) session.restore(); }, 10000);

function renderList(rows) {
  const list = $('list');
  list.replaceChildren();
  $('empty').hidden = rows.length > 0;
  for (const row of rows) {
    const link = document.createElement('a');
    link.href = '#' + row.id;
    if (row.id === selected) link.setAttribute('aria-current', 'page');
    link.append(text('span', row.question));
    const done = row.status === 'answered' ? `답함 · ${VERDICT[row.verdict] || row.verdict}` : '답 기다리는 중';
    link.append(text('small', `${KIND[row.kind] || row.kind} · ${row.item} · ${done}`));
    const item = document.createElement('li');
    item.append(link);
    list.append(item);
  }
}

async function refresh() {
  try {
    const body = await api('');
    canOperate = body.can_operate === true;
    renderList(body.requests);
    say(body.requests.length ? '요청을 골라 내용을 확인하세요.' : '열린 요청이 없습니다.');
    if (!selected && body.requests[0]) selected = body.requests[0].id;
    if (selected) await show(selected);
  } catch (error) {
    $('detail').hidden = true;
    renderList([]);
    say(error.status === 401 ? 'Rosy Account로 로그인해야 요청을 볼 수 있습니다.' : error.message, error.status === 401 ? 'forbidden' : 'error');
  }
}

function section(title) {
  const box = document.createElement('section');
  box.append(text('h3', title));
  return box;
}

function candidates(req) {
  const answered = req.answer?.verdict;
  const box = section('후보와 뜻');
  const dl = document.createElement('dl');
  dl.className = 'request-candidates';
  const means = req.means || {};
  const names = [...Object.keys(req.candidates || {}), 'neither'];
  for (const name of names) {
    const row = document.createElement('div');
    if (answered === name) row.dataset.chosen = 'true';
    const label = name === 'neither' ? '어느 쪽도 아님' : `${name} · ${req.candidates[name]} ${req.unit}`;
    row.append(text('dt', label), text('dd', means[name] || ''));
    dl.append(row);
  }
  box.append(dl, text('p', `허용 오차 ${req.tolerance} ${req.unit} 안에 드는 후보가 판정이 됩니다. 값은 셀 설정에 직접 쓰이지 않습니다.`));
  return box;
}

function answerForm(req) {
  const form = document.createElement('form');
  form.className = 'answer-form';
  if (req.kind === 'measure') {
    const label = text('label', `잰 값 (${req.unit})`, 'ui-field-label');
    const input = document.createElement('input');
    input.className = 'ui-field';
    Object.assign(input, {type: 'number', name: 'value', required: true, step: 'any'});
    label.append(input);
    form.append(label);
  } else {
    const set = document.createElement('fieldset');
    set.append(text('legend', '확인 결과'));
    for (const [value, name] of [['pass', '통과'], ['fail', '실패']]) {
      const label = document.createElement('label');
      label.className = 'ui-check';
      const input = document.createElement('input');
      input.className = 'ui-field';
      Object.assign(input, {type: 'radio', name: 'result', value, required: true});
      label.append(input, ' ' + name);
      set.append(label);
    }
    form.append(set);
  }
  const note = text('label', '메모 (선택)', 'ui-field-label');
  const noteInput = document.createElement('input');
  noteInput.className = 'ui-field';
  Object.assign(noteInput, {name: 'note', maxLength: 300, autocomplete: 'off'});
  note.append(noteInput);
  const submit = document.createElement('ui-button');
  submit.setAttribute('kind', 'primary');
  submit.setAttribute('type', 'submit');
  submit.textContent = '답 남기기';
  form.append(note, text('p', '답은 한 번만 남고 로그인한 이름으로 기록됩니다. 다시 재려면 새 요청을 엽니다.'), submit);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const data = new FormData(form);
    const body = req.kind === 'measure' ? {value: Number(data.get('value'))} : {result: data.get('result')};
    body.note = data.get('note') || '';
    submit.setAttribute('disabled', '');
    try {
      await api(`/${encodeURIComponent(req.id)}/answer`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      await refresh();
      say('답을 남겼습니다.');
    } catch (error) {
      submit.removeAttribute('disabled');
      say(error.status === 409 ? '이미 다른 사람이 답했습니다. 목록을 새로 불러옵니다.' : error.message, 'error');
      if (error.status === 409) await refresh();
    }
  });
  return form;
}

function render(req) {
  const detail = $('detail');
  detail.replaceChildren();
  detail.hidden = false;
  detail.append(text('h3', req.question), text('p', `${KIND[req.kind] || req.kind} · ${req.item} · 열린 때 ${when(req.opened_at)}`));
  if (req.image) {
    const img = document.createElement('img');
    img.className = 'request-picture';
    img.src = `/api/calibration/v1/requests/${encodeURIComponent(req.id)}/image`;
    img.alt = '이 요청에 붙은 그림';
    detail.append(img);
  }
  const how = section('하는 방법');
  const steps = document.createElement('ol');
  steps.className = 'request-steps';
  for (const step of (req.kind === 'check' ? req.steps : req.how) || []) steps.append(text('li', step));
  how.append(steps);
  detail.append(how);
  if (req.kind === 'measure') detail.append(candidates(req));
  if (req.status === 'answered') {
    const a = req.answer;
    const done = section('답');
    const result = a.verdict ? `${a.value} ${a.unit} → ${a.verdict === 'neither' ? '어느 후보도 지지하지 않음' : a.verdict + ' 후보 지지'}` : VERDICT[a.result];
    done.append(text('p', result), text('p', `${a.by} · ${when(a.at)}`));
    if (a.note) done.append(text('p', `메모: ${a.note}`));
    detail.append(done);
  } else if (canOperate) {
    detail.append(answerForm(req));
  } else {
    detail.append(text('p', account?.enabled ? '답을 남기려면 보정 답 권한이 있는 계정이어야 합니다.' : '이 화면은 읽기 전용입니다. 답은 셀 PC에서 cell_requests.py answer로 남깁니다.'));
  }
}

async function show(id) {
  try {
    render(await api('/' + encodeURIComponent(id)));
    for (const link of document.querySelectorAll('#list a')) {
      if (link.hash === '#' + id) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
  } catch (error) { say(error.message, 'error'); }
}

window.addEventListener('hashchange', () => { selected = location.hash.slice(1); if (selected) show(selected); });
selected = location.hash.slice(1);
session.restore().then(refresh);
