// D-941 5/7: the charge-bay plan remains display-only; task buttons use pipeline APIs.
import { setOffBy } from "/common/cause-line.js";
import { patchHidden, patchText, uiTag } from "/common/control-dom.js";
import { isRouteAbsent } from "/console/assets/poll-gate.js";
import { owns } from "/console/assets/unit-scope.js";
import { chargeBayRows, inspectorTargetsFromRows } from "/console/assets/charge-bays-model.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";

export { chargeBayRows, inspectorTargetsFromRows, formatArmLiveJointText } from "/console/assets/charge-bays-model.js";

/** Choices that act on a robot need the server's occupant; the console never substitutes one. */
// The human-safety gate is cell-wide and must never be disabled for want of a robot.
const needsRobot = (choice) => Boolean(choice.visionCheckCell || choice.cableGuardToggle
  || choice.zoneId);

function markNoRobot(button, choice, card) {
  if (!needsRobot(choice) || card.robot_id) return;
  setOffBy(button, "대상 로봇 없음");
}

export function createChargeBaysView({ scope, el, call, auth, confirmedAction = null, selection = null, readWorkcellObs = null }) {
  const state = el("charge-bays-state");
  const list = el("charge-bay-rows");
  const hint = el("charge-bays-hint");
  const inspector = typeof el === "function" ? el("omx-right-inspector") : null;
  // 셀 카메라는 Vision 임대 프레임으로만 본다(D-136). Fleet은 바이트를 중계하지 않는다.
  const frames = createCellFrameFeed({ call, scope });
  for (const box of [list, inspector]) if (box) scope.listen(box, "click", () => {
    framesOn = true;
    for (const s of inspector?.querySelectorAll(".omx-inspector-cam-standby") || []) s.hidden = true;
  }, true);
  let inFlight = false;
  let unavailable = false;
  const liveStreamOn = true;
  let inspectorOpen = false;
  let activeInspectorId = null;
  // Choosing a robot only inspects it (no Vision lease); frames start after a click inside the cards or inspector.
  let framesOn = false;
  const selectedInspectorCam = {};
  let dualCamMode = false;
  let lastRows = null;
  let lastInspectorSig = "";
  let lastListSig = "";
  const draftChoices = new Map();

  scope.listen(document, "visibilitychange", () => {
    frames.setRunning(!document.hidden && liveStreamOn && inspectorOpen && owns("drive"));
    if (!document.hidden && owns("drive")) void refresh();
  });

  if (selection?.subscribe) {
    const offSelection = selection.subscribe((id) => {
      if (!id || (!String(id).startsWith("arm_") && !String(id).startsWith("cell_"))) return;
      activeInspectorId = id;
      framesOn = false;
      lastInspectorSig = "";
      if (lastRows) renderInspector(lastRows);
    });
    scope.onDispose?.(offSelection);
  }

  async function executeChoice(choice, card, button, confirmed = false) {
    if (auth.locked || button.hasAttribute("disabled")) return;
    if (needsRobot(choice) && !card.robot_id) return;  // no occupant from the server: never guess one
    if (choice.cancelTaskId && !confirmed) {  // irreversible: the shared confirmation, or nothing (fail closed)
      if (!confirmedAction) return;
      return confirmedAction.run({message: `태스크(${choice.cancelTaskId})를 즉시 취소하고 셀 인터락을 해제할까요?`, opener: button,
        eligible: () => !auth.locked, request: () => executeChoice(choice, card, button, true)});
    }
    const origLabel = button.textContent;
    setOffBy(button, "요청 처리 중");
    button.textContent = `${origLabel} (처리 중…)`;
    try {
      if (choice.cancelTaskId) {
        await call(`/api/fleet/pipeline/cell-tasks/${choice.cancelTaskId}/cancel`, {method: "POST"});
      } else if (choice.retryTaskId) {
        await call(`/api/fleet/pipeline/cell-tasks/${choice.retryTaskId}/retry`, {method: "POST"});
      } else if (choice.visionCheckCell) {
        await call("/api/fleet/pipeline/vision-auto-check", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({cell_id: choice.visionCheckCell, robot_id: card.robot_id}),
        });
      } else if (choice.cableGuardToggle) {
        await call("/api/fleet/pipeline/cable-guard", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({toggle: true, robot_id: card.robot_id}),
        });
      } else if (choice.clearArmHold) {
        await call("/api/fleet/pipeline/arm-holds/clear", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            arm_id: choice.clearArmHold,
            note: "Fleet 콘솔 카메라로 홈 복귀(folded: true) 확인 후 홀드 해제",
          }),
        });
      } else if (choice.humanSafetyCell) {
        await call("/api/fleet/pipeline/human-safety-gate", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            cell_id: choice.humanSafetyCell,
            human_detected: choice.humanDetected,
            robot_id: card.robot_id || undefined,
          }),
        });
      } else if (choice.zoneId) {
        await call("/api/fleet/pipeline/station-zones/dispatch", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({zone_id: choice.zoneId, robot_id: card.robot_id}),
        });
      } else if (choice.decisionSubject) {
        await call("/api/fleet/pipeline/decision-gate", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({subject_id: choice.decisionSubject, auto_execute: true}),
        });
      } else {
        await call("/api/fleet/pipeline/cell-tasks", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({preset: choice.preset, ...(card.robot_id ? {robot_id: card.robot_id} : {})}),
        });
      }
      await refresh();
      if (choice.requiresPresence) {
        patchText(hint, "ACT 정책 작업이 대기열에 등록되었습니다. 셀 워크스페이스(/console/cell#real2sim-heading)에서 이름 있는 운영자의 입회 표시(D-911)를 눌러 실행을 시작하세요.");
        patchHidden(hint, false);
      }
    } catch (error) {
      patchText(hint, `작업 요청 실패: ${error.message}`);
      patchHidden(hint, false);
    } finally {
      button.textContent = origLabel;
      setOffBy(button, "");
    }
  }

  function renderInspector(rows) {
    if (!inspector) return;
    // No choice yet still shows the first cell's tabs (frames stay off until a click, framesOn).
    if (!rows?.cards?.length) {
      lastInspectorSig = "";
      if (inspector.childElementCount) inspector.replaceChildren();
      return;
    }
    const targets = inspectorTargetsFromRows(rows, readWorkcellObs?.());
    const active = targets.find((t) => t.id === activeInspectorId) || targets[0];
    if (!active) return;

    const camViews = active.cameraViews || [];
    const activeCamId = selectedInspectorCam[active.id] || camViews[0]?.id || "arm_s_top";
    const activeCam = camViews.find((v) => v.id === activeCamId) || camViews[0]
      || {id: activeCamId, label: activeCamId, source: activeCamId};
    const nextSig = JSON.stringify([
      active.id,
      active.robot_id || null,
      dualCamMode,
      framesOn,
      activeCamId,
      targets.map((t) => [t.id, t.shortTab]),
      active.title,
      active.text || "대기 중",
      active.status || "neutral",
      active.task ? [active.task.task_id, active.task.status, active.task.arm_id || ""] : null,
      active.jointLiveText || active.healthText || "",
      camViews.map((v) => [v.id, v.source, v.label]),
      active.dualPair || null,
      active.buttons || [],
      active.quickControls || [],
    ]);
    if (nextSig === lastInspectorSig && inspector.firstElementChild) return;
    lastInspectorSig = nextSig;

    const tabs = document.createElement("div");
    tabs.className = "omx-inspector-tabs";
    for (const t of targets) {
      const btn = document.createElement("ui-button");
      btn.setAttribute("kind", "segment");
      btn.setAttribute("aria-pressed", String(t.id === active.id));
      btn.setAttribute("aria-selected", String(t.id === active.id));
      btn.setAttribute("type", "button");
      btn.setAttribute("data-work-read", "");
      btn.dataset.inspectTarget = t.id;
      btn.textContent = t.shortTab;
      btn.addEventListener("click", () => {
        activeInspectorId = t.id;
        lastInspectorSig = "";
        selection?.set?.(t.id, { source: "inspector" });
        renderInspector(rows);
      });
      tabs.append(btn);
    }
    const dualBtn = document.createElement("ui-button");
    dualBtn.setAttribute("kind", "segment");
    dualBtn.setAttribute("aria-pressed", String(dualCamMode));
    dualBtn.setAttribute("type", "button");
    dualBtn.setAttribute("data-work-read", "");
    dualBtn.dataset.dualCamToggle = "true";
    dualBtn.textContent = dualCamMode ? "2CH ON" : "2CH";
    dualBtn.title = "상단+손목 2채널 동시 보기";
    dualBtn.addEventListener("click", () => {
      dualCamMode = !dualCamMode;
      lastInspectorSig = "";
      renderInspector(rows);
    });
    tabs.append(dualBtn);

    const head = document.createElement("div");
    head.className = "omx-inspector-head";
    const titleEl = document.createElement("strong");
    titleEl.textContent = active.title;
    head.append(titleEl, uiTag(active.text || "대기 중", active.status || "neutral"));

    const cameraBindings = [];
    let camStageNode;
    if (dualCamMode && camViews.length >= 2) {
      camStageNode = document.createElement("div");
      camStageNode.className = "omx-inspector-dual-grid";
      const [idA, idB] = active.dualPair || [camViews[0].id, camViews[1].id];
      const viewA = camViews.find((v) => v.id === idA) || camViews[0];
      const viewB = camViews.find((v) => v.id === idB && v.id !== viewA.id) || camViews.find((v) => v.id !== viewA.id) || camViews[1];
      for (const dv of [viewA, viewB]) {
        const pane = document.createElement("div");
        pane.className = "omx-inspector-dual-pane";
        const dFrame = document.createElement("div");
        dFrame.className = "omx-inspector-cam-frame";
        const dImg = document.createElement("img");
        dImg.className = "omx-inspector-main-cam omx-inspector-cam";
        dImg.alt = `${dv.label} 실시간 카메라`;
        dImg.loading = "lazy";
        dFrame.append(dImg);
        if (!framesOn) {
          const standby = document.createElement("span");
          standby.className = "omx-inspector-cam-standby";
          standby.setAttribute("role", "status");
          standby.textContent = "영상 대기 · 클릭하여 연결";
          dFrame.append(standby);
        }
        const dCap = document.createElement("small");
        dCap.className = "omx-inspector-cam-badge";
        dCap.textContent = dv.label;
        cameraBindings.push([dImg, dv, dCap, dv.label]);
        pane.append(dFrame, dCap);
        camStageNode.append(pane);
      }
    } else {
      camStageNode = document.createElement("div");
      camStageNode.className = "omx-inspector-single-wrap";
      const mainFrame = document.createElement("div");
      mainFrame.className = "omx-inspector-cam-frame";
      const mainImg = document.createElement("img");
      mainImg.className = "omx-inspector-main-cam omx-inspector-cam";
      mainImg.alt = `${active.title} 실시간 메인 카메라`;
      mainImg.loading = "lazy";
      mainFrame.append(mainImg);
      if (!framesOn) {
        const standby = document.createElement("span");
        standby.className = "omx-inspector-cam-standby";
        standby.setAttribute("role", "status");
        standby.textContent = "영상 대기 · 클릭하여 연결";
        mainFrame.append(standby);
      }
      const stageBar = document.createElement("div");
      stageBar.className = "omx-inspector-stage-bar";
      const mainCap = document.createElement("small");
      mainCap.className = "omx-inspector-cam-badge";
      mainCap.textContent = `[${activeCam.label}]`;
      const zoomBtn = document.createElement("ui-button");
      zoomBtn.className = "omx-inspector-zoom";
      zoomBtn.setAttribute("kind", "quiet");
      zoomBtn.setAttribute("type", "button");
      zoomBtn.setAttribute("data-work-read", "");
      zoomBtn.setAttribute("aria-expanded", "false");
      zoomBtn.textContent = "크게 보기";
      zoomBtn.setAttribute("aria-label", `${activeCam.label} 크게 보기`);
      const applyZoom = (zoomed) => {
        mainImg.classList.toggle("focused", zoomed);
        zoomBtn.setAttribute("aria-expanded", String(zoomed));
        zoomBtn.textContent = zoomed ? "원래 크기" : "크게 보기";
        zoomBtn.setAttribute("aria-label", `${activeCam.label} ${zoomed ? "원래 크기" : "크게 보기"}`);
      };
      zoomBtn.addEventListener("click", () => applyZoom(!mainImg.classList.contains("focused")));
      mainImg.addEventListener("click", () => applyZoom(!mainImg.classList.contains("focused")));
      camStageNode.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && mainImg.classList.contains("focused")) {
          ev.stopPropagation();
          applyZoom(false);
        }
      });
      stageBar.append(mainCap, zoomBtn);
      cameraBindings.push([mainImg, activeCam, mainCap, `[${activeCam.label}]`]);
      camStageNode.append(mainFrame, stageBar);
    }

    const pipGrid = document.createElement("div");
    pipGrid.className = "omx-inspector-pip-grid";
    for (const v of camViews) {
      const pip = document.createElement("button");
      pip.type = "button";
      pip.setAttribute("data-work-read", "");
      pip.className = `omx-inspector-pip${v.id === activeCam.id ? " active" : ""}`;
      pip.setAttribute("aria-pressed", String(v.id === activeCam.id));
      pip.setAttribute("aria-label", `${v.label} 카메라 선택`);
      const pFrame = document.createElement("div");
      pFrame.className = "omx-inspector-cam-frame";
      const pImg = document.createElement("img");
      pImg.className = "omx-inspector-cam";
      pImg.alt = "";
      pImg.setAttribute("aria-hidden", "true");
      pImg.loading = "lazy";
      pFrame.append(pImg);
      if (!framesOn) {
        const standby = document.createElement("span");
        standby.className = "omx-inspector-cam-standby";
        standby.textContent = "대기";
        pFrame.append(standby);
      }
      cameraBindings.push([pImg, v]);
      const pLbl = document.createElement("small");
      pLbl.textContent = v.label;
      pip.append(pFrame, pLbl);
      pip.addEventListener("click", () => {
        selectedInspectorCam[active.id] = v.id;
        lastInspectorSig = "";
        renderInspector(rows);
      });
      pipGrid.append(pip);
    }

    const meta = document.createElement("p");
    meta.className = "omx-inspector-meta";
    const taskBase = active.task ? `${active.task.task_id} · ${active.task.status} · ${active.task.arm_id || "—"}` : "";
    meta.textContent = [taskBase, active.jointLiveText || active.healthText || ""].filter(Boolean).join(" | ");

    const draft = draftChoices.get(active.id) || {};
    const quickDispatchBar = document.createElement("div");
    quickDispatchBar.className = "omx-inspector-quick-dispatch";
    const tierField = document.createElement("label");
    tierField.className = "omx-inspector-field";
    const tierText = document.createElement("span");
    tierText.textContent = "적재 층";
    const tierSel = document.createElement("select"); tierSel.className = "ui-field";
    tierSel.setAttribute("data-work-read", "");
    const initialTier = draft.tier ?? (active.id === "arm_b" ? "2" : "1");
    for (const [val, lbl] of [["1", "T1 (1층·벨트)"], ["2", "T2 (2층)"], ["3", "T3 (3층)"]] ) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = lbl;
      if (val === initialTier) opt.selected = true;
      tierSel.append(opt);
    }
    tierSel.addEventListener("change", () => draftChoices.set(active.id, { ...draftChoices.get(active.id), tier: tierSel.value }));
    tierField.append(tierText, tierSel);
    const dispField = document.createElement("label");
    dispField.className = "omx-inspector-field";
    const dispText = document.createElement("span");
    dispText.textContent = "복구 위치";
    const dispSel = document.createElement("select"); dispSel.className = "ui-field";
    dispSel.setAttribute("data-work-read", "");
    const initialDisp = draft.disp ?? "";
    for (const [val, lbl] of [["", "정위치 (Nominal)"], ["auto", "Auto ROI 감지"], ["belt_far", "Belt-Far 복구"], ["floor_front", "Floor-Front 복구"]]) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = lbl;
      if (val === initialDisp) opt.selected = true;
      dispSel.append(opt);
    }
    dispSel.addEventListener("change", () => draftChoices.set(active.id, { ...draftChoices.get(active.id), disp: dispSel.value }));
    dispField.append(dispText, dispSel);
    const runCustomBtn = document.createElement("ui-button");
    runCustomBtn.setAttribute("kind", "primary");
    runCustomBtn.setAttribute("type", "button");
    runCustomBtn.setAttribute("data-work-read", "");
    const targetArm = active.id.startsWith("arm_") ? active.id : (active.id === "cell_ab" ? "arm_a" : "arm_s");
    const targetCell = targetArm === "arm_s" ? "cell_s" : "cell_ab";
    runCustomBtn.textContent = `${targetArm} 맞춤 실행`;
    runCustomBtn.addEventListener("click", async () => {
      if (auth.locked || runCustomBtn.hasAttribute("disabled")) return;
      setOffBy(runCustomBtn, "요청 처리 중");
      const orig = runCustomBtn.textContent;
      runCustomBtn.textContent = "등록 중…";
      try {
        await call("/api/fleet/pipeline/cell-tasks", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            cell_id: targetCell,
            arm_id: targetArm,
            tier: Number(tierSel.value || 1),
            displaced_to: dispSel.value || null,
            robot_id: active.robot_id || undefined,  // absent: the server picks, the console never guesses
          }),
        });
        await refresh();
      } catch (err) {
        patchText(hint, `맞춤 실행 실패: ${err.message}`);
        patchHidden(hint, false);
      } finally {
        runCustomBtn.textContent = orig;
        setOffBy(runCustomBtn, "");
      }
    });
    quickDispatchBar.append(tierField, dispField, runCustomBtn);

    const actions = document.createElement("div");
    actions.className = "omx-card-actions";
    for (const choice of [...(active.buttons || []), ...(active.quickControls || [])]) {
      const button = document.createElement("ui-button");
      button.setAttribute("kind", "quiet");
      button.setAttribute("type", "button");
      button.setAttribute("data-work-read", "");
      button.textContent = choice.label;
      markNoRobot(button, choice, active);
      button.addEventListener("click", () => executeChoice(choice, active, button));
      actions.append(button);
    }

    const disclosure = document.createElement("details");
    disclosure.className = "omx-pipeline-disclosure";
    disclosure.open = inspectorOpen;
    const summary = document.createElement("summary");
    summary.textContent = `셀 파이프라인 제어 · ${active.title || active.id} (${active.text || "대기 중"})`;
    disclosure.addEventListener("toggle", () => {
      inspectorOpen = disclosure.open;
      frames.setRunning(!document.hidden && liveStreamOn && inspectorOpen && owns("drive"));
    });
    disclosure.append(summary, tabs, head, camStageNode, pipGrid, meta, quickDispatchBar, actions);
    inspector.replaceChildren(disclosure);
    if (framesOn && inspectorOpen) for (const binding of cameraBindings) frames.bind(...binding);
  }

  function show(rows, note) {
    lastRows = rows;
    renderInspector(rows);
    const listSig = JSON.stringify([rows?.bays || [], rows?.cells || [], rows?.actions || []]);
    if (listSig !== lastListSig) {
      lastListSig = listSig;
      const items = [];
      for (const b of rows?.bays || []) {
        const li = document.createElement("li");
        li.append(`${b.id} `, uiTag(b.text, b.status));
        items.push(li);
      }
      for (const c of rows?.cells || []) {
        const li = document.createElement("li");
        li.append(`${c.id} `, uiTag(c.text, c.status));
        items.push(li);
      }
      for (const a of rows?.actions || []) {
        const li = document.createElement("li");
        li.textContent = `${a.robot}: ${a.text}`;
        items.push(li);
      }
      list.replaceChildren(...items);
    }
    patchText(hint, note);
    patchHidden(hint, !note);
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable || auth.locked || document.hidden || !owns("drive")) return;
    inFlight = true;
    try {
      const plan = await call("/api/fleet/charge-bays", { signals: [life.signal] });
      life.check();
      const rows = chargeBayRows(plan);
      patchText(state, `칸 ${rows.bays.length}`);
      show(rows, rows.bays.length ? rows.summary : "활성 지도에 충전 칸(charge)이 없습니다");
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
      patchText(state, "—");
      show(null, error.code === "NO_ACTIVE_MAP" ? "활성 지도가 없습니다" : "충전 칸 계획을 읽지 못했습니다");
    } finally {
      inFlight = false;
    }
  }

  return { refresh };
}
