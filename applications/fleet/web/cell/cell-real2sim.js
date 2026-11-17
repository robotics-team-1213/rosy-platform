// Real-to-Sim <-> Sim-to-Real closed-loop pipeline view for the Cell workspace (D-947, D-1012).
import {
  CELL_TASKS_PATH,
  cellTaskSummaryPairs,
  cellTaskRows,
} from './cell-real2sim-specs.js';
import {createCellActions, renderSelect, renderTable} from './cell-real2sim-actions.js';
import {createCellViews} from './cell-real2sim-views.js';

export * from './cell-real2sim-specs.js';

export function createReal2SimPipeline({request, $, isOperator = () => false, cellFrames = null, confirm = null}) {
  const status = $('real2sim-status');
  let generation = 0;
  const initialCellParam = typeof window !== 'undefined'
    ? new URLSearchParams(window.location?.search || '').get('cell')
    : null;
  let activeWorkspace = ['cell_s', 'cell_a', 'cell_b', 'cell_ab'].includes(initialCellParam)
    ? initialCellParam
    : 'prep';
  const state = {
    selectedCameraByCard: {},
    selectedInspectorTarget: activeWorkspace === 'cell_b' ? 'arm_b' : (activeWorkspace === 'cell_a' || activeWorkspace === 'cell_ab') ? 'arm_a' : 'arm_s',
    selectedInspectorCamByTarget: {},
    selectedTierByTarget: {},
    selectedDisplacedByTarget: {},
    dualInspectorCamMode: false,
  };
  let lastCellTasksBody = null;
  let lastCellTasksAt = 0;
  let connected = false;
  let liveStreamOn = true;
  let activeBtn = null;
  const PREP_PURPOSE = $('cell-purpose')?.textContent
    || '레시피와 작업대 설정으로 적재 계획을 미리 보고 Fleet에 작업을 제안합니다. 승인·진행은 그 단계에서, 로봇 상태·예외 확인은 관제에서 합니다.';
  const WORKSPACE_PURPOSE = {
    prep: PREP_PURPOSE,
    cell_s: 'Cell S · S3 하역 셔틀(arm_s) 실시간 카메라, 엔코더 관측, 작업 큐 등록과 안전 제어를 수행합니다.',
    cell_a: 'Cell A · S5 1·3층 적층(arm_a) 실시간 카메라, 엔코더 관측, 작업 큐 등록과 안전 제어를 수행합니다.',
    cell_b: 'Cell B · S5 2층 적층·반출(arm_b) 실시간 카메라, 엔코더 관측, 작업 큐 등록과 안전 제어를 수행합니다.',
    cell_ab: 'Cell A/B · S5 2암 통합(arm_a · arm_b) 실시간 카메라, 엔코더 관측, 협동 작업 큐와 안전 제어를 수행합니다.',
  };

  const markInflight = btn => {
    btn.dataset.inflight = '1';
    btn.disabled = true;
    btn.setAttribute('reason', '요청 처리 중');
  };

  const trackedRequest = async (path, options) => {
    const btn = activeBtn;
    activeBtn = null;
    if (btn) markInflight(btn);
    try { return await request(path, options); }
    finally {
      if (btn) { delete btn.dataset.inflight; syncOperatorButtons(); }
    }
  };

  async function withBusyButton(btn, fn) {
    if (btn) {
      if (!isOperator() || btn.disabled) return;
      markInflight(btn);
    }
    try { return await fn(); }
    finally {
      if (btn) { delete btn.dataset.inflight; syncOperatorButtons(); }
    }
  }

  const ctx = {
    request: trackedRequest,
    confirm,
    $,
    state,
    cellFrames,
    isOperator: () => Boolean(isOperator()),
    withBusyButton,
    syncOperatorButtons: () => syncOperatorButtons(),
    bump: () => ++generation,
    gen: () => generation,
    getScope: () => (['cell_s', 'cell_a', 'cell_b', 'cell_ab'].includes(activeWorkspace) ? activeWorkspace : 'cell_s'),
    selectInspectorTarget: (...args) => selectInspectorTarget(...args),
    refreshCellTasks: (...args) => refreshCellTasks(...args),
  };
  const actions = createCellActions(ctx);
  Object.assign(ctx, actions, {
    bindActionButton(btn, b, fallbackRobotId) {
      btn.dataset.operatorAction = '1';
      btn.addEventListener('click', () => {
        activeBtn = btn;
        queueMicrotask(() => { if (activeBtn === btn) activeBtn = null; });
      });
      actions.bindActionButton(btn, b, fallbackRobotId);
    },
  });
  const {
    runPresetTask, createCustomTask, loadStationZonesYaml, saveStationZonesYaml,
    runVisionAutoCheck, toggleCableGuard, refreshPipeline, evaluate, queueRun, promotePhysics,
  } = actions;
  const {renderRightInspector, renderVisualCards, renderCameraMatrix, syncCardSelection} = createCellViews(ctx);

  function toggleLiveStream() {
    liveStreamOn = !liveStreamOn;
    const btn = $('cell-live-stream-toggle');
    if (btn) {
      btn.textContent = liveStreamOn ? '실시간 카메라 자동갱신 (ON · 2초)' : '실시간 카메라 자동갱신 (OFF · 일시정지)';
    }
    cellFrames?.setRunning(liveStreamOn);
  }

  function syncOperatorButtons() {
    const allowed = Boolean(isOperator());
    const reason = allowed ? '' : '운영자 권한이 필요합니다';
    const staticIds = [
      'real2sim-evaluate', 'real2sim-run', 'real2sim-promote',
      'cell-task-preset-run', 'cell-task-create', 'cell-vision-auto-check',
    ];
    const dynamicBtns = typeof document !== 'undefined'
      ? [...document.querySelectorAll('#real2sim-section [data-operator-action="1"]')]
      : [];
    const buttons = new Set([...staticIds.map(id => $(id)).filter(Boolean), ...dynamicBtns]);
    for (const btn of buttons) {
      if (btn.dataset?.inflight === '1') {
        markInflight(btn);
        continue;
      }
      btn.disabled = !allowed;
      if (allowed) btn.removeAttribute('reason');
      else btn.setAttribute('reason', reason);
    }
  }

  function clear() {
    generation++;
    connected = false;
    lastCellTasksBody = null;
    lastCellTasksAt = 0;
    cellFrames?.setRunning(false);
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
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = '접속하면 OMX 셀(cell_s · cell_ab) 작업 큐와 실물 실행 상태를 확인할 수 있습니다.';
    syncOperatorButtons();
  }

  function dispose() {
    clear();
    cellFrames?.dispose();
  }

  async function refresh() {
    const current = ++generation;
    connected = true;
    syncOperatorButtons();
    if (activeWorkspace === 'prep') return;
    if (status) status.textContent = '실물↔시뮬 파이프라인 상태를 확인하는 중입니다.';
    void refreshPipeline(current);
    await refreshCellTasks(current);
  }

  function selectInspectorTarget(targetId, preferredCamId = null) {
    if (!targetId) return;
    const normalized = targetId === 'pinky' ? 'rosy_46' : targetId;
    state.selectedInspectorTarget = normalized;
    if (preferredCamId) {
      state.selectedInspectorCamByTarget[normalized] = preferredCamId;
    }
    if (lastCellTasksBody) {
      syncCardSelection();
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


  const S3_PRESET_OPTIONS = [
    {value: 's3_shuttle', label: 'S3 셔틀: Pinky 적재함 -> 벨트 인입 (cell_s · arm_s)'},
    {value: 's3_recover_belt_far', label: 'S3 벨트-원거리 오배치 복구 후 셔틀 (arm_s)'},
    {value: 's3_recover_floor_front', label: 'S3 바닥-전방 낙하 복구 후 셔틀 (arm_s)'},
    {value: 's3_auto_recover_or_shuttle', label: 'S3 자동 변위 감지 · 복구 셔틀 (arm_s)'},
  ];
  const S5_A_PRESET_OPTIONS = [
    {value: 's5_tier1_arm_a', label: 'S5 1층 적재: 벨트 -> 선박 1층 (cell_a · arm_a)'},
    {value: 's5_tier3_arm_a', label: 'S5 3층 적재: 벨트 -> 선박 3층 (cell_a · arm_a)'},
  ];
  const S5_B_PRESET_OPTIONS = [
    {value: 's5_tier2_arm_b', label: 'S5 2층 적재: 벨트 -> 선박 2층 (cell_b · arm_b)'},
  ];
  const S5_PRESET_OPTIONS = [
    {value: 's5_tier1_arm_a', label: 'S5 1층 적재: 벨트 -> 선박 1층 (cell_ab · arm_a)'},
    {value: 's5_tier2_arm_b', label: 'S5 2층 적재: 벨트 -> 선박 2층 (cell_ab · arm_b)'},
    {value: 's5_tier3_arm_a', label: 'S5 3층 적재: 벨트 -> 선박 3층 (cell_ab · arm_a)'},
  ];
  const PREP_HEADING_IDS = [
    'saved-heading', 'recipe-heading', 'cell-heading',
    'preview-heading', 'proposal-heading', 'mission-heading',
    'print-heading', 'catalog-heading',
  ];

  function applyWorkspaceScope(mode) {
    activeWorkspace = ['cell_s', 'cell_a', 'cell_b', 'cell_ab'].includes(mode) ? mode : 'prep';
    const isPrep = activeWorkspace === 'prep';
    const isCellMode = !isPrep;
    const cellMain = $('cell-main');
    if (cellMain && cellMain.dataset) cellMain.dataset.cellWorkspace = activeWorkspace;
    const purposeEl = $('cell-purpose');
    if (purposeEl) purposeEl.textContent = WORKSPACE_PURPOSE[activeWorkspace] || PREP_PURPOSE;
    if (typeof window !== 'undefined' && window.location?.href && window.history?.replaceState) {
      const url = new URL(window.location.href);
      if (isPrep) url.searchParams.delete('cell');
      else url.searchParams.set('cell', activeWorkspace);
      const nextUrl = `${url.pathname}${url.search}${url.hash}`;
      const currUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      if (nextUrl !== currUrl) window.history.replaceState(null, '', nextUrl);
    }
    const cellLine = $('cell-line');
    if (cellLine) cellLine.hidden = !isPrep;
    const switcher = $('cell-workspace-switcher');
    if (switcher && typeof switcher.querySelectorAll === 'function') {
      for (const btn of switcher.querySelectorAll('[data-cell-workspace]')) {
        const isActive = btn.dataset.cellWorkspace === activeWorkspace;
        btn.setAttribute('kind', isActive ? 'primary' : 'quiet');
        btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      }
    }
    const real2simSection = $('real2sim-section');
    if (real2simSection) {
      real2simSection.hidden = !isCellMode;
    }
    if (typeof document !== 'undefined') {
      const subnav = document.querySelector('.ui-subnav');
      if (subnav) subnav.hidden = !isPrep;
      const obsSection = document.querySelector('ui-section[aria-labelledby="observation-heading"]');
      if (obsSection) obsSection.hidden = isPrep;
      const targetCell = (activeWorkspace === 'cell_a' || activeWorkspace === 'cell_b') ? 'cell_ab' : activeWorkspace;
      const targetArm = activeWorkspace === 'cell_a' ? 'arm_a' : activeWorkspace === 'cell_b' ? 'arm_b' : '';
      for (const sec of document.querySelectorAll('#workcell-observations section[data-workcell-scope]')) {
        sec.hidden = isPrep ? true : sec.dataset.workcellScope !== targetCell;
      }
      for (const card of document.querySelectorAll('#workcell-observations article[data-arm-id]')) {
        card.hidden = Boolean(targetArm && card.dataset.armId && card.dataset.armId !== targetArm);
      }
      for (const card of document.querySelectorAll('#workcell-observations article[data-camera-arm]')) {
        card.hidden = Boolean(targetArm && card.dataset.cameraArm && card.dataset.cameraArm !== targetArm);
      }
      for (const wall of document.querySelectorAll('#workcell-observations .cell-camera-wall')) {
        wall.hidden = isCellMode;
      }
      for (const hid of PREP_HEADING_IDS) {
        const sec = document.querySelector(`ui-section[aria-labelledby="${hid}"]`);
        if (!sec) continue;
        if (isCellMode) {
          sec.hidden = true;
        } else if (hid === 'print-heading' || hid === 'catalog-heading') {
          sec.hidden = false;
        }
      }
      if (!isCellMode && subnav) {
        const activeLink = subnav.querySelector('a[aria-current="step"]') || subnav.querySelector('a[aria-current="location"]') || subnav.querySelector('a[href^="#"]');
        const activeId = activeLink?.getAttribute('href')?.slice(1) || 'saved-heading';
        for (const hid of ['saved-heading', 'recipe-heading', 'cell-heading', 'preview-heading', 'proposal-heading', 'mission-heading']) {
          const sec = document.querySelector(`ui-section[aria-labelledby="${hid}"]`);
          if (sec) sec.hidden = (hid !== activeId);
        }
        for (const hid of ['print-heading', 'catalog-heading']) {
          const sec = document.querySelector(`ui-section[aria-labelledby="${hid}"]`);
          if (sec) sec.hidden = (activeId !== 'saved-heading');
        }
        const screenLabel = $('cell-screen');
        if (screenLabel && activeLink?.textContent) screenLabel.textContent = activeLink.textContent;
      } else {
        const screenLabel = $('cell-screen');
        if (screenLabel) {
          screenLabel.textContent = activeWorkspace === 'cell_s' ? 'Cell S · S3 공급 (arm_s)'
            : activeWorkspace === 'cell_a' ? 'Cell A · S5 1·3단 (arm_a)'
            : activeWorkspace === 'cell_b' ? 'Cell B · S5 2단 (arm_b)'
            : 'Cell A/B · S5 2암 통합';
        }
      }
    }
    if (typeof window !== 'undefined' && typeof CustomEvent === 'function') {
      window.dispatchEvent(new CustomEvent('rosy:cell-workspace', {detail: {mode: activeWorkspace}}));
    }
    if (!isCellMode) {
      cellFrames?.setRunning(false);
      return;
    }
    cellFrames?.setRunning(liveStreamOn);
    const headingEl = $('real2sim-heading');
    if (headingEl) {
      headingEl.textContent = activeWorkspace === 'cell_a'
        ? 'Cell A · S5 1·3단 적층 작업대 (arm_a 단독 · 협동 통로 인터락)'
        : activeWorkspace === 'cell_b'
        ? 'Cell B · S5 2단 적층·반출 작업대 (arm_b 단독 · 협동 통로 인터락)'
        : activeWorkspace === 'cell_ab'
        ? 'Cell A/B · S5 적층 작업대 (arm_a · arm_b 2암 협동 · T1/T2/T3)'
        : 'Cell S · S3 공급 작업대 (arm_s 단독 · Pinky 하역 인터락)';
    }
    const presetOptions = activeWorkspace === 'cell_a' ? S5_A_PRESET_OPTIONS
      : activeWorkspace === 'cell_b' ? S5_B_PRESET_OPTIONS
      : activeWorkspace === 'cell_ab' ? S5_PRESET_OPTIONS : S3_PRESET_OPTIONS;
    renderSelect($('cell-task-preset'), presetOptions, presetOptions[0].value, item => item.label);
    const cellOptions = activeWorkspace === 'cell_s'
      ? [{value: 'cell_s', label: 'cell_s (S3 셔틀)'}]
      : [{value: 'cell_ab', label: activeWorkspace === 'cell_a' ? 'cell_ab (Cell A · S5 1·3단)' : activeWorkspace === 'cell_b' ? 'cell_ab (Cell B · S5 2단)' : 'cell_ab (S5 적재)'}];
    renderSelect($('cell-task-cell'), cellOptions, cellOptions[0].value, item => item.label);
    const armOptions = activeWorkspace === 'cell_a'
      ? [{value: 'arm_a', label: 'arm_a (1·3층)'}]
      : activeWorkspace === 'cell_b'
      ? [{value: 'arm_b', label: 'arm_b (2층)'}]
      : activeWorkspace === 'cell_ab'
      ? [{value: 'arm_a', label: 'arm_a (1·3층)'}, {value: 'arm_b', label: 'arm_b (2층)'}]
      : [{value: 'arm_s', label: 'arm_s'}];
    renderSelect($('cell-task-arm'), armOptions, armOptions[0].value, item => item.label);
    for (const selId of ['cell-task-cell', 'cell-task-arm']) {
      const sel = $(selId);
      const wrapper = sel?.closest?.('label') || sel?.parentElement;
      if (wrapper) wrapper.hidden = (sel?.options?.length ?? 0) <= 1;
    }
    const tierOptions = (activeWorkspace === 'cell_a' || activeWorkspace === 'cell_ab')
      ? [{value: '1', label: '1층 (Tier 1)'}, {value: '3', label: '3층 (Tier 3)'}]
      : activeWorkspace === 'cell_b'
      ? [{value: '2', label: '2층 (Tier 2)'}]
      : [{value: '1', label: '1층 (Tier 1)'}];
    renderSelect($('cell-task-tier'), tierOptions, tierOptions[0].value, item => item.label);
    const tierField = $('cell-task-tier-field');
    if (tierField) {
      tierField.hidden = (activeWorkspace === 'cell_s');
    }
    const displacedField = $('cell-task-displaced-field');
    if (displacedField) {
      displacedField.hidden = (activeWorkspace !== 'cell_s');
    }
    if (activeWorkspace !== 'cell_s' && $('cell-task-displaced')) {
      $('cell-task-displaced').value = '';
    }
    state.selectedInspectorTarget = activeWorkspace === 'cell_b' ? 'arm_b'
      : activeWorkspace === 'cell_a' ? 'arm_a'
      : activeWorkspace === 'cell_ab' ? (state.selectedInspectorTarget === 'arm_b' ? 'arm_b' : 'arm_a')
      : 'arm_s';
    if (lastCellTasksBody) {
      renderCellTasks(lastCellTasksBody);
    } else {
      renderCameraMatrix();
      syncOperatorButtons();
    }
    if (connected && (!lastCellTasksBody || Date.now() - lastCellTasksAt > 5000)) {
      void refreshCellTasks(++generation);
    }
  }

  function renderCellTasks(body) {
    lastCellTasksBody = body;
    const scope = ctx.getScope();
    const scopedTasks = Array.isArray(body?.tasks)
      ? body.tasks.filter(t => {
          if (scope === 'cell_a') return t.arm_id === 'arm_a';
          if (scope === 'cell_b') return t.arm_id === 'arm_b';
          return !scope || t.cell_id === scope;
        })
      : [];
    const scopedSummary = Array.isArray(body?.tasks)
      ? {
          total: scopedTasks.length,
          queued: scopedTasks.filter(t => t.status === 'QUEUED').length,
          running: scopedTasks.filter(t => t.status === 'RUNNING').length,
          completed: scopedTasks.filter(t => t.status === 'COMPLETED').length,
        }
      : body?.summary;
    const scopedBody = body ? {...body, tasks: scopedTasks, summary: scopedSummary} : body;
    renderVisualCards(scopedBody);
    renderCameraMatrix();
    renderRightInspector(scopedBody);
    const allPairs = cellTaskSummaryPairs(scopedBody);
    const pairs = allPairs.filter(([term]) => {
      if (scope === 'cell_s' && term.includes('cell_ab')) return false;
      if ((scope === 'cell_ab' || scope === 'cell_a' || scope === 'cell_b') && term.includes('cell_s')) return false;
      return true;
    });
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
    renderTable($('cell-tasks-rows'), $('cell-tasks-table'), cellTaskRows(scopedBody));
    syncOperatorButtons();
    const taskStatus = $('cell-tasks-status');
    if (taskStatus) {
      const label = scope === 'cell_a' ? 'Cell A (arm_a · S5 1·3단)'
        : scope === 'cell_b' ? 'Cell B (arm_b · S5 2단)'
        : scope === 'cell_ab' ? 'Cell A/B (S5)' : 'Cell S (S3)';
      taskStatus.textContent = `${label} 작업 원장: ${scopedTasks.length}건`;
    }
  }

  async function refreshCellTasks(expectedGen = generation) {
    try {
      const body = await request(CELL_TASKS_PATH);
      if (expectedGen !== generation) return;
      lastCellTasksAt = Date.now();
      renderCellTasks(body);
    } catch (error) {
      if (expectedGen !== generation) return;
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `OMX 셀 작업 조회 실패: ${error.message}`;
      }
    }
  }

  const switcherEl = $('cell-workspace-switcher');
  if (switcherEl && typeof switcherEl.querySelectorAll === 'function') {
    for (const btn of switcherEl.querySelectorAll('[data-cell-workspace]')) {
      btn.addEventListener('click', () => {
        applyWorkspaceScope(btn.dataset.cellWorkspace || 'prep');
      });
    }
  }
  applyWorkspaceScope(activeWorkspace);
  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('hashchange', () => { if (activeWorkspace !== 'prep') applyWorkspaceScope(activeWorkspace); });
  }

  $('cell-task-arm')?.addEventListener('change', () => {
    const pickedArm = $('cell-task-arm')?.value;
    if (pickedArm === 'arm_b') {
      renderSelect($('cell-task-tier'), [{value: '2', label: '2층 (Tier 2)'}], '2', item => item.label);
    } else if (pickedArm === 'arm_a') {
      renderSelect($('cell-task-tier'), [{value: '1', label: '1층 (Tier 1)'}, {value: '3', label: '3층 (Tier 3)'}], '1', item => item.label);
    }
  });
  $('real2sim-refresh')?.addEventListener('click', () => { void refresh(); });
  $('real2sim-evaluate')?.addEventListener('click', () => { void evaluate(); });
  $('real2sim-run')?.addEventListener('click', () => { void queueRun(); });
  $('real2sim-promote')?.addEventListener('click', () => { void promotePhysics(); });
  $('cell-task-refresh')?.addEventListener('click', () => { void refreshCellTasks(++generation); });
  $('cell-task-preset-run')?.addEventListener('click', () => { void withBusyButton($('cell-task-preset-run'), runPresetTask); });
  $('cell-task-create')?.addEventListener('click', () => { void withBusyButton($('cell-task-create'), createCustomTask); });
  $('cell-vision-auto-check')?.addEventListener('click', () => {
    void withBusyButton($('cell-vision-auto-check'), () => runVisionAutoCheck($('cell-task-cell')?.value || 'cell_s'));
  });
  $('cell-cable-guard-toggle')?.addEventListener('click', () => { void toggleCableGuard(); });
  $('cell-live-stream-toggle')?.addEventListener('click', () => { toggleLiveStream(); });
  $('station-zones-load')?.addEventListener('click', () => { void loadStationZonesYaml(); });
  $('station-zones-save')?.addEventListener('click', () => { void saveStationZonesYaml(); });
  return {refresh, evaluate, queueRun, promotePhysics, refreshCellTasks, runPresetTask, createCustomTask, applyWorkspaceScope, syncOperatorButtons, clear, dispose};
}
