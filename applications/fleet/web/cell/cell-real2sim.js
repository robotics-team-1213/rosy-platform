// Real-to-Sim <-> Sim-to-Real closed-loop pipeline view for the Cell workspace (D-947, D-1012).

export const REAL2SIM_PATH = '/api/fleet/cell-app/real2sim-pipeline';
export const EVALUATE_PATH = '/api/fleet/cell-app/real2sim-pipeline/evaluate';
export const RUNS_PATH = '/api/fleet/cell-app/real2sim-pipeline/runs';
export const PROMOTE_PATH = '/api/fleet/cell-app/real2sim-pipeline/promote-physics';
export const CELL_TASKS_PATH = '/api/fleet/pipeline/cell-tasks';
export const PINKY_TASKS_PATH = '/api/fleet/pipeline/pinky-tasks';

const STATUS_LABEL = {
  ready: '정상 · 준비됨',
  attention: '확인 필요',
  pending: '대기',
};

const TRACK_LABEL = {
  learning_and_physics: '직렬 물리·학습 트랙 (Stage 1 -> Stage 2)',
  ros2_execution_contract: 'ROS 2 실행 계약 검증 트랙 (별도)',
};

export function readoutPairs(body) {
  if (!body || !body.active) return [];
  const cad = body.cad_inventory || {};
  const active = body.active || {};
  const fix = active.ship_fixation || {};
  const cam = active.camera_check || {};
  const diff = body.diff || {};
  const sysid = body.sysid_summary || {};
  const worst = Array.isArray(cam.worst_mm) && cam.worst_mm.length ? Math.max(...cam.worst_mm).toFixed(1) : '0.0';
  const bestRms = sysid.best_holdout_rms_deg != null ? `${sysid.best_holdout_rms_deg}° (${sysid.best_fit_id || '—'})` : '미측정';
  return [
    ['CAD 대장 · 3D 메쉬', `${cad.revision || '—'} · STL ${cad.mesh_count ?? 0}개 (${cad.berth_kit || 'v16-modular'} / 다리 ${cad.temp_bridge || 'v7'} / 판 ${cad.temp_plate || 'v11'})`],
    ['선박 고정 (v16 스페이서)', `팔 A ${fix.arm_a_gap_dy_mm ?? '—'} mm · 팔 B ${fix.arm_b_gap_dy_mm ?? '—'} mm (공칭 ${fix.nominal_spacer_dy_mm ?? 39} mm) · yaw ${fix.within_v16_yaw_budget ? '예산 내' : '초과'}`],
    ['오목 벨트 스토퍼 (2 cm 하향)', `벨트 코↔스토퍼 ${fix.belt_to_stopper_flat_mm ?? '—'} mm · 하향 ${fix.stopper_drop_mm ?? 20} mm`],
    ['위 카메라 패드 검산', `패드 ${cam.pads ?? 0}개 · 최대 오차 ${worst} mm (${cam.within_3mm ? '정상 <=3 mm' : '재측량 필요 G-19'})`],
    ['쌍둥이(Twin) · 물리 상수(SysID)', `카메라 윤곽 ${sysid.twin_camera_outline_px ?? 2.8} px (<=${sysid.twin_camera_limit_px ?? 3.0} px) · 최적 보류 RMS ${bestRms}`],
    ['스냅샷 차이 · 재실행 단계', `변경 ${Object.keys(diff.changed || {}).length}항목 · 재실행 ${(diff.rerun || []).join(', ') || '없음'} · 레지스트리 ${(diff.gaps || []).join(', ') || '변경 없음'}`],
  ];
}

export function loopRows(body) {
  return (body?.loop_steps || []).map(row => [
    `${row.step}단계 (${row.direction})`,
    row.title,
    row.tool,
    STATUS_LABEL[row.status] || row.status,
    row.summary,
  ]);
}

export function stageRows(body) {
  return (body?.stages || []).map(stage => [
    stage.stage_order != null ? `Stage ${stage.stage_order}` : '독립 트랙',
    stage.stage.toUpperCase(),
    TRACK_LABEL[stage.track] || stage.track,
    stage.role,
    stage.release_case
      ? `케이스 ${stage.release_case} · 핸드오프 ${stage.isaac_handoff?.schema || '—'}`
      : stage.rerun
      ? `대상 단계: ${stage.rerun.join(', ')} ${(stage.flags || []).join(' ')}`.trim()
      : stage.command || '—',
  ]);
}

export function sysidRows(body) {
  return (body?.sysid_summary?.fits || []).map(fit => [
    fit.id,
    `${fit.arm} (base: ${fit.base})`,
    (fit.keys || []).join(', '),
    fit.base_hold_mean_deg != null && fit.fitted_hold_mean_deg != null
      ? `${fit.base_hold_mean_deg}° -> ${fit.fitted_hold_mean_deg}° (보류 ${fit.episodes_hold}건)`
      : '—',
    fit.ok ? '통과 (승격 가능)' : '보류 (경계/악화)',
    fit.verdict || '—',
  ]);
}

export function surveyRows(body) {
  return (body?.sysid_summary?.next_experiments || []).slice(0, 6).map(item => [
    item.constant,
    String(item.relative_width),
    item.known,
    item.experiment,
  ]);
}

export function runRows(body) {
  return (body?.runs || []).map(run => [
    run.run_id,
    run.status || 'QUEUED',
    `${run.snapshot_id} (${run.berth_kit} · ${run.physics})`,
    (run.rerun_stages || []).join(', ') || '—',
    run.cli_command || '—',
  ]);
}

export function cellTaskSummaryPairs(body) {
  if (!body) return [];
  const s = body.summary || {};
  const cells = body.cells || {};
  const s3 = cells.cell_s?.gate || {};
  const s5 = cells.cell_ab?.gate || {};
  return [
    ['OMX 태스크 원장', `전체 ${s.total ?? 0}건 · 대기 ${s.queued ?? 0}건 · 실행 중 ${s.running ?? 0}건 · 완료 ${s.completed ?? 0}건`],
    ['cell_s (S3 · arm_s)', `${s3.phase || 'IDLE'} · AMR 잠금 ${s3.amr_motion_inhibited ? 'ON' : 'OFF'}`],
    ['cell_ab (S5 · arm_a/arm_b)', `${s5.phase || 'IDLE'} · AMR 잠금 ${s5.amr_motion_inhibited ? 'ON' : 'OFF'}`],
  ];
}

export function cellTaskRows(body) {
  return (body?.tasks || []).slice().reverse().map(t => {
    const stopEv = t.hardware_telemetry?.stop_event || {};
    const foldedTxt = stopEv.folded === true
      ? `홈 복귀 완료 (folded: true · [${(stopEv.state || []).join(', ')}])`
      : Array.isArray(stopEv.state)
      ? `[${stopEv.state.join(', ')}]`
      : '—';
    const disp = t.displaced_to ? ` (복구: ${t.displaced_to})` : '';
    return [
      t.task_id,
      `${t.cell_id} / ${t.arm_id}`,
      `${t.src_site} -> ${t.dst_site} (T${t.tier ?? 1})${disp}`,
      t.status || 'QUEUED',
      foldedTxt,
    ];
  });
}

export function visualCardSpecs(body = {}) {
  const tasks = Array.isArray(body?.tasks) ? body.tasks : [];
  const pinkyTasks = Array.isArray(body?.pinky_tasks) ? body.pinky_tasks : [];
  const cells = body?.cells || {};
  const lastForCell = cellId => {
    const matches = tasks.filter(t => t.cell_id === cellId);
    return matches.length ? matches[matches.length - 1] : null;
  };
  const formatTaskMeta = task => {
    if (!task) return {last_task: '대기 중 (최근 태스크 없음)', folded_state: 'folded: true (홈 대기)', task_id: null, status: null};
    const stopEv = task.hardware_telemetry?.stop_event || {};
    const hs = task.health_summary || {};
    const health = stopEv.health || {};
    const maxTemp = hs.max_temp_c ?? (Array.isArray(health.temp_c) && health.temp_c.length ? Math.max(...health.temp_c) : null);
    const maxCur = hs.max_current_ma ?? (Array.isArray(health.current_ma) && health.current_ma.length ? Math.max(...health.current_ma) : null);
    const healthTxt = [maxTemp != null ? `${maxTemp}°C` : '', maxCur != null ? `${maxCur}mA` : '', hs.substage || ''].filter(Boolean).join(' · ');
    const stateArr = Array.isArray(stopEv.state) ? stopEv.state.map(v => Number(v).toFixed(1)).join(', ') : '';
    const baseFold = stopEv.folded === true
      ? `홈 복귀 완료 (folded: true${stateArr ? ` · [${stateArr}]` : ''})`
      : stateArr ? `[${stateArr}]` : '실행/대기';
    return {
      task_id: task.task_id,
      status: task.status || 'QUEUED',
      last_task: `${task.task_id} · ${task.arm_id} · ${task.status || 'QUEUED'}`,
      folded_state: [baseFold, healthTxt].filter(Boolean).join(' · '),
    };
  };
  const taskControlButtons = meta => {
    if (!meta?.task_id) return [];
    if (meta.status === 'QUEUED' || meta.status === 'RUNNING') {
      return [{label: '작업 취소', cancelTaskId: meta.task_id}];
    }
    return [{label: '재실행', retryTaskId: meta.task_id}];
  };
  const s3Gate = cells.cell_s?.gate || {};
  const s5Gate = cells.cell_ab?.gate || {};
  const s3Meta = formatTaskMeta(lastForCell('cell_s'));
  const s5Meta = formatTaskMeta(lastForCell('cell_ab'));
  const lastPinky = pinkyTasks.length ? pinkyTasks[pinkyTasks.length - 1] : null;
  return [
    {
      id: 'cell_s',
      title: 'cell_s · S3 하역 셔틀 (arm_s)',
      cameraUrl: '/api/fleet/pipeline/cell-camera/cell_s',
      phase: s3Gate.phase || 'IDLE',
      amr_motion_inhibited: Boolean(s3Gate.amr_motion_inhibited),
      ...s3Meta,
      buttons: [
        {label: 'S3 셔틀 (Pinky→Belt)', preset: 's3_shuttle'},
        {label: '자동 감지·복구 셔틀', preset: 's3_auto_recover_or_shuttle'},
        {label: 'Belt-Far 이탈 복구', preset: 's3_recover_belt_far'},
        {label: 'Floor-Front 바닥 복구', preset: 's3_recover_floor_front'},
        ...taskControlButtons(s3Meta),
      ],
    },
    {
      id: 'cell_ab',
      title: 'cell_ab · S5 팔레트 적재 (arm_a · arm_b)',
      cameraUrl: '/api/fleet/pipeline/cell-camera/cell_ab',
      phase: s5Gate.phase || 'IDLE',
      amr_motion_inhibited: Boolean(s5Gate.amr_motion_inhibited),
      ...s5Meta,
      buttons: [
        {label: '1층 적재 (arm_a)', preset: 's5_tier1_arm_a'},
        {label: '2층 적재 (arm_b)', preset: 's5_tier2_arm_b'},
        {label: '3층 적재 (arm_a)', preset: 's5_tier3_arm_a'},
        {label: 'S3→S5 연속 실행', preset: 'full_s3_to_s5_pipeline'},
        ...taskControlButtons(s5Meta),
      ],
    },
    {
      id: 'pinky',
      robot_id: lastPinky?.robot_id || 'rosy_46',
      title: `Pinky AMR · ${lastPinky?.robot_id || 'rosy_46'} 도킹·배차 (케이블 보호 ≤1.5cm)`,
      cameraUrl: '/api/fleet/pipeline/cell-camera/pinky',
      phase: lastPinky?.target_place ? `위치 ${lastPinky.target_place}` : (s3Gate.docked_robot?.robot_id ? `S3 도킹 (${s3Gate.docked_robot.robot_id})` : 'READY'),
      amr_motion_inhibited: Boolean(s3Gate.amr_motion_inhibited || s5Gate.amr_motion_inhibited),
      last_task: lastPinky ? `${lastPinky.task_id} · ${lastPinky.action} -> ${lastPinky.target_place}` : 'S3 도킹 및 미세이동 준비 완료',
      folded_state: s3Gate.amr_motion_inhibited ? 'AMR 이동 잠금 (팔 작업 중)' : '케이블 보호 미세이동 모드 (최대 1.5cm · 0.02m/s)',
      buttons: [
        {label: 'S3 도킹+하역', pinkyAction: 'dock_and_unload_s3'},
        {label: 'S3 도킹', pinkyAction: 'dock_s3'},
        {label: '미세 전진 1.5cm', pinkyAction: 'micro_forward_2cm'},
        {label: '미세 후진 1.5cm', pinkyAction: 'micro_reverse_2cm'},
        {label: '즉시 정지', pinkyAction: 'stop_now'},
        {label: '충전소(C1)', pinkyAction: 'charge_c1'},
        {label: '출구(S1) 출발', pinkyAction: 'depart_s1'},
      ],
    },
  ];
}

export function createReal2SimPipeline({request, $, isOperator = () => false}) {
  const status = $('real2sim-status');
  let generation = 0;

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

  function renderVisualCards(body) {
    const wrap = $('cell-visual-cards');
    if (!wrap) return;
    const cards = visualCardSpecs(body);
    wrap.replaceChildren(...cards.map(card => {
      const article = document.createElement('article');
      article.className = 'cell-visual-card';
      article.dataset.cardId = card.id;

      const thumb = document.createElement('img');
      thumb.className = 'cell-visual-thumb';
      thumb.src = `${card.cameraUrl}?t=${Date.now()}`;
      thumb.alt = card.title;
      thumb.loading = 'lazy';

      const head = document.createElement('div');
      head.className = 'cell-visual-head';
      const title = document.createElement('strong');
      title.textContent = card.title;
      const badge = document.createElement('span');
      badge.className = 'cell-visual-badge';
      badge.textContent = `${card.phase} · AMR 잠금 ${card.amr_motion_inhibited ? 'ON' : 'OFF'}`;
      head.append(title, badge);

      const meta = document.createElement('p');
      meta.className = 'cell-visual-meta';
      meta.textContent = `${card.last_task} | ${card.folded_state}`;

      const actions = document.createElement('div');
      actions.className = 'cell-visual-actions';
      for (const b of card.buttons) {
        const btn = document.createElement('ui-button');
        btn.setAttribute('kind', b.cancelTaskId ? 'irreversible' : 'quiet');
        btn.setAttribute('type', 'button');
        btn.textContent = b.label;
        if (b.preset) {
          btn.dataset.cellQuickPreset = b.preset;
          btn.addEventListener('click', () => runQuickPreset(b.preset));
        } else if (b.pinkyAction) {
          btn.dataset.pinkyQuickAction = b.pinkyAction;
          btn.addEventListener('click', () => runPinkyQuickAction(card.robot_id || 'rosy_46', b.pinkyAction));
        } else if (b.cancelTaskId) {
          btn.addEventListener('click', () => cancelOrRetryTask(b.cancelTaskId, 'cancel'));
        } else if (b.retryTaskId) {
          btn.addEventListener('click', () => cancelOrRetryTask(b.retryTaskId, 'retry'));
        }
        actions.append(btn);
      }

      article.append(thumb, head, meta, actions);
      return article;
    }));
  }

  async function cancelOrRetryTask(taskId, op) {
    const current = ++generation;
    const verb = op === 'cancel' ? '취소' : '재실행';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `태스크(${taskId}) ${verb} 요청 중입니다.`;
    try {
      await request(`${CELL_TASKS_PATH}/${taskId}/${op}`, {method: 'POST'});
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `태스크(${taskId}) ${verb} 완료`;
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `태스크 ${verb} 실패: ${error.message}`;
    }
  }

  async function runQuickPreset(preset) {
    const current = ++generation;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `카드 원클릭 프리셋(${preset})을 실행하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({preset}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const ids = (res.tasks || [res.task]).filter(Boolean).map(t => t.task_id).join(', ');
        $('cell-tasks-status').textContent = `카드 프리셋 실행 등록 완료: ${ids}`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `카드 프리셋 등록 실패: ${error.message}`;
    }
  }

  async function runPinkyQuickAction(robotId, action) {
    const current = ++generation;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `핑키(${robotId}) 작업(${action})을 실행하는 중입니다.`;
    try {
      const res = await request(PINKY_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({robot_id: robotId, action}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const spawned = res.spawned_cell_task ? ` + 셀 태스크(${res.spawned_cell_task.task_id})` : '';
        $('cell-tasks-status').textContent = `핑키(${robotId}) ${action} 완료 -> ${res.pinky_task?.target_place || '—'}${spawned}`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `핑키 작업 실행 실패: ${error.message}`;
    }
  }

  function renderCellTasks(body) {
    renderVisualCards(body);
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

  async function runPresetTask() {
    const current = ++generation;
    const preset = $('cell-task-preset')?.value || 's3_shuttle';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `프리셋(${preset}) 태스크를 할당하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({preset}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const ids = (res.tasks || [res.task]).filter(Boolean).map(t => t.task_id).join(', ');
        $('cell-tasks-status').textContent = `프리셋 태스크 등록 완료: ${ids}`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `프리셋 태스크 등록 실패: ${error.message}`;
    }
  }

  async function createCustomTask() {
    const current = ++generation;
    const cellId = $('cell-task-cell')?.value || 'cell_s';
    const armId = $('cell-task-arm')?.value || (cellId === 'cell_s' ? 'arm_s' : 'arm_a');
    const tier = Number($('cell-task-tier')?.value || 1);
    const displacedTo = $('cell-task-displaced')?.value || null;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `맞춤 태스크(${cellId}/${armId})를 큐에 등록하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, arm_id: armId, tier, displaced_to: displacedTo}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `맞춤 태스크 큐 등록 완료: ${res.task?.task_id || '—'} (${cellId}/${armId})`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `맞춤 태스크 등록 실패: ${error.message}`;
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
  return {refresh, evaluate, queueRun, promotePhysics, refreshCellTasks, runPresetTask, createCustomTask, clear};
}
