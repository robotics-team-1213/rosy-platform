// Cell task action handlers for the Real-to-Sim pipeline view (split from cell-real2sim.js).
import {
  REAL2SIM_PATH,
  EVALUATE_PATH,
  RUNS_PATH,
  PROMOTE_PATH,
  CELL_TASKS_PATH,
  PINKY_TASKS_PATH,
  DECISION_GATE_PATH,
  HUMAN_SAFETY_PATH,
  HUMAN_SAFETY_CLEAR_PATH,
  STATION_ZONES_PATH,
  STATION_ZONES_DISPATCH_PATH,
  CABLE_GUARD_PATH,
  VISION_CHECK_PATH,
  ARM_HOLDS_CLEAR_PATH,
  readoutPairs,
  loopRows,
  stageRows,
  sysidRows,
  surveyRows,
  runRows,
} from './cell-real2sim-specs.js';
import {SAFETY_NOTE, safetyRefusalText} from '/console/assets/authorization.js';

export function renderSelect(selectEl, items, currentValue, labelFn) {
  if (!selectEl) return;
  selectEl.replaceChildren(...items.map(item => {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = labelFn(item);
    if (item.value === currentValue) option.selected = true;
    return option;
  }));
}

export function renderTable(tbody, tableEl, rows) {
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

export function createCellActions(ctx) {
  const {request, $} = ctx;
  const refreshCellTasks = (...args) => ctx.refreshCellTasks(...args);

  function bindActionButton(btn, b, fallbackRobotId = 'rosy_46') {
    const targetRobotId = b.robot_id || fallbackRobotId;
    if (b.decisionSubject) {
      btn.dataset.decisionSubject = b.decisionSubject;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runDecisionGate(b.decisionSubject); });
    } else if (b.visionCheckCell) {
      btn.dataset.visionCheckCell = b.visionCheckCell;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runVisionAutoCheck(b.visionCheckCell); });
    } else if (b.cableGuardToggle) {
      btn.dataset.cableGuardToggle = 'true';
      btn.addEventListener('click', ev => { ev.stopPropagation(); void toggleCableGuard(); });
    } else if (b.clearArmHold) {
      btn.dataset.clearArmHold = b.clearArmHold;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runClearArmHold(b.clearArmHold); });
    } else if (b.humanSafetyCell) {
      btn.dataset.humanSafetyCell = b.humanSafetyCell;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runHumanSafetyGate(b.humanSafetyCell, b.humanDetected, targetRobotId); });
    } else if (b.zoneId) {
      btn.dataset.zoneId = b.zoneId;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runStationZoneDispatch(b.zoneId, targetRobotId); });
    } else if (b.preset) {
      btn.dataset.cellQuickPreset = b.preset;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runQuickPreset(b.preset); });
    } else if (b.pinkyAction) {
      btn.dataset.pinkyQuickAction = b.pinkyAction;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runPinkyQuickAction(targetRobotId, b.pinkyAction); });
    } else if (b.cancelTaskId) {
      btn.addEventListener('click', ev => { ev.stopPropagation(); void cancelOrRetryTask(b.cancelTaskId, 'cancel'); });
    } else if (b.retryTaskId) {
      btn.addEventListener('click', ev => { ev.stopPropagation(); void cancelOrRetryTask(b.retryTaskId, 'retry'); });
    }
  }

  async function runHumanSafetyGate(cellId, humanDetected, robotId) {
    const actionTxt = humanDetected ? '사람 감지 비상정지(HUMAN_HOLD)' : '사람 이탈 · 정지 해제(작업은 재개 전까지 대기)';
    let note = '';
    if (!humanDetected) {  // clearing a hold: the operator types what they checked; no confirmation, no request
      note = ctx.confirm ? await ctx.confirm({message: `${cellId}에서 사람이 없는 것을 직접 확인했습니까? 확인한 내용은 감사 기록에 남습니다.`,
        action: '정지 해제', note: SAFETY_NOTE}) : false;
      if (!note) return;
    }
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `${actionTxt} (${cellId}) 처리 중입니다.`;
    try {
      const res = await request(humanDetected ? HUMAN_SAFETY_PATH : HUMAN_SAFETY_CLEAR_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, human_detected: humanDetected, robot_id: robotId, ...(humanDetected ? {} : {note})}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const detail = humanDetected
          ? `일시정지 작업 ${(res.paused_tasks || []).length}건`
          : `재개 대기 작업 ${(res.still_paused_tasks || []).length}건`;
        $('cell-tasks-status').textContent = `${actionTxt} 완료 (${detail})`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `${actionTxt} 실패: ${safetyRefusalText(error)}`;
    }
  }

  async function runStationZoneDispatch(zoneId, robotId) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 이동/반출 작업를 즉시 실행하는 중입니다.`;
    try {
      const res = await request(STATION_ZONES_DISPATCH_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({zone_id: zoneId, robot_id: robotId}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const spawned = res.spawned_cell_task ? ` + 셀 작업(${res.spawned_cell_task.task_id})` : '';
        $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 실행 완료 -> ${res.pinky_task?.target_place || '—'}${spawned}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 실행 실패: ${safetyRefusalText(error)}`;
    }
  }

  async function runVisionAutoCheck(cellId = 'cell_s') {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `비전 카메라(${cellId}) 자동 안전·이탈 점검 중입니다.`;
    try {
      const res = await request(VISION_CHECK_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, robot_id: 'rosy_46'}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const v = res.vision || {};
        $('cell-tasks-status').textContent = `비전 자동 점검(${cellId}) 완료: 사람 감지=${v.human_detected ? 'YES(E-Stop)' : 'NO(정상)'} · 이탈=${v.displaced_to || '없음'} · 프레임 ${v.snapshot_bytes ?? 0}B`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `비전 자동 점검 실패: ${error.message}`;
    }
  }

  async function toggleCableGuard() {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = '선 꼬임 보호 모드를 전환하는 중입니다.';
    try {
      const res = await request(CABLE_GUARD_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({toggle: true, robot_id: 'rosy_46'}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = res.cable_tangled
          ? '선 꼬임 보호 ON (최대 1.5cm · 0.02m/s 미세 이동)'
          : '선 꼬임 보호 OFF (정상 주행 속도 모드)';
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `선 꼬임 보호 전환 실패: ${error.message}`;
    }
  }

  async function runClearArmHold(cellOrArmId) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `팔 홀드(${cellOrArmId}) 점검 및 해제를 요청하는 중입니다.`;
    try {
      const res = await request(ARM_HOLDS_CLEAR_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          arm_id: cellOrArmId,
          note: 'Fleet 콘솔 카메라로 홈 복귀(folded: true) 및 간섭 없음 확인 후 홀드 해제',
        }),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `팔 홀드 해제 완료: ${(res.cleared_arms || []).join(', ')}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `팔 홀드 해제 실패: ${error.message}`;
    }
  }

  async function loadStationZonesYaml() {
    try {
      const res = await request(STATION_ZONES_PATH);
      if ($('station-zones-yaml')) $('station-zones-yaml').value = res.yaml_text || '';
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `station_zones.yaml 불러오기 완료 (임시칸 ${(res.staging_bays || []).length}개 · 반출대 ${(res.export_stations || []).length}개)`;
      }
    } catch (error) {
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `station_zones.yaml 조회 실패: ${error.message}`;
    }
  }

  async function saveStationZonesYaml() {
    const current = ctx.bump();
    const yamlText = $('station-zones-yaml')?.value || '';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = 'station_zones.yaml 설정을 저장하고 카드를 갱신하는 중입니다.';
    try {
      const res = await request(STATION_ZONES_PATH, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({yaml_text: yamlText}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `station_zones.yaml 저장·반영 완료 (임시칸 ${(res.staging_bays || []).length}개 · 반출대 ${(res.export_stations || []).length}개)`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `station_zones.yaml 저장 실패: ${error.message}`;
    }
  }

  async function runDecisionGate(subjectId) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `Decision Gate(${subjectId}) 상황을 판단해 제안하는 중입니다.`;
    try {
      const res = await request(DECISION_GATE_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subject_id: subjectId}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const d = res.decision || {};
        $('cell-tasks-status').textContent = `Decision(${subjectId}): ${d.choice || '—'} (${d.reason || ''}) -> 제안 등록 (다른 운영자의 승인 필요)`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `Decision Gate 실행 실패: ${error.message}`;
    }
  }

  async function cancelOrRetryTask(taskId, op) {
    const current = ctx.bump();
    const verb = op === 'cancel' ? '취소' : '재실행';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `작업(${taskId}) ${verb} 요청 중입니다.`;
    try {
      await request(`${CELL_TASKS_PATH}/${taskId}/${op}`, {method: 'POST'});
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `작업(${taskId}) ${verb} 완료`;
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `작업 ${verb} 실패: ${error.message}`;
    }
  }

  async function runQuickPreset(preset) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `카드 원클릭 프리셋(${preset})을 실행하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({preset}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const ids = (res.tasks || [res.task]).filter(Boolean).map(t => t.task_id).join(', ');
        $('cell-tasks-status').textContent = `카드 프리셋 실행 등록 완료: ${ids}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `카드 프리셋 등록 실패: ${safetyRefusalText(error)}`;
    }
  }

  async function runPinkyQuickAction(robotId, action) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `핑키(${robotId}) 작업(${action})을 실행하는 중입니다.`;
    try {
      const res = await request(PINKY_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({robot_id: robotId, action}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const spawned = res.spawned_cell_task ? ` + 셀 작업(${res.spawned_cell_task.task_id})` : '';
        $('cell-tasks-status').textContent = `핑키(${robotId}) ${action} 완료 -> ${res.pinky_task?.target_place || '—'}${spawned}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `핑키 작업 실행 실패: ${safetyRefusalText(error)}`;
    }
  }

  async function runPresetTask() {
    const current = ctx.bump();
    const preset = $('cell-task-preset')?.value || 's3_shuttle';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `프리셋(${preset}) 작업를 할당하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({preset}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const ids = (res.tasks || [res.task]).filter(Boolean).map(t => t.task_id).join(', ');
        $('cell-tasks-status').textContent = `프리셋 작업 등록 완료: ${ids}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `프리셋 작업 등록 실패: ${safetyRefusalText(error)}`;
    }
  }

  async function createCustomTask() {
    const current = ctx.bump();
    const cellId = $('cell-task-cell')?.value || 'cell_s';
    const armId = $('cell-task-arm')?.value || (cellId === 'cell_s' ? 'arm_s' : 'arm_a');
    const tier = Number($('cell-task-tier')?.value || 1);
    const displacedTo = $('cell-task-displaced')?.value || null;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `맞춤 작업(${cellId}/${armId})를 큐에 등록하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, arm_id: armId, tier, displaced_to: displacedTo}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `맞춤 작업 큐 등록 완료: ${res.task?.task_id || '—'} (${cellId}/${armId})`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `맞춤 작업 등록 실패: ${safetyRefusalText(error)}`;
    }
  }

  function renderBody(body) {
    const status = $('real2sim-status');
    const snaps = (body.snapshots || []).map(s => ({
      value: s.id,
      label: `${s.id} (${s.taken_at ? s.taken_at.slice(0, 16).replace('T', ' ') : '시각 미상'})`,
    }));
    renderSelect($('real2sim-snapshot'), snaps, body.active?.id || '', item => item.label);
    renderSelect($('real2sim-prev'), [{value: '', label: '자동 (직전 스냅샷)'}, ...snaps], body.previous?.id || '', item => item.label);
    const cands = (body.physics_candidates || []).map(c => ({
      value: c.name,
      label: c.holdout_rms_deg != null ? `${c.name} (보류 RMS ${c.holdout_rms_deg}°)` : c.name,
    }));
    if (cands.length) renderSelect($('real2sim-physics'), cands, $('real2sim-physics')?.value || 'servo-antijitter-20261112', item => item.label);
    const fits = (body.sysid_summary?.fits || []).map(f => ({
      value: f.id,
      label: `${f.id} (${f.ok ? '통과' : '보류'} · ${f.fitted_hold_mean_deg ?? '—'}°)`,
    }));
    if (fits.length) renderSelect($('real2sim-fit-id'), fits, $('real2sim-fit-id')?.value || body.sysid_summary?.best_fit_id || fits[0].value, item => item.label);
    const pairs = readoutPairs(body);
    const figures = $('real2sim-figures');
    if (figures) {
      figures.replaceChildren(...pairs.flatMap(([term, desc]) => {
        const dt = document.createElement('dt'); dt.textContent = term;
        const dd = document.createElement('dd'); dd.textContent = desc;
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
    if (handoffEl) handoffEl.textContent = isaacStage?.isaac_handoff ? JSON.stringify(isaacStage.isaac_handoff, null, 2) : '';
    ctx.syncOperatorButtons?.();
    if (status) status.textContent = `스냅샷 ${body.active?.id || '—'} · 이전 ${body.previous?.id || '없음'} · Stage 1(MuJoCo) -> Stage 2(Isaac Sim) 파이프라인 준비 완료`;
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

  async function refreshPipeline(current) {
    const status = $('real2sim-status');
    try {
      const snap = $('real2sim-snapshot')?.value || '', prev = $('real2sim-prev')?.value || '';
      const params = new URLSearchParams({
        berth_kit: $('real2sim-berth-kit')?.value || 'v16-modular',
        ship_spacer_dy_mm: $('real2sim-spacer-dy')?.value || '39',
        ship_stern_hook_mm: $('real2sim-stern-hook')?.value || '0',
      });
      if (snap) params.set('snapshot', snap);
      if (prev) params.set('prev', prev);
      const body = await request(`${REAL2SIM_PATH}?${params.toString()}`);
      if (current !== ctx.gen()) return;
      renderBody(body);
    } catch (error) {
      if (current !== ctx.gen()) return;
      if (status) status.textContent = `실물↔시뮬 파이프라인을 읽지 못했습니다: ${error.message}`;
    }
  }

  async function evaluate() {
    const current = ctx.bump();
    const status = $('real2sim-status');
    if (!status) return;
    status.textContent = '선택한 고정 키트·보정 설정으로 Stage 1 -> Stage 2 파이프라인을 평가하는 중입니다.';
    try {
      const body = await request(EVALUATE_PATH, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(currentPayload())});
      if (current !== ctx.gen()) return;
      renderBody(body);
    } catch (error) {
      if (current !== ctx.gen()) return;
      status.textContent = `실물↔시뮬 파이프라인 평가 실패: ${error.message}`;
    }
  }

  async function queueRun() {
    const current = ctx.bump();
    const status = $('real2sim-status');
    if (!status) return;
    status.textContent = 'Stage 1(MuJoCo) -> Stage 2(Isaac Sim) 실행 번들을 큐에 등록하는 중입니다.';
    try {
      const res = await request(RUNS_PATH, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(currentPayload())});
      if (current !== ctx.gen()) return;
      renderTable($('real2sim-runs-rows'), $('real2sim-runs-table'), runRows(res));
      status.textContent = `파이프라인 실행 큐 등록 완료: ${res.run?.run_id || '—'} (${(res.run?.rerun_stages || []).join(', ')})`;
    } catch (error) {
      if (current !== ctx.gen()) return;
      status.textContent = `파이프라인 실행 큐 등록 실패: ${error.message}`;
    }
  }

  async function promotePhysics() {
    const current = ctx.bump();
    const status = $('real2sim-status');
    if (!status) return;
    const fitId = $('real2sim-fit-id')?.value || '';
    const candidateName = ($('real2sim-promote-name')?.value || '').trim();
    status.textContent = `SysID 후보(${fitId} -> ${candidateName || '이름 미지정'})를 검증·승격하는 중입니다.`;
    try {
      const res = await request(PROMOTE_PATH, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({fit_id: fitId, candidate_name: candidateName})});
      if (current !== ctx.gen()) return;
      const cands = (res.physics_candidates || []).map(c => ({
        value: c.name,
        label: c.holdout_rms_deg != null ? `${c.name} (보류 RMS ${c.holdout_rms_deg}°)` : c.name,
      }));
      renderSelect($('real2sim-physics'), cands, res.promoted, item => item.label);
      status.textContent = `물리 상수 후보 승격 완료: ${res.promoted} (${res.verdict})`;
    } catch (error) {
      if (current !== ctx.gen()) return;
      status.textContent = `물리 상수 후보 승격 실패: ${error.message}`;
    }
  }

  return {bindActionButton, runHumanSafetyGate, runStationZoneDispatch, runVisionAutoCheck, toggleCableGuard, runClearArmHold, loadStationZonesYaml, saveStationZonesYaml, runDecisionGate, cancelOrRetryTask, runQuickPreset, runPinkyQuickAction, runPresetTask, createCustomTask, renderBody, refreshPipeline, evaluate, queueRun, promotePhysics};
}
