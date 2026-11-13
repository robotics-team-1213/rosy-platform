// Real-to-Sim <-> Sim-to-Real closed-loop pipeline view for the Cell workspace (D-947, D-1012).
import {
  REAL2SIM_PATH,
  EVALUATE_PATH,
  RUNS_PATH,
  PROMOTE_PATH,
  CELL_TASKS_PATH,
  readoutPairs,
  loopRows,
  stageRows,
  sysidRows,
  surveyRows,
  runRows,
  cellTaskSummaryPairs,
  cellTaskRows,
} from '/console/assets/cell-real2sim-specs.js';
import {createCellActions} from '/console/assets/cell-real2sim-actions.js';
import {createCellViews} from '/console/assets/cell-real2sim-views.js';

export * from '/console/assets/cell-real2sim-specs.js';

export function createReal2SimPipeline({request, $, isOperator = () => false}) {
  const status = $('real2sim-status');
  let generation = 0;
  const state = {
    selectedCameraByCard: {},
    selectedInspectorTarget: 'arm_s',
    selectedInspectorCamByTarget: {},
    dualInspectorCamMode: false,
  };
  let lastCellTasksBody = null;
  let liveStreamOn = true;
  let pausedStamp = Date.now();
  let liveStreamTimer = null;

  const ctx = {
    request,
    $,
    state,
    bump: () => ++generation,
    gen: () => generation,
    activeCameraStamp: () => activeCameraStamp(),
    selectInspectorTarget: (...args) => selectInspectorTarget(...args),
    refreshCellTasks: (...args) => refreshCellTasks(...args),
  };
  const actions = createCellActions(ctx);
  Object.assign(ctx, actions);
  const {
    runPresetTask, createCustomTask, loadStationZonesYaml, saveStationZonesYaml,
    runVisionAutoCheck, toggleCableGuard,
  } = actions;
  const {renderRightInspector, renderVisualCards, renderCameraMatrix} = createCellViews(ctx);

  function activeCameraStamp() {
    if (liveStreamOn) {
      pausedStamp = Date.now();
    }
    return pausedStamp;
  }

  function refreshLiveCameraImages() {
    const stamp = activeCameraStamp();
    const wrap = $('cell-visual-cards');
    if (wrap && typeof wrap.querySelectorAll === 'function') {
      for (const img of wrap.querySelectorAll('img.cell-visual-thumb')) {
        const base = img.dataset.baseUrl || img.src.split('?')[0];
        img.src = `${base}?t=${stamp}`;
      }
    }
    const wall = $('cell-camera-matrix');
    if (wall && typeof wall.querySelectorAll === 'function') {
      for (const img of wall.querySelectorAll('img')) {
        const base = img.dataset.baseUrl || img.src.split('?')[0];
        img.src = `${base}?t=${stamp}`;
      }
    }
    const inspector = $('omx-right-inspector');
    if (inspector && typeof inspector.querySelectorAll === 'function') {
      for (const img of inspector.querySelectorAll('img.omx-inspector-cam')) {
        const base = img.dataset.baseUrl || img.src.split('?')[0];
        img.src = `${base}?t=${stamp}`;
      }
    }
  }

  function toggleLiveStream() {
    liveStreamOn = !liveStreamOn;
    const btn = $('cell-live-stream-toggle');
    if (btn) {
      btn.textContent = liveStreamOn ? '실시간 카메라 자동갱신 (ON · 2초)' : '실시간 카메라 자동갱신 (OFF · 일시정지)';
    }
    if (liveStreamOn) refreshLiveCameraImages();
  }

  if (typeof window !== 'undefined' && typeof window.setInterval === 'function') {
    liveStreamTimer = window.setInterval(() => {
      if (liveStreamOn) refreshLiveCameraImages();
    }, 2000);
  }

  function renderSelect(selectEl, items, currentValue, labelFn) {
    if (!selectEl) return;
    selectEl.replaceChildren(...items.map(item => {
      const option = document.createElement('option');
      option.value = item.value;
      option.textContent = labelFn(item);
      if (item.value === currentValue) option.selected = true;
      return option;
    }));
  }

  function renderTable(tbody, tableEl, rows) {
    if (!tbody || !tableEl) return;
    tbody.replaceChildren(...rows.map(cells => {
      const tr = document.createElement('tr');
      for (const value of cells) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.append(td);
      }
      return tr;
    }));
    tableEl.hidden = !rows.length;
  }

  function syncOperatorButtons() {
    const allowed = Boolean(isOperator());
    const reason = allowed ? '' : '운영자 권한이 필요합니다';
    for (const id of ['real2sim-evaluate', 'real2sim-run', 'real2sim-promote']) {
      const btn = $(id);
      if (btn) {
        btn.disabled = !allowed;
        btn.setAttribute('reason', reason);
      }
    }
    for (const id of ['cell-task-preset-run', 'cell-task-create']) {
      const btn = $(id);
      if (btn) {
        btn.disabled = false;
        btn.removeAttribute('reason');
      }
    }
  }

  function renderBody(body) {
    const snaps = (body.snapshots || []).map(s => ({
      value: s.id,
      label: `${s.id} (${s.taken_at ? s.taken_at.slice(0, 16).replace('T', ' ') : '시각 미상'})`,
    }));
    renderSelect($('real2sim-snapshot'), snaps, body.active?.id || '', item => item.label);
    renderSelect(
      $('real2sim-prev'),
      [{value: '', label: '자동 (직전 스냅샷)'}, ...snaps],
      body.previous?.id || '',
      item => item.label,
    );
    const cands = (body.physics_candidates || []).map(c => ({
      value: c.name,
      label: c.holdout_rms_deg != null ? `${c.name} (보류 RMS ${c.holdout_rms_deg}°)` : c.name,
    }));
    if (cands.length) {
      const currentPhysics = $('real2sim-physics')?.value || 'servo-antijitter-20261112';
      renderSelect($('real2sim-physics'), cands, currentPhysics, item => item.label);
    }
    const fits = (body.sysid_summary?.fits || []).map(f => ({
      value: f.id,
      label: `${f.id} (${f.ok ? '통과' : '보류'} · ${f.fitted_hold_mean_deg ?? '—'}°)`,
    }));
    if (fits.length) {
      const currentFit = $('real2sim-fit-id')?.value || body.sysid_summary?.best_fit_id || fits[0].value;
      renderSelect($('real2sim-fit-id'), fits, currentFit, item => item.label);
    }

    const pairs = readoutPairs(body);
    const figures = $('real2sim-figures');
    if (figures) {
      figures.replaceChildren(...pairs.flatMap(([term, desc]) => {
        const dt = document.createElement('dt');
        dt.textContent = term;
        const dd = document.createElement('dd');
        dd.textContent = desc;
        return [dt, dd];
      }));
      figures.hidden = !pairs.length;
    }

    renderTable($('real2sim-loop-rows'), $('real2sim-loop-table'), loopRows(body));
    renderTable($('real2sim-stage-rows'), $('real2sim-stage-table'), stageRows(body));
    renderTable($('real2sim-sysid-rows'), $('real2sim-sysid-table'), sysidRows(body));
    renderTable($('real2sim-survey-rows'), $('real2sim-survey-table'), surveyRows(body));
    renderTable($('real2sim-runs-rows'), $('real2sim-runs-table'), runRows(body));

    const handoffEl = $('real2sim-handoff');
    const isaacStage = (body.stages || []).find(s => s.stage === 'isaac');
    if (handoffEl) {
      handoffEl.textContent = isaacStage?.isaac_handoff
        ? JSON.stringify(isaacStage.isaac_handoff, null, 2)
        : '';
    }
    syncOperatorButtons();
    status.textContent = `스냅샷 ${body.active?.id || '—'} · 이전 ${body.previous?.id || '없음'} · Stage 1(MuJoCo) -> Stage 2(Isaac Sim) 파이프라인 준비 완료`;
  }

  function clear() {
    generation++;
    if ($('real2sim-figures')) {
      $('real2sim-figures').hidden = true;
      $('real2sim-figures').replaceChildren();
    }
    for (const [tableId, rowsId] of [
      ['real2sim-loop-table', 'real2sim-loop-rows'],
      ['real2sim-stage-table', 'real2sim-stage-rows'],
      ['real2sim-sysid-table', 'real2sim-sysid-rows'],
      ['real2sim-survey-table', 'real2sim-survey-rows'],
      ['real2sim-runs-table', 'real2sim-runs-rows'],
      ['cell-tasks-table', 'cell-tasks-rows'],
    ]) {
      if ($(tableId)) $(tableId).hidden = true;
      if ($(rowsId)) $(rowsId).replaceChildren();
    }
    if ($('cell-tasks-figures')) {
      $('cell-tasks-figures').hidden = true;
      $('cell-tasks-figures').replaceChildren();
    }
    if ($('real2sim-handoff')) $('real2sim-handoff').textContent = '';
    if (status) status.textContent = '접속하면 실물↔시뮬 파이프라인 상태를 확인할 수 있습니다.';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = '접속하면 OMX 셀(cell_s · cell_ab) 태스크 큐와 실물 실행 상태를 확인할 수 있습니다.';
  }

  function currentPayload() {
    return {
      snapshot_id: $('real2sim-snapshot')?.value || null,
      prev_id: $('real2sim-prev')?.value || null,
      berth_kit: $('real2sim-berth-kit')?.value || 'v16-modular',
      ship_spacer_dy_mm: Number($('real2sim-spacer-dy')?.value || 39),
      ship_stern_hook_mm: Number($('real2sim-stern-hook')?.value || 0),
      physics: $('real2sim-physics')?.value || 'twin-kp-20261109',
      compensate_zero: $('real2sim-comp-zero') ? $('real2sim-comp-zero').checked : true,
      cam_jitter: $('real2sim-cam-jitter') ? $('real2sim-cam-jitter').checked : true,
    };
  }

  async function refresh() {
    const current = ++generation;
    if (!status) return;
    status.textContent = '실물↔시뮬 파이프라인 상태를 확인하는 중입니다.';
    try {
      const snap = $('real2sim-snapshot')?.value || '';
      const prev = $('real2sim-prev')?.value || '';
      const kit = $('real2sim-berth-kit')?.value || 'v16-modular';
      const dy = $('real2sim-spacer-dy')?.value || '39';
      const hook = $('real2sim-stern-hook')?.value || '0';
      const params = new URLSearchParams({berth_kit: kit, ship_spacer_dy_mm: dy, ship_stern_hook_mm: hook});
      if (snap) params.set('snapshot', snap);
      if (prev) params.set('prev', prev);
      const body = await request(`${REAL2SIM_PATH}?${params.toString()}`);
      if (current !== generation) return;
      renderBody(body);
      await refreshCellTasks(current);
    } catch (error) {
      if (current !== generation) return;
      status.textContent = `실물↔시뮬 파이프라인을 읽지 못했습니다: ${error.message}`;
    }
  }

  function selectInspectorTarget(targetId, preferredCamId = null) {
    if (!targetId) return;
    const normalized = targetId === 'pinky' ? 'rosy_46' : targetId;
    state.selectedInspectorTarget = normalized;
    if (preferredCamId) {
      state.selectedInspectorCamByTarget[normalized] = preferredCamId;
    }
    if (lastCellTasksBody) {
      renderVisualCards(lastCellTasksBody);
      renderRightInspector(lastCellTasksBody);
    }
  }

  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('rosy:inspect-target', ev => {
      const targetId = ev?.detail?.targetId;
      const camId = ev?.detail?.camId || null;
      if (targetId) selectInspectorTarget(targetId, camId);
    });
  }


  function renderCellTasks(body) {
    lastCellTasksBody = body;
    renderVisualCards(body);
    renderCameraMatrix(body);
    renderRightInspector(body);
    const pairs = cellTaskSummaryPairs(body);
    const figs = $('cell-tasks-figures');
    if (figs) {
      figs.replaceChildren(...pairs.flatMap(([term, desc]) => {
        const dt = document.createElement('dt');
        dt.textContent = term;
        const dd = document.createElement('dd');
        dd.textContent = desc;
        return [dt, dd];
      }));
      figs.hidden = !pairs.length;
    }
    renderTable($('cell-tasks-rows'), $('cell-tasks-table'), cellTaskRows(body));
    syncOperatorButtons();
    const taskStatus = $('cell-tasks-status');
    if (taskStatus) {
      const s = body?.summary || {};
      taskStatus.textContent = `OMX 셀 태스크 원장: 전체 ${s.total ?? (body?.tasks?.length || 0)}건 (대기 ${s.queued ?? 0} · 실행 ${s.running ?? 0} · 완료 ${s.completed ?? 0})`;
    }
  }

  async function refreshCellTasks(expectedGen = generation) {
    try {
      const body = await request(CELL_TASKS_PATH);
      if (expectedGen !== generation) return;
      renderCellTasks(body);
    } catch (error) {
      if (expectedGen !== generation) return;
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `OMX 셀 태스크 조회 실패: ${error.message}`;
      }
    }
  }


  async function evaluate() {
    const current = ++generation;
    if (!status) return;
    status.textContent = '선택한 고정 키트·보정 설정으로 Stage 1 -> Stage 2 파이프라인을 평가하는 중입니다.';
    try {
      const body = await request(EVALUATE_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(currentPayload()),
      });
      if (current !== generation) return;
      renderBody(body);
    } catch (error) {
      if (current !== generation) return;
      status.textContent = `실물↔시뮬 파이프라인 평가 실패: ${error.message}`;
    }
  }

  async function queueRun() {
    const current = ++generation;
    if (!status) return;
    status.textContent = 'Stage 1(MuJoCo) -> Stage 2(Isaac Sim) 실행 번들을 큐에 등록하는 중입니다.';
    try {
      const res = await request(RUNS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(currentPayload()),
      });
      if (current !== generation) return;
      renderTable($('real2sim-runs-rows'), $('real2sim-runs-table'), runRows(res));
      status.textContent = `파이프라인 실행 큐 등록 완료: ${res.run?.run_id || '—'} (${(res.run?.rerun_stages || []).join(', ')})`;
    } catch (error) {
      if (current !== generation) return;
      status.textContent = `파이프라인 실행 큐 등록 실패: ${error.message}`;
    }
  }

  async function promotePhysics() {
    const current = ++generation;
    if (!status) return;
    const fitId = $('real2sim-fit-id')?.value || '';
    const candidateName = ($('real2sim-promote-name')?.value || '').trim();
    status.textContent = `SysID 후보(${fitId} -> ${candidateName || '이름 미지정'})를 검증·승격하는 중입니다.`;
    try {
      const res = await request(PROMOTE_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({fit_id: fitId, candidate_name: candidateName}),
      });
      if (current !== generation) return;
      const cands = (res.physics_candidates || []).map(c => ({
        value: c.name,
        label: c.holdout_rms_deg != null ? `${c.name} (보류 RMS ${c.holdout_rms_deg}°)` : c.name,
      }));
      renderSelect($('real2sim-physics'), cands, res.promoted, item => item.label);
      status.textContent = `물리 상수 후보 승격 완료: ${res.promoted} (${res.verdict})`;
    } catch (error) {
      if (current !== generation) return;
      status.textContent = `물리 상수 후보 승격 실패: ${error.message}`;
    }
  }

  $('real2sim-refresh')?.addEventListener('click', () => { void refresh(); });
  $('real2sim-evaluate')?.addEventListener('click', () => { void evaluate(); });
  $('real2sim-run')?.addEventListener('click', () => { void queueRun(); });
  $('real2sim-promote')?.addEventListener('click', () => { void promotePhysics(); });
  $('cell-task-refresh')?.addEventListener('click', () => { void refreshCellTasks(++generation); });
  $('cell-task-preset-run')?.addEventListener('click', () => { void runPresetTask(); });
  $('cell-task-create')?.addEventListener('click', () => { void createCustomTask(); });
  $('cell-vision-auto-check')?.addEventListener('click', () => { void runVisionAutoCheck($('cell-task-cell')?.value || 'cell_s'); });
  $('cell-cable-guard-toggle')?.addEventListener('click', () => { void toggleCableGuard(); });
  $('cell-live-stream-toggle')?.addEventListener('click', () => { toggleLiveStream(); });
  $('station-zones-load')?.addEventListener('click', () => { void loadStationZonesYaml(); });
  $('station-zones-save')?.addEventListener('click', () => { void saveStationZonesYaml(); });
  return {refresh, evaluate, queueRun, promotePhysics, refreshCellTasks, runPresetTask, createCustomTask, clear};
}
