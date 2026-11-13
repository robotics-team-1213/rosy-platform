// Right inspector, visual cards and camera matrix renderers for the Real-to-Sim pipeline view (split from cell-real2sim.js).
import {CELL_TASKS_PATH, CAMERA_WALL_VIEWS, inspectorSpecs, visualCardSpecs} from './cell-real2sim-specs.js';

export function createCellViews(ctx) {
  const {request, $, state} = ctx;
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
    const activeSpec = specs.find(s => s.id === state.selectedInspectorTarget) || specs[0];
    if (!activeSpec) return;

    const tabs = document.createElement('div');
    tabs.className = 'omx-inspector-tabs';
    for (const s of specs) {
      const tab = document.createElement('ui-button');
      tab.setAttribute('kind', 'quiet');
      if (s.id === activeSpec.id) tab.setAttribute('kind', 'primary');
      tab.setAttribute('type', 'button');
      tab.dataset.inspectTarget = s.id;
      tab.textContent = s.shortTab;
      tab.addEventListener('click', () => selectInspectorTarget(s.id));
      tabs.append(tab);
    }
    const dualBtn = document.createElement('ui-button');
    dualBtn.setAttribute('kind', 'quiet');
    if (state.dualInspectorCamMode) dualBtn.setAttribute('kind', 'primary');
    dualBtn.setAttribute('type', 'button');
    dualBtn.dataset.dualCamToggle = 'true';
    dualBtn.textContent = state.dualInspectorCamMode ? '📺 2채널(상단+손목) ON' : '📺 2채널 동시 보기';
    dualBtn.addEventListener('click', () => {
      state.dualInspectorCamMode = !state.dualInspectorCamMode;
      renderRightInspector(body);
    });
    tabs.append(dualBtn);

    const head = document.createElement('div');
    head.className = 'omx-inspector-head';
    const title = document.createElement('strong');
    title.textContent = activeSpec.title;
    const badge = document.createElement('span');
    badge.className = 'cell-visual-badge';
    badge.textContent = activeSpec.badge;
    head.append(title, badge);

    const camViews = activeSpec.cameraViews || [];
    const activeCamId = state.selectedInspectorCamByTarget[activeSpec.id] || camViews[0]?.id || 'arm_s_top';
    const activeCam = camViews.find(v => v.id === activeCamId) || camViews[0] || {id: activeCamId, label: activeCamId, source: activeCamId};

    const stage = document.createElement('div');
    stage.className = 'omx-inspector-stage';
    if (state.dualInspectorCamMode && camViews.length >= 2) {
      const dualGrid = document.createElement('div');
      dualGrid.className = 'omx-inspector-dual-grid';
      const [idA, idB] = activeSpec.dualPair || [camViews[0].id, camViews[1].id];
      const viewA = camViews.find(v => v.id === idA) || camViews[0];
      const viewB = camViews.find(v => v.id === idB && v.id !== viewA.id) || camViews.find(v => v.id !== viewA.id) || camViews[1];
      for (const dv of [viewA, viewB]) {
        const pane = document.createElement('div');
        pane.className = 'omx-inspector-dual-pane';
        const dImg = document.createElement('img');
        dImg.className = 'omx-inspector-main-cam omx-inspector-cam';
        dImg.alt = dv.label;
        dImg.loading = 'lazy';
        const dQual = document.createElement('span');
        dQual.className = 'cell-visual-badge';
        dQual.textContent = `🎥 [${dv.label}]`;
        frames()?.bind(dImg, dv, dQual, `🎥 [${dv.label}]`);
        pane.append(dImg, dQual);
        dualGrid.append(pane);
      }
      stage.append(dualGrid);
    } else {
      const mainCam = document.createElement('img');
      mainCam.className = 'omx-inspector-main-cam omx-inspector-cam';
      mainCam.alt = `${activeSpec.title} 메인 카메라`;
      mainCam.tabIndex = 0;
      mainCam.addEventListener('click', () => mainCam.classList.toggle('focused'));

      const qualLine = document.createElement('span');
      qualLine.className = 'cell-visual-badge';
      qualLine.textContent = `🎥 [${activeCam.label}]`;
      frames()?.bind(mainCam, activeCam, qualLine, `🎥 [${activeCam.label}]`);
      stage.append(mainCam, qualLine);
    }

    const pipGrid = document.createElement('div');
    pipGrid.className = 'omx-inspector-pip-grid';
    for (const v of camViews) {
      const pip = document.createElement('div');
      pip.className = `omx-inspector-pip${v.id === activeCam.id ? ' active' : ''}`;
      pip.tabIndex = 0;
      const pImg = document.createElement('img');
      pImg.className = 'omx-inspector-cam';
      pImg.alt = v.label;
      pImg.loading = 'lazy';
      frames()?.bind(pImg, v);
      const pLbl = document.createElement('small');
      pLbl.textContent = `📷 ${v.label}`;
      pip.append(pImg, pLbl);
      pip.addEventListener('click', () => {
        state.selectedInspectorCamByTarget[activeSpec.id] = v.id;
        renderRightInspector(body);
      });
      pipGrid.append(pip);
    }
    stage.append(pipGrid);

    const readout = document.createElement('dl');
    readout.className = 'omx-inspector-readout';
    for (const [k, v] of (activeSpec.telemetryRows || [])) {
      const dt = document.createElement('dt');
      dt.textContent = k;
      const dd = document.createElement('dd');
      dd.textContent = v;
      readout.append(dt, dd);
    }

    const quickDispatchBar = document.createElement('div');
    quickDispatchBar.className = 'omx-inspector-quick-dispatch';
    const tierSel = document.createElement('select'); tierSel.className = 'ui-field';
    for (const [val, lbl] of [['1', 'T1 (1층·벨트)'], ['2', 'T2 (2층)'], ['3', 'T3 (3층)']]) {
      const opt = document.createElement('option');
      opt.value = val;
      opt.textContent = lbl;
      if (activeSpec.id === 'arm_b' && val === '2') opt.selected = true;
      tierSel.append(opt);
    }
    const dispSel = document.createElement('select'); dispSel.className = 'ui-field';
    for (const [val, lbl] of [['', '정위치 (Nominal)'], ['auto', 'Auto ROI 감지'], ['belt_far', 'Belt-Far 복구'], ['floor_front', 'Floor-Front 복구']]) {
      const opt = document.createElement('option');
      opt.value = val;
      opt.textContent = lbl;
      dispSel.append(opt);
    }
    const targetArm = activeSpec.id.startsWith('arm_') ? activeSpec.id : (activeSpec.id === 'cell_ab' ? 'arm_a' : 'arm_s');
    const targetCell = targetArm === 'arm_s' ? 'cell_s' : 'cell_ab';
    const runCustomBtn = document.createElement('ui-button');
    runCustomBtn.setAttribute('kind', 'primary');
    runCustomBtn.setAttribute('type', 'button');
    runCustomBtn.textContent = `▶ ${targetArm} 즉시 실행`;
    runCustomBtn.addEventListener('click', async () => {
      const current = ctx.bump();
      if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `우측 인스펙터 맞춤 태스크(${targetCell}/${targetArm})를 큐에 등록하는 중입니다.`;
      try {
        const res = await request(CELL_TASKS_PATH, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            cell_id: targetCell,
            arm_id: targetArm,
            tier: Number(tierSel.value || 1),
            displaced_to: dispSel.value || null,
            robot_id: activeSpec.robot_id || 'rosy_46',
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
    });
    quickDispatchBar.append(tierSel, dispSel, runCustomBtn);

    const actions = document.createElement('div');
    actions.className = 'omx-inspector-actions';
    for (const b of (activeSpec.buttons || [])) {
      const btn = document.createElement('ui-button');
      btn.setAttribute('kind', 'quiet');
      if (b.cancelTaskId) btn.setAttribute('kind', 'irreversible');
      btn.setAttribute('type', 'button');
      btn.textContent = b.label;
      bindActionButton(btn, b, activeSpec.robot_id || 'rosy_46');
      actions.append(btn);
    }

    panel.replaceChildren(tabs, head, stage, readout, quickDispatchBar, actions);
  }

  function renderVisualCards(body) {
    const wrap = $('cell-visual-cards');
    if (!wrap) return;
    const cards = visualCardSpecs(body);
    wrap.replaceChildren(...cards.map(card => {
      const article = document.createElement('article');
      const isSelected = state.selectedInspectorTarget === card.id
        || (card.id === 'cell_s' && state.selectedInspectorTarget === 'arm_s')
        || (card.id === 'cell_ab' && (state.selectedInspectorTarget === 'arm_a' || state.selectedInspectorTarget === 'arm_b'))
        || (card.id === 'pinky' && state.selectedInspectorTarget.startsWith('rosy_'));
      article.className = `cell-visual-card${isSelected ? ' selected-inspector' : ''}`;
      article.dataset.cardId = card.id;
      article.addEventListener('click', () => {
        const defaultTarget = card.id === 'cell_s' ? 'arm_s' : (card.id === 'cell_ab' ? 'arm_a' : (card.robot_id || 'rosy_46'));
        selectInspectorTarget(defaultTarget, state.selectedCameraByCard[card.id] || null);
      });

      const activeViewId = state.selectedCameraByCard[card.id] || card.cameraViews?.[0]?.id || card.id;
      const activeView = (card.cameraViews || []).find(v => v.id === activeViewId) || (card.cameraViews || [])[0]
        || {id: card.id, label: card.title, roiTarget: card.robot_id || card.id};

      const thumb = document.createElement('img');
      thumb.className = 'cell-visual-thumb';
      thumb.alt = card.title;
      thumb.loading = 'lazy';
      frames()?.bind(thumb, activeView);
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
      frames()?.bind(thumb, activeView, camQualityBadge, '🎥 영상');
      for (const v of (card.cameraViews || [])) {
        const pill = document.createElement('ui-button');
        pill.setAttribute('kind', 'quiet');
        if (v.id === activeViewId) pill.setAttribute('kind', 'primary');
        pill.setAttribute('type', 'button');
        pill.dataset.cameraView = v.id;
        pill.textContent = `📷 ${v.label}`;
        pill.addEventListener('click', ev => {
          ev.stopPropagation();
          state.selectedCameraByCard[card.id] = v.id;
          frames()?.bind(thumb, v, camQualityBadge, '🎥 영상');
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
      }
      for (const b of card.buttons) {
        const btn = document.createElement('ui-button');
        btn.setAttribute('kind', 'quiet');
        if (b.cancelTaskId) btn.setAttribute('kind', 'irreversible');
        btn.setAttribute('type', 'button');
        btn.textContent = b.label;
        bindActionButton(btn, b, card.robot_id || 'rosy_46');
        actions.append(btn);
      }

      article.append(thumb, camSwitcher, head, meta, actions);
      return article;
    }));
  }

  function renderCameraMatrix() {
    const wall = $('cell-camera-matrix');
    if (!wall) return;
    wall.replaceChildren(...CAMERA_WALL_VIEWS.map(cam => {
      const card = document.createElement('article');
      card.className = 'cell-observation-card';
      card.tabIndex = 0;
      const h4 = document.createElement('h4');
      h4.textContent = cam.label;
      const img = document.createElement('img');
      img.alt = cam.label;
      img.loading = 'lazy';
      const meta = document.createElement('pre');
      meta.textContent = cam.roiTarget ? '천장 Cam ROI 확대' : `Vision 소스 ${cam.source}`;
      frames()?.bind(img, cam, meta, cam.roiTarget ? '천장 Cam ROI' : cam.source);
      card.addEventListener('click', () => {
        card.classList.toggle('focused');
        const camTargetMap = {
          arm_s_top: 'arm_s',
          arm_s_wrist: 'arm_s',
          top: 'cell_ab',
          side: 'cell_ab',
          arm_a_wrist: 'arm_a',
          arm_b_wrist: 'arm_b',
          pinky_dock: 'rosy_46',
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
        side: {label: '▶ 3층 적재 (arm_a)', preset: 's5_tier3_arm_a'},
        arm_a_wrist: {label: '▶ 1층 적재 (arm_a)', preset: 's5_tier1_arm_a'},
        arm_b_wrist: {label: '▶ 2층 적재 (arm_b)', preset: 's5_tier2_arm_b'},
        pinky_dock: {label: '▶ S3 도킹+하역', pinkyAction: 'dock_and_unload_s3'},
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

  return {renderRightInspector, renderVisualCards, renderCameraMatrix};
}
