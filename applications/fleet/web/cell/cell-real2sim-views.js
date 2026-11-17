// Right inspector, visual cards and camera matrix renderers for the Real-to-Sim pipeline view (split from cell-real2sim.js).
import {CELL_TASKS_PATH, CAMERA_WALL_VIEWS, S3_VIEWS, CELL_A_VIEWS, CELL_B_VIEWS, S5_VIEWS, inspectorSpecs, visualCardSpecs} from './cell-real2sim-specs.js';

export function createCellViews(ctx) {
  const {request, $, state} = ctx;
  const frames = () => ctx.cellFrames;
  const refreshCellTasks = (...args) => ctx.refreshCellTasks(...args);
  const selectInspectorTarget = (...args) => ctx.selectInspectorTarget(...args);
  const bindActionButton = (...args) => ctx.bindActionButton(...args);
  const runQuickPreset = (...args) => ctx.runQuickPreset(...args);
  const runPinkyQuickAction = (...args) => ctx.runPinkyQuickAction(...args);
  const runStationZoneDispatch = (...args) => ctx.runStationZoneDispatch(...args);

  const isCardSelected = cardId => state.selectedInspectorTarget === cardId
    || (cardId === 'cell_s' && state.selectedInspectorTarget === 'arm_s')
    || (cardId === 'cell_a' && state.selectedInspectorTarget === 'arm_a')
    || (cardId === 'cell_b' && state.selectedInspectorTarget === 'arm_b')
    || (cardId === 'cell_ab' && (state.selectedInspectorTarget === 'arm_a' || state.selectedInspectorTarget === 'arm_b'))
    || (cardId === 'pinky' && state.selectedInspectorTarget.startsWith('rosy_'));

  function applyOperatorGate(btn) {
    const allowed = Boolean(ctx.isOperator?.());
    btn.dataset.operatorAction = '1';
    if (btn.dataset.inflight === '1') {
      btn.disabled = true;
      btn.setAttribute('reason', '요청 처리 중');
      return;
    }
    btn.disabled = !allowed;
    if (allowed) btn.removeAttribute('reason');
    else btn.setAttribute('reason', '운영자 권한이 필요합니다');
  }

  function makeActionButton(b, fallbackRobotId) {
    const btn = document.createElement('ui-button');
    btn.setAttribute('kind', 'quiet');
    if (b.humanSafetyCell) btn.setAttribute('kind', b.humanDetected ? 'irreversible' : 'primary');
    btn.setAttribute('type', 'button');
    btn.textContent = b.label;
    bindActionButton(btn, b, fallbackRobotId);
    applyOperatorGate(btn);
    return btn;
  }

  function syncCardSelection() {
    const wrap = $('cell-visual-cards');
    if (!wrap) return;
    for (const article of wrap.querySelectorAll('.cell-visual-card[data-card-id]')) {
      article.classList.toggle('selected-inspector', isCardSelected(article.dataset.cardId));
    }
    for (const btn of wrap.querySelectorAll('[data-inspect-target]')) {
      btn.setAttribute('kind', btn.dataset.inspectTarget === state.selectedInspectorTarget ? 'primary' : 'quiet');
    }
  }

  function mountInspectorMedia(slots, activeSpec, activeCam) {
    const camViews = activeSpec.cameraViews || [];
    slots.stageMedia.replaceChildren();
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
      slots.stageMedia.append(dualGrid);
      slots.stageMode = 'dual';
      slots.stageCamId = `${viewA.id}|${viewB.id}`;
      slots.mainCam = null;
      slots.qualLine = null;
      return;
    }
    const mainCam = document.createElement('img');
    mainCam.className = 'omx-inspector-main-cam omx-inspector-cam';
    mainCam.alt = `${activeSpec.title} 메인 카메라`;
    mainCam.tabIndex = 0;
    mainCam.addEventListener('click', () => mainCam.classList.toggle('focused'));
    mainCam.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); mainCam.classList.toggle('focused'); }
      else if (ev.key === 'Escape') mainCam.classList.remove('focused');
    });
    const qualLine = document.createElement('span');
    qualLine.className = 'cell-visual-badge';
    qualLine.textContent = `🎥 [${activeCam.label}]`;
    frames()?.bind(mainCam, activeCam, qualLine, `🎥 [${activeCam.label}]`);
    slots.stageMedia.append(mainCam, qualLine);
    slots.stageMode = 'single';
    slots.stageCamId = activeCam.id;
    slots.mainCam = mainCam;
    slots.qualLine = qualLine;
  }

  function updateInspectorCam(slots, activeSpec, activeCam) {
    for (const pip of slots.pipGrid.children) {
      pip.classList.toggle('active', pip.dataset.camId === activeCam.id);
    }
    const wantDual = Boolean(state.dualInspectorCamMode && (activeSpec.cameraViews || []).length >= 2);
    if (!wantDual && slots.stageMode === 'single' && slots.mainCam) {
      if (slots.stageCamId !== activeCam.id) {
        frames()?.bind(slots.mainCam, activeCam, slots.qualLine, `🎥 [${activeCam.label}]`);
        slots.stageCamId = activeCam.id;
      }
      return;
    }
    if (wantDual !== (slots.stageMode === 'dual') || slots.stageCamId !== activeCam.id) {
      mountInspectorMedia(slots, activeSpec, activeCam);
    }
  }

  function renderReadout(readout, rows) {
    readout.replaceChildren(...rows.flatMap(([k, v]) => {
      const dt = document.createElement('dt');
      dt.textContent = k;
      const dd = document.createElement('dd');
      dd.textContent = v;
      return [dt, dd];
    }));
  }

  function renderRightInspector(body) {
    const panel = $('omx-right-inspector');
    if (!panel) return;
    const scope = ctx.getScope?.() || null;
    const specs = inspectorSpecs(body, {scope});
    const activeSpec = specs.find(s => s.id === state.selectedInspectorTarget) || specs[0];
    if (!activeSpec) return;
    if (state.selectedInspectorTarget !== activeSpec.id) {
      state.selectedInspectorTarget = activeSpec.id;
    }

    const camViews = activeSpec.cameraViews || [];
    const activeCamId = state.selectedInspectorCamByTarget[activeSpec.id] || camViews[0]?.id || 'arm_s_top';
    const activeCam = camViews.find(v => v.id === activeCamId) || camViews[0] || {id: activeCamId, label: activeCamId, source: activeCamId};
    const buttonsKey = JSON.stringify(activeSpec.buttons || []);
    const readoutKey = JSON.stringify(activeSpec.telemetryRows || []);
    const specIdsKey = specs.map(s => s.id).join(',');
    const slots = panel._slots;

    if (slots && slots.targetId === activeSpec.id && slots.scope === (scope || '') && slots.specIdsKey === specIdsKey) {
      for (const tab of slots.tabs.querySelectorAll('[data-inspect-target]')) {
        tab.setAttribute('kind', tab.dataset.inspectTarget === activeSpec.id ? 'primary' : 'quiet');
      }
      slots.dualBtn.setAttribute('kind', state.dualInspectorCamMode ? 'primary' : 'quiet');
      slots.dualBtn.textContent = state.dualInspectorCamMode ? '📺 2채널(상단+손목) ON' : '📺 2채널 동시 보기';
      slots.title.textContent = activeSpec.title;
      slots.badge.textContent = activeSpec.badge;
      updateInspectorCam(slots, activeSpec, activeCam);
      if (slots.readoutKey !== readoutKey) {
        slots.readoutKey = readoutKey;
        renderReadout(slots.readout, activeSpec.telemetryRows || []);
      }
      if (slots.buttonsKey !== buttonsKey) {
        slots.buttonsKey = buttonsKey;
        slots.actions.replaceChildren(...(activeSpec.buttons || []).map(b => makeActionButton(b, activeSpec.robot_id || 'rosy_46')));
      } else {
        for (const btn of slots.actions.children) applyOperatorGate(btn);
      }
      applyOperatorGate(slots.runCustomBtn);
      return;
    }

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
    tabs.append(dualBtn);

    const head = document.createElement('div');
    head.className = 'omx-inspector-head';
    const title = document.createElement('strong');
    title.textContent = activeSpec.title;
    const badge = document.createElement('span');
    badge.className = 'cell-visual-badge';
    badge.textContent = activeSpec.badge;
    head.append(title, badge);

    const stage = document.createElement('div');
    stage.className = 'omx-inspector-stage';
    const stageMedia = document.createElement('div');
    stageMedia.className = 'omx-inspector-stage';
    const pipGrid = document.createElement('div');
    pipGrid.className = 'omx-inspector-pip-grid';
    stage.append(stageMedia, pipGrid);

    const readout = document.createElement('dl');
    readout.className = 'omx-inspector-readout';
    renderReadout(readout, activeSpec.telemetryRows || []);

    const quickDispatchBar = document.createElement('div');
    quickDispatchBar.className = 'omx-inspector-quick-dispatch';
    const targetArm = activeSpec.id.startsWith('arm_') ? activeSpec.id : (activeSpec.id === 'cell_ab' ? 'arm_a' : 'arm_s');
    const targetCell = targetArm === 'arm_s' ? 'cell_s' : 'cell_ab';
    const tierSel = document.createElement('select'); tierSel.className = 'ui-field';
    const tierPairs = (scope === 'cell_a' || targetArm === 'arm_a')
      ? [['1', 'T1 (1층·벨트)'], ['3', 'T3 (3층)']]
      : (scope === 'cell_b' || targetArm === 'arm_b')
      ? [['2', 'T2 (2층)']]
      : [['1', 'T1 (1층·벨트)'], ['2', 'T2 (2층)'], ['3', 'T3 (3층)']];
    const savedTier = state.selectedTierByTarget?.[activeSpec.id];
    const hasSavedTier = tierPairs.some(([val]) => val === savedTier);
    for (const [val, lbl] of tierPairs) {
      const opt = document.createElement('option');
      opt.value = val;
      opt.textContent = lbl;
      if (hasSavedTier ? val === savedTier : (activeSpec.id === 'arm_b' && val === '2')) opt.selected = true;
      tierSel.append(opt);
    }
    tierSel.addEventListener('change', () => { (state.selectedTierByTarget ??= {})[activeSpec.id] = tierSel.value; });

    const dispSel = document.createElement('select'); dispSel.className = 'ui-field';
    const savedDisp = state.selectedDisplacedByTarget?.[activeSpec.id] ?? '';
    for (const [val, lbl] of [['', '정위치 (Nominal)'], ['auto', 'Auto ROI 감지'], ['belt_far', 'Belt-Far 복구'], ['floor_front', 'Floor-Front 복구']]) {
      const opt = document.createElement('option');
      opt.value = val;
      opt.textContent = lbl;
      if (val === savedDisp) opt.selected = true;
      dispSel.append(opt);
    }
    dispSel.addEventListener('change', () => { (state.selectedDisplacedByTarget ??= {})[activeSpec.id] = dispSel.value; });

    const runCustomBtn = document.createElement('ui-button');
    runCustomBtn.setAttribute('kind', 'primary');
    runCustomBtn.setAttribute('type', 'button');
    runCustomBtn.textContent = `▶ ${targetArm} 즉시 실행`;
    applyOperatorGate(runCustomBtn);
    runCustomBtn.addEventListener('click', () => {
      void (ctx.withBusyButton || ((_, fn) => fn()))(runCustomBtn, async () => {
        const current = ctx.bump();
        if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `우측 인스펙터 맞춤 작업(${targetCell}/${targetArm})를 큐에 등록하는 중입니다.`;
        try {
          const res = await request(CELL_TASKS_PATH, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              cell_id: targetCell,
              arm_id: targetArm,
              tier: targetCell === 'cell_ab' ? Number(tierSel.value || 1) : 1,
              displaced_to: targetCell === 'cell_s' ? (dispSel.value || null) : null,
              robot_id: activeSpec.robot_id || 'rosy_46',
            }),
          });
          if (current !== ctx.gen()) return;
          await refreshCellTasks(current);
          if ($('cell-tasks-status')) {
            $('cell-tasks-status').textContent = `인스펙터 맞춤 작업 등록 완료: ${res.task?.task_id || '—'} (${targetCell}/${targetArm})`;
          }
        } catch (error) {
          if (current !== ctx.gen()) return;
          if ($('cell-tasks-status')) $('cell-tasks-status').textContent = `인스펙터 맞춤 작업 등록 실패: ${error.message}`;
        }
      });
    });
    if (targetCell === 'cell_ab') quickDispatchBar.append(tierSel, runCustomBtn);
    else quickDispatchBar.append(dispSel, runCustomBtn);

    const actions = document.createElement('div');
    actions.className = 'omx-inspector-actions';
    for (const b of (activeSpec.buttons || [])) actions.append(makeActionButton(b, activeSpec.robot_id || 'rosy_46'));

    const nextSlots = {
      targetId: activeSpec.id, scope: scope || '', specIdsKey, buttonsKey, readoutKey,
      tabs, dualBtn, title, badge, stageMedia, pipGrid, readout, runCustomBtn, actions,
      stageMode: '', stageCamId: '', mainCam: null, qualLine: null,
    };
    for (const v of camViews) {
      const pip = document.createElement('div');
      pip.className = `omx-inspector-pip${v.id === activeCam.id ? ' active' : ''}`;
      pip.dataset.camId = v.id;
      pip.tabIndex = 0;
      const pImg = document.createElement('img');
      pImg.className = 'omx-inspector-cam';
      pImg.alt = v.label;
      pImg.loading = 'lazy';
      frames()?.bind(pImg, v);
      const pLbl = document.createElement('small');
      pLbl.textContent = `📷 ${v.label}`;
      pip.append(pImg, pLbl);
      const pickPip = () => {
        state.selectedInspectorCamByTarget[activeSpec.id] = v.id;
        updateInspectorCam(nextSlots, activeSpec, v);
      };
      pip.addEventListener('click', pickPip);
      pip.addEventListener('keydown', ev => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pickPip(); }
      });
      pipGrid.append(pip);
    }
    dualBtn.addEventListener('click', () => {
      state.dualInspectorCamMode = !state.dualInspectorCamMode;
      dualBtn.setAttribute('kind', state.dualInspectorCamMode ? 'primary' : 'quiet');
      dualBtn.textContent = state.dualInspectorCamMode ? '📺 2채널(상단+손목) ON' : '📺 2채널 동시 보기';
      const curCamId = state.selectedInspectorCamByTarget[activeSpec.id] || camViews[0]?.id || 'arm_s_top';
      const curCam = camViews.find(v => v.id === curCamId) || camViews[0] || activeCam;
      mountInspectorMedia(nextSlots, activeSpec, curCam);
    });
    mountInspectorMedia(nextSlots, activeSpec, activeCam);

    panel._slots = nextSlots;
    panel.replaceChildren(tabs, head, stage, readout, quickDispatchBar, actions);
  }

  function renderVisualCards(body) {
    const wrap = $('cell-visual-cards');
    if (!wrap) return;
    const scope = ctx.getScope?.() || null;
    const cards = visualCardSpecs(body, {scope});
    const existing = [...wrap.children];
    const sameShape = existing.length === cards.length
      && existing.every((el, idx) => el._refs && el.dataset.cardId === cards[idx].id);
    if (sameShape) {
      for (let i = 0; i < cards.length; i++) {
        const card = cards[i], refs = existing[i]._refs;
        const buttonsKey = JSON.stringify(card.buttons || []);
        existing[i].classList.toggle('selected-inspector', isCardSelected(card.id));
        refs.badge.textContent = (card.id === 'cell_ab' || card.id === 'cell_a' || card.id === 'cell_b')
          ? `${card.phase} · 협동 통로 ${card.amr_motion_inhibited ? '점유' : '대기'}`
          : `${card.phase} · AMR 잠금 ${card.amr_motion_inhibited ? 'ON' : 'OFF'}`;
        refs.meta.textContent = `${card.last_task} | ${card.folded_state}`;
        for (const btn of refs.actions.querySelectorAll('[data-inspect-target]')) {
          btn.setAttribute('kind', btn.dataset.inspectTarget === state.selectedInspectorTarget ? 'primary' : 'quiet');
        }
        if (refs.buttonsKey !== buttonsKey) {
          refs.buttonsKey = buttonsKey;
          refs.actions.replaceChildren(
            ...refs.inspectButtons,
            ...card.buttons.map(b => makeActionButton(b, card.robot_id || 'rosy_46')),
          );
        } else {
          for (const btn of refs.actions.querySelectorAll('[data-operator-action="1"]')) applyOperatorGate(btn);
        }
      }
      return;
    }
    wrap.replaceChildren(...cards.map(card => {
      const article = document.createElement('article');
      article.className = `cell-visual-card${isCardSelected(card.id) ? ' selected-inspector' : ''}`;
      article.dataset.cardId = card.id;
      article.addEventListener('click', () => {
        const defaultTarget = card.id === 'cell_s' ? 'arm_s'
          : card.id === 'cell_b' ? 'arm_b'
          : (card.id === 'cell_a' || card.id === 'cell_ab') ? 'arm_a'
          : (card.robot_id || 'rosy_46');
        selectInspectorTarget(defaultTarget, state.selectedCameraByCard[card.id] || null);
      });

      const activeViewId = state.selectedCameraByCard[card.id] || card.cameraViews?.[0]?.id || card.id;
      const activeView = (card.cameraViews || []).find(v => v.id === activeViewId) || (card.cameraViews || [])[0]
        || {id: card.id, label: card.title, roiTarget: card.robot_id || card.id};

      const thumb = document.createElement('img');
      thumb.className = 'cell-visual-thumb';
      thumb.alt = card.title;
      thumb.loading = 'lazy';
      thumb.tabIndex = 0;
      thumb.addEventListener('click', ev => {
        ev.stopPropagation();
        thumb.classList.toggle('focused');
      });
      thumb.addEventListener('keydown', ev => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          ev.stopPropagation();
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
            : card.id === 'cell_a' ? 'arm_a'
            : card.id === 'cell_b' ? 'arm_b'
            : card.id === 'cell_ab' ? (state.selectedInspectorTarget === 'arm_b' ? 'arm_b' : 'arm_a')
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
      badge.textContent = (card.id === 'cell_ab' || card.id === 'cell_a' || card.id === 'cell_b')
        ? `${card.phase} · 협동 통로 ${card.amr_motion_inhibited ? '점유' : '대기'}`
        : `${card.phase} · AMR 잠금 ${card.amr_motion_inhibited ? 'ON' : 'OFF'}`;
      head.append(title, badge);

      const meta = document.createElement('p');
      meta.className = 'cell-visual-meta';
      meta.textContent = `${card.last_task} | ${card.folded_state}`;

      const actions = document.createElement('div');
      actions.className = 'cell-visual-actions';
      const inspectTargets = card.id === 'cell_s'
        ? [['arm_s', '🔍 우측 연동: arm_s']]
        : card.id === 'cell_a'
        ? [['arm_a', '🔍 우측 연동: arm_a']]
        : card.id === 'cell_b'
        ? [['arm_b', '🔍 우측 연동: arm_b']]
        : card.id === 'cell_ab'
        ? [['arm_a', '🔍 우측 연동: arm_a'], ['arm_b', '🔍 우측 연동: arm_b']]
        : [['rosy_46', '🔍 우측 연동: rosy_46'], ['rosy_45', '🔍 rosy_45'], ['rosy_42', '🔍 rosy_42']];
      const inspectButtons = [];
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
        inspectButtons.push(iBtn);
        actions.append(iBtn);
      }
      for (const b of card.buttons) {
        actions.append(makeActionButton(b, card.robot_id || 'rosy_46'));
      }

      article._refs = {badge, meta, actions, inspectButtons, buttonsKey: JSON.stringify(card.buttons || [])};
      article.append(thumb, camSwitcher, head, meta, actions);
      return article;
    }));
  }

  function renderCameraMatrix() {
    const wall = $('cell-camera-matrix');
    if (!wall) return;
    const panel = $('cell-camera-matrix-panel');
    if (panel && !panel.dataset.matrixBound) {
      panel.dataset.matrixBound = '1';
      panel.addEventListener('toggle', () => renderCameraMatrix());
    }
    if (panel && !panel.open) {
      if (wall.childElementCount) wall.replaceChildren();
      wall.dataset.renderedScope = '';
      return;
    }
    const scope = ctx.getScope?.() || null;
    const scopeKey = scope || 'all';
    if (wall.dataset.renderedScope === scopeKey && wall.childElementCount > 0) return;
    wall.dataset.renderedScope = scopeKey;
    const views = scope === 'cell_a' ? CELL_A_VIEWS
      : scope === 'cell_b' ? CELL_B_VIEWS
      : scope === 'cell_ab' ? S5_VIEWS
      : (scope === 'cell_s' ? S3_VIEWS : CAMERA_WALL_VIEWS);
    wall.replaceChildren(...views.map(cam => {
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
        const s5DefaultArm = scope === 'cell_b' ? 'arm_b'
          : scope === 'cell_a' ? 'arm_a'
          : (state.selectedInspectorTarget === 'arm_b' ? 'arm_b' : 'arm_a');
        const camTargetMap = {
          arm_s_top: 'arm_s',
          arm_s_wrist: 'arm_s',
          top: s5DefaultArm,
          side: s5DefaultArm,
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
        top: scope === 'cell_b'
          ? {label: '▶ 2층 적재 (arm_b)', preset: 's5_tier2_arm_b'}
          : {label: '▶ 1층 적재 (arm_a)', preset: 's5_tier1_arm_a'},
        side: scope === 'cell_b'
          ? {label: '▶ 2층 적재 (arm_b)', preset: 's5_tier2_arm_b'}
          : {label: '▶ 3층 적재 (arm_a)', preset: 's5_tier3_arm_a'},
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
        applyOperatorGate(actBtn);
        actBtn.addEventListener('click', ev => {
          ev.stopPropagation();
          void (ctx.withBusyButton || ((_, fn) => fn()))(actBtn, async () => {
            if (qAct.preset) await runQuickPreset(qAct.preset);
            else if (qAct.pinkyAction) await runPinkyQuickAction('rosy_46', qAct.pinkyAction);
            else if (qAct.zoneId) await runStationZoneDispatch(qAct.zoneId, 'rosy_46');
          });
        });
        card.append(h4, img, meta, actBtn);
      } else {
        card.append(h4, img, meta);
      }
      return card;
    }));
  }

  return {renderRightInspector, renderVisualCards, renderCameraMatrix, syncCardSelection};
}
