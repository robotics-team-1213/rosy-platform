// D-941 5/7: the charge-bay plan remains display-only; task buttons use pipeline APIs.
import { isRouteAbsent } from "/console/assets/poll-gate.js";
import { chargeBayRows, inspectorTargetsFromRows } from "/console/assets/charge-bays-model.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";

export { chargeBayRows, inspectorTargetsFromRows, formatArmLiveJointText } from "/console/assets/charge-bays-model.js";

export function createChargeBaysView({ scope, el, call, auth, confirmedAction = null }) {
  const state = el("charge-bays-state");
  const list = el("charge-bay-rows");
  const hint = el("charge-bays-hint");
  const inspector = typeof el === "function" ? el("omx-right-inspector") : null;
  // 셀 카메라는 Vision 임대 프레임으로만 본다(D-136). Fleet은 바이트를 중계하지 않는다.
  const frames = createCellFrameFeed({ call, scope });
  for (const box of [list, inspector]) if (box) scope.listen(box, "click", () => { framesOn = true; }, true);
  let inFlight = false;
  let unavailable = false;
  let liveStreamOn = true;
  const selectedCamByCard = {};
  let activeInspectorId = null;
  // Choosing a robot only inspects it (no Vision lease); frames start after a click inside the cards or inspector.
  let framesOn = false;
  const selectedInspectorCam = {};
  let dualCamMode = false;
  let lastRows = null;

  scope.listen(document, "visibilitychange", () => {
    frames.setRunning(!document.hidden && liveStreamOn);
    if (!document.hidden) void refresh();
  });

  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("rosy:inspect-target", (ev) => {
      const targetId = ev?.detail?.targetId;
      const camId = ev?.detail?.camId;
      if (!targetId) return;
      activeInspectorId = targetId === "pinky" ? "rosy_46" : targetId;
      framesOn = false;
      if (camId) selectedInspectorCam[activeInspectorId] = camId;
      if (lastRows) renderInspector(lastRows);
      if (ev?.detail?.scroll && inspector?.scrollIntoView) {
        inspector.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  }

  function tag(text, status) {
    const t = document.createElement("ui-tag");
    t.setAttribute("status", status);
    t.textContent = text;
    return t;
  }

  async function executeChoice(choice, card, button, confirmed = false) {
    if (auth.locked || button.hasAttribute("disabled")) return;
    if (choice.cancelTaskId && !confirmed) {  // irreversible: the shared confirmation, or nothing (fail closed)
      if (!confirmedAction) return;
      return confirmedAction.run({message: `태스크(${choice.cancelTaskId})를 즉시 취소하고 셀 인터락을 해제할까요?`, opener: button,
        eligible: () => !auth.locked, request: () => executeChoice(choice, card, button, true)});
    }
    const origLabel = button.textContent;
    button.setAttribute("reason", "요청 처리 중");
    button.setAttribute("disabled", "");
    button.textContent = `${origLabel} (처리 중…)`;
    try {
      if (choice.cancelTaskId) {
        await call(`/api/fleet/pipeline/cell-tasks/${choice.cancelTaskId}/cancel`, {method: "POST"});
      } else if (choice.retryTaskId) {
        await call(`/api/fleet/pipeline/cell-tasks/${choice.retryTaskId}/retry`, {method: "POST"});
      } else if (choice.visionCheckCell) {
        await call("/api/fleet/pipeline/vision-auto-check", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({cell_id: choice.visionCheckCell, robot_id: card.robot_id || "rosy_46"}),
        });
      } else if (choice.cableGuardToggle) {
        await call("/api/fleet/pipeline/cable-guard", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({toggle: true, robot_id: card.robot_id || "rosy_46"}),
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
            robot_id: card.robot_id || "rosy_46",
          }),
        });
      } else if (choice.zoneId) {
        await call("/api/fleet/pipeline/station-zones/dispatch", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({zone_id: choice.zoneId, robot_id: card.robot_id || "rosy_46"}),
        });
      } else if (choice.decisionSubject) {
        await call("/api/fleet/pipeline/decision-gate", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({subject_id: choice.decisionSubject, auto_execute: true}),
        });
      } else {
        await call(choice.preset ? "/api/fleet/pipeline/cell-tasks" : "/api/fleet/pipeline/pinky-tasks", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify(choice.preset ? {preset: choice.preset} :
            {robot_id: card.robot_id || "rosy_46", action: choice.pinkyAction}),
        });
      }
      await refresh();
    } catch (error) {
      hint.textContent = `작업 요청 실패: ${error.message}`;
      hint.hidden = false;
    } finally {
      button.textContent = origLabel;
      button.removeAttribute("disabled");
      button.removeAttribute("reason");
    }
  }

  function renderInspector(rows) {
    if (!inspector) return;
    if (!rows?.cards?.length || !activeInspectorId) {
      inspector.replaceChildren();
      return;
    }
    const targets = inspectorTargetsFromRows(rows);
    const active = targets.find((t) => t.id === activeInspectorId) || targets[0];
    if (!active) return;

    const tabs = document.createElement("div");
    tabs.className = "omx-inspector-tabs";
    for (const t of targets) {
      const btn = document.createElement("ui-button");
      btn.setAttribute("kind", t.id === active.id ? "primary" : "quiet");
      btn.setAttribute("type", "button");
      btn.setAttribute("data-work-read", "");
      btn.dataset.inspectTarget = t.id;
      btn.textContent = t.shortTab;
      btn.addEventListener("click", () => {
        activeInspectorId = t.id;
        if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
          window.dispatchEvent(new CustomEvent("rosy:focus-anchor", { detail: { targetId: t.id, stationId: t.station_id || null } }));
        }
        renderInspector(rows);
      });
      tabs.append(btn);
    }
    const dualBtn = document.createElement("ui-button");
    dualBtn.setAttribute("kind", dualCamMode ? "primary" : "quiet");
    dualBtn.setAttribute("type", "button");
    dualBtn.setAttribute("data-work-read", "");
    dualBtn.dataset.dualCamToggle = "true";
    dualBtn.textContent = dualCamMode ? "📺 2채널(상단+손목) ON" : "📺 2채널 동시 보기";
    dualBtn.addEventListener("click", () => {
      dualCamMode = !dualCamMode;
      renderInspector(rows);
    });
    tabs.append(dualBtn);

    const head = document.createElement("div");
    head.className = "omx-inspector-head";
    const titleEl = document.createElement("strong");
    titleEl.textContent = active.title;
    head.append(titleEl, tag(active.text || "대기 중", active.status || "neutral"));

    const camViews = active.cameraViews || [];
    const activeCamId = selectedInspectorCam[active.id] || camViews[0]?.id || "arm_s_top";
    const activeCam = camViews.find((v) => v.id === activeCamId) || camViews[0]
      || {id: activeCamId, label: activeCamId, source: activeCamId};

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
        const dImg = document.createElement("img");
        dImg.className = "omx-inspector-main-cam omx-inspector-cam";
        dImg.alt = `${dv.label} 실시간 카메라`;
        dImg.loading = "lazy";
        const dCap = document.createElement("small");
        dCap.className = "omx-inspector-cam-badge";
        dCap.textContent = `🎥 ${dv.label}`;
        cameraBindings.push([dImg, dv, dCap, `🎥 ${dv.label}`]);
        pane.append(dImg, dCap);
        camStageNode.append(pane);
      }
    } else {
      camStageNode = document.createElement("div");
      camStageNode.className = "omx-inspector-single-wrap";
      const mainImg = document.createElement("img");
      mainImg.className = "omx-inspector-main-cam omx-inspector-cam";
      mainImg.alt = `${active.title} 실시간 메인 카메라`;
      mainImg.loading = "lazy";
      mainImg.tabIndex = 0;
      mainImg.addEventListener("click", () => mainImg.classList.toggle("focused"));
      const mainCap = document.createElement("small");
      mainCap.className = "omx-inspector-cam-badge";
      mainCap.textContent = `🎥 [${activeCam.label}]`;
      cameraBindings.push([mainImg, activeCam, mainCap, `🎥 [${activeCam.label}]`]);
      camStageNode.append(mainImg, mainCap);
    }

    const pipGrid = document.createElement("div");
    pipGrid.className = "omx-inspector-pip-grid";
    for (const v of camViews) {
      const pip = document.createElement("div");
      pip.className = `omx-inspector-pip${v.id === activeCam.id ? " active" : ""}`;
      const pImg = document.createElement("img");
      pImg.className = "omx-inspector-cam";
      pImg.alt = v.label;
      pImg.loading = "lazy";
      cameraBindings.push([pImg, v]);
      const pLbl = document.createElement("small");
      pLbl.textContent = `📷 ${v.label}`;
      pip.append(pImg, pLbl);
      pip.addEventListener("click", () => {
        selectedInspectorCam[active.id] = v.id;
        renderInspector(rows);
      });
      pipGrid.append(pip);
    }

    const meta = document.createElement("p");
    meta.className = "omx-inspector-meta";
    const taskBase = active.task ? `${active.task.task_id} · ${active.task.status} · ${active.task.arm_id || "—"}` : "";
    meta.textContent = [taskBase, active.jointLiveText || active.healthText || ""].filter(Boolean).join(" | ");

    const quickDispatchBar = document.createElement("div");
    quickDispatchBar.className = "omx-inspector-quick-dispatch";
    const tierSel = document.createElement("select"); tierSel.className = "ui-field";
    tierSel.setAttribute("data-work-read", "");
    for (const [val, lbl] of [["1", "T1 (1층·벨트)"], ["2", "T2 (2층)"], ["3", "T3 (3층)"]]) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = lbl;
      if (active.id === "arm_b" && val === "2") opt.selected = true;
      tierSel.append(opt);
    }
    const dispSel = document.createElement("select"); dispSel.className = "ui-field";
    dispSel.setAttribute("data-work-read", "");
    for (const [val, lbl] of [["", "정위치 (Nominal)"], ["auto", "Auto ROI 감지"], ["belt_far", "Belt-Far 복구"], ["floor_front", "Floor-Front 복구"]]) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = lbl;
      dispSel.append(opt);
    }
    const runCustomBtn = document.createElement("ui-button");
    runCustomBtn.setAttribute("kind", "primary");
    runCustomBtn.setAttribute("type", "button");
    runCustomBtn.setAttribute("data-work-read", "");
    const targetArm = active.id.startsWith("arm_") ? active.id : (active.id === "cell_ab" ? "arm_a" : "arm_s");
    const targetCell = targetArm === "arm_s" ? "cell_s" : "cell_ab";
    runCustomBtn.textContent = `▶ ${targetArm} 맞춤 실행`;
    runCustomBtn.addEventListener("click", async () => {
      if (auth.locked || runCustomBtn.hasAttribute("disabled")) return;
      runCustomBtn.setAttribute("reason", "요청 처리 중");
      runCustomBtn.setAttribute("disabled", "");
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
            robot_id: active.robot_id || "rosy_46",
          }),
        });
        await refresh();
      } catch (err) {
        hint.textContent = `맞춤 실행 실패: ${err.message}`;
        hint.hidden = false;
      } finally {
        runCustomBtn.textContent = orig;
        runCustomBtn.removeAttribute("disabled");
        runCustomBtn.removeAttribute("reason");
      }
    });
    quickDispatchBar.append(tierSel, dispSel, runCustomBtn);

    const actions = document.createElement("div");
    actions.className = "omx-card-actions";
    for (const choice of [...(active.buttons || []), ...(active.quickControls || [])]) {
      const button = document.createElement("ui-button");
      button.setAttribute("kind", choice.cancelTaskId ? "irreversible" : "quiet");
      button.setAttribute("type", "button");
      button.setAttribute("data-work-read", "");
      button.textContent = choice.label;
      button.addEventListener("click", () => executeChoice(choice, active, button));
      actions.append(button);
    }

    inspector.replaceChildren(tabs, head, camStageNode, pipGrid, meta, quickDispatchBar, actions);
    if (framesOn) for (const binding of cameraBindings) frames.bind(...binding);
  }

  function show(rows, note) {
    lastRows = rows;
    renderInspector(rows);
    list.replaceChildren();
    const cellItems = new Map();
    const robotItems = new Map();
    for (const b of rows?.bays || []) {
      const li = document.createElement("li");
      li.append(`${b.id} `, tag(b.text, b.status));
      list.append(li);
    }
    for (const c of rows?.cells || []) {
      const li = document.createElement("li");
      li.append(`${c.id} `, tag(c.text, c.status));
      list.append(li);
      cellItems.set(c.id, li);
    }
    for (const a of rows?.actions || []) {
      const li = document.createElement("li");
      li.textContent = `${a.robot}: ${a.text}`;
      list.append(li);
      robotItems.set(a.robot, li);
    }
    for (const card of rows?.cards || []) {
      const li = (card.kind === "omx" ? cellItems : robotItems).get(card.id) || document.createElement("li");
      if (li.parentNode !== list) list.append(li);
      const article = document.createElement("article");
      article.className = "omx-dense-card";
      article.addEventListener("click", (ev) => {
        if (ev.target?.closest?.("ui-button, button, img")) return;
        activeInspectorId = card.id === "cell_s" ? "arm_s" : (card.id === "cell_ab" ? "arm_a" : card.id);
        renderInspector(rows);
        frames.bind(camera, activeCam);
      });
      const activeCamId = selectedCamByCard[card.id] || card.cameraViews?.[0]?.id;
      const activeCam = (card.cameraViews || []).find((v) => v.id === activeCamId)
        || (card.cameraViews || [])[0] || {id: card.id, label: card.title, roiTarget: card.id};
      const camera = document.createElement("img");
      camera.loading = "lazy";
      camera.className = "cell-cam-thumb";
      camera.alt = `${card.title} 카메라`;
      if (framesOn && (activeInspectorId === card.id ||
          (card.id === "cell_s" && activeInspectorId === "arm_s") ||
          (card.id === "cell_ab" && ["arm_a", "arm_b"].includes(activeInspectorId)))) {
        queueMicrotask(() => { if (camera.isConnected) frames.bind(camera, activeCam); });
      }
      camera.tabIndex = 0;
      camera.addEventListener("click", () => {
        camera.classList.toggle("focused");
        activeInspectorId = card.id === "cell_s" ? "arm_s" : (card.id === "cell_ab" ? "arm_a" : card.id);
        renderInspector(rows);
        frames.bind(camera, activeCam);
      });
      camera.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          camera.classList.toggle("focused");
        } else if (ev.key === "Escape") {
          camera.classList.remove("focused");
        }
      });
      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = card.title;
      const camBar = document.createElement("div");
      camBar.className = "omx-card-actions";
      for (const v of (card.cameraViews || [])) {
        const camBtn = document.createElement("ui-button");
        camBtn.setAttribute("kind", v.id === activeCamId ? "primary" : "quiet");
        camBtn.setAttribute("type", "button");
        camBtn.setAttribute("data-work-read", "");
        camBtn.textContent = `📷 ${v.label}`;
        camBtn.addEventListener("click", () => {
          selectedCamByCard[card.id] = v.id;
          if (camera.isConnected) frames.bind(camera, v);
          for (const ch of camBar.children || []) {
            if (!ch.dataset.streamToggle) {
              ch.setAttribute("kind", ch === camBtn ? "primary" : "quiet");
            }
          }
          const targetId = v.id.startsWith("arm_a") ? "arm_a"
            : v.id.startsWith("arm_b") ? "arm_b"
            : (v.id.startsWith("arm_s") || card.id === "cell_s") ? "arm_s"
            : card.id;
          activeInspectorId = targetId;
          selectedInspectorCam[targetId] = v.id;
          renderInspector(rows);
        });
        camBar.append(camBtn);
      }
      const streamBtn = document.createElement("ui-button");
      streamBtn.setAttribute("kind", "quiet");
      streamBtn.setAttribute("type", "button");
      streamBtn.setAttribute("data-work-read", "");
      streamBtn.dataset.streamToggle = "true";
      streamBtn.textContent = liveStreamOn ? "자동갱신 ON(2초)" : "자동갱신 일시정지";
      streamBtn.addEventListener("click", () => {
        liveStreamOn = !liveStreamOn;
        frames.setRunning(liveStreamOn);
        streamBtn.textContent = liveStreamOn ? "자동갱신 ON(2초)" : "자동갱신 일시정지";
      });
      camBar.append(streamBtn);
      const status = document.createElement("p");
      status.append(tag(card.text, card.status));
      const task = document.createElement("p");
      const taskBase = card.task ? `${card.task.task_id} · ${card.task.status} · ${card.task.arm_id || "—"}` : "";
      task.textContent = [taskBase, card.healthText || ""].filter(Boolean).join(" | ");
      const buttons = document.createElement("div");
      buttons.className = "omx-card-actions";
      for (const choice of [...(card.buttons || []), ...(card.quickControls || [])]) {
        const button = document.createElement("ui-button");
        button.setAttribute("kind", choice.cancelTaskId ? "irreversible" : "quiet");
        button.setAttribute("type", "button");
        button.setAttribute("data-work-read", "");
        button.textContent = choice.label;
        button.addEventListener("click", () => executeChoice(choice, card, button));
        buttons.append(button);
      }
      details.append(title, camBar, status, task, buttons);
      article.append(camera, details);
      li.append(article);
    }
    hint.textContent = note;
    hint.hidden = !note;
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable || auth.locked || document.hidden) return;
    inFlight = true;
    try {
      const plan = await call("/api/fleet/charge-bays", { signals: [life.signal] });
      life.check();
      const rows = chargeBayRows(plan);
      state.textContent = `칸 ${rows.bays.length}`;
      show(rows, rows.bays.length ? rows.summary : "활성 지도에 충전 칸(charge)이 없습니다");
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
      state.textContent = "—";
      show(null, error.code === "NO_ACTIVE_MAP" ? "활성 지도가 없습니다" : "충전 칸 계획을 읽지 못했습니다");
    } finally {
      inFlight = false;
    }
  }

  return { refresh };
}
