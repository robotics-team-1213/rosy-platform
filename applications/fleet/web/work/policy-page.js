// D-793 /console/policy: 학습 정책 단계·승인 창·확인 요청·사고 잠금. 규칙은 서버가 판단한다.
import {createFleetClient} from '/common/fleet-client.js';
import {confirmIrreversible} from '/common/ui.js';
import {bindEstop, bindTopbarToggle, showSession, showSignedOut, tickClock, watchFleet} from '/console/assets/fleet-header.js';
import {
  ADMIN_REASON, OPERATOR_REASON, REASON_LABELS, RESOLUTION_LABELS, STAGE_LABELS, WINDOW_LABELS,
  errorText, executionVerdict, incidentLock, nextStage, proposalLock, remaining, roles, windowLock,
} from '/console/assets/policy-model.js';

const request = createFleetClient(), $ = id => document.getElementById(id);
// D-926 2: the same app bar as the other work screens, so the emergency stop and account stay in reach here.
bindEstop(request);
bindTopbarToggle();
tickClock();
setInterval(tickClock, 1000);
watchFleet(request);
let who = roles(null), state = null, busy = false;
const workcell = () => $('policy-workcell').value;
const base = () => `/api/fleet/workcells/${encodeURIComponent(workcell())}/policy`;

function element(tag, text = '', attrs = {}) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function button(label, lock, onClick, kind = 'quiet') {
  const node = element('ui-button', label, {kind});
  if (lock) { node.disabled = true; node.setAttribute('reason', lock); }
  node.addEventListener('click', () => onClick(node));
  return node;
}

function message(text, kind = 'warning') {
  $('policy-message').hidden = !text; $('policy-message').textContent = text || '';
  $('policy-message').setAttribute('state', kind);
}

async function post(path, body, success) {
  if (busy) return;
  busy = true;
  try {
    await request(base() + path, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body ?? {})});
    message(success, 'ready');
  }
  catch (error) { message(errorText(error)); }
  finally { busy = false; await refresh(); }
}

async function confirmed(opener, text, action, path, body, success) {
  if (await confirmIrreversible({message: text, action, opener})) await post(path, body, success);
}

function list(id, items, render, empty) {
  const target = $(id);
  target.replaceChildren(...(items.length ? items.map(render) : [element('li', empty)]));
}

function renderIncident(item) {
  const row = element('li');
  row.append(element('ui-tag', item.cleared_ns === null ? '잠금' : '해제됨',
    {status: item.cleared_ns === null ? 'crit' : 'neutral'}), element('span', ` ${item.description} — 신고 ${item.reported_by}`));
  if (item.cleared_ns === null) {
    row.append(button('잠금 해제…', incidentLock(item, who), node => confirmed(node,
      `"${item.description}" 사고 잠금을 해제할까요? 원인을 확인한 뒤에만 해제하세요.`, '잠금 해제',
      `/incidents/${item.incident_id}/clear`, {operator_confirmed: true, note: '원인 확인 후 해제'}, '사고 잠금을 해제했습니다.')));
  }
  return row;
}

function renderConfirmation(item) {
  const row = element('li');
  row.append(element('ui-tag', item.resolution ? RESOLUTION_LABELS[item.resolution] : '대기',
    {status: item.resolution ? 'neutral' : 'warn'}),
  element('span', ` ${REASON_LABELS[item.reason] || item.reason}${item.policy_revision ? ` · ${item.policy_revision}` : ''} — ${item.created_by}`),
  element('pre', JSON.stringify(item.evidence, null, 2), {class: 'policy-evidence'}));
  if (!item.resolution) {
    const actions = element('ui-actions');
    for (const resolution of state.rules.resolutions) {
      actions.append(button(`${RESOLUTION_LABELS[resolution]}…`, who.admin ? '' : ADMIN_REASON, node => confirmed(node,
        `"${REASON_LABELS[item.reason] || item.reason}" 확인 요청을 ${RESOLUTION_LABELS[resolution]}으로 처리할까요?`
          + (resolution === 'resume' ? ' 팔 제어 보류는 관제의 팔 복구에서 따로 풉니다.' : ' 열린 승인 창이 닫힙니다.'),
        RESOLUTION_LABELS[resolution], `/confirmations/${item.confirmation_id}/resolve`,
        {operator_confirmed: true, resolution, note: `${RESOLUTION_LABELS[resolution]} (콘솔)`}, '확인 요청을 처리했습니다.')));
    }
    row.append(actions);
  }
  return row;
}

function renderWindow(item) {
  const row = element('li');
  const status = item.active ? '열림' : item.approved_by ? '닫힘' : item.closed_ns ? '취소됨' : '승인 대기';
  row.append(element('ui-tag', status, {status: item.active ? 'active' : item.approved_by || item.closed_ns ? 'neutral' : 'warn'}),
    element('span', ` ${WINDOW_LABELS[item.kind]} · ${item.policy_revision} · ${item.scope} — 요청 ${item.requested_by}`
      + (item.active ? ` · ${remaining(item.expires_ns, state.now_ns)} 남음` : '')));
  if (!item.approved_by && !item.closed_ns) {
    row.append(button('승인…', windowLock(item, state.rules, who), node => confirmed(node,
      `${item.policy_revision}의 ${WINDOW_LABELS[item.kind]} 승인 창을 열까요? ${item.minutes}분 동안 "${item.scope}" 범위로 실행될 수 있습니다.`,
      '승인 창 열기', `/windows/${item.window_id}/approve`, {operator_confirmed: true}, '승인 창을 열었습니다.')));
  }
  if (item.active || (!item.approved_by && !item.closed_ns)) {
    row.append(button('닫기', who.operator ? '' : OPERATOR_REASON, () => post(`/windows/${item.window_id}/close`,
      {operator_confirmed: true, reason: '콘솔에서 닫음'}, '승인 창을 닫았습니다.')));
  }
  return row;
}

function renderStage(item) {
  return element('li', `${item.policy_revision} — ${STAGE_LABELS[item.stage]} · 작업대 ${item.rig_revision} · 보정 ${item.calibration_revision}`);
}

function renderProposal(item) {
  const row = element('li');
  row.append(element('ui-tag', item.state === 'PENDING' ? '대기' : item.state === 'APPROVED' ? '승인됨' : '거절됨',
    {status: item.state === 'PENDING' ? 'warn' : 'neutral'}),
  element('span', ` ${item.policy_revision}: ${STAGE_LABELS[item.from_stage] || '미등록'} → ${STAGE_LABELS[item.to_stage]} — 제안 ${item.proposed_by} · ${item.note}`));
  if (item.state === 'PENDING') {
    row.append(button('승인…', proposalLock(item, state.rules, who), node => confirmed(node,
      `${item.policy_revision}을(를) ${STAGE_LABELS[item.to_stage]}로 올릴까요? 근거 ${item.evidence_sha256.slice(0, 12)}…`,
      '단계 승인', `/proposals/${item.proposal_id}/decision`, {operator_confirmed: true, approve: true}, '단계를 승인했습니다.')),
    button('거절…', who.admin ? '' : ADMIN_REASON, node => confirmed(node,
      `"${item.policy_revision}"의 ${STAGE_LABELS[item.to_stage]} 제안을 거절할까요?`, '제안 거절',
      `/proposals/${item.proposal_id}/decision`, {operator_confirmed: true, approve: false}, '제안을 거절했습니다.')));
  }
  return row;
}

function render() {
  $('policy-content').hidden = false;
  const verdict = executionVerdict(state);
  $('policy-verdict').textContent = verdict.text; $('policy-verdict').setAttribute('state', verdict.state);
  list('policy-incidents', state.incidents, renderIncident, '사고 기록이 없습니다.');
  list('policy-confirmations', state.confirmations, renderConfirmation, '확인 요청이 없습니다.');
  list('policy-windows', state.windows, renderWindow, '승인 창 기록이 없습니다.');
  list('policy-stages', state.policies, renderStage, '등록된 정책이 없습니다. 학습 결과를 0단계로 등록하세요.');
  list('policy-proposals', state.proposals, renderProposal, '단계 제안 기록이 없습니다.');
  const policies = $('policy-window-policy'), chosen = policies.value;
  policies.replaceChildren(...state.policies.map(item => element('option', `${item.policy_revision} (${STAGE_LABELS[item.stage] || item.stage})`, {value: item.policy_revision})));
  if (chosen) policies.value = chosen;
  if (!$('policy-window-kind').options.length) {
    for (const [kind, rule] of Object.entries(state.rules.windows)) {
      $('policy-window-kind').append(element('option', `${WINDOW_LABELS[kind]} · ${rule.min_stage} 이상 · 기본 ${rule.default_minutes}분, 최대 ${rule.max_minutes}분`, {value: kind}));
    }
  }
  for (const id of ['policy-window-request', 'policy-proposal-submit']) {
    $(id).disabled = !who.admin; who.admin ? $(id).removeAttribute('reason') : $(id).setAttribute('reason', ADMIN_REASON);
  }
  for (const id of ['policy-incident-report', 'policy-sync-owner']) {
    $(id).disabled = !who.operator; who.operator ? $(id).removeAttribute('reason') : $(id).setAttribute('reason', OPERATOR_REASON);
  }
}

async function refresh() {
  if (!workcell()) return;
  try { state = await request(base()); render(); }
  catch (error) {
    $('policy-content').hidden = true;
    $('policy-verdict').textContent = errorText(error); $('policy-verdict').setAttribute('state', 'unavailable');
  }
}

$('policy-incident-report').addEventListener('click', async () => {
  const text = $('policy-incident-text').value.trim();
  if (!text) { message('사고 내용을 적어 주세요.'); return; }
  await confirmed($('policy-incident-report'), `"${text}" 사고를 신고할까요? 이 작업셀의 승인 창이 모두 닫힙니다.`, '사고 신고',
    '/incidents', {operator_confirmed: true, description: text}, '사고를 신고했습니다. 승인 창이 닫혔습니다.');
  $('policy-incident-text').value = '';
});
$('policy-sync-owner').addEventListener('click', () => post('/confirmations/sync-owner', undefined, '팔 제어 상태를 가져왔습니다.'));
$('policy-window-request').addEventListener('click', () => {
  const minutes = $('policy-window-minutes').value, policy = state?.policies.find(item => item.policy_revision === $('policy-window-policy').value);
  if (!policy || !$('policy-window-scope').value.trim()) { message('정책과 허용 범위를 고르세요.'); return; }
  post('/windows', {operator_confirmed: true, policy_revision: policy.policy_revision, kind: $('policy-window-kind').value,
    minutes: minutes ? Number(minutes) : null, scope: $('policy-window-scope').value.trim(),
    rig_revision: policy.rig_revision, calibration_revision: policy.calibration_revision}, '승인 창을 요청했습니다. 다른 관리자의 승인이 필요할 수 있습니다.');
});
$('policy-proposal-submit').addEventListener('click', () => {
  const revision = $('policy-proposal-revision').value.trim();
  const current = state?.policies.find(item => item.policy_revision === revision);
  const target = nextStage(state.rules, current?.stage);
  if (!target) { message('이미 마지막 단계입니다.'); return; }
  if (!$('policy-proposal-form').reportValidity()) return;
  post('/proposals', {operator_confirmed: true, policy_revision: revision, to_stage: target,
    rig_revision: $('policy-proposal-rig').value.trim(), calibration_revision: $('policy-proposal-cal').value.trim(),
    evidence_sha256: $('policy-proposal-evidence').value.trim(), note: $('policy-proposal-note').value.trim()},
  `${STAGE_LABELS[target]} 제안을 올렸습니다.`);
});
for (const form of ['policy-incident-form', 'policy-window-form', 'policy-proposal-form']) {
  $(form).addEventListener('submit', event => event.preventDefault());
}
$('policy-workcell').addEventListener('change', refresh);

async function start() {
  try {
    const session = await request('/api/fleet/auth/session');
    who = roles(session);
    showSession(session);
    const {workcells} = await request('/api/fleet/policy-governance/workcells');
    $('policy-workcell').replaceChildren(...workcells.map(id => element('option', id, {value: id})));
    $('policy-workcell').hidden = !workcells.length;
    document.querySelector('[for="policy-workcell"]').hidden = !workcells.length;
    if (!workcells.length) {
      $('policy-verdict').textContent = '설정된 OMX 작업셀이 없습니다. 사이트 설치 담당자에게 작업셀 등록을 요청하세요.';
      $('policy-verdict').setAttribute('state', 'empty'); return;
    }
    await refresh();
    setInterval(refresh, 2000);
  } catch (error) {
    $('policy-verdict').textContent = errorText(error); $('policy-verdict').setAttribute('state', 'unavailable');
    $('policy-login').hidden = error.status !== 401;
    if (error.status === 401) showSignedOut();
  }
}
start();
