import {accountFetch} from '/account-session.js';
import {describeBy, setOff} from '/common/cause-line.js';
import {actionIcon} from '/common/ui.js';
import '/commands.js';
import {hasActiveMonitorWork, renderMonitorHosts, statusTag} from '/canonical-monitor.js';
import {initRecordingTodo, loadRecordingTodo} from '/canonical-todo.js';

const $ = (id) => document.getElementById(id);
const JOINTS = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper'];
const GPU_KINDS = new Set(['collect_dart', 'train_stage', 'eval_ladder']);
const RUN_TAG = {
  launching: ['progress', '준비 중'], running: ['progress', '실행 중'], stopping: ['progress', '중지 요청'],
  succeeded: ['fresh', '완료'], failed: ['danger', '실패'], cancelled: ['caution', '중단됨'], interrupted: ['caution', '중단됨'],
};
const KIND_LABEL = {
  align_real: 'align_real · 실물 정렬', collect_dart: 'collect_dart · DART 수집',
  train_stage: 'train_stage · ACT 학습', eval_ladder: 'eval_ladder · L1 평가', cell_live_check: 'cell_live_check · 셀 검사',
};
let token = '', manager = false, busy = false, pollInFlight = false, snap = null;
let selectedRunId = null, selectedRun = null, selectedEvalKey = null, pollTimer = null;

const el = (tag, text, cls) => {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (cls) node.className = cls;
  return node;
};

function quietBtn(label, icon, onClick) {
  const button = document.createElement('ui-button');
  button.setAttribute('kind', 'quiet');
  button.textContent = label;
  if (icon) actionIcon(button, icon);
  button.addEventListener('click', onClick);
  return button;
}

const showErr = (msg) => {
  $('canon-error').textContent = msg || '';
  $('canon-error').hidden = !msg;
};

const showNotice = (state, msg) => {
  $('canon-notice').setAttribute('state', state);
  $('canon-notice').textContent = msg;
};

async function bootstrapAuth() {
  try {
    const optRes = await accountFetch('/api/accounts/options', {cache: 'no-store'});
    if (optRes.ok && (await optRes.json()).enabled) {
      const sesRes = await accountFetch('/api/accounts/session', {cache: 'no-store'});
      if (sesRes.ok) {
        const acc = await sesRes.json();
        token = acc.token || '';
        manager = Array.isArray(acc.capabilities) && acc.capabilities.includes('manage');
      }
      return;
    }
    const lrn = await accountFetch('/api/learning', {cache: 'no-store'});
    if (lrn.ok) {
      token = (await lrn.json()).token || '';
      manager = true;
    }
  } catch (err) {
    showErr(err.message);
  }
}

async function api(suffix, body) {
  const opts = body === undefined
    ? {cache: 'no-store'}
    : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Pinky-Token': token}, body: JSON.stringify(body)};
  const res = await accountFetch('/api/learning/canonical' + suffix, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function fmtJoint(pose, idx, unit) {
  if (!pose) return '—';
  const normVal = idx < 5 ? pose.norm?.[idx] : pose.gripper_units;
  const radVal = pose.sim_rad?.[idx];
  const tickVal = pose.raw_ticks?.[idx];
  if (unit === 'norm') return normVal != null ? String(normVal) : '—';
  if (unit === 'sim_rad') return radVal != null ? String(radVal) : '—';
  if (unit === 'raw_ticks') return tickVal != null ? String(tickVal) : '—';
  const parts = [`n:${normVal ?? '—'}`, `r:${radVal ?? '—'}`];
  if (tickVal != null) parts.push(`t:${tickVal}`);
  return parts.join(' / ');
}

function marginText(spec, arm, jname) {
  if (arm !== 'arm_b') return spec.envelope_margins?.arm_a_reviewed_note || '—';
  const mkey = jname === 'gripper' ? 'gripper_units' : jname;
  const cm = spec.envelope_margins?.arm_b_reviewed_lib?.canonical_margins?.[mkey];
  if (!cm) return '—';
  const band = cm.holder_safe_band ? ` · holder[${cm.holder_safe_band.join('..')}]` : '';
  return `low -${cm.low_margin} / high +${cm.high_margin}${band}`;
}

function renderSpec() {
  if (!snap?.spec) return;
  const spec = snap.spec, unit = $('canon-unit').value;
  $('canon-evidence-badge').replaceChildren(statusTag('caution', '시뮬레이션 근거 · 실물 제어 아님'));
  $('canon-spec-sha').textContent = `sha256: ${(snap.spec_sha256 || '').slice(0, 12)} · ${snap.spec_source || 'builtin'}`;

  const lib = spec.envelope_margins?.arm_b_reviewed_lib || {};
  const gateBase = lib.data_gate_home_max_j234_rad ?? 0.239;
  const jitter = spec.start_jitter_rad ?? 0.035;
  const gateSum = (gateBase + jitter).toFixed(3);
  const gateLim = lib.data_gate_limit_rad ?? 0.35;
  const gapMm = spec.open_gap_m != null ? Math.round(spec.open_gap_m * 1000) : 42;
  const kpis = [
    ['data_gate 여유 (j234+지터)', `${gateBase} + ${jitter} = ${gateSum} < ${gateLim} rad`],
    ['집게 기준 (열림 / 닫힘)', `open ${spec.sim_jaw_open} (${gapMm} mm) / closed ${spec.sim_jaw_closed}`],
    ['접힘 허용 오차 (folded_tol)', String(spec.real_entry_bridge?.folded_tol_norm ?? 10.0)],
    ['실물 진입 브리지', `${spec.real_entry_bridge?.phases?.length ?? 2}단계 분리 (unfold -> pan/roll/jaw)`],
  ];
  $('canon-kpis').replaceChildren(...kpis.map(([k, v]) => {
    const card = el('div', undefined, 'canon-kpi');
    card.append(el('span', k, 'canon-kpi-label'), el('span', v, 'canon-kpi-value'));
    return card;
  }));

  const rows = [];
  for (const arm of ['arm_a', 'arm_b']) {
    const idle = spec.idle_park?.[arm], canon = spec.canonical_start?.[arm];
    for (let i = 0; i < JOINTS.length; i++) {
      const tr = el('tr');
      for (const cell of [arm, JOINTS[i], fmtJoint(idle, i, unit), fmtJoint(canon, i, unit), marginText(spec, arm, JOINTS[i])]) {
        tr.append(el('td', cell));
      }
      rows.push(tr);
    }
  }
  $('canon-spec-body').replaceChildren(...rows);

  const br = spec.real_entry_bridge || {};
  const brNodes = [el('p', `사전 정리: ${br.pre_entry || '—'}`)];
  for (const ph of br.phases || []) {
    brNodes.push(el('p', `Phase ${ph.phase} (${ph.name}): [${(ph.joints || []).join(', ')}] — ${ph.note || ''}`));
  }
  $('canon-bridge-body').replaceChildren(...brNodes);
}

function collectWatchedAndRuns() {
  const evals = [], lives = [];
  const pushWatch = (src, w) => {
    for (const ev of w?.eval_ladder || []) evals.push({src, doc: ev, key: `${src}:${ev.folder || ''}:${ev.file || ev.step || evals.length}`});
    for (const lc of w?.cell_live_checks || []) lives.push({src, doc: lc});
  };
  for (const w of Object.values(snap?.watched || {})) pushWatch(w.label || w.id, w);
  for (const [pid, p] of Object.entries(snap?.peers || {})) {
    for (const w of Object.values(p.summary?.watched || {})) pushWatch(`${p.label || pid}/${w.label || w.id}`, w);
  }
  for (const r of snap?.runs || []) {
    if (r.kind === 'eval_ladder' && r.result?.assessment) {
      evals.push({src: `run:${r.id.slice(0, 8)}`, doc: r.result.assessment, key: `run:${r.id}`});
    } else if (r.kind === 'cell_live_check' && r.result) {
      lives.push({src: `run:${r.id.slice(0, 8)}`, doc: r.result});
    }
  }
  return {evals, lives};
}

function fmtEvalProfile(p) {
  if (!p) return '—';
  const ep = p.policy_episodes ?? p.episodes ?? '?';
  const tp = p.teacher_episodes ?? p.policy_episodes ?? p.episodes;
  return `${p.policy_successes ?? '?'}/${ep} (teacher ${p.teacher_successes ?? '?'}${tp != null ? '/' + tp : ''})`;
}

function liveStateEntries(doc) {
  const out = [];
  if (doc?.states && typeof doc.states === 'object') out.push(['', doc.states]);
  if (doc?.checkpoints && typeof doc.checkpoints === 'object') {
    for (const [step, cpDoc] of Object.entries(doc.checkpoints)) {
      if (cpDoc?.states && typeof cpDoc.states === 'object') out.push([`step ${step}`, cpDoc.states]);
    }
  }
  return out;
}

function renderEvidence() {
  const {evals, lives} = collectWatchedAndRuns();
  const erows = evals.map(({src, doc, key}) => {
    const tr = el('tr');
    if (selectedEvalKey === key) tr.setAttribute('aria-selected', 'true');
    const verdict = doc.verdict || doc.status || 'unknown';
    const nom = doc.profiles?.nominal, dly = doc.profiles?.delayed;
    const layers = Object.entries(doc.per_layer || {}).map(([k, v]) => `${k}:${v?.successes ?? v}/${v?.episodes ?? ''}`).join(' ') || '—';
    const col = ((nom?.neighbour_disturbed ?? 0) + (nom?.arm_link_contacts ?? 0) + (dly?.neighbour_disturbed ?? 0) + (dly?.arm_link_contacts ?? 0));
    const vTd = el('td');
    vTd.append(statusTag(verdict === 'pass' ? 'fresh' : 'danger', verdict));
    const aTd = el('td');
    aTd.append(quietBtn('보기', 'list', () => {
      selectedEvalKey = key;
      $('canon-eval-detail').hidden = false;
      $('canon-eval-detail').replaceChildren(el('h4', `${src} · ${doc.file || ''}`), el('pre', JSON.stringify(doc, null, 2)));
      renderEvidence();
    }));
    tr.append(el('td', `${src} · ${doc.file || doc.task || ''}`), vTd, el('td', fmtEvalProfile(nom)), el('td', fmtEvalProfile(dly)), el('td', layers), el('td', String(col)), aTd);
    return tr;
  });
  $('canon-eval-body').replaceChildren(...erows);
  $('canon-eval-empty').hidden = erows.length > 0;

  const warnings = [], lrows = [];
  for (const {src, doc} of lives) {
    const revBase = `${src}${doc.name ? ' · ' + doc.name : ''} (${doc.arm_id || ''} ${(doc.policy_revision || '').slice(0, 12)})`;
    for (const [cpTag, states] of liveStateEntries(doc)) {
      const rev = cpTag ? `${revBase} · ${cpTag}` : revBase;
      for (const [sname, goals] of Object.entries(states)) {
        const entries = goals && typeof goals === 'object' && 'strict_ok' in goals ? [['default', goals]] : Object.entries(goals || {});
        for (const [gname, g] of entries) {
          const oor = [...(g.strict_oor || []).map((o) => `S:${o.name}`), ...(g.margin_oor || []).map((o) => `M:${o.name}`)].join(', ') || '없음';
          const tr = el('tr');
          const wTd = el('td');
          if (g.wrist_roll_warning) {
            warnings.push(`${rev} · ${sname} · ${gname}: ${g.wrist_roll_warning}`);
            wTd.append(statusTag('danger', 'wrist_roll_warning'));
          } else {
            wTd.append(statusTag('fresh', '경고 없음'));
          }
          tr.append(el('td', rev), el('td', sname), el('td', gname), el('td', g.strict_ok ? 'PASS' : 'OUT'), el('td', g.margin_ok ? 'PASS' : 'OUT'), el('td', oor), wTd);
          lrows.push(tr);
        }
      }
    }
  }
  $('canon-live-body').replaceChildren(...lrows);
  $('canon-live-empty').hidden = lrows.length > 0;

  const warnBox = $('canon-wrist-warn');
  warnBox.hidden = warnings.length === 0;
  if (warnings.length) {
    const head = el('div', undefined, 'canon-card-head');
    head.append(statusTag('danger', 'wrist_roll_warning'), el('strong', '손목 롤 분기 이탈 경고 — 오프라인 cell_live_check 확인 필요'));
    const ul = el('ul', undefined, 'canon-list');
    for (const w of warnings) ul.append(el('li', w));
    warnBox.replaceChildren(head, ul);
  } else {
    warnBox.replaceChildren();
  }
}

function setOptions(selectEl, items, emptyLabel) {
  const prev = selectEl.value;
  selectEl.replaceChildren();
  if (!items.length && emptyLabel !== null) {
    selectEl.append(new Option(emptyLabel, ''));
    return;
  }
  for (const [val, label] of items) selectEl.append(new Option(label, val));
  if ([...selectEl.options].some((o) => o.value === prev)) selectEl.value = prev;
}

function renderLauncher() {
  const kind = $('canon-kind').value, arm = $('canon-arm').value;
  for (const [k, boxId] of [['align_real', 'canon-fields-align'], ['collect_dart', 'canon-fields-collect'],
      ['train_stage', 'canon-fields-train'], ['eval_ladder', 'canon-fields-eval'], ['cell_live_check', 'canon-fields-live']]) {
    const box = $(boxId);
    const hide = kind !== k;
    box.hidden = hide;
    for (const ctrl of box.querySelectorAll('input, select')) ctrl.disabled = hide;
  }
  const flipBox = $('canon-align-flip');
  if (arm !== 'arm_b' || kind !== 'align_real') { flipBox.checked = false; flipBox.disabled = true; } else { flipBox.disabled = false; }

  const sources = Object.values(snap?.named_sources || {}).filter((s) => !s.arm_id || s.arm_id === arm);
  const doneRuns = (snap?.runs || []).filter((r) => r.status === 'succeeded' && r.arm_id === arm);
  const byKind = (sKinds, rKinds) => [
    ...sources.filter((s) => sKinds.has(s.kind)).map((s) => [s.id, `${s.label} (${s.id})`]),
    ...doneRuns.filter((r) => rKinds.has(r.kind)).map((r) => [r.id, `${r.kind} · ${r.id.slice(0, 8)}`]),
  ];

  setOptions($('canon-align-source'), byKind(new Set(['real_dataset']), new Set()), '등록된 실물 소스 없음');
  setOptions($('canon-train-dataset'), byKind(new Set(['real_dataset', 'sim_dataset']), new Set(['align_real', 'collect_dart'])), '등록된 학습 자료 없음');
  setOptions($('canon-train-resume'), [['', '없음 (Stage 1)'], ...doneRuns.filter((r) => r.kind === 'train_stage').map((r) => [r.id, `train · ${r.id.slice(0, 8)}`])], null);
  const ckpts = byKind(new Set(['checkpoint']), new Set(['train_stage']));
  setOptions($('canon-eval-ckpt'), ckpts, '체크포인트 없음');
  setOptions($('canon-live-ckpt'), ckpts, '체크포인트 없음');
  setOptions($('canon-live-frames'), byKind(new Set(['frames_dir']), new Set()), '프레임 소스 없음');
  setOptions($('canon-live-env'), byKind(new Set(['chunk_library']), new Set()), '안전 영역 라이브러리 없음');

  const missingRef = (
    (kind === 'align_real' && !$('canon-align-source').value)
    || (kind === 'train_stage' && !$('canon-train-dataset').value)
    || (kind === 'eval_ladder' && !$('canon-eval-ckpt').value)
    || (kind === 'cell_live_check' && (!$('canon-live-ckpt').value || !$('canon-live-frames').value || !$('canon-live-env').value))
  );
  const reason = !snap?.configured ? '표준 시작 자세 실행기가 설정되지 않았습니다 (읽기 전용).'
    : !manager ? '조회 화면입니다. 작업 실행·중지는 프로젝트 관리 권한이 필요합니다.'
    : !snap?.writable ? '실행 가능한 Python 환경이 설정되지 않았습니다.'
    : (GPU_KINDS.has(kind) && snap?.gpu_lock?.busy) ? 'GPU 작업 슬롯이 사용 중입니다. 완료 후 실행하세요.'
    : missingRef ? '선택한 팔에 연결된 등록 자료 또는 완료 실행이 없습니다.' : '';
  const causeEl = $('canon-job-cause');
  causeEl.textContent = reason;
  causeEl.hidden = !reason;
  const submitBtn = $('canon-job-submit');
  setOff(submitBtn, busy || Boolean(reason), '');
  describeBy(submitBtn, 'canon-job-cause', Boolean(reason));
}

function renderRuns() {
  const runs = snap?.runs || [];
  const cards = runs.map((r) => {
    const card = el('article', undefined, 'canon-card');
    const head = el('div', undefined, 'canon-card-head');
    const [tState, tLabel] = RUN_TAG[r.status] || ['unknown', r.status];
    head.append(el('h3', `${KIND_LABEL[r.kind] || r.kind} · ${r.arm_id}`), statusTag(tState, tLabel));
    card.append(head, el('p', `${r.id.slice(0, 12)} · ${r.gpu_required ? 'GPU' : 'CPU'}`, 'quiet canon-mono'));
    if (r.error) card.append(el('p', r.error));
    card.append(quietBtn('로그·상세 보기', 'list', () => work(() => openRun(r.id))));
    return card;
  });
  $('canon-runs').replaceChildren(...cards);
  $('canon-runs-empty').hidden = cards.length > 0;
  syncCancel();
}

function syncCancel() {
  const active = selectedRun && (selectedRun.status === 'running' || selectedRun.status === 'stopping');
  const reason = !snap?.configured ? '실행기가 설정되지 않았습니다.'
    : !manager ? '중지는 프로젝트 관리 권한이 필요합니다.'
    : !active ? '실행 중인 작업을 선택하면 중지할 수 있습니다.' : '';
  const finalReason = reason || (busy ? '요청 처리 중입니다.' : '');
  setOff($('canon-job-cancel'), busy || Boolean(reason), finalReason);
}

async function openRun(rid) {
  selectedRunId = rid;
  selectedRun = await api('/runs/' + rid);
  $('canon-run-detail').hidden = false;
  $('canon-run-title').textContent = `${selectedRun.kind} · ${selectedRun.arm_id} (${selectedRun.id.slice(0, 12)})`;
  $('canon-job-log').textContent = selectedRun.log_tail || JSON.stringify(selectedRun.result || {status: selectedRun.status}, null, 2);
  syncCancel();
}

function scheduleNextPoll() {
  clearTimeout(pollTimer);
  const active = snap && hasActiveMonitorWork(snap);
  const stamp = new Date().toLocaleTimeString('ko-KR', {hour12: false});
  $('canon-poll-state').textContent = active ? `자동 갱신 10초 · 마지막 갱신 ${stamp}` : `마지막 갱신 ${stamp}`;
  if (active && !document.hidden) {
    pollTimer = setTimeout(() => backgroundPoll(), 10000);
  }
}

function renderAll() {
  renderMonitorHosts($('canon-hosts'), $('canon-hosts-empty'), snap, {
    busy, manager, onRefreshPeer: (pid) => work(() => api(`/peers/${pid}/refresh`, {}).then(() => loadSnapshot())),
  });
  renderEvidence();
  renderLauncher();
  renderRuns();
  renderSpec();
  showNotice(snap?.configured ? 'ready' : 'unavailable', snap?.configured
    ? (manager ? `연결됨 (${snap.host_id || 'local'}) · 작업 실행 및 관찰 가능` : `조회 전용 (${snap.host_id || 'local'})`)
    : '표준 시작 자세 실행기가 연결되지 않아 내장 Design 2 규격만 표시합니다.');
}

async function loadSnapshot({background = false} = {}) {
  if (!background) void loadRecordingTodo();
  const next = await api('');
  if (background && busy) return;
  snap = next;
  renderAll();
  if (selectedRunId && snap?.configured) await openRun(selectedRunId);
  scheduleNextPoll();
}

async function backgroundPoll() {
  if (busy || pollInFlight || document.hidden) return;
  pollInFlight = true;
  try {
    await loadSnapshot({background: true});
  } catch (err) {
    showErr(err.message);
    if (snap && hasActiveMonitorWork(snap) && !document.hidden) {
      clearTimeout(pollTimer);
      pollTimer = setTimeout(() => backgroundPoll(), 10000);
    }
  } finally {
    pollInFlight = false;
  }
}

async function work(fn) {
  if (busy) return;
  busy = true;
  if (snap) renderLauncher();
  syncCancel();
  showErr('');
  try {
    await fn();
  } catch (err) {
    showErr(err.message);
  } finally {
    busy = false;
    if (snap) renderAll();
  }
}

function buildJobParams(kind) {
  if (kind === 'align_real') {
    return {source_id: $('canon-align-source').value, trim_dead_idle: $('canon-align-trim').checked, wrist_flip: $('canon-align-flip').checked};
  }
  if (kind === 'collect_dart') {
    return {episodes: Number($('canon-collect-episodes').value), seed: Number($('canon-collect-seed').value),
      jitter_deg: Number($('canon-collect-jitter').value), color_random: $('canon-collect-color').checked, pose_random: $('canon-collect-pose').checked};
  }
  if (kind === 'train_stage') {
    const out = {dataset_ref: $('canon-train-dataset').value, steps: Number($('canon-train-steps').value),
      batch_size: Number($('canon-train-batch').value), save_freq: Number($('canon-train-save').value), seed: Number($('canon-train-seed').value),
      chunk_size: Number($('canon-train-chunk').value), n_action_steps: Number($('canon-train-nsteps').value),
      lr: Number($('canon-train-lr').value), kl_weight: Number($('canon-train-kl').value), use_vae: $('canon-train-vae').checked};
    if ($('canon-train-resume').value) out.resume_run_id = $('canon-train-resume').value;
    return out;
  }
  if (kind === 'eval_ladder') {
    return {checkpoint_ref: $('canon-eval-ckpt').value, task: $('canon-eval-task').value,
      nominal_episodes: Number($('canon-eval-nom').value), delayed_episodes: Number($('canon-eval-dly').value),
      delay_frames: Number($('canon-eval-df').value), n_action_steps: Number($('canon-eval-nsteps').value), seed_base: Number($('canon-eval-seed').value)};
  }
  return {checkpoint_ref: $('canon-live-ckpt').value, frames_source_id: $('canon-live-frames').value, envelope_source_id: $('canon-live-env').value};
}

$('canon-unit').addEventListener('change', renderSpec);
$('canon-kind').addEventListener('change', renderLauncher);
$('canon-arm').addEventListener('change', renderLauncher);
$('canon-refresh').addEventListener('click', () => work(() => loadSnapshot()));
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && snap && hasActiveMonitorWork(snap)) backgroundPoll();
  else if (document.hidden) clearTimeout(pollTimer);
});
$('canon-job-cancel').addEventListener('click', () => work(async () => {
  if (!selectedRunId) return;
  selectedRun = await api(`/jobs/${selectedRunId}/cancel`, {});
  await loadSnapshot();
}));
$('canon-job-form').addEventListener('submit', (e) => {
  e.preventDefault();
  work(async () => {
    const kind = $('canon-kind').value, arm = $('canon-arm').value;
    const reqId = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    const created = await api('/jobs', {request_id: reqId, kind, arm_id: arm, params: buildJobParams(kind)});
    selectedRunId = created.id;
    await loadSnapshot();
  });
});

initRecordingTodo({notice: showNotice});
work(async () => {
  await bootstrapAuth();
  await loadSnapshot();
});
