// Dynamic Fleet E2E pipeline bar & live ledger mounted above #cell-visual-cards on /console/cell.
import { setOffBy } from "/common/cause-line.js";

export const PIPELINE_STATUS_PATH = '/api/fleet/pipeline/status';
export const UNLOAD_RELEASE_PATH = '/api/fleet/pipeline/unload-release';
export const RECOVERY_TOOLS_INVOKE_PATH = '/api/fleet/pipeline/recovery-tools/invoke';
export const CELL_PLANS_PATH = '/api/fleet/pipeline/cell-plans';
export const pinkyCancelPath = id => `/api/fleet/pipeline/pinky-tasks/${encodeURIComponent(id)}/cancel`;
export const reparkClosePath = id => `/api/fleet/pipeline/repark/${encodeURIComponent(id)}`;
export const cellPlanAdmitPath = id => `/api/fleet/pipeline/cell-plans/${encodeURIComponent(id)}/admit`;
export const cellPlanCancelPath = id => `/api/fleet/pipeline/cell-plans/${encodeURIComponent(id)}/cancel`;
export const cellReadinessPath = id => `/api/fleet/pipeline/cells/${encodeURIComponent(id)}/readiness`;

const PINKY_TERMINAL = new Set(['ARRIVED', 'FAILED', 'CANCELLED', 'REFUSED']);
const PLAN_ADMITTABLE = new Set(['PROPOSED', 'PARTIALLY_ADMITTED']);
const PLAN_CANCELLABLE = new Set(['PROPOSED', 'QUEUED', 'PARTIALLY_ADMITTED']);
const FALLBACK_PINKYS = ['rosy_46', 'rosy_45', 'rosy_42'];

export function discoverPinkyIds(tasksBody, statusBody) {
  const seen = new Set();
  const add = id => {
    if (typeof id === 'string' && id.trim()) seen.add(id.trim());
  };
  for (const r of statusBody?.robot_layer?.robots || statusBody?.robots || statusBody?.pinky_robots || []) {
    add(typeof r === 'string' ? r : r?.robot_id);
  }
  for (const id of tasksBody?.pinky_robots || []) add(id);
  for (const cell of Object.values(tasksBody?.cells || {})) add(cell?.gate?.docked_robot?.robot_id);
  for (const t of tasksBody?.pinky_tasks || []) add(t?.robot_id);
  return seen.size ? [...seen] : [...FALLBACK_PINKYS];
}

export function formatPinkyTaskRow(task) {
  return [
    task.task_id || '—',
    task.robot_id || '—',
    task.action || '—',
    task.place_id || task.target_place || '—',
    task.status || 'QUEUED',
    task.reason || '—',
    task.trip_id || '—',
  ];
}

export function createPipelinePanel(ctx) {
  const {$, state, namedReason, runPinkyQuickAction, runQuickPreset, cancelPinkyTask, closeRepark, cancelOrRetryTask, invokeRecoveryTool, admitCellPlan, cancelCellPlan, onRobotChange} = ctx;

  function ensurePanel() {
    let panel = $('cell-pipeline-panel');
    if (panel) return panel;
    const cards = $('cell-visual-cards');
    const parent = cards?.parentNode;
    if (!parent || typeof document.createElement !== 'function') return null;
    panel = document.createElement('section');
    panel.id = 'cell-pipeline-panel';
    panel.className = 'cell-pipeline-panel';
    parent.insertBefore(panel, cards);
    return panel;
  }

  function makeBtn(label, kind, disabledReason, onClick) {
    const btn = document.createElement('ui-button');
    if (kind === 'primary') btn.setAttribute('kind', 'primary');
    else btn.setAttribute('kind', 'quiet');
    btn.setAttribute('type', 'button');
    btn.textContent = label;
    if (disabledReason) setOffBy(btn, disabledReason);
    btn.addEventListener('click', ev => {
      ev.stopPropagation();
      onClick();
    });
    return btn;
  }

  function makeStepCard(titleText, bodyNodes) {
    const step = document.createElement('article');
    step.className = 'cell-pipeline-step';
    const h = document.createElement('strong');
    h.textContent = titleText;
    const actions = document.createElement('div');
    actions.className = 'cell-pipeline-actions';
    actions.append(...bodyNodes);
    step.append(h, actions);
    return step;
  }

  function render(tasksBody, statusBody, unloadReleaseBody, plansBody) {
    const panel = ensurePanel();
    if (!panel) return;
    const opReason = typeof namedReason === 'function' ? namedReason() : '';
    const ids = discoverPinkyIds(tasksBody, statusBody);
    const activeRobot = (state.selectedRobotId && ids.includes(state.selectedRobotId)) ? state.selectedRobotId : ids[0];
    state.selectedRobotId = activeRobot;

    const nodes = [];
    if (tasksBody?.pinky_dispatch_enabled === false) {
      const banner = document.createElement('p');
      banner.className = 'cell-pipeline-banner';
      banner.dataset.kind = 'warning';
      banner.textContent = 'ROSY_FLEET_PINKY_TASK_DISPATCH=1 미활성: Pinky 작업은 QUEUED 상태로만 기록되며 자동 주행하지 않습니다.';
      nodes.push(banner);
    }

    const header = document.createElement('div');
    header.className = 'cell-pipeline-header';
    const heading = document.createElement('h4');
    heading.textContent = '실시간 E2E 파이프라인 제어 (Pinky · OMX)';
    const pickerWrap = document.createElement('label');
    pickerWrap.className = 'cell-pipeline-picker';
    const pickerLbl = document.createElement('span');
    pickerLbl.textContent = '대상 Pinky';
    const sel = document.createElement('select');
    sel.id = 'cell-pipeline-robot';
    sel.className = 'ui-field';
    for (const id of ids) {
      const opt = document.createElement('option');
      opt.value = id;
      opt.textContent = id;
      if (id === activeRobot) opt.selected = true;
      sel.append(opt);
    }
    sel.addEventListener('change', () => {
      state.selectedRobotId = sel.value;
      onRobotChange?.(sel.value);
    });
    pickerWrap.append(pickerLbl, sel);
    header.append(heading, pickerWrap);
    nodes.push(header);

    const step1 = makeStepCard('1단계 · 도킹·이동', [
      ['S3 도킹+하역', 'dock_and_unload_s3', 'primary'],
      ['S3 도킹', 'dock_s3', 'quiet'],
      ['S5 도킹', 'dock_s5', 'quiet'],
      ['충전소 C1', 'charge_c1', 'quiet'],
      ['출구 S1 이동', 'depart_s1', 'quiet'],
    ].map(([lbl, act, kind]) => makeBtn(lbl, kind, opReason, () => void runPinkyQuickAction(activeRobot, act))));

    const step2 = makeStepCard('2단계 · 상차·하역', [
      ['S3 하역 셔틀', 's3_shuttle', 'primary'],
      ['S5 1층 적재', 's5_tier1_arm_a', 'quiet'],
      ['S5 2층 적재', 's5_tier2_arm_b', 'quiet'],
      ['S3→S5 연속', 'full_s3_to_s5_pipeline', 'quiet'],
    ].map(([lbl, preset, kind]) => makeBtn(lbl, kind, '', () => void runQuickPreset(preset, activeRobot))));

    const openReparks = Object.values(tasksBody?.repark_requests || {}).filter(r => r && r.state === 'REQUESTED');
    const step3Nodes = [
      makeBtn('Belt-Far 복구', 'quiet', '', () => void runQuickPreset('s3_recover_belt_far', activeRobot)),
      makeBtn('Floor-Front 복구', 'quiet', '', () => void runQuickPreset('s3_recover_floor_front', activeRobot)),
    ];
    for (const req of openReparks) {
      const box = document.createElement('div');
      box.className = 'cell-pipeline-repark';
      const moveArr = req.need_site_dxdy_m || req.need_arm_dxdy_m || [];
      const info = document.createElement('span');
      info.textContent = `재주차 요청(${req.robot_id || activeRobot} · ${req.request_id}) dx/dy=[${moveArr.join(', ')}]`;
      box.append(
        info,
        makeBtn('재주차 완료(DONE)', 'primary', '', () => void closeRepark?.(req.request_id, 'DONE')),
        makeBtn('재주차 실패(FAILED)', 'quiet', '', () => void closeRepark?.(req.request_id, 'FAILED')),
      );
      step3Nodes.push(box);
    }
    const handoff = tasksBody?.recovery_handoff || {};
    for (const f of handoff.active_failures || []) {
      const hbox = document.createElement('div');
      hbox.className = 'cell-pipeline-repark';
      const vetoesTxt = Array.isArray(f.vetoes) && f.vetoes.length ? ` · veto: ${f.vetoes.join(', ')}` : '';
      const camTxt = f.arm_id ? (f.cameras_fresh ? ' · 3cam 신선' : ' · 3cam 미확인') : '';
      const stageTxt = f.homing_stage && f.homing_stage !== 'IDLE' ? ` · homing=${f.homing_stage}` : '';
      const hinfo = document.createElement('span');
      hinfo.textContent = `미해결(${f.trigger_code} · ${f.arm_id || f.robot_id || 'cell'} · ${f.state}${stageTxt}${camTxt}${vetoesTxt})`;
      const callTool = (toolName, args, label) => void invokeRecoveryTool?.({
        tool_name: toolName,
        arguments: args,
        caller_kind: 'operator',
        request_id: ['ui', toolName, Date.now()].join('-'),
        expected_context_sha256: f.context_sha256,
        root_task_id: f.root_task_id,
        rationale: `${label} (${f.trigger_code})`,
      });
      const elig = f.eligible_tools || {};
      const strats = f.homing_strategies || {};
      const camSeqs = f.camera_sequences || {};
      const liftReason = strats.release_and_lift
        ? (strats.release_and_lift.allowed ? '' : (strats.release_and_lift.reason || '그리퍼·상승 불가'))
        : (elig.safe_fold_home?.allowed ? '' : (elig.safe_fold_home?.reason || '그리퍼·상승 불가'));
      const parkReason = strats.guarded_slow_park
        ? (strats.guarded_slow_park.allowed ? '' : (strats.guarded_slow_park.reason || '3카메라 확인 후 가드 복귀 가능'))
        : (elig.safe_fold_home?.allowed ? '' : (elig.safe_fold_home?.reason || '가드 복귀 불가'));
      const autoReason = strats.auto_fold
        ? (strats.auto_fold.allowed ? '' : (strats.auto_fold.reason || '자동 폴드 불가'))
        : (elig.safe_fold_home?.allowed ? '' : (elig.safe_fold_home?.reason || '자동 폴드 불가'));
      const visReason = elig.record_visual_checkpoint?.allowed ? '' : (elig.record_visual_checkpoint?.reason || '3카메라 판정 불가');
      hbox.append(
        hinfo,
        makeBtn('그리퍼 열기+상승', 'primary', liftReason,
          () => callTool('safe_fold_home', {arm_id: f.arm_id || null, strategy: 'release_and_lift'}, '그리퍼 열기+상승')),
        makeBtn('3카메라 이탈 확인', 'quiet', visReason,
          () => callTool('record_visual_checkpoint', {
            arm_id: f.arm_id || null, stage: 'after_lift', verdict: 'CLEAR',
            cargo_detached: true, gripper_open: true, overhead_clear: true,
            cameras_checked: camSeqs, observation_summary: 'Top/Side/Wrist 3카메라 컨테이너 이탈 및 상공 비어 있음 확인',
          }, '3카메라 이탈 확인')),
        makeBtn('가드 홈 복귀(park)', 'primary', parkReason,
          () => callTool('safe_fold_home', {arm_id: f.arm_id || null, strategy: 'guarded_slow_park'}, '가드 홈 복귀')),
        makeBtn('홈 접힘 확인', 'quiet', visReason,
          () => callTool('record_visual_checkpoint', {
            arm_id: f.arm_id || null, stage: 'after_park', verdict: 'FOLDED_HOME',
            cargo_detached: true, gripper_open: true, overhead_clear: true,
            cameras_checked: camSeqs, observation_summary: '3카메라 홈 접힘 완료 육안 확인',
          }, '홈 접힘 확인')),
        makeBtn('자동 폴드', 'quiet', autoReason,
          () => callTool('safe_fold_home', {arm_id: f.arm_id || null, strategy: 'auto_fold'}, '자동 폴드')),
        makeBtn('ACT 폴백(입회 필요)', 'quiet', elig.enqueue_vla_act_fallback?.allowed ? '' : (elig.enqueue_vla_act_fallback?.reason || 'ACT 폴백 불가'),
          () => callTool('enqueue_vla_act_fallback', {mode: 'act', max_chunks: 2}, 'ACT 폴백')),
        makeBtn('VLA Shadow 제안', 'quiet', elig.enqueue_vla_act_fallback?.allowed ? '' : (elig.enqueue_vla_act_fallback?.reason || 'VLA 제안 불가'),
          () => callTool('enqueue_vla_act_fallback', {mode: 'vla_shadow', max_chunks: 2}, 'VLA Shadow 제안')),
        makeBtn('사람 검토 요청', 'quiet', '', () => callTool('escalate_human', {summary: f.trigger_code}, '사람 검토 요청')),
      );
      step3Nodes.push(hbox);
    }
    for (const rec of (handoff.recent_invocations || []).slice(-3).reverse()) {
      const rinfo = document.createElement('span');
      rinfo.className = 'cell-pipeline-repark';
      rinfo.textContent = `AI·복구 이력: ${rec.tool_name} (${rec.caller_kind}) -> ${rec.status}${rec.reason ? ` · ${rec.reason}` : ''}`;
      step3Nodes.push(rinfo);
    }
    const step3 = makeStepCard('3단계 · 복구·재주차', step3Nodes);

    const rel = unloadReleaseBody || {};
    const relMeta = document.createElement('span');
    relMeta.className = 'cell-pipeline-release-meta';
    const countTxt = rel.batch_id ? `배치 ${rel.batch_id} (${rel.completed ?? 0}/${rel.expected ?? '자동'})` : '하역 배치 없음';
    const depTxt = rel.departure?.state ? ` · 출발 ${rel.departure.state}` : '';
    const whyTxt = Array.isArray(rel.reasons) && rel.reasons.length ? ` · 보류: ${rel.reasons.join(', ')}` : rel.ready ? ' · 출발 가능' : '';
    relMeta.textContent = `${countTxt}${depTxt}${whyTxt}`;
    const departReason = opReason || (rel.ready ? '' : (Array.isArray(rel.reasons) && rel.reasons.length ? `출발 불가: ${rel.reasons.join(', ')}` : 'S3 하역 완료 확인 대기'));
    const step4 = makeStepCard('4단계 · S3 출발 판정', [
      relMeta,
      makeBtn('S3 출발 (depart_s3)', 'primary', departReason, () => void runPinkyQuickAction(activeRobot, 'depart_s3')),
    ]);

    const steps = document.createElement('div');
    steps.className = 'cell-pipeline-steps';
    steps.append(step1, step2, step3, step4);
    nodes.push(steps);

    const recentPinkys = [...(tasksBody?.pinky_tasks || [])].reverse().slice(0, 12);
    if (recentPinkys.length) {
      const wrap = document.createElement('div');
      wrap.className = 'cell-pipeline-ledger';
      const tbl = document.createElement('table');
      tbl.className = 'cell-pipeline-table';
      const thead = document.createElement('thead');
      const hr = document.createElement('tr');
      for (const col of ['Pinky 작업', '로봇', '동작', '목적지', '상태', '사유', '트립 ID', '제어']) {
        const th = document.createElement('th');
        th.textContent = col;
        hr.append(th);
      }
      thead.append(hr);
      const tbody = document.createElement('tbody');
      const taskById = new Map((tasksBody?.tasks || []).map(t => [t.task_id, t]));
      for (const pt of recentPinkys) {
        const tr = document.createElement('tr');
        for (const val of formatPinkyTaskRow(pt)) {
          const td = document.createElement('td');
          td.textContent = val;
          tr.append(td);
        }
        const ctrlTd = document.createElement('td');
        const ctrlWrap = document.createElement('div');
        ctrlWrap.className = 'cell-pipeline-actions';
        if (!PINKY_TERMINAL.has(pt.status || 'QUEUED')) {
          ctrlWrap.append(makeBtn('취소', 'quiet', opReason, () => void cancelPinkyTask?.(pt.task_id)));
        }
        const spawned = pt.spawned_cell_task_id ? taskById.get(pt.spawned_cell_task_id) : null;
        if (spawned && spawned.status === 'QUEUED') {
          ctrlWrap.append(makeBtn(`셀 취소(${spawned.task_id})`, 'quiet', '', () => void cancelOrRetryTask?.(spawned.task_id, 'cancel')));
        }
        ctrlTd.append(ctrlWrap);
        tr.append(ctrlTd);
        tbody.append(tr);
      }
      tbl.append(thead, tbody);
      wrap.append(tbl);
      nodes.push(wrap);
    }

    const recentPlans = [...(plansBody?.plans || [])].reverse().slice(0, 8);
    if (recentPlans.length) {
      const planWrap = document.createElement('div');
      planWrap.className = 'cell-pipeline-ledger';
      const tbl = document.createElement('table');
      tbl.className = 'cell-pipeline-table';
      const thead = document.createElement('thead');
      const hr = document.createElement('tr');
      for (const col of ['계획 ID', '모드', '출처', '상태', '진행', '사유', '승인·취소']) {
        const th = document.createElement('th');
        th.textContent = col;
        hr.append(th);
      }
      thead.append(hr);
      const tbody = document.createElement('tbody');
      for (const plan of recentPlans) {
        const tr = document.createElement('tr');
        for (const val of [
          plan.plan_id || '—',
          plan.mode || '—',
          plan.order_source || '—',
          plan.status || 'PROPOSED',
          `${plan.completed_steps ?? 0}/${plan.total_steps ?? 0}`,
          plan.hold_reason || '—',
        ]) {
          const td = document.createElement('td');
          td.textContent = val;
          tr.append(td);
        }
        const ctrlTd = document.createElement('td');
        const ctrlWrap = document.createElement('div');
        ctrlWrap.className = 'cell-pipeline-actions';
        const admitReason = opReason || (PLAN_ADMITTABLE.has(plan.status) ? '' : '승인 가능 상태가 아닙니다');
        const cancelReason = opReason || (PLAN_CANCELLABLE.has(plan.status) ? '' : '이미 종료된 계획입니다');
        ctrlWrap.append(
          makeBtn('일괄 승인', 'primary', admitReason, () => void admitCellPlan?.(plan)),
          makeBtn('계획 취소', 'quiet', cancelReason, () => void cancelCellPlan?.(plan)),
        );
        ctrlTd.append(ctrlWrap);
        tr.append(ctrlTd);
        tbody.append(tr);
      }
      tbl.append(thead, tbody);
      planWrap.append(tbl);
      nodes.push(planWrap);
    }
    panel.replaceChildren(...nodes);
  }

  return {render};
}
