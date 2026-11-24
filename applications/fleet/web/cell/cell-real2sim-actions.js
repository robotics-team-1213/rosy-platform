// Cell task action handlers for the Real-to-Sim pipeline view (split from cell-real2sim.js).
import { setOffBy } from "/common/cause-line.js";
import { pinkyCancelPath, reparkClosePath, RECOVERY_TOOLS_INVOKE_PATH } from './cell-pipeline-panel.js';
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
  BED_CONFIRM_TTL_S,
  bedConfirmPath,
  presenceConfirmPath,
} from './cell-real2sim-specs.js';

const BED_CONFIRM_ERROR = {
  NAMED_OPERATOR_REQUIRED: '이름 있는 운영자 로그인이 필요합니다',
  CELL_TASK_NOT_QUEUED: '대기 중인 작업이나 적재함 확인이 무효가 된 실행 중 작업만 확인할 수 있습니다',
  BED_CONFIRM_ROBOT_NOT_STOPPED: '핑키가 멈춰 있지 않습니다. 핑키가 정차 위치에 멈춘 뒤 다시 확인하세요',
  BED_CONFIRM_ROBOT_MISMATCH: '작업에 지정된 핑키가 아닙니다',
  BED_CONFIRM_POSE_UNAVAILABLE: '지도에서 핑키 위치를 확인하지 못했습니다. 정차 위치를 확인하세요',
};
const PRESENCE_CONFIRM_ERROR = {
  ...BED_CONFIRM_ERROR,
  CELL_TASK_NOT_QUEUED: '대기(QUEUED) 상태의 작업에만 입회 표시할 수 있습니다',
};

export function createCellActions(ctx) {
  const {request, $} = ctx;
  const refreshCellTasks = (...args) => ctx.refreshCellTasks(...args);
  const activeRobotId = explicit => explicit || ctx.state?.selectedRobotId || 'rosy_46';

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
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runQuickPreset(b.preset, b.robot_id); });
    } else if (b.pinkyAction) {
      setOffBy(btn, ctx.namedReason());
      btn.dataset.pinkyQuickAction = b.pinkyAction;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void runPinkyQuickAction(targetRobotId, b.pinkyAction); });
    } else if (b.bedConfirmTaskId || b.presenceConfirmTaskId) {
      const reason = ctx.namedReason();  // D-1057: the server refuses a shared or development identity too
      setOffBy(btn, reason);
      const [kind, taskId] = b.bedConfirmTaskId ? ['bed', b.bedConfirmTaskId] : ['presence', b.presenceConfirmTaskId];
      btn.dataset[`${kind}ConfirmTaskId`] = taskId;
      btn.addEventListener('click', ev => { ev.stopPropagation(); void confirmOperator(kind, taskId, targetRobotId); });
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
        $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 요청 등록됨 (QUEUED) -> ${res.pinky_task?.target_place || '—'}${spawned}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 실행 실패: ${error.message}`;
    }
  }

  async function runVisionAutoCheck(cellId = 'cell_s', robotId = null) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `비전 카메라(${cellId}) 자동 안전·이탈 점검 중입니다.`;
    try {
      const res = await request(VISION_CHECK_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, robot_id: activeRobotId(robotId)}),
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

  async function toggleCableGuard(robotId = null) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = '선 꼬임 보호 모드를 전환하는 중입니다.';
    try {
      const res = await request(CABLE_GUARD_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({toggle: true, robot_id: activeRobotId(robotId)}),
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
        $('cell-tasks-status').textContent = `Decision(${subjectId}): ${d.choice || '—'} (${d.reason || ''}) -> 판정·요청 등록됨`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `Decision Gate 실행 실패: ${error.message}`;
    }
  }

  // Named-operator confirmations of a QUEUED task (D-1057): same request shape, validity and messages.
  const CONFIRM_KINDS = {
    bed: {name: '적재함 확인', obj: '적재함 확인을', subj: '적재함 확인이', path: bedConfirmPath},
    presence: {name: '입회 표시', obj: '입회 표시를', subj: '입회 표시가', path: presenceConfirmPath},
  };
  async function confirmOperator(kind, taskId, robotId) {
    const {name, obj, subj, path} = CONFIRM_KINDS[kind];
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `태스크(${taskId}) ${obj} 보내는 중입니다.`;
    try {
      const res = await request(path(taskId), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({robot_id: robotId}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = res.renewed === false
          ? `태스크(${taskId}) ${subj} 아직 유효합니다. 유효 시간은 늘지 않습니다.`
          : `태스크(${taskId}) ${name} 완료 · ${res.expires_in_s ?? BED_CONFIRM_TTL_S}초 동안 유효`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      const errTable = kind === 'presence' ? PRESENCE_CONFIRM_ERROR : BED_CONFIRM_ERROR;
      const text = error.status === 404 && !error.code ? `서버에 ${name} 기능이 아직 없습니다 (D-1057)`
        : errTable[error.code] || error.message;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `${name} 실패: ${text}`;
    }
  }
  const confirmBed = (taskId, robotId) => confirmOperator('bed', taskId, robotId);
  const confirmPresence = (taskId, robotId) => confirmOperator('presence', taskId, robotId);

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

  async function cancelPinkyTask(taskId) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `핑키 배차(${taskId}) 취소를 요청하는 중입니다.`;
    try {
      const res = await request(pinkyCancelPath(taskId), {method: 'POST'});
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = res?.confirmed === false
          ? `정지 요청 전송됨 (${taskId}) · 트립 종료 미확인(자동 재시도 중)`
          : `핑키 배차 취소 완료: ${taskId}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `핑키 배차 취소 실패: ${error.message}`;
    }
  }

  async function closeRepark(requestId, stateVal) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `재주차(${requestId}) ${stateVal} 보고 중입니다.`;
    try {
      const res = await request(reparkClosePath(requestId), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({state: stateVal}),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const retry = res?.request?.retry_task_id ? ` -> 재시도(${res.request.retry_task_id})` : '';
        $('cell-tasks-status').textContent = `재주차(${requestId}) ${stateVal} 처리 완료${retry}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `재주차 처리 실패: ${error.message}`;
    }
  }

  async function invokeRecoveryTool(payload) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `복구 툴(${payload?.tool_name}) 실행 중입니다.`;
    try {
      const res = await request(RECOVERY_TOOLS_INVOKE_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (current !== ctx.gen()) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const act = res?.result?.action || res?.status || 'EXECUTED';
        $('cell-tasks-status').textContent = `복구 툴(${payload?.tool_name}) 완료: ${act}`;
      }
    } catch (error) {
      if (current !== ctx.gen()) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `복구 툴(${payload?.tool_name}) 거부: ${error.message}`;
    }
  }

  async function runQuickPreset(preset, robotId = null) {
    const current = ctx.bump();
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `카드 원클릭 프리셋(${preset})을 실행하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({preset, robot_id: activeRobotId(robotId)}),
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
        $('cell-tasks-status').textContent = `핑키(${robotId}) ${action} 배차 요청 등록됨 (QUEUED) -> ${res.pinky_task?.target_place || '—'}${spawned}`;
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
        body: JSON.stringify({preset, robot_id: activeRobotId()}),
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
    const dstSite = $('cell-task-dst')?.value || undefined;  // empty: the server's cell and tier default
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `맞춤 태스크(${cellId}/${armId})를 큐에 등록하는 중입니다.`;
    try {
      const res = await request(CELL_TASKS_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, arm_id: armId, robot_id: activeRobotId(), tier, displaced_to: displacedTo, dst_site: dstSite}),
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

  return {bindActionButton, confirmBed, confirmPresence, runHumanSafetyGate, runStationZoneDispatch, runVisionAutoCheck, toggleCableGuard, runClearArmHold, loadStationZonesYaml, saveStationZonesYaml, runDecisionGate, cancelOrRetryTask, cancelPinkyTask, closeRepark, invokeRecoveryTool, runQuickPreset, runPinkyQuickAction, runPresetTask, createCustomTask};
}
