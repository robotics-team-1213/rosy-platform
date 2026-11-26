// Right inspector, visual cards and camera matrix renderers for the Real-to-Sim pipeline view (split from cell-real2sim.js).
import { setOffBy } from "/common/cause-line.js";
import { randomUUID } from "/console/assets/uuid.js";
import { buildCameraZoomHeading } from "./cell-camera-zoom.js";
import { buildInspectorCamFrame, renderOmxInspector } from "/console/assets/omx-inspector.js";
import { CELL_TASKS_PATH, CAMERA_WALL_VIEWS, inspectorSpecs, visualCardSpecs } from "./cell-real2sim-specs.js";

export function createCellViews(ctx) {
  const {request, $, state} = ctx;
  const matrixBtns = [];
  const frames = () => ctx.cellFrames;
  const refreshCellTasks = (...args) => ctx.refreshCellTasks(...args);
  const selectInspectorTarget = (...args) => ctx.selectInspectorTarget(...args);
  const bindActionButton = (...args) => ctx.bindActionButton(...args);
  const runQuickPreset = (...args) => ctx.runQuickPreset(...args);
  const runPinkyQuickAction = (...args) => ctx.runPinkyQuickAction(...args);
  const runStationZoneDispatch = (...args) => ctx.runStationZoneDispatch(...args);

  function renderRightInspector(body) {
    const panel = $('omx-right-inspector');
    if (!panel) return;
    const specs = inspectorSpecs(body);
    if (!specs.length) return;
    state.draftChoicesByTarget ??= new Map();
    renderOmxInspector(panel, {
      targets: specs,
      activeId: state.selectedInspectorTarget,
      dualCamMode: Boolean(state.dualInspectorCamMode),
      selectedCamByTarget: state.selectedInspectorCamByTarget,
      draftChoices: state.draftChoicesByTarget,
      frames: frames(),
      framesActive: true,
      runButtonLabel: undefined,
      quickDispatchReason: typeof ctx.namedReason === 'function' ? ctx.namedReason() : '',
      actionsClass: 'omx-inspector-actions',
      onSelectTarget: (id) => selectInspectorTarget(id),
      onToggleDual: () => {
        state.dualInspectorCamMode = !state.dualInspectorCamMode;
        renderRightInspector(body);
      },
      onSelectCam: (targetId, camId) => {
        state.selectedInspectorCamByTarget[targetId] = camId;
        renderRightInspector(body);
      },
      onQuickDispatch: async ({ targetCell, targetArm, tier, displacedTo, robotId, button }) => {
        const current = await ctx.confirmAndBump?.(`${targetArm} 맞춤 태스크(${targetCell} · ${tier}층${displacedTo ? ' · ' + displacedTo : ''})를 큐에 등록할까요?`, button);
        if (!current) return;
        if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `우측 인스펙터 맞춤 태스크(${targetCell}/${targetArm})를 큐에 등록하는 중입니다.`;
        try {
          const res = await request(CELL_TASKS_PATH, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Idempotency-Key': randomUUID()},
            body: JSON.stringify({
              cell_id: targetCell,
              arm_id: targetArm,
              tier,
              displaced_to: displacedTo,
              robot_id: robotId || undefined,
              propose: false,
            }),
          });
          if (current !== ctx.gen()) return;
          await refreshCellTasks(current);
          if ($('cell-tasks-status')) {
            $('cell-tasks-status').textContent = `인스펙터 맞춤 태스크 등록 완료: ${res.task?.task_id || '—'} (${targetCell}/${targetArm})`;
          }
        } catch (error) {
          if (current !== ctx.gen()) return;
          if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `인스펙터 맞춤 태스크 등록 실패: ${error.message}`;
        }
      },
      onRenderAction: (btn, choice, active) => bindActionButton(btn, choice, active.robot_id || undefined),
    });
  }

  function renderVisualCards(body) {
    const wrap = $('cell-visual-cards');
    if (!wrap) return;
    const cards = visualCardSpecs(body);
    const pendingBinds = [];
    wrap.replaceChildren(...cards.map(card => {
      const article = document.createElement('article');
      const isSelected = state.selectedInspectorTarget === card.id
        || (card.id === 'cell_s' && state.selectedInspectorTarget === 'arm_s')
        || (card.id === 'cell_ab' && (state.selectedInspectorTarget === 'arm_a' || state.selectedInspectorTarget === 'arm_b'))
        || (card.id === 'pinky' && state.selectedInspectorTarget.startsWith('rosy_'));
      article.className = `cell-visual-card${isSelected ? ' selected-inspector' : ''}`;
      article.dataset.cardId = card.id;
      article.addEventListener('click', () => {
        const defaultTarget = card.id === 'cell_s' ? 'arm_s' : (card.id === 'cell_ab' ? 'arm_a' : (card.robot_id || undefined));
        if (defaultTarget) selectInspectorTarget(defaultTarget, state.selectedCameraByCard[card.id] || null);
      });

      const activeViewId = state.selectedCameraByCard[card.id] || card.cameraViews?.[0]?.id || card.id;
      const activeView = (card.cameraViews || []).find(v => v.id === activeViewId) || (card.cameraViews || [])[0]
        || {id: card.id, label: card.title, roiTarget: card.robot_id || card.id};

      const thumb = document.createElement('img');
      thumb.className = 'cell-visual-thumb';
      thumb.alt = card.title;
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
      const camQualityBadge = document.createElement('span');
      camQualityBadge.className = 'cell-visual-badge';
      camQualityBadge.textContent = '영상 수신 대기';
      pendingBinds.push([thumb, activeView, camQualityBadge, '영상']);
      for (const v of (card.cameraViews || [])) {
        const pill = document.createElement('ui-button');
        pill.setAttribute('kind', 'quiet');
        if (v.id === activeViewId) pill.setAttribute('kind', 'primary');
        pill.setAttribute('type', 'button');
        pill.dataset.cameraView = v.id;
        pill.textContent = v.label;
        pill.addEventListener('click', ev => {
          ev.stopPropagation();
          state.selectedCameraByCard[card.id] = v.id;
          frames()?.bind(thumb, v, camQualityBadge, '영상');
          for (const child of camSwitcher.children || []) {
            if (child.tagName === 'UI-BUTTON') {
              child.setAttribute('kind', 'quiet');
              if (child === pill) child.setAttribute('kind', 'primary');
            }
          }
          const targetForView = v.id.startsWith('arm_a') ? 'arm_a'
            : v.id.startsWith('arm_b') ? 'arm_b'
            : (v.id.startsWith('arm_s') || card.id === 'cell_s') ? 'arm_s'
            : card.id === 'cell_ab' ? 'cell_ab'
            : (card.robot_id || undefined);
          if (targetForView) selectInspectorTarget(targetForView, v.id);
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
        ? [['arm_s', 'arm_s 상세']]
        : card.id === 'cell_ab'
        ? [['arm_a', 'arm_a 상세'], ['arm_b', 'arm_b 상세']]
        : [['rosy_46', 'rosy_46 상세'], ['rosy_45', 'rosy_45'], ['rosy_42', 'rosy_42']];
      for (const [tId, tLabel] of inspectTargets) {
        const iBtn = document.createElement('ui-button');
        iBtn.setAttribute('kind', 'quiet');
        if (state.selectedInspectorTarget === tId) iBtn.setAttribute('kind', 'primary');
        iBtn.setAttribute('type', 'button');
        iBtn.dataset.inspectTarget = tId;
        iBtn.textContent = tLabel;
        iBtn.addEventListener('click', ev => {
          ev.stopPropagation();
          selectInspectorTarget(tId);
        });
        actions.append(iBtn);
        if (body.calibration_origin && ['arm_s', 'arm_a', 'arm_b'].includes(tId)) {
          const link = document.createElement('a');
          link.href = `${body.calibration_origin}/?arm=${tId}`;
          link.textContent = `${tId} 보정`;
          link.addEventListener('click', event => event.stopPropagation());
          actions.append(link);
        }
      }
      for (const b of card.buttons) {
        const btn = document.createElement('ui-button');
        btn.setAttribute('kind', 'quiet');
        btn.setAttribute('type', 'button');
        btn.textContent = b.label;
        bindActionButton(btn, b, card.robot_id || undefined);
        actions.append(btn);
      }

      article.append(buildInspectorCamFrame(thumb), camSwitcher, head);
      if (card.fieldStatus) {
        const readiness = document.createElement('p');
        readiness.className = 'cell-visual-meta';
        readiness.textContent = card.fieldStatus.arms;
        const queue = document.createElement('p');
        queue.className = 'cell-visual-meta';
        queue.textContent = card.fieldStatus.queue;
        article.append(readiness, queue);
        if (card.fieldStatus.refusal) {
          const refusal = document.createElement('p');
          refusal.className = 'cell-pipeline-banner';
          refusal.dataset.kind = 'warning';
          refusal.textContent = [card.fieldStatus.refusal, card.fieldStatus.next].filter(Boolean).join(' · ');
          article.append(refusal);
        }
      }
      article.append(meta, actions);
      return article;
    }));
    for (const args of pendingBinds) frames()?.bind(...args);
  }

  function renderCameraMatrix() {
    const wall = $('cell-camera-matrix');
    if (!wall) return;
    const reason = typeof ctx.namedReason === 'function' ? ctx.namedReason() : '';
    if (wall.childElementCount) {
      for (const btn of matrixBtns) setOffBy(btn, reason);
      return;
    }
    const pendingBinds = [];
    wall.replaceChildren(...CAMERA_WALL_VIEWS.map(cam => {
      const card = document.createElement('article');
      card.className = 'cell-observation-card';
      const img = document.createElement('img');
      img.alt = cam.label;
      const meta = document.createElement('pre');
      meta.textContent = cam.roiTarget ? '천장 Cam ROI 확대' : `Vision 소스 ${cam.source}`;
      pendingBinds.push([img, cam, meta, cam.roiTarget ? '천장 Cam ROI' : cam.source]);
      const camTargetMap = {
        arm_s_top: 'arm_s',
        arm_s_wrist: 'arm_s',
        top: 'cell_ab',
        side: 'cell_ab',
        arm_a_wrist: 'arm_a',
        arm_b_wrist: 'arm_b',
        pinky_dock: cam.roiTarget || 'rosy_46',
      };
      card.append(buildCameraZoomHeading(card, cam.label, () => {
        selectInspectorTarget(camTargetMap[cam.id] || 'arm_s', cam.id);
      }), buildInspectorCamFrame(img), meta);
      const camQuickMap = {
        arm_s_top: {label: 'S3 셔틀 실행', preset: 's3_shuttle'},
        arm_s_wrist: {label: '자동 복구 셔틀', preset: 's3_auto_recover_or_shuttle'},
        top: {label: 'S3→S5 연속 실행', preset: 'full_s3_to_s5_pipeline'},
        side: {label: '3층 적재 (arm_a)', preset: 's5_tier3_arm_a'},
        arm_a_wrist: {label: '1층 적재 (arm_a)', preset: 's5_tier1_arm_a'},
        arm_b_wrist: {label: '2층 적재 (arm_b)', preset: 's5_tier2_arm_b'},
        pinky_dock: {label: 'S3 도킹+하역', pinkyAction: 'dock_and_unload_s3', robotId: cam.roiTarget},
      };
      const qAct = camQuickMap[cam.id];
      if (qAct) {
        const actBtn = document.createElement('ui-button');
        actBtn.setAttribute('kind', 'quiet');
        actBtn.setAttribute('type', 'button');
        actBtn.textContent = qAct.label;
        setOffBy(actBtn, reason);
        matrixBtns.push(actBtn);
        actBtn.addEventListener('click', ev => {
          ev.stopPropagation();
          if (qAct.preset) void runQuickPreset(qAct.preset, null, ev.currentTarget);
          else if (qAct.pinkyAction) void runPinkyQuickAction(qAct.robotId || undefined, qAct.pinkyAction, ev.currentTarget);
          else if (qAct.zoneId) void runStationZoneDispatch(qAct.zoneId, qAct.robotId || undefined, ev.currentTarget);
        });
        card.append(actBtn);
      }
      return card;
    }));
    for (const args of pendingBinds) frames()?.bind(...args);
  }

  return {renderRightInspector, renderVisualCards, renderCameraMatrix};
}
