// Real-to-Sim <-> Sim-to-Real closed-loop pipeline view for the Cell workspace (D-947, D-1012).

export const REAL2SIM_PATH = '/api/fleet/cell-app/real2sim-pipeline';
export const EVALUATE_PATH = '/api/fleet/cell-app/real2sim-pipeline/evaluate';
export const RUNS_PATH = '/api/fleet/cell-app/real2sim-pipeline/runs';
export const PROMOTE_PATH = '/api/fleet/cell-app/real2sim-pipeline/promote-physics';
export const CELL_TASKS_PATH = '/api/fleet/pipeline/cell-tasks';
export const PINKY_TASKS_PATH = '/api/fleet/pipeline/pinky-tasks';
export const DECISION_GATE_PATH = '/api/fleet/pipeline/decision-gate';
export const HUMAN_SAFETY_PATH = '/api/fleet/pipeline/human-safety-gate';
export const STATION_ZONES_PATH = '/api/fleet/pipeline/station-zones';
export const STATION_ZONES_DISPATCH_PATH = '/api/fleet/pipeline/station-zones/dispatch';
export const CABLE_GUARD_PATH = '/api/fleet/pipeline/cable-guard';
export const VISION_CHECK_PATH = '/api/fleet/pipeline/vision-auto-check';
export const ARM_HOLDS_CLEAR_PATH = '/api/fleet/pipeline/arm-holds/clear';

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
  const decisions = body?.decisions || {};
  const formatTaskMeta = (task, subjectId) => {
    const dec = decisions[subjectId] || task?.decision || null;
    const decTxt = dec ? `Decision: ${dec.choice} (${dec.reason})` : '';
    if (!task) {
      return {
        last_task: '대기 중 (최근 태스크 없음)',
        folded_state: ['folded: true (홈 대기)', decTxt].filter(Boolean).join(' · '),
        task_id: null,
        status: null,
      };
    }
    const stopEv = task.hardware_telemetry?.stop_event || {};
    const hs = task.health_summary || {};
    const health = stopEv.health || {};
    const maxTemp = hs.max_temp_c ?? (Array.isArray(health.temp_c) && health.temp_c.length ? Math.max(...health.temp_c) : null);
    const maxCur = hs.max_current_ma ?? (Array.isArray(health.current_ma) && health.current_ma.length ? Math.max(...health.current_ma) : null);
    const healthTxt = [maxTemp != null ? `${maxTemp}°C` : '', maxCur != null ? `${maxCur}mA` : '', hs.substage || '', decTxt].filter(Boolean).join(' · ');
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
    if (meta.status === 'QUEUED' || meta.status === 'RUNNING' || meta.status === 'PAUSED_HUMAN') {
      return [{label: '작업 취소', cancelTaskId: meta.task_id}];
    }
    return [{label: '재실행', retryTaskId: meta.task_id}];
  };
  const s3Gate = cells.cell_s?.gate || {};
  const s5Gate = cells.cell_ab?.gate || {};
  const s3Meta = formatTaskMeta(lastForCell('cell_s'), 'cell_s');
  const s5Meta = formatTaskMeta(lastForCell('cell_ab'), 'cell_ab');
  const lastPinky = pinkyTasks.length ? pinkyTasks[pinkyTasks.length - 1] : null;
  const pinkyId = lastPinky?.robot_id || 'rosy_46';
  const pinkyDec = decisions[pinkyId] || lastPinky?.decision || null;
  const hs = body?.human_safety || {};
  const s3Human = Boolean(hs.human_detected?.cell_s || hs.active_estop || s3Gate.phase === 'HUMAN_HOLD');
  const s5Human = Boolean(hs.human_detected?.cell_ab || hs.active_estop || s5Gate.phase === 'HUMAN_HOLD');
  const anyHuman = Boolean(hs.active_estop || s3Human || s5Human);
  const armHolds = body?.arm_holds || {};
  const s3Hold = armHolds.arm_s?.held ? `홀드(arm_s: ${armHolds.arm_s.reason || '점검 필요'})` : '';
  const s5HoldArms = ['arm_a', 'arm_b'].filter(a => armHolds[a]?.held);
  const s5Hold = s5HoldArms.length ? `홀드(${s5HoldArms.join('/')})` : '';
  if (s3Hold) s3Meta.folded_state = [s3Meta.folded_state, s3Hold].filter(Boolean).join(' · ');
  if (s5Hold) s5Meta.folded_state = [s5Meta.folded_state, s5Hold].filter(Boolean).join(' · ');
  const cableTangled = body?.cable_tangled !== false;
  const stationZones = body?.station_zones || {};
  const extraExportForCell = (cellId, defaultIds) =>
    (stationZones.export_stations || [])
      .filter(z => z.cell_id === cellId && !defaultIds.includes(z.id))
      .map(z => ({label: `${z.label} (YAML: ${z.id})`, zoneId: z.id}));
  const extraPinkyZones = [
    ...(stationZones.staging_bays || []),
    ...(stationZones.export_stations || []).filter(z => !z.cell_id),
  ]
    .filter(z => !['STG_C2', 'STG_S3_WAIT', 'EXP_S1'].includes(z.id))
    .map(z => ({label: `${z.label} (YAML: ${z.id})`, zoneId: z.id}));
  return [
    {
      id: 'cell_s',
      title: 'cell_s · S3 하역 셔틀 (arm_s)',
      cameraUrl: '/api/fleet/pipeline/cell-camera/cell_s',
      cameraViews: [
        {id: 'cell_s', label: 'S3 상단(arm_s_top)', url: '/api/fleet/pipeline/cell-camera/arm_s_top'},
        {id: 'arm_s_wrist', label: 'arm_s 손목', url: '/api/fleet/pipeline/cell-camera/arm_s_wrist'},
        {id: 'side', label: 'S3/S5 측면', url: '/api/fleet/pipeline/cell-camera/side'},
      ],
      phase: s3Gate.phase || 'IDLE',
      amr_motion_inhibited: Boolean(s3Gate.amr_motion_inhibited),
      ...s3Meta,
      buttons: [
        {label: 'S3 셔틀 (Pinky→Belt)', preset: 's3_shuttle'},
        {label: '상황 판단·자동 실행 (Decision)', decisionSubject: 'cell_s'},
        {label: '비전 자동 점검 (카메라)', visionCheckCell: 'cell_s'},
        {label: '자동 감지·복구 셔틀', preset: 's3_auto_recover_or_shuttle'},
        {label: 'Belt-Far 이탈 복구', preset: 's3_recover_belt_far'},
        {label: 'Floor-Front 바닥 복구', preset: 's3_recover_floor_front'},
        {label: '반출대3 반출 (YAML: EXP_S3_BELT)', zoneId: 'EXP_S3_BELT'},
        ...extraExportForCell('cell_s', ['EXP_S3_BELT']),
        {
          label: s3Human ? '사람 이탈 · 자동 재개' : '사람 감지 비상정지 (E-Stop)',
          humanSafetyCell: 'cell_s',
          humanDetected: !s3Human,
        },
        {label: s3Hold ? '팔 홀드 해제 (arm_s · 확인됨)' : '팔 홀드 점검·해제 (arm_s)', clearArmHold: 'cell_s'},
        ...taskControlButtons(s3Meta),
      ],
    },
    {
      id: 'cell_ab',
      title: 'cell_ab · S5 팔레트 적재 (arm_a · arm_b)',
      cameraUrl: '/api/fleet/pipeline/cell-camera/cell_ab',
      cameraViews: [
        {id: 'top', label: 'S5 상단(top)', url: '/api/fleet/pipeline/cell-camera/top'},
        {id: 'side', label: '측면(side)', url: '/api/fleet/pipeline/cell-camera/side'},
        {id: 'arm_a_wrist', label: 'arm_a 손목', url: '/api/fleet/pipeline/cell-camera/arm_a_wrist'},
        {id: 'arm_b_wrist', label: 'arm_b 손목', url: '/api/fleet/pipeline/cell-camera/arm_b_wrist'},
      ],
      phase: s5Gate.phase || 'IDLE',
      amr_motion_inhibited: Boolean(s5Gate.amr_motion_inhibited),
      ...s5Meta,
      buttons: [
        {label: '1층 적재 (arm_a)', preset: 's5_tier1_arm_a'},
        {label: '상황 판단·자동 실행 (Decision)', decisionSubject: 'cell_ab'},
        {label: '비전 자동 점검 (카메라)', visionCheckCell: 'cell_ab'},
        {label: '2층 적재 (arm_b)', preset: 's5_tier2_arm_b'},
        {label: '3층 적재 (arm_a)', preset: 's5_tier3_arm_a'},
        {label: 'S3→S5 연속 실행', preset: 'full_s3_to_s5_pipeline'},
        {label: '반출대2 반출 (YAML: EXP_S5_PALLET)', zoneId: 'EXP_S5_PALLET'},
        ...extraExportForCell('cell_ab', ['EXP_S5_PALLET']),
        {
          label: s5Human ? '사람 이탈 · 자동 재개' : '사람 감지 비상정지 (E-Stop)',
          humanSafetyCell: 'cell_ab',
          humanDetected: !s5Human,
        },
        {label: s5Hold ? '팔 홀드 해제 (arm_a/b · 확인됨)' : '팔 홀드 점검·해제 (arm_a/b)', clearArmHold: 'cell_ab'},
        ...taskControlButtons(s5Meta),
      ],
    },
    {
      id: 'pinky',
      robot_id: pinkyId,
      title: `Pinky AMR · ${pinkyId} 도킹·배차 (${cableTangled ? '케이블 보호 ≤1.5cm' : '정상 주행'})`,
      cameraUrl: '/api/fleet/pipeline/cell-camera/pinky',
      cameraViews: [
        {id: 'pinky', label: 'S3 도킹 뷰(pinky)', url: '/api/fleet/pipeline/cell-camera/pinky'},
        {id: 'side', label: '측면 도킹(side)', url: '/api/fleet/pipeline/cell-camera/side'},
        {id: 'arm_s_top', label: 'S3 상단(arm_s_top)', url: '/api/fleet/pipeline/cell-camera/arm_s_top'},
        {id: 'top', label: '전체 상단(top)', url: '/api/fleet/pipeline/cell-camera/top'},
      ],
      phase: lastPinky?.target_place ? `위치 ${lastPinky.target_place}` : (s3Gate.docked_robot?.robot_id ? `S3 도킹 (${s3Gate.docked_robot.robot_id})` : 'READY'),
      amr_motion_inhibited: Boolean(s3Gate.amr_motion_inhibited || s5Gate.amr_motion_inhibited),
      last_task: lastPinky ? `${lastPinky.task_id} · ${lastPinky.action} -> ${lastPinky.target_place}` : 'S3 도킹 및 미세이동 준비 완료',
      folded_state: [
        anyHuman
          ? '사람 감지 비상정지 (HUMAN_HOLD · 이탈 시 자동 재개)'
          : (s3Gate.amr_motion_inhibited
              ? 'AMR 이동 잠금 (팔 작업 중)'
              : (cableTangled ? '케이블 보호 미세이동 모드 (최대 1.5cm · 0.02m/s)' : '정상 주행 모드 (선 꼬임 보호 해제)')),
        pinkyDec ? `Decision: ${pinkyDec.choice} (${pinkyDec.reason})` : '',
      ].filter(Boolean).join(' · '),
      buttons: [
        {label: 'S3 도킹+하역', pinkyAction: 'dock_and_unload_s3'},
        {label: '상황 판단·자동 실행 (Decision)', decisionSubject: pinkyId},
        {label: '임시칸1 이동 (YAML: STG_C2)', zoneId: 'STG_C2'},
        {label: '임시칸2 이동 (YAML: STG_S3_WAIT)', zoneId: 'STG_S3_WAIT'},
        {label: '반출대1 이동 (YAML: EXP_S1)', zoneId: 'EXP_S1'},
        ...extraPinkyZones,
        {
          label: cableTangled ? '선 꼬임 보호 ON (≤1.5cm) · 해제' : '선 꼬임 보호 OFF (정상 주행) · 켜기',
          cableGuardToggle: true,
        },
        {label: 'S3 도킹', pinkyAction: 'dock_s3'},
        {label: '미세 전진 1.5cm', pinkyAction: 'micro_forward_2cm'},
        {label: '미세 후진 1.5cm', pinkyAction: 'micro_reverse_2cm'},
        {label: '즉시 정지', pinkyAction: 'stop_now'},
        {label: '충전소(C1)', pinkyAction: 'charge_c1'},
        {label: '출구(S1) 출발', pinkyAction: 'depart_s1'},
        {
          label: anyHuman ? '사람 이탈 · 자동 재개' : '사람 감지 비상정지 (E-Stop)',
          humanSafetyCell: 'all',
          humanDetected: !anyHuman,
        },
      ],
    },
  ];
}

export function inspectorSpecs(body = {}) {
  const cards = visualCardSpecs(body);
  const s3Card = cards.find(c => c.id === 'cell_s') || {};
  const s5Card = cards.find(c => c.id === 'cell_ab') || {};
  const pinkyCard = cards.find(c => c.id === 'pinky') || {};
  const tasks = Array.isArray(body?.tasks) ? body.tasks : [];
  const lastForArm = armId => {
    const matches = tasks.filter(t => t.arm_id === armId);
    return matches.length ? matches[matches.length - 1] : null;
  };
  const armJointSnapshot = (armId, fallbackText) => {
    const t = lastForArm(armId);
    const stopEv = t?.hardware_telemetry?.stop_event || {};
    const stateArr = Array.isArray(stopEv.state) ? stopEv.state.map(v => Number(v).toFixed(1)).join(', ') : '';
    if (stateArr) {
      return `${t.task_id} · folded=${Boolean(stopEv.folded)} · [${stateArr}] (완료 스냅샷)`;
    }
    return fallbackText || 'folded: true · 홈 대기 (완료 스냅샷)';
  };
  const armHolds = body?.arm_holds || {};
  const holdText = armId => armHolds[armId]?.held
    ? `홀드 활성 (${armHolds[armId].reason || '점검 필요'})`
    : '정상 (홀드 없음)';
  const pinkyButtonsFor = robotId => (pinkyCard.buttons || []).map(b => ({
    ...b,
    robot_id: robotId,
    ...(b.decisionSubject ? {decisionSubject: robotId} : {}),
  }));
  return [
    {
      id: 'arm_s',
      shortTab: '🦾 arm_s (S3)',
      title: '🦾 OMX-AI #3 · arm_s (cell_s · S3 하역 셔틀)',
      badge: `${s3Card.phase || 'IDLE'} · AMR 잠금 ${s3Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: [
        {id: 'arm_s_wrist', label: 'arm_s 손목(근접)', url: '/api/fleet/pipeline/cell-camera/arm_s_wrist'},
        {id: 'arm_s_top', label: 'S3 상단(탑뷰)', url: '/api/fleet/pipeline/cell-camera/arm_s_top'},
        {id: 'side', label: '측면·도킹(side)', url: '/api/fleet/pipeline/cell-camera/side'},
        {id: 'pinky', label: 'S3 도킹 뷰', url: '/api/fleet/pipeline/cell-camera/pinky'},
      ],
      telemetryRows: [
        ['셀 위상 · 잠금', `${s3Card.phase || 'IDLE'} · AMR 잠금 ${s3Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['관절 스냅샷', armJointSnapshot('arm_s', s3Card.folded_state)],
        ['최근 태스크', s3Card.last_task || '대기 중'],
        ['팔 홀드 · 안전', holdText('arm_s')],
      ],
      buttons: (s3Card.buttons || []).map(b => b.clearArmHold ? {...b, clearArmHold: 'arm_s'} : b),
    },
    {
      id: 'arm_a',
      shortTab: '🦾 arm_a (S5)',
      title: '🦾 OMX-AI #1 · arm_a (cell_ab · S5 1·3층 적재)',
      badge: `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: [
        {id: 'arm_a_wrist', label: 'arm_a 손목(근접)', url: '/api/fleet/pipeline/cell-camera/arm_a_wrist'},
        {id: 'top', label: 'S5 상단(탑뷰)', url: '/api/fleet/pipeline/cell-camera/top'},
        {id: 'side', label: '측면(side)', url: '/api/fleet/pipeline/cell-camera/side'},
        {id: 'arm_b_wrist', label: 'arm_b 손목(교차)', url: '/api/fleet/pipeline/cell-camera/arm_b_wrist'},
      ],
      telemetryRows: [
        ['셀 위상 · 잠금', `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['관절 스냅샷', armJointSnapshot('arm_a', s5Card.folded_state)],
        ['최근 태스크', s5Card.last_task || '대기 중'],
        ['팔 홀드 · 안전', holdText('arm_a')],
      ],
      buttons: (s5Card.buttons || []).map(b => b.clearArmHold ? {...b, label: '팔 홀드 점검·해제 (arm_a)', clearArmHold: 'arm_a'} : b),
    },
    {
      id: 'arm_b',
      shortTab: '🦾 arm_b (S5)',
      title: '🦾 OMX-AI #2 · arm_b (cell_ab · S5 2층 적재 · 반출)',
      badge: `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: [
        {id: 'arm_b_wrist', label: 'arm_b 손목(근접)', url: '/api/fleet/pipeline/cell-camera/arm_b_wrist'},
        {id: 'top', label: 'S5 상단(탑뷰)', url: '/api/fleet/pipeline/cell-camera/top'},
        {id: 'side', label: '측면(side)', url: '/api/fleet/pipeline/cell-camera/side'},
        {id: 'arm_a_wrist', label: 'arm_a 손목(교차)', url: '/api/fleet/pipeline/cell-camera/arm_a_wrist'},
      ],
      telemetryRows: [
        ['셀 위상 · 잠금', `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['관절 스냅샷', armJointSnapshot('arm_b', s5Card.folded_state)],
        ['최근 태스크', s5Card.last_task || '대기 중'],
        ['팔 홀드 · 안전', holdText('arm_b')],
      ],
      buttons: (s5Card.buttons || []).map(b => b.clearArmHold ? {...b, label: '팔 홀드 점검·해제 (arm_b)', clearArmHold: 'arm_b'} : b),
    },
    {
      id: 'cell_s',
      shortTab: '📦 cell_s',
      title: s3Card.title || 'cell_s · S3 하역 셔틀 (arm_s)',
      badge: `${s3Card.phase || 'IDLE'} · AMR 잠금 ${s3Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: s3Card.cameraViews || [],
      telemetryRows: [
        ['셀 위상 · 잠금', `${s3Card.phase || 'IDLE'} · AMR 잠금 ${s3Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['관절 · 상태', s3Card.folded_state || '대기 중'],
        ['최근 태스크', s3Card.last_task || '대기 중'],
      ],
      buttons: s3Card.buttons || [],
    },
    {
      id: 'cell_ab',
      shortTab: '📦 cell_ab',
      title: s5Card.title || 'cell_ab · S5 팔레트 적재 (arm_a · arm_b)',
      badge: `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: s5Card.cameraViews || [],
      telemetryRows: [
        ['셀 위상 · 잠금', `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['관절 · 상태', s5Card.folded_state || '대기 중'],
        ['최근 태스크', s5Card.last_task || '대기 중'],
      ],
      buttons: s5Card.buttons || [],
    },
    ...['rosy_46', 'rosy_45', 'rosy_42'].map(rid => ({
      id: rid,
      robot_id: rid,
      shortTab: `🤖 ${rid}`,
      title: `🤖 Pinky AMR · ${rid} 도킹·배차 (${body?.cable_tangled !== false ? '케이블 보호 ≤1.5cm' : '정상 주행'})`,
      badge: pinkyCard.phase || 'READY',
      cameraViews: pinkyCard.cameraViews || [],
      telemetryRows: [
        ['도킹 · 위치', pinkyCard.phase || 'READY'],
        ['주행 · 안전 모드', pinkyCard.folded_state || '케이블 보호 미세이동 모드'],
        ['최근 배차', pinkyCard.last_task || 'S3 도킹 및 미세이동 준비 완료'],
      ],
      buttons: pinkyButtonsFor(rid),
    })),
  ];
}

export function createReal2SimPipeline({request, $, isOperator = () => false}) {
  const status = $('real2sim-status');
  let generation = 0;
  const selectedCameraByCard = {};
  let selectedInspectorTarget = 'arm_s';
  const selectedInspectorCamByTarget = {};
  let lastCellTasksBody = null;
  let liveStreamOn = true;
  let pausedStamp = Date.now();
  let liveStreamTimer = null;

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
    selectedInspectorTarget = normalized;
    if (preferredCamId) {
      selectedInspectorCamByTarget[normalized] = preferredCamId;
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

  function renderRightInspector(body) {
    const panel = $('omx-right-inspector');
    if (!panel) return;
    const specs = inspectorSpecs(body);
    const activeSpec = specs.find(s => s.id === selectedInspectorTarget) || specs[0];
    if (!activeSpec) return;

    const tabs = document.createElement('div');
    tabs.className = 'omx-inspector-tabs';
    for (const s of specs) {
      const tab = document.createElement('ui-button');
      tab.setAttribute('kind', s.id === activeSpec.id ? 'primary' : 'quiet');
      tab.setAttribute('type', 'button');
      tab.dataset.inspectTarget = s.id;
      tab.textContent = s.shortTab;
      tab.addEventListener('click', () => selectInspectorTarget(s.id));
      tabs.append(tab);
    }

    const head = document.createElement('div');
    head.className = 'omx-inspector-head';
    const title = document.createElement('strong');
    title.textContent = activeSpec.title;
    const badge = document.createElement('span');
    badge.className = 'cell-visual-badge';
    badge.textContent = activeSpec.badge;
    head.append(title, badge);

    const camViews = activeSpec.cameraViews || [];
    const activeCamId = selectedInspectorCamByTarget[activeSpec.id] || camViews[0]?.id || 'arm_s_top';
    const activeCam = camViews.find(v => v.id === activeCamId) || camViews[0] || {id: activeCamId, label: activeCamId, url: `/api/fleet/pipeline/cell-camera/${activeCamId}`};
    const camMap = new Map((body?.cameras || []).map(c => [c.id, c]));
    const formatQuality = viewId => {
      const c = camMap.get(viewId) || camMap.get(viewId === 'cell_s' ? 'arm_s_top' : (viewId === 'cell_ab' ? 'top' : viewId));
      if (!c) return 'LIVE 스트림 연동';
      return [
        c.fresh !== false ? 'LIVE' : 'STALE',
        c.sequence != null ? `seq #${c.sequence}` : '',
        c.condition || '',
        c.mean_intensity != null ? `밝기 ${c.mean_intensity}` : '',
        c.spatial_contrast != null ? `대비 ${c.spatial_contrast}` : '',
      ].filter(Boolean).join(' · ');
    };

    const stage = document.createElement('div');
    stage.className = 'omx-inspector-stage';
    const mainCam = document.createElement('img');
    mainCam.className = 'omx-inspector-main-cam omx-inspector-cam';
    mainCam.dataset.baseUrl = activeCam.url;
    mainCam.src = `${activeCam.url}?t=${activeCameraStamp()}`;
    mainCam.alt = `${activeSpec.title} 메인 카메라`;
    mainCam.tabIndex = 0;
    mainCam.addEventListener('click', () => mainCam.classList.toggle('focused'));

    const qualLine = document.createElement('span');
    qualLine.className = 'cell-visual-badge';
    qualLine.textContent = `🎥 [${activeCam.label}] ${formatQuality(activeCam.id)}`;

    const pipGrid = document.createElement('div');
    pipGrid.className = 'omx-inspector-pip-grid';
    for (const v of camViews) {
      const pip = document.createElement('div');
      pip.className = `omx-inspector-pip${v.id === activeCam.id ? ' active' : ''}`;
      pip.tabIndex = 0;
      const pImg = document.createElement('img');
      pImg.className = 'omx-inspector-cam';
      pImg.dataset.baseUrl = v.url;
      pImg.src = `${v.url}?t=${activeCameraStamp()}`;
      pImg.alt = v.label;
      pImg.loading = 'lazy';
      const pLbl = document.createElement('small');
      pLbl.textContent = `📷 ${v.label}`;
      pip.append(pImg, pLbl);
      pip.addEventListener('click', () => {
        selectedInspectorCamByTarget[activeSpec.id] = v.id;
        renderRightInspector(body);
      });
      pipGrid.append(pip);
    }
    stage.append(mainCam, qualLine, pipGrid);

    const readout = document.createElement('dl');
    readout.className = 'omx-inspector-readout';
    for (const [k, v] of (activeSpec.telemetryRows || [])) {
      const dt = document.createElement('dt');
      dt.textContent = k;
      const dd = document.createElement('dd');
      dd.textContent = v;
      readout.append(dt, dd);
    }

    const actions = document.createElement('div');
    actions.className = 'omx-inspector-actions';
    for (const b of (activeSpec.buttons || [])) {
      const btn = document.createElement('ui-button');
      btn.setAttribute('kind', b.cancelTaskId ? 'irreversible' : 'quiet');
      btn.setAttribute('type', 'button');
      btn.textContent = b.label;
      bindActionButton(btn, b, activeSpec.robot_id || 'rosy_46');
      actions.append(btn);
    }

    panel.replaceChildren(tabs, head, stage, readout, actions);
  }

  function renderVisualCards(body) {
    const wrap = $('cell-visual-cards');
    if (!wrap) return;
    const cards = visualCardSpecs(body);
    wrap.replaceChildren(...cards.map(card => {
      const article = document.createElement('article');
      const isSelected = selectedInspectorTarget === card.id
        || (card.id === 'cell_s' && selectedInspectorTarget === 'arm_s')
        || (card.id === 'cell_ab' && (selectedInspectorTarget === 'arm_a' || selectedInspectorTarget === 'arm_b'))
        || (card.id === 'pinky' && selectedInspectorTarget.startsWith('rosy_'));
      article.className = `cell-visual-card${isSelected ? ' selected-inspector' : ''}`;
      article.dataset.cardId = card.id;
      article.addEventListener('click', () => {
        const defaultTarget = card.id === 'cell_s' ? 'arm_s' : (card.id === 'cell_ab' ? 'arm_a' : (card.robot_id || 'rosy_46'));
        selectInspectorTarget(defaultTarget, selectedCameraByCard[card.id] || null);
      });

      const activeViewId = selectedCameraByCard[card.id] || card.cameraViews?.[0]?.id || card.id;
      const activeView = (card.cameraViews || []).find(v => v.id === activeViewId) || {url: card.cameraUrl};

      const thumb = document.createElement('img');
      thumb.className = 'cell-visual-thumb';
      thumb.dataset.baseUrl = activeView.url;
      thumb.src = `${activeView.url}?t=${activeCameraStamp()}`;
      thumb.alt = card.title;
      thumb.loading = 'lazy';
      thumb.tabIndex = 0;
      thumb.addEventListener('click', () => {
        thumb.classList.toggle('focused');
      });
      thumb.addEventListener('keydown', ev => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          thumb.classList.toggle('focused');
        } else if (ev.key === 'Escape') {
          thumb.classList.remove('focused');
        }
      });

      const camSwitcher = document.createElement('div');
      camSwitcher.className = 'cell-cam-switcher';
      const camMap = new Map((body?.cameras || []).map(c => [c.id, c]));
      const formatCamQuality = viewId => {
        const c = camMap.get(viewId) || camMap.get(viewId === 'cell_s' ? 'arm_s_top' : (viewId === 'cell_ab' ? 'top' : viewId));
        if (!c) return '';
        return [
          c.fresh !== false ? 'LIVE' : 'STALE',
          c.sequence != null ? `#${c.sequence}` : '',
          c.condition || '',
          c.mean_intensity != null ? `밝기 ${c.mean_intensity}` : '',
        ].filter(Boolean).join(' · ');
      };
      const camQualityBadge = document.createElement('span');
      camQualityBadge.className = 'cell-visual-badge';
      camQualityBadge.textContent = formatCamQuality(activeViewId);
      thumb.addEventListener('error', () => {
        camQualityBadge.textContent = '프레임 수신 재시도 중';
      });
      for (const v of (card.cameraViews || [])) {
        const pill = document.createElement('ui-button');
        pill.setAttribute('kind', v.id === activeViewId ? 'primary' : 'quiet');
        pill.setAttribute('type', 'button');
        pill.dataset.cameraView = v.id;
        pill.textContent = `📷 ${v.label}`;
        pill.addEventListener('click', ev => {
          ev.stopPropagation();
          selectedCameraByCard[card.id] = v.id;
          thumb.dataset.baseUrl = v.url;
          thumb.src = `${v.url}?t=${Date.now()}`;
          camQualityBadge.textContent = formatCamQuality(v.id);
          for (const child of camSwitcher.children || []) {
            if (child.tagName === 'UI-BUTTON') {
              child.setAttribute('kind', child === pill ? 'primary' : 'quiet');
            }
          }
          const targetForView = v.id.startsWith('arm_a') ? 'arm_a'
            : v.id.startsWith('arm_b') ? 'arm_b'
            : (v.id.startsWith('arm_s') || card.id === 'cell_s') ? 'arm_s'
            : card.id === 'cell_ab' ? 'cell_ab'
            : (card.robot_id || 'rosy_46');
          selectInspectorTarget(targetForView, v.id);
        });
        camSwitcher.append(pill);
      }
      if (camQualityBadge.textContent) {
        camSwitcher.append(camQualityBadge);
      }

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
      const inspectTargets = card.id === 'cell_s'
        ? [['arm_s', '🔍 우측 연동: arm_s']]
        : card.id === 'cell_ab'
        ? [['arm_a', '🔍 우측 연동: arm_a'], ['arm_b', '🔍 우측 연동: arm_b']]
        : [['rosy_46', '🔍 우측 연동: rosy_46'], ['rosy_45', '🔍 rosy_45'], ['rosy_42', '🔍 rosy_42']];
      for (const [tId, tLabel] of inspectTargets) {
        const iBtn = document.createElement('ui-button');
        iBtn.setAttribute('kind', selectedInspectorTarget === tId ? 'primary' : 'quiet');
        iBtn.setAttribute('type', 'button');
        iBtn.dataset.inspectTarget = tId;
        iBtn.textContent = tLabel;
        iBtn.addEventListener('click', ev => {
          ev.stopPropagation();
          selectInspectorTarget(tId);
        });
        actions.append(iBtn);
      }
      for (const b of card.buttons) {
        const btn = document.createElement('ui-button');
        btn.setAttribute('kind', b.cancelTaskId ? 'irreversible' : 'quiet');
        btn.setAttribute('type', 'button');
        btn.textContent = b.label;
        bindActionButton(btn, b, card.robot_id || 'rosy_46');
        actions.append(btn);
      }

      article.append(thumb, camSwitcher, head, meta, actions);
      return article;
    }));
  }

  function renderCameraMatrix(body) {
    const wall = $('cell-camera-matrix');
    if (!wall) return;
    const defaultCams = [
      {id: 'arm_s_top', label: 'S3 상단 (arm_s_top)', topic: '/arm_s_top_camera/image_raw', url: '/api/fleet/pipeline/cell-camera/arm_s_top'},
      {id: 'arm_s_wrist', label: 'arm_s 손목 (arm_s_wrist)', topic: '/arm_s_wrist_camera/image_raw', url: '/api/fleet/pipeline/cell-camera/arm_s_wrist'},
      {id: 'top', label: 'S5 상단 (top)', topic: '/top_camera/image_raw', url: '/api/fleet/pipeline/cell-camera/top'},
      {id: 'side', label: '셀 측면 · 도킹 (side)', topic: '/side_camera/image_raw', url: '/api/fleet/pipeline/cell-camera/side'},
      {id: 'arm_a_wrist', label: 'arm_a 손목 (arm_a_wrist)', topic: '/arm_a_wrist_camera/image_raw', url: '/api/fleet/pipeline/cell-camera/arm_a_wrist'},
      {id: 'arm_b_wrist', label: 'arm_b 손목 (arm_b_wrist)', topic: '/arm_b_wrist_camera/image_raw', url: '/api/fleet/pipeline/cell-camera/arm_b_wrist'},
    ];
    const cams = Array.isArray(body?.cameras) && body.cameras.length ? body.cameras : defaultCams;
    const stamp = activeCameraStamp();
    wall.replaceChildren(...cams.map(cam => {
      const card = document.createElement('article');
      card.className = 'cell-observation-card';
      card.tabIndex = 0;
      const h4 = document.createElement('h4');
      const kb = cam.bytes ? ` · ${Math.round(cam.bytes / 1024)}KB` : '';
      h4.textContent = `${cam.label}${kb}`;
      const img = document.createElement('img');
      img.dataset.baseUrl = cam.url;
      img.src = `${cam.url}?t=${stamp}`;
      img.alt = cam.label;
      img.loading = 'lazy';
      const meta = document.createElement('pre');
      const qualParts = [
        cam.topic || '',
        cam.fresh !== false ? 'LIVE (실시간 수신)' : 'STALE (스냅샷)',
        cam.sequence != null ? `seq #${cam.sequence}` : '',
        cam.condition ? `상태 ${cam.condition}` : '',
        cam.mean_intensity != null ? `밝기 ${cam.mean_intensity}` : '',
        cam.spatial_contrast != null ? `대비 ${cam.spatial_contrast}` : '',
      ].filter(Boolean);
      meta.textContent = qualParts.join(' · ');
      card.addEventListener('click', () => {
        card.classList.toggle('focused');
        const camTargetMap = {
          arm_s_top: 'arm_s',
          arm_s_wrist: 'arm_s',
          top: 'cell_ab',
          side: 'rosy_46',
          arm_a_wrist: 'arm_a',
          arm_b_wrist: 'arm_b',
          pinky: 'rosy_46',
        };
        selectInspectorTarget(camTargetMap[cam.id] || 'arm_s', cam.id);
      });
      card.addEventListener('keydown', ev => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          card.classList.toggle('focused');
        } else if (ev.key === 'Escape') {
          card.classList.remove('focused');
        }
      });
      const camQuickMap = {
        arm_s_top: {label: '▶ S3 셔틀 실행', preset: 's3_shuttle'},
        arm_s_wrist: {label: '▶ 자동 복구 셔틀', preset: 's3_auto_recover_or_shuttle'},
        top: {label: '▶ S3→S5 연속 실행', preset: 'full_s3_to_s5_pipeline'},
        side: {label: '▶ S3 도킹+하역', pinkyAction: 'dock_and_unload_s3'},
        arm_a_wrist: {label: '▶ 1층 적재 (arm_a)', preset: 's5_tier1_arm_a'},
        arm_b_wrist: {label: '▶ 2층 적재 (arm_b)', preset: 's5_tier2_arm_b'},
        pinky: {label: '▶ 임시칸1 이동 (STG_C2)', zoneId: 'STG_C2'},
      };
      const qAct = camQuickMap[cam.id];
      if (qAct) {
        const actBtn = document.createElement('ui-button');
        actBtn.setAttribute('kind', 'quiet');
        actBtn.setAttribute('type', 'button');
        actBtn.textContent = qAct.label;
        actBtn.addEventListener('click', ev => {
          ev.stopPropagation();
          if (qAct.preset) void runQuickPreset(qAct.preset);
          else if (qAct.pinkyAction) void runPinkyQuickAction('rosy_46', qAct.pinkyAction);
          else if (qAct.zoneId) void runStationZoneDispatch(qAct.zoneId, 'rosy_46');
        });
        card.append(h4, img, meta, actBtn);
      } else {
        card.append(h4, img, meta);
      }
      return card;
    }));
  }

  async function runHumanSafetyGate(cellId, humanDetected, robotId) {
    const current = ++generation;
    const actionTxt = humanDetected ? '사람 감지 비상정지(HUMAN_HOLD)' : '사람 이탈 · 작업 자동 재개';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `${actionTxt} (${cellId}) 처리 중입니다.`;
    try {
      const res = await request(HUMAN_SAFETY_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, human_detected: humanDetected, robot_id: robotId}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const detail = humanDetected
          ? `일시정지 태스크 ${(res.paused_tasks || []).length}건`
          : `자동 재개 태스크 ${(res.resumed_tasks || []).length}건`;
        $('cell-tasks-status').textContent = `${actionTxt} 완료 (${detail})`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `${actionTxt} 실패: ${error.message}`;
    }
  }

  async function runStationZoneDispatch(zoneId, robotId) {
    const current = ++generation;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 이동/반출 태스크를 즉시 실행하는 중입니다.`;
    try {
      const res = await request(STATION_ZONES_DISPATCH_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({zone_id: zoneId, robot_id: robotId}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const spawned = res.spawned_cell_task ? ` + 셀 태스크(${res.spawned_cell_task.task_id})` : '';
        $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 실행 완료 -> ${res.pinky_task?.target_place || '—'}${spawned}`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `YAML 구역(${zoneId}) 실행 실패: ${error.message}`;
    }
  }

  async function runVisionAutoCheck(cellId = 'cell_s') {
    const current = ++generation;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `비전 카메라(${cellId}) 자동 안전·이탈 점검 중입니다.`;
    try {
      const res = await request(VISION_CHECK_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cell_id: cellId, robot_id: 'rosy_46'}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const v = res.vision || {};
        $('cell-tasks-status').textContent = `비전 자동 점검(${cellId}) 완료: 사람 감지=${v.human_detected ? 'YES(E-Stop)' : 'NO(정상)'} · 이탈=${v.displaced_to || '없음'} · 프레임 ${v.snapshot_bytes ?? 0}B`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `비전 자동 점검 실패: ${error.message}`;
    }
  }

  async function toggleCableGuard() {
    const current = ++generation;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = '선 꼬임 보호 모드를 전환하는 중입니다.';
    try {
      const res = await request(CABLE_GUARD_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({toggle: true, robot_id: 'rosy_46'}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = res.cable_tangled
          ? '선 꼬임 보호 ON (최대 1.5cm · 0.02m/s 미세 이동)'
          : '선 꼬임 보호 OFF (정상 주행 속도 모드)';
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `선 꼬임 보호 전환 실패: ${error.message}`;
    }
  }

  async function runClearArmHold(cellOrArmId) {
    const current = ++generation;
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
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `팔 홀드 해제 완료: ${(res.cleared_arms || []).join(', ')}`;
      }
    } catch (error) {
      if (current !== generation) return;
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
    const current = ++generation;
    const yamlText = $('station-zones-yaml')?.value || '';
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = 'station_zones.yaml 설정을 저장하고 카드를 갱신하는 중입니다.';
    try {
      const res = await request(STATION_ZONES_PATH, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({yaml_text: yamlText}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        $('cell-tasks-status').textContent = `station_zones.yaml 저장·반영 완료 (임시칸 ${(res.staging_bays || []).length}개 · 반출대 ${(res.export_stations || []).length}개)`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `station_zones.yaml 저장 실패: ${error.message}`;
    }
  }

  async function runDecisionGate(subjectId) {
    const current = ++generation;
    if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `Decision Gate(${subjectId}) 상황을 판단하고 자동 실행하는 중입니다.`;
    try {
      const res = await request(DECISION_GATE_PATH, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subject_id: subjectId, auto_execute: true}),
      });
      if (current !== generation) return;
      await refreshCellTasks(current);
      if ($('cell-tasks-status')) {
        const d = res.decision || {};
        $('cell-tasks-status').textContent = `Decision(${subjectId}): ${d.choice || '—'} (${d.reason || ''}) -> 자동 실행 완료`;
      }
    } catch (error) {
      if (current !== generation) return;
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `Decision Gate 실행 실패: ${error.message}`;
    }
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
  $('cell-vision-auto-check')?.addEventListener('click', () => { void runVisionAutoCheck($('cell-task-cell')?.value || 'cell_s'); });
  $('cell-cable-guard-toggle')?.addEventListener('click', () => { void toggleCableGuard(); });
  $('cell-live-stream-toggle')?.addEventListener('click', () => { toggleLiveStream(); });
  $('station-zones-load')?.addEventListener('click', () => { void loadStationZonesYaml(); });
  $('station-zones-save')?.addEventListener('click', () => { void saveStationZonesYaml(); });
  return {refresh, evaluate, queueRun, promotePhysics, refreshCellTasks, runPresetTask, createCustomTask, clear};
}
