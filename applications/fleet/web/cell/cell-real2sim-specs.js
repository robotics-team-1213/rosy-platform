// Real-to-Sim pipeline paths, table row builders and card/inspector specs (split from cell-real2sim.js).

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

// 카메라 뷰는 Vision 소스만 가리킨다(D-136). cell S(arm_s·S3)에는 측면 카메라가 없고,
// Pinky 도킹은 천장 Cam(ceiling_north) ROI 확대로 위에서 본다.
export const DOCK_VIEW_LABEL = '도킹 확대 (천장 Cam)';
export const dockView = robotId => ({id: 'pinky_dock', label: DOCK_VIEW_LABEL, roiTarget: robotId || 'rosy_46'});
export const S3_VIEWS = [
  {id: 'arm_s_top', label: 'S3 상단(arm_s_top)', source: 'arm_s_top'},
  {id: 'arm_s_wrist', label: 'arm_s 손목', source: 'arm_s_wrist'},
];
export const S5_VIEWS = [
  {id: 'top', label: 'S5 상단(top)', source: 'top'},
  {id: 'side', label: '측면(A/B · side)', source: 'side'},
  {id: 'arm_a_wrist', label: 'arm_a 손목', source: 'arm_a_wrist'},
  {id: 'arm_b_wrist', label: 'arm_b 손목', source: 'arm_b_wrist'},
];
export const CAMERA_WALL_VIEWS = [
  ...S3_VIEWS.map(v => ({...v})),
  dockView('rosy_46'),
  ...S5_VIEWS.map(v => ({...v})),
];


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
      cameraViews: S3_VIEWS.map(v => ({...v})),
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
      cameraViews: S5_VIEWS.map(v => ({...v})),
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
      cameraViews: [dockView(pinkyId), {...S3_VIEWS[0]}],
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
  const armLiveStates = body?.arm_live_states || {};
  const armJointSnapshot = (armId, fallbackText) => {
    const live = armLiveStates[armId];
    if (live && Array.isArray(live.joints_deg) && live.joints_deg.length) {
      const stateArr = live.joints_deg.slice(0, 6).map(v => Number(v).toFixed(1)).join(', ');
      const ageTxt = live.age_s != null ? `${Number(live.age_s).toFixed(0)}초 전` : '';
      const modeBadge = live.fresh !== false ? `LIVE${ageTxt ? ` · ${ageTxt}` : ''}` : `스냅샷${ageTxt ? ` · ${ageTxt}` : ''}`;
      const tempTxt = live.temp_c != null ? `${live.temp_c}°C` : '';
      const curTxt = live.current_ma != null ? `${live.current_ma}mA` : '';
      return [
        `[${modeBadge}]`,
        `folded=${Boolean(live.folded)}`,
        `[${stateArr}]`,
        tempTxt,
        curTxt,
        live.substage || '',
      ].filter(Boolean).join(' · ');
    }
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
      cell_id: 'cell_s',
      station_id: 'S3',
      dualPair: ['arm_s_top', 'arm_s_wrist'],
      shortTab: '🦾 arm_s (S3)',
      title: '🦾 OMX-AI #3 · arm_s (cell_s · S3 하역 셔틀)',
      badge: `${s3Card.phase || 'IDLE'} · AMR 잠금 ${s3Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: [
        {id: 'arm_s_wrist', label: 'arm_s 손목(근접)', source: 'arm_s_wrist'},
        {id: 'arm_s_top', label: 'S3 상단(탑뷰)', source: 'arm_s_top'},
        dockView('rosy_46'),
      ],
      telemetryRows: [
        ['셀 위상 · 연계역', `${s3Card.phase || 'IDLE'} · 정류장 S3 · AMR 잠금 ${s3Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['실시간 관절 · 온도', armJointSnapshot('arm_s', s3Card.folded_state)],
        ['최근 태스크', s3Card.last_task || '대기 중'],
        ['팔 홀드 · 안전', holdText('arm_s')],
      ],
      buttons: (s3Card.buttons || []).map(b => b.clearArmHold ? {...b, clearArmHold: 'arm_s'} : b),
    },
    {
      id: 'arm_a',
      cell_id: 'cell_ab',
      station_id: 'S2',
      dualPair: ['top', 'arm_a_wrist'],
      shortTab: '🦾 arm_a (S5)',
      title: '🦾 OMX-AI #1 · arm_a (cell_ab · S5 1·3층 적재)',
      badge: `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: [
        {id: 'arm_a_wrist', label: 'arm_a 손목(근접)', source: 'arm_a_wrist'},
        {id: 'top', label: 'S5 상단(탑뷰)', source: 'top'},
        {id: 'side', label: '측면(A/B · side)', source: 'side'},
        {id: 'arm_b_wrist', label: 'arm_b 손목(교차)', source: 'arm_b_wrist'},
      ],
      telemetryRows: [
        ['셀 위상 · 연계역', `${s5Card.phase || 'IDLE'} · 정류장 S2/S5 · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['실시간 관절 · 온도', armJointSnapshot('arm_a', s5Card.folded_state)],
        ['최근 태스크', s5Card.last_task || '대기 중'],
        ['팔 홀드 · 안전', holdText('arm_a')],
      ],
      buttons: (s5Card.buttons || []).map(b => b.clearArmHold ? {...b, label: '팔 홀드 점검·해제 (arm_a)', clearArmHold: 'arm_a'} : b),
    },
    {
      id: 'arm_b',
      cell_id: 'cell_ab',
      station_id: 'S5',
      dualPair: ['top', 'arm_b_wrist'],
      shortTab: '🦾 arm_b (S5)',
      title: '🦾 OMX-AI #2 · arm_b (cell_ab · S5 2층 적재 · 반출)',
      badge: `${s5Card.phase || 'IDLE'} · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`,
      cameraViews: [
        {id: 'arm_b_wrist', label: 'arm_b 손목(근접)', source: 'arm_b_wrist'},
        {id: 'top', label: 'S5 상단(탑뷰)', source: 'top'},
        {id: 'side', label: '측면(A/B · side)', source: 'side'},
        {id: 'arm_a_wrist', label: 'arm_a 손목(교차)', source: 'arm_a_wrist'},
      ],
      telemetryRows: [
        ['셀 위상 · 연계역', `${s5Card.phase || 'IDLE'} · 정류장 S5 · AMR 잠금 ${s5Card.amr_motion_inhibited ? 'ON' : 'OFF'}`],
        ['실시간 관절 · 온도', armJointSnapshot('arm_b', s5Card.folded_state)],
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
      cameraViews: [dockView(rid), ...(pinkyCard.cameraViews || []).filter(v => !v.roiTarget)],
      telemetryRows: [
        ['도킹 · 위치', pinkyCard.phase || 'READY'],
        ['주행 · 안전 모드', pinkyCard.folded_state || '케이블 보호 미세이동 모드'],
        ['최근 배차', pinkyCard.last_task || 'S3 도킹 및 미세이동 준비 완료'],
      ],
      buttons: pinkyButtonsFor(rid),
    })),
  ];
}
