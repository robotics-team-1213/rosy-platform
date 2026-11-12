// Real-to-Sim <-> Sim-to-Real closed-loop pipeline view for the Cell workspace (D-947, D-1012).

export const REAL2SIM_PATH = '/api/fleet/cell-app/real2sim-pipeline';
export const EVALUATE_PATH = '/api/fleet/cell-app/real2sim-pipeline/evaluate';
export const RUNS_PATH = '/api/fleet/cell-app/real2sim-pipeline/runs';
export const PROMOTE_PATH = '/api/fleet/cell-app/real2sim-pipeline/promote-physics';

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
    ]) {
      if ($(tableId)) $(tableId).hidden = true;
      if ($(rowsId)) $(rowsId).replaceChildren();
    }
    if ($('real2sim-handoff')) $('real2sim-handoff').textContent = '';
    if (status) status.textContent = '접속하면 실물↔시뮬 파이프라인 상태를 확인할 수 있습니다.';
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
    } catch (error) {
      if (current !== generation) return;
      status.textContent = `실물↔시뮬 파이프라인을 읽지 못했습니다: ${error.message}`;
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
  return {refresh, evaluate, queueRun, promotePhysics, clear};
}
