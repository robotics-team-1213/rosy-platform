import {createFleetClient} from '/common/fleet-client.js';
import {renderStructuredDocument} from '/console/assets/cell-document-editor.js';

const $ = id => document.getElementById(id);
const request = createFleetClient({credential: () => $('credential').value, origin: location.origin});
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
function invalidate() { previewRefs = null; layoutData = null; $('preview').textContent = ''; $('layout').replaceChildren(); $('layout-layer').replaceChildren(); refreshControls(); }
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
    const needsJob = ['admit', 'reconcile', 'resume', 'cancel'].includes(id);
    const jobAllowed = !needsJob || (job && job.mission_id === $('mission-id').value &&
      (id === 'admit' ? job.status === 'PROPOSED' : id === 'cancel' ? ['READY', 'ACTION_SUCCEEDED', 'HOLD'].includes(job.status) && job.reason !== 'CANCELLED_BY_OPERATOR' : job.status === 'HOLD' && job.reason !== 'CANCELLED_BY_OPERATOR'));
    const allowed = role === 'operator' && !busy && jobAllowed && !sheetBlocked && (id !== 'propose' || previewRefs !== null);
    $(id).disabled = !allowed;
    if (!allowed) $(id).setAttribute('reason', busy ? '요청 처리 중' : role !== 'operator' ? '운영자 접속 필요' :
      sheetBlocked ? '작업자 간지 삽입 확인 대기' : '저장 후 미리보기 필요');
    else $(id).removeAttribute('reason');
  }
}
async function action(fn) {
  if (busy) return;
  busy = true; refreshControls();
  $('notice').textContent = '요청 처리 중 · 입력 잠시 잠금';
  try { await fn(); } catch (error) {
    if (error.status === 409 || error.status === 401 || error.status === 403) { job = null; jobGeneration = null; }
    $('notice').textContent = error.message;
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
  const result = await api('/api/fleet/cell-app/documents');
  $('saved').replaceChildren(...result.documents.map(item => {
    const li = document.createElement('li'); li.textContent = `${item.kind} · ${item.id} · ${item.updated_at}`; return li;
  }));
}
function loaded(kind, revision) {
  const text = JSON.stringify(revision.document, null, 2);
  $(kind + '-document').value = text;
  revisions.set(kind, {...revision, text});
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
      $(kind + '-revision').textContent = '수정한 문서 · 저장 전';
      refreshControls();
    } catch { $('notice').textContent = '문서 구조를 확인한 뒤 불러오세요.'; }
  });
  refreshControls();
}
for (const kind of ['recipe', 'cell']) {
  for (const part of ['id', 'document']) $(kind + '-' + part).addEventListener('input', () => {
    editEpoch++; invalidate();
    if (part === 'document') {
      try { const document = JSON.parse($(kind + '-document').value); if (kind === 'recipe') recipeFields(document); else cellFields(document); }
      catch { $(kind + '-fields').replaceChildren(); $(kind + '-structure').replaceChildren(); }
    }
  });
  $(kind + '-file').addEventListener('change', async () => {
    const file = $(kind + '-file').files[0];
    if (!file || busy) return;
    editEpoch++; invalidate(); const epoch = editEpoch;
    await action(async () => {
      if (file.size > 64 * 1024) throw new Error('문서는 64 KiB 이하 파일을 선택하세요.');
      const document = JSON.parse(await file.text());
      if (epoch !== editEpoch) return;
      if (!document || typeof document !== 'object' || Array.isArray(document)) throw new Error('문서는 JSON object여야 합니다.');
      $(kind + '-document').value = JSON.stringify(document, null, 2);
      if (kind === 'recipe') recipeFields(document); else cellFields(document);
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
    const revision = await post(`/api/fleet/cell-app/documents/${kind}/${encodeURIComponent(id)}`, {
      document: JSON.parse($(kind + '-document').value),
      expected_digest: previous?.id === id ? previous.digest : null,
    });
    loaded(kind, revision); await list(); $('notice').textContent = '문서 저장 완료 · 실행 가능 여부는 미리보기에서 확인하세요.';
  }));
}
$('credential').addEventListener('input', () => { editEpoch++; role = null; job = null; jobGeneration = null; invalidate(); });
$('connect').addEventListener('click', () => action(async () => {
  const session = await api('/api/fleet/session'); role = session.role;
  $('session').textContent = `${session.principal_id} · ${role}`;
  await list(); $('notice').textContent = '접속 완료 · 문서를 준비하세요.';
}));
$('compile').addEventListener('click', () => action(async () => {
  invalidate(); const refs = references(); const result = await post('/api/fleet/cell-app/compile', refs);
  previewRefs = refs;
  $('summary').textContent = `${result.summary.transfer_count}회 전송 · 팔레트 완료 표시 ${result.summary.pallet_markers.length}개`;
  $('preview').textContent = JSON.stringify(result.candidate.job, null, 2);
  layoutData = result.candidate;
  const places = result.candidate.job.steps.filter(step => step.kind === 'place' && step.target);
  const groups = [...new Set(places.map(step => `${step.pallet}|${step.layer}`))];
  $('layout-layer').replaceChildren(...groups.map(group => {
    const option = document.createElement('option'); option.value = group;
    const [pallet, layer] = group.split('|'); option.textContent = `${pallet} · ${Number(layer) + 1}층`; return option;
  }));
  renderLayout();
  if (!$('request-key').value) $('request-key').value = crypto.randomUUID();
  $('notice').textContent = '미리보기 완료 · 내용을 확인하고 작업 범위를 입력하세요.';
}));
$('propose').addEventListener('click', () => action(async () => {
  if (!previewRefs) throw new Error('미리보기를 먼저 확인하세요.');
  if (JSON.stringify(references()) !== JSON.stringify(previewRefs)) throw new Error('문서가 바뀌었습니다. 미리보기를 다시 확인하세요.');
  const result = await post('/api/fleet/cell-app/proposals', {...previewRefs,
    request_key: $('request-key').value, workcell_id: $('workcell').value, instance_id: $('instance').value});
  $('proposal').textContent = `제안 ${result.proposal.proposal_id}\n상태 ${result.mission?.status || result.proposal.state}\n운영자 별도 승인 대기`;
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
  $('job-summary').textContent = `${job.status} · ${job.steps.length}단계 중 ${job.current_step_index + 1}단계 · ${job.reason || '확인한 상태'}`;
  $('step-progress').replaceChildren(...job.steps.map(step => {
    const li = document.createElement('li');
    const inputs = step.step.inputs;
    li.textContent = `${step.step_index + 1} · ${inputs.pallet_id} · ${inputs.layer_index + 1}층 · ${inputs.item} · ${step.status}${step.reason ? ' · ' + step.reason : ''}`;
    return li;
  }));
  $('sheet-progress').replaceChildren(...(job.operator_checkpoints ?? []).map(row => {
    const li = document.createElement('li');
    const instruction = row.status === 'WAITING_ACCESS' ?
      '삽입 확인 대기 · 작업자 접근 허가가 확인되지 않아 아직 진행할 수 없습니다' : '간지 지점 도달 전';
    li.textContent = `${row.pallet_id} · ${row.layer_index + 1}층 · ${row.thickness_m * 1000} mm · ${instruction}`;
    return li;
  }));
  $('notice').textContent = `작업 ${job.status} · ${job.reason || ''} · 확인한 정지 세대 ${jobGeneration}`;
}
$('mission-id').addEventListener('input', () => { editEpoch++; job = null; jobGeneration = null; refreshControls(); });
$('read-job').addEventListener('click', () => action(readJob));
$('new-proposal').addEventListener('click', () => {
  if (busy) return;
  $('request-key').value = crypto.randomUUID(); $('proposal').textContent = '';
  $('notice').textContent = '새 요청 키를 준비했습니다. 앞선 요청의 결과가 불명확하면 먼저 작업 ID로 상태를 확인하세요.';
});
for (const command of ['admit', 'resume', 'reconcile', 'cancel']) {
  $(command).addEventListener('click', () => action(async () => {
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
  }));
}
refreshControls();
