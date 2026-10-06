import {createFleetClient} from '/common/fleet-client.js';
import {confirmIrreversible} from '/common/ui.js';
import {renderStructuredDocument} from '/console/assets/cell-document-editor.js';

const $ = id => document.getElementById(id);
const JOB_STATUS_LABEL = {
  PROPOSED: '제안됨 · 승인 대기', READY: '실행 대기', RUNNING: '실행 중',
  ACTION_SUCCEEDED: '장치 동작 완료 · 목표 확인 대기', GOAL_CONFIRMED: '목표 확인 완료',
  HOLD: '작업 보류', WAITING: '시작 대기',
};
const JOB_REASON_LABEL = {
  CANCELLED_BY_OPERATOR: '운영자가 취소함',
  OPERATOR_SHEET_ACCESS_UNAVAILABLE: '작업자 간지 접근 확인 필요',
  SITE_AUTHORITY_CHANGED: '사이트 제어 권한 변경 · 재확인 필요',
  FLEET_FENCE_CHANGED_BEFORE_SUBMISSION: '전송 전 정지 세대 변경',
  FLEET_CLAIM_MISSING_BEFORE_SUBMISSION: '전송 전 장치 예약 확인 불가',
  site_stop: '사이트 정지 · 실제 장치 상태 확인 필요',
};
function jobStatusLabel(status, reason) {
  return reason === 'CANCELLED_BY_OPERATOR' ? '작업 취소됨' : JOB_STATUS_LABEL[status] || '상태 확인 필요';
}
function jobReasonLabel(reason) {
  return !reason ? '' : JOB_REASON_LABEL[reason] || '사유 확인 필요 · 진행 원장 상세를 확인하세요';
}
$('credential').value = sessionStorage.getItem('rosy-console-token') || '';
const request = createFleetClient({credential: () => $('credential').value, origin: location.origin});
function stopNotice(message, state) {
  const notice = $('estop-feedback');
  notice.textContent = message;
  notice.setAttribute('state', state);
  notice.hidden = false;
}
$('estop').addEventListener('click', async () => {
  stopNotice('비상 정지 요청 중…', 'pending');
  try {
    const result = await request('/api/fleet/estop', {method: 'POST'});
    const summary = result.total > 0
      ? `정지 요청 응답: ${result.stopped}/${result.total} · 물리 정지 미확인`
      : '정지 요청 대상 로봇 없음 — 등록 목록과 현장 상태를 확인하세요.';
    stopNotice(summary, result.total > 0 && result.stopped === result.total ? 'warning' : 'error');
  } catch (error) {
    stopNotice(error.status >= 500 || !error.status
      ? '비상 정지 결과 확인 불가 — Fleet 연결과 로봇 상태를 즉시 확인하세요.'
      : `비상 정지 요청 거절 — ${error.message}`, 'error');
  }
});
let editEpoch = 0;
async function api(path, options) {
  const epoch = editEpoch;
  const result = await request(path, options);
  if (epoch !== editEpoch) throw new Error('입력 또는 계정이 바뀌었습니다. 현재 문서와 작업 상태를 다시 확인하세요.');
  return result;
}
const revisions = new Map();
let previewRefs = null;
let role = null;
let busy = false;
let job = null;
let jobGeneration = null;
let layoutData = null;
const commands = ['recipe-save', 'cell-save', 'compile', 'propose', 'admit', 'reconcile', 'resume', 'cancel'];
const jobActionLabels = {admit: '실행 승인', reconcile: '실제 상태를 대조', resume: '재승인', cancel: '취소'};
function invalidate() {
  previewRefs = null; layoutData = null;
  $('summary').setAttribute('state', 'unavailable');
  $('summary').textContent = '저장한 레시피와 셀을 기준으로 계획을 계산합니다.';
  $('preview').textContent = ''; $('layout').replaceChildren(); $('layout-layer').replaceChildren(); $('layout-preview').hidden = true; refreshControls();
}
function clearSession() {
  role = null; job = null; jobGeneration = null; invalidate();
  $('session').textContent = '접속 전';
  revisions.clear();
  for (const kind of ['recipe', 'cell']) {
    $(kind + '-revision').setAttribute('state', 'empty');
    $(kind + '-revision').textContent = '저장 전';
  }
  $('proposal').textContent = '';
  $('job-state').textContent = '';
  $('job-summary').textContent = '작업 ID로 상태를 확인하세요.';
  $('step-progress').replaceChildren(); $('sheet-progress').replaceChildren();
  $('saved').hidden = true;
  $('saved-status').hidden = false;
  $('saved-status').setAttribute('state', 'unavailable');
  $('saved-status').textContent = '접속하면 저장된 문서를 확인할 수 있습니다.';
}
function refreshControls() {
  for (const field of document.querySelectorAll('input, textarea, select')) {
    field.disabled = busy;
    field.setAttribute('reason', busy ? '요청 처리 중 · 입력 잠시 잠금' : '');
    field.setAttribute('aria-describedby', 'notice');
  }
  for (const control of document.querySelectorAll('[data-document-edit]')) {
    control.disabled = busy;
    control.setAttribute('reason', busy ? '요청 처리 중' : '');
  }
  for (const id of ['connect', 'recipe-load', 'cell-load', 'read-job', 'new-proposal']) {
    $(id).disabled = busy;
    $(id).setAttribute('reason', busy ? '요청 처리 중' : '');
  }
  for (const id of commands) {
    const sheetBlocked = id === 'resume' && job?.operator_checkpoints?.some(row => row.status === 'WAITING_ACCESS');
    const needsJob = id in jobActionLabels;
    const jobAllowed = !needsJob || (job && job.mission_id === $('mission-id').value &&
      (id === 'admit' ? job.status === 'PROPOSED' : id === 'cancel' ? ['READY', 'ACTION_SUCCEEDED', 'HOLD'].includes(job.status) && job.reason !== 'CANCELLED_BY_OPERATOR' : job.status === 'HOLD' && job.reason !== 'CANCELLED_BY_OPERATOR'));
    const allowed = role === 'operator' && !busy && jobAllowed && !sheetBlocked && (id !== 'propose' || previewRefs !== null);
    let reason = '';
    if (!allowed) {
      reason = '저장 후 미리보기 필요';
      if (needsJob && !jobAllowed) reason = job?.mission_id === $('mission-id').value
        ? `현재 작업 상태에서는 ${jobActionLabels[id]}할 수 없습니다` : '작업 상태를 먼저 확인하세요';
      if (sheetBlocked) reason = '작업자 간지 삽입 확인 대기';
      if (role !== 'operator') reason = '운영자 접속 필요';
      if (busy) reason = '요청 처리 중';
    }
    $(id).disabled = !allowed;
    $(id).setAttribute('reason', reason);
  }
}
async function action(fn) {
  if (busy) return;
  busy = true; refreshControls();
  $('notice').textContent = '요청 처리 중 · 입력 잠시 잠금';
  try { await fn(); } catch (error) {
    if (error.status === 401 || error.status === 403) clearSession();
    else if (error.status === 409) { job = null; jobGeneration = null; }
    $('notice').textContent = error.status === 403
      ? '이 계정에는 Cell 작업 권한이 없습니다. 운영자 토큰을 확인하고 다시 접속하세요.' : error.message;
    if (error.status === 401 || error.status === 403) $('notice').scrollIntoView({block: 'center'});
  }
  finally { busy = false; refreshControls(); }
}
function post(path, body) { return api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); }
function references() {
  const result = {};
  for (const kind of ['recipe', 'cell']) {
    const id = $(kind + '-id').value;
    const revision = revisions.get(kind);
    if (!revision || revision.id !== id || revision.text !== $(kind + '-document').value) throw new Error('문서를 먼저 저장하거나 불러오세요.');
    result[kind + '_id'] = id; result[kind + '_digest'] = revision.digest;
  }
  return result;
}
async function list() {
  const saved = $('saved'), status = $('saved-status');
  saved.hidden = true;
  status.hidden = false;
  status.setAttribute('state', 'pending');
  status.textContent = '저장된 문서를 확인하는 중입니다.';
  let result;
  try { result = await api('/api/fleet/cell-app/documents'); }
  catch (error) {
    status.setAttribute('state', 'error');
    status.textContent = '저장된 문서를 확인하지 못했습니다. 접속 상태를 확인하고 다시 시도하세요.';
    throw error;
  }
  saved.replaceChildren(...result.documents.map(item => {
    const li = document.createElement('li'); li.textContent = `${item.kind} · ${item.id} · ${item.updated_at}`; return li;
  }));
  saved.hidden = result.documents.length === 0;
  status.hidden = result.documents.length > 0;
  if (!status.hidden) {
    status.setAttribute('state', 'empty');
    status.textContent = '저장된 문서가 없습니다. 위에서 레시피와 셀 문서를 작성하고 저장하세요.';
  }
}
function loaded(kind, revision) {
  const text = JSON.stringify(revision.document, null, 2);
  $(kind + '-document').value = text;
  revisions.set(kind, {...revision, text});
  $(kind + '-revision').setAttribute('state', 'ready');
  $(kind + '-revision').textContent = `저장된 버전 ${revision.digest.slice(0, 12)}`;
  invalidate();
  if (kind === 'recipe') recipeFields(revision.document);
  else cellFields(revision.document);
}
function cellFields(cell) {
  structuredFields('cell', cell);
  $('cell-fields').replaceChildren();
  for (const [path, title] of [
    [['kinematics_revision'], '장치 URDF revision'],
    [['approach_clearance_m'], '접근 여유 (m)'], [['fingertip_overhang_m'], '손가락 돌출 (m)'],
    ...['x', 'y', 'z', 'yaw'].map(axis => [['home', axis], `home ${axis} (${axis === 'yaw' ? 'rad' : 'm'})`])]) {
    const value = path.reduce((object, key) => object?.[key], cell);
    if (value === undefined) continue;
    const label = document.createElement('label'); label.textContent = title;
    const input = document.createElement('input'); input.className = 'ui-field';
    input.type = typeof value === 'number' ? 'number' : 'text'; input.step = 'any'; input.value = value;
    input.disabled = busy; input.setAttribute('reason', busy ? '요청 처리 중 · 입력 잠시 잠금' : '');
    input.setAttribute('aria-describedby', 'notice');
    input.addEventListener('input', () => {
      editEpoch++; invalidate();
      try {
        const document = JSON.parse($('cell-document').value);
        const parent = path.slice(0, -1).reduce((object, key) => object[key], document);
        parent[path.at(-1)] = input.type === 'number' ? (input.value === '' ? null : Number(input.value)) : input.value;
        $('cell-document').value = JSON.stringify(document, null, 2);
      } catch { $('notice').textContent = '셀 티칭 문서를 확인한 뒤 불러오세요.'; }
    });
    label.append(input); $('cell-fields').append(label);
  }
}
function recipeFields(recipe) {
  structuredFields('recipe', recipe);
  $('recipe-fields').replaceChildren();
  for (const [field, title, unit, parent] of [
    ['length', '박스 길이', 'm', 'box'], ['width', '박스 폭', 'm', 'box'],
    ['height', '박스 높이', 'm', 'box'], ['mass_kg', '박스 질량', 'kg', 'box'],
    ['grasp_depth', '잡는 깊이', 'm', 'box'], ['gap', '박스 사이 간격', 'm', null]]) {
    const value = parent ? recipe[parent]?.[field] : recipe[field];
    if (value === undefined) continue;
    const label = document.createElement('label'); label.textContent = `${title} (${unit})`;
    const input = document.createElement('input'); input.className = 'ui-field';
    input.disabled = busy;
    input.setAttribute('reason', busy ? '요청 처리 중 · 입력 잠시 잠금' : '');
    input.setAttribute('aria-describedby', 'notice');
    input.type = 'number'; input.step = 'any'; input.value = value;
    input.addEventListener('input', () => {
      editEpoch++; invalidate();
      try {
        const document = JSON.parse($('recipe-document').value);
        const number = input.value === '' ? null : Number(input.value);
        if (parent) document[parent][field] = number; else document[field] = number;
        $('recipe-document').value = JSON.stringify(document, null, 2);
      } catch { $('notice').textContent = '레시피 문서를 확인한 뒤 불러오세요.'; }
    });
    label.append(input); $('recipe-fields').append(label);
  }
}
function structuredFields(kind, value) {
  renderStructuredDocument(kind, value, $(kind + '-structure'), (mutate, redraw = false) => {
    if (busy) return;
    editEpoch++; invalidate();
    try {
      const draft = JSON.parse($(kind + '-document').value);
      mutate(draft);
      $(kind + '-document').value = JSON.stringify(draft, null, 2);
      if (redraw) structuredFields(kind, draft);
      $(kind + '-revision').setAttribute('state', 'warning');
      $(kind + '-revision').textContent = '수정한 문서 · 저장 전';
      refreshControls();
    } catch { $('notice').textContent = '문서 구조를 확인한 뒤 불러오세요.'; }
  });
  refreshControls();
}
for (const kind of ['recipe', 'cell']) {
  for (const part of ['id', 'document']) $(kind + '-' + part).addEventListener('input', () => {
    editEpoch++; invalidate();
    $(kind + '-revision').setAttribute('state', 'warning');
    $(kind + '-revision').textContent = '수정한 문서 · 저장 전';
    if (part === 'document') {
      try { const document = JSON.parse($(kind + '-document').value); if (kind === 'recipe') recipeFields(document); else cellFields(document); }
      catch { $(kind + '-fields').replaceChildren(); $(kind + '-structure').replaceChildren(); }
    }
  });
  $(kind + '-file').addEventListener('change', async () => {
    const file = $(kind + '-file').files[0];
    $(kind + '-file-name').textContent = file?.name || '선택한 파일 없음';
    if (!file || busy) return;
    editEpoch++; invalidate(); const epoch = editEpoch;
    await action(async () => {
      if (file.size > 64 * 1024) throw new Error('문서는 64 KiB 이하 파일을 선택하세요.');
      const document = JSON.parse(await file.text());
      if (epoch !== editEpoch) return;
      if (!document || typeof document !== 'object' || Array.isArray(document)) throw new Error('문서는 JSON object여야 합니다.');
      $(kind + '-document').value = JSON.stringify(document, null, 2);
      if (kind === 'recipe') recipeFields(document); else cellFields(document);
      $(kind + '-revision').setAttribute('state', 'warning');
      $(kind + '-revision').textContent = '가져온 문서 · 저장 전';
      $('notice').textContent = '파일을 불러왔습니다. 이름과 설정을 확인하고 저장하세요.';
    });
  });
  $(kind + '-load').addEventListener('click', () => action(async () => {
    loaded(kind, await api(`/api/fleet/cell-app/documents/${kind}/${encodeURIComponent($(kind + '-id').value)}`));
    $('notice').textContent = '저장된 문서를 불러왔습니다.';
  }));
  $(kind + '-save').addEventListener('click', () => action(async () => {
    const id = $(kind + '-id').value, previous = revisions.get(kind);
    const status = $(kind + '-revision');
    status.setAttribute('state', 'pending');
    status.textContent = '저장 요청 중 · 결과 확인 대기';
    let revision;
    try {
      revision = await post(`/api/fleet/cell-app/documents/${kind}/${encodeURIComponent(id)}`, {
        document: JSON.parse($(kind + '-document').value),
        expected_digest: previous?.id === id ? previous.digest : null,
      });
    } catch (error) {
      status.setAttribute('state', 'error');
      status.textContent = error.status === 409
        ? '저장 충돌 · 작성 내용을 복사한 뒤 최신 문서를 불러와 비교하세요.'
        : error instanceof SyntaxError ? '저장 전 JSON 형식을 확인하세요.'
        : error.status && error.status < 500 ? '저장 거절 · 문서 형식과 권한을 확인하세요.'
        : '저장 결과 확인 불가 · 문서 목록과 최신 버전을 확인한 뒤 다시 시도하세요.';
      throw error;
    }
    loaded(kind, revision); await list(); $('notice').textContent = '문서 저장 완료 · 실행 가능 여부는 미리보기에서 확인하세요.';
  }));
}
$('credential').addEventListener('input', () => {
  editEpoch++; clearSession();
  $('notice').textContent = '운영자 계정으로 접속해 저장된 레시피와 셀을 준비하세요.';
});
$('connect').addEventListener('click', () => action(async () => {
  const session = await api('/api/fleet/session'); role = session.role;
  $('session').textContent = `${session.principal_id} · ${role}`;
  await list(); $('notice').textContent = '접속 완료 · 문서를 준비하세요.';
}));
$('compile').addEventListener('click', () => action(async () => {
  invalidate();
  let refs, result;
  try { refs = references(); result = await post('/api/fleet/cell-app/compile', refs); }
  catch (error) {
    $('summary').setAttribute('state', refs ? 'error' : 'warning');
    $('summary').textContent = !refs
      ? '미리보기 전에 두 문서를 저장하거나 불러오세요.'
      : error.status === 409
      ? '미리보기 실패 · 저장된 문서가 바뀌었습니다. 최신 문서를 불러와 확인하세요.'
      : error.status && error.status < 500
      ? '미리보기 거절 · 문서 형식과 권한을 확인한 뒤 다시 확인하세요.'
      : '미리보기 결과 확인 불가 · 문서와 연결 상태를 확인하고 다시 확인하세요.';
    throw error;
  }
  previewRefs = refs;
  $('summary').setAttribute('state', 'ready');
  $('summary').textContent = `${result.summary.transfer_count}회 전송 · 팔레트 완료 표시 ${result.summary.pallet_markers.length}개`;
  $('preview').textContent = JSON.stringify(result.candidate.job, null, 2);
  layoutData = result.candidate;
  const places = result.candidate.job.steps.filter(step => step.kind === 'place' && step.target);
  const groups = [...new Set(places.map(step => `${step.pallet}|${step.layer}`))];
  $('layout-layer').replaceChildren(...groups.map(group => {
    const option = document.createElement('option'); option.value = group;
    const [pallet, layer] = group.split('|'); option.textContent = `${pallet} · ${Number(layer) + 1}층`; return option;
  }));
  $('layout-preview').hidden = !groups.length;
  renderLayout();
  if (!$('request-key').value) $('request-key').value = crypto.randomUUID();
  $('notice').textContent = '미리보기 완료 · 내용을 확인하고 작업 범위를 입력하세요.';
}));
$('propose').addEventListener('click', () => action(async () => {
  if (!previewRefs) throw new Error('미리보기를 먼저 확인하세요.');
  if (JSON.stringify(references()) !== JSON.stringify(previewRefs)) throw new Error('문서가 바뀌었습니다. 미리보기를 다시 확인하세요.');
  const result = await post('/api/fleet/cell-app/proposals', {...previewRefs,
    request_key: $('request-key').value, workcell_id: $('workcell').value, instance_id: $('instance').value});
  $('proposal').textContent = `제안 ${result.proposal.proposal_id}\n상태 ${jobStatusLabel(result.mission?.status || result.proposal.state)}\n운영자 별도 승인 대기`;
  $('mission-id').value = result.proposal.proposal_id;
  job = null;
  $('notice').textContent = '제안 완료 · 관제에서 별도 승인 후 진행 상태를 확인하세요.';
}));
function renderLayout() {
  if (!layoutData) return;
  const places = layoutData.job.steps.filter(step => step.kind === 'place' && step.target && `${step.pallet}|${step.layer}` === $('layout-layer').value);
  if (!places.length) return;
  const xs = places.map(step => step.target.x), ys = places.map(step => step.target.y);
  const minX = Math.min(...xs), minY = Math.min(...ys);
  const box = layoutData.recipe.box;
  const margin = Math.max(box.length, box.width);
  const spanX = Math.max(...xs) - minX + margin, spanY = Math.max(...ys) - minY + margin;
  const scale = Math.min(680 / spanX, 230 / spanY);
  const ns = 'http://www.w3.org/2000/svg';
  $('layout').replaceChildren(...places.flatMap((step, ordinal) => {
    const x = 60 + (step.target.x - minX + margin / 2) * scale, y = 260 - (step.target.y - minY + margin / 2) * scale;
    const pallet = layoutData.recipe.pallets.find(item => item.id === step.pallet);
    const geometry = step.item === 'box' ? box : pallet;
    const width = geometry.length * scale, height = geometry.width * scale;
    const point = document.createElementNS(ns, 'rect');
    point.setAttribute('x', x - width / 2); point.setAttribute('y', y - height / 2);
    point.setAttribute('width', width); point.setAttribute('height', height);
    point.setAttribute('transform', `rotate(${-step.target.yaw * 180 / Math.PI} ${x} ${y})`);
    const label = document.createElementNS(ns, 'text'); label.setAttribute('x', x + 8); label.setAttribute('y', y);
    label.textContent = `${ordinal + 1} · ${step.pallet} · ${step.layer + 1}층`;
    return [point, label];
  }));
}
$('layout-layer').addEventListener('change', renderLayout);
async function readJob() {
  const id = $('mission-id').value;
  job = null; jobGeneration = null;
  $('job-state').textContent = '현재 상태 확인 중';
  $('job-summary').textContent = '현재 상태 확인 중'; $('step-progress').replaceChildren();
  $('sheet-progress').replaceChildren();
  const result = await api(`/api/fleet/cell-jobs/${encodeURIComponent(id)}`);
  const control = await api('/api/fleet/dispatch-control');
  jobGeneration = control.generation;
  job = result.job; $('job-state').textContent = JSON.stringify(job, null, 2);
  $('job-summary').textContent = `${jobStatusLabel(job.status, job.reason)} · ${job.steps.length}단계 중 ${job.current_step_index + 1}단계${job.reason ? ' · ' + jobReasonLabel(job.reason) : ''}`;
  $('step-progress').replaceChildren(...job.steps.map(step => {
    const li = document.createElement('li');
    const inputs = step.step.inputs;
    li.textContent = `${step.step_index + 1} · ${inputs.pallet_id} · ${inputs.layer_index + 1}층 · ${inputs.item} · ${jobStatusLabel(step.status, step.reason)}${step.reason ? ' · ' + jobReasonLabel(step.reason) : ''}`;
    return li;
  }));
  $('sheet-progress').replaceChildren(...(job.operator_checkpoints ?? []).map(row => {
    const li = document.createElement('li');
    const instruction = row.status === 'WAITING_ACCESS' ?
      '삽입 확인 대기 · 작업자 접근 허가가 확인되지 않아 아직 진행할 수 없습니다' : '간지 지점 도달 전';
    li.textContent = `${row.pallet_id} · ${row.layer_index + 1}층 · ${row.thickness_m * 1000} mm · ${instruction}`;
    return li;
  }));
  $('notice').textContent = `작업 ${jobStatusLabel(job.status, job.reason)}${job.reason ? ' · ' + jobReasonLabel(job.reason) : ''} · 확인한 정지 세대 ${jobGeneration}`;
}
$('mission-id').addEventListener('input', () => { editEpoch++; job = null; jobGeneration = null; refreshControls(); });
$('read-job').addEventListener('click', () => action(readJob));
$('new-proposal').addEventListener('click', () => {
  if (busy) return;
  $('request-key').value = crypto.randomUUID(); $('proposal').textContent = '';
  $('notice').textContent = '새 요청 키를 준비했습니다. 앞선 요청의 결과가 불명확하면 먼저 작업 ID로 상태를 확인하세요.';
});
for (const command of ['admit', 'resume', 'reconcile', 'cancel']) {
  $(command).addEventListener('click', async () => {
    if (command === 'cancel') {
      if (busy || role !== 'operator' || !job || job.mission_id !== $('mission-id').value) return;
      const id = job.mission_id, epoch = editEpoch;
      const allowed = await confirmIrreversible({
        message: `작업 "${id}"을 취소할까요? 작업 취소는 실행 중인 장치를 정지하지 않습니다. 실제 장치 상태를 확인하세요.`,
        action: '작업 취소', opener: $(command),
      });
      if (!allowed || busy || epoch !== editEpoch || role !== 'operator' || job?.mission_id !== id) return;
    }
    await action(async () => {
      if (!job || job.mission_id !== $('mission-id').value) throw new Error('작업 상태를 먼저 확인하세요.');
      if (command === 'resume' && job.operator_checkpoints?.some(row => row.status === 'WAITING_ACCESS')) {
        throw new Error('작업자 간지 삽입 확인 대기 · 일반 재승인으로 진행할 수 없습니다.');
      }
      const id = encodeURIComponent(job.mission_id);
      let body = {};
      if (command === 'admit' || command === 'resume') {
        if (jobGeneration === null) throw new Error('정지 세대를 확인하려면 작업 상태를 다시 읽으세요.');
        body = {expected_generation: jobGeneration};
      }
      const path = command === 'admit' ? `/api/fleet/missions/${id}/admit` : `/api/fleet/cell-jobs/${id}/${command}`;
      await post(path, body); await readJob();
    });
  });
}
refreshControls();
