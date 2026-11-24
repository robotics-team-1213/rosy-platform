// Dynamic Fleet E2E pipeline bar & live ledger mounted above #cell-visual-cards on /console/cell.
import { setOffBy } from "/common/cause-line.js";

export const PIPELINE_STATUS_PATH = '/api/fleet/pipeline/status';
export const UNLOAD_RELEASE_PATH = '/api/fleet/pipeline/unload-release';
export const pinkyCancelPath = id => `/api/fleet/pipeline/pinky-tasks/${encodeURIComponent(id)}/cancel`;
export const reparkClosePath = id => `/api/fleet/pipeline/repark/${encodeURIComponent(id)}`;

const PINKY_TERMINAL = new Set(['ARRIVED', 'FAILED', 'CANCELLED', 'REFUSED']);
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
  const {$, state, namedReason, runPinkyQuickAction, runQuickPreset, cancelPinkyTask, closeRepark, cancelOrRetryTask, onRobotChange} = ctx;

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

  function render(tasksBody, statusBody, unloadReleaseBody) {
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
    panel.replaceChildren(...nodes);
  }

  return {render};
}
