// Cell task action handlers for the Real-to-Sim pipeline view (split from cell-real2sim.js).
import {
  CELL_TASKS_PATH,
  PINKY_TASKS_PATH,
  DECISION_GATE_PATH,
  HUMAN_SAFETY_PATH,
  STATION_ZONES_PATH,
  STATION_ZONES_DISPATCH_PATH,
  CABLE_GUARD_PATH,
  VISION_CHECK_PATH,
  ARM_HOLDS_CLEAR_PATH,
} from './cell-real2sim-specs.js';

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
    const current = ctx.bump();
    const actionTxt = humanDetected ? '사람 감지 비상정지(HUMAN_HOLD)' : '사람 이탈 · 작업 자동 재개';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `${actionTxt} (${cellId}) 처리 중입니다.`;
    try {
      const res = await request(HUMAN_SAFETY_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, human_detected: humanDetected, robot_id: robotId}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const detail = humanDetected
          ? `일시정지 태스크 ${(res.paused_tasks || []).length}건`
          : `자동 재개 태스크 ${(res.resumed_tasks || []).length}건`;
        $('cell-tasks-status').textContent = `${actionTxt} 완료 (${detail})`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `${actionTxt} 실패: ${error.message}`;
    }
  }

  async function runStationZoneDispatch(zoneId, robotId) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 이동/반출 태스크를 즉시 실행하는 중입니다.`;
    try {
      const res = await request(STATION_ZONES_DISPATCH_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({zone_id: zoneId, robot_id: robotId}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const spawned = res.spawned_cell_task ? ` + 셀 태스크(${res.spawned_cell_task.task_id})` : '';
        $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 실행 완료 -> ${res.pinky_task?.target_place || '—'}${spawned}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 실행 실패: ${error.message}`;
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
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `Decision Gate(${subjectId}) 상황을 판단하고 자동 실행하는 중입니다.`;
    try {
      const res = await request(DECISION_GATE_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subject_id: subjectId, auto_execute: true}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const d = res.decision || {};
        $('cell-tasks-status').textContent = `Decision(${subjectId}): ${d.choice || '—'} (${d.reason || ''}) -> 자동 실행 완료`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `Decision Gate 실행 실패: ${error.message}`;
    }
  }

  async function cancelOrRetryTask(taskId, op) {
    const current = ctx.bump();
    const verb = op === 'cancel' ? '취소' : '재실행';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `태스크(${taskId}) ${verb} 요청 중입니다.`;
    try {
      await request(`${CELL_TASKS_PATH}/${taskId}/${op}`, {method: 'POST'});
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `태스크(${taskId}) ${verb} 완료`;
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `태스크 ${verb} 실패: ${error.message}`;
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
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `카드 프리셋 등록 실패: ${error.message}`;
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
        const spawned = res.spawned_cell_task ? ` + 셀 태스크(${res.spawned_cell_task.task_id})` : '';
        $('cell-tasks-status').textContent = `핑키(${robotId}) ${action} 완료 -> ${res.pinky_task?.target_place || '—'}${spawned}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `핑키 작업 실행 실패: ${error.message}`;
    }
  }

  async function runPresetTask() {
    const current = ctx.bump();
    const preset = $('cell-task-preset')?.value || 's3_shuttle';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `프리셋(${preset}) 태스크를 할당하는 중입니다.`;
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
        $('cell-tasks-status').textContent = `프리셋 태스크 등록 완료: ${ids}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `프리셋 태스크 등록 실패: ${error.message}`;
    }
  }

  async function createCustomTask() {
    const current = ctx.bump();
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
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `맞춤 태스크 큐 등록 완료: ${res.task?.task_id || '—'} (${cellId}/${armId})`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `맞춤 태스크 등록 실패: ${error.message}`;
    }
  }

  return {bindActionButton, runHumanSafetyGate, runStationZoneDispatch, runVisionAutoCheck, toggleCableGuard, runClearArmHold, loadStationZonesYaml, saveStationZonesYaml, runDecisionGate, cancelOrRetryTask, runQuickPreset, runPinkyQuickAction, runPresetTask, createCustomTask};
}
