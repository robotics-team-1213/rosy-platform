// Shared pure-DOM OMX right inspector used by both Console charge-bays and Cell real2sim.
import { setOffBy } from "/common/cause-line.js";
import { node, uiTag } from "/common/control-dom.js";
import { buildCamRoiSvg } from "/console/assets/cell-cam-roi.js";

const TIER_CHOICES = [["1", "T1 (1층·벨트)"], ["2", "T2 (2층)"], ["3", "T3 (3층)"]];
const DISP_CHOICES = [["", "정위치 (Nominal)"], ["auto", "Auto ROI 감지"], ["belt_far", "Belt-Far 복구"], ["floor_front", "Floor-Front 복구"]];

/** Build a frame box with a permanent standby layer so paint() updates never re-create layout nodes. */
export function buildInspectorCamFrame(img, standbyText = "영상 확인 중", roiSvg = null) {
  const wrap = node("div", "", "omx-inspector-cam-frame");
  const standby = node("span", standbyText, "omx-inspector-cam-standby");
  standby.setAttribute("role", "status");
  wrap.append(img);
  if (roiSvg) wrap.append(roiSvg);
  wrap.append(standby);
  return wrap;
}

function buildSelectField(labelText, choices, selectedValue, onChange) {
  const field = node("label", "", "omx-inspector-field");
  field.append(node("span", labelText));
  const select = node("select");
  select.className = "ui-field";
  select.setAttribute("aria-label", labelText);
  select.setAttribute("data-work-read", "");
  for (const [val, lbl] of choices) {
    const opt = node("option", lbl);
    opt.value = val;
    if (val === selectedValue) opt.selected = true;
    select.append(opt);
  }
  select.addEventListener("change", () => onChange(select.value));
  field.append(select);
  return { field, select };
}

function buildTab(text, active, onClick) {
  const btn = node("ui-button", text);
  btn.setAttribute("kind", "segment");
  btn.setAttribute("type", "button");
  btn.setAttribute("data-work-read", "");
  btn.setAttribute("aria-pressed", String(active));
  btn.addEventListener("click", onClick);
  return btn;
}

/**
 * Render the OMX right inspector into `container`, mounting before binding Vision frames so
 * attached <img> elements never flash a detached standby state for 2 seconds.
 */
export function renderOmxInspector(container, {
  targets = [], activeId = null, dualCamMode = false, selectedCamByTarget = {}, draftChoices = new Map(),
  frames = null, framesActive = true, cameraRois = null, showRoi = true, standbyText = "영상 확인 중",
  tagText = null, tagStatus = "neutral", disclosure = null, runButtonLabel = null, quickDispatchReason = "",
  actionChoices = null, actionsClass = "omx-inspector-actions", onSelectTarget = () => {}, onToggleDual = () => {},
  onToggleRoi = null, onSelectCam = () => {}, onQuickDispatch = async () => {}, onRenderAction = null, onDisclosureToggle = null,
}) {
  if (!container || !targets.length) return;
  const active = targets.find((t) => t.id === activeId) || targets[0];
  const camViews = active.cameraViews || [];
  const activeCamId = selectedCamByTarget[active.id] || camViews[0]?.id || "arm_s_top";
  const activeCam = camViews.find((v) => v.id === activeCamId) || camViews[0]
    || { id: activeCamId, label: activeCamId, source: activeCamId };

  const tabs = node("div", "", "omx-inspector-tabs");
  for (const t of targets) {
    const isCurrent = t.id === active.id;
    const btn = buildTab(t.shortTab, isCurrent, () => onSelectTarget(t.id));
    btn.setAttribute("aria-selected", String(isCurrent));
    btn.dataset.inspectTarget = t.id;
    tabs.append(btn);
  }
  const dualBtn = buildTab(dualCamMode ? "2CH ON" : "2CH", dualCamMode, () => onToggleDual());
  dualBtn.dataset.dualCamToggle = "true";
  dualBtn.title = "상단+손목 2채널 동시 보기";
  tabs.append(dualBtn);
  if (onToggleRoi && cameraRois) {
    const roiBtn = buildTab(showRoi ? "ROI 표시" : "ROI 숨김", showRoi, () => onToggleRoi());
    roiBtn.dataset.roiToggle = "true";
    tabs.append(roiBtn);
  }

  const head = node("div", "", "omx-inspector-head");
  head.append(
    node("strong", active.title),
    tagText ? uiTag(tagText, tagStatus) : node("span", active.badge || "", "cell-visual-badge"),
  );

  const stage = node("div", "", "omx-inspector-stage");
  const cameraBindings = [];
  if (dualCamMode && camViews.length >= 2) {
    const dualGrid = node("div", "", "omx-inspector-dual-grid");
    const [idA, idB] = active.dualPair || [camViews[0].id, camViews[1].id];
    const viewA = camViews.find((v) => v.id === idA) || camViews[0];
    const viewB = camViews.find((v) => v.id === idB && v.id !== viewA.id) || camViews.find((v) => v.id !== viewA.id) || camViews[1];
    for (const dv of [viewA, viewB]) {
      const pane = node("div", "", "omx-inspector-dual-pane");
      const dImg = node("img", "", "omx-inspector-main-cam omx-inspector-cam");
      dImg.alt = `${dv.label} 실시간 카메라`;
      dImg.loading = "lazy";
      const dCap = node("small", `[${dv.label}]`, "omx-inspector-cam-badge");
      cameraBindings.push([dImg, dv, dCap, `[${dv.label}]`]);
      pane.append(buildInspectorCamFrame(dImg, standbyText, showRoi ? buildCamRoiSvg(dv, cameraRois) : null), dCap);
      dualGrid.append(pane);
    }
    stage.append(dualGrid);
  } else {
    const wrap = node("div", "", "omx-inspector-single-wrap");
    const mainImg = node("img", "", "omx-inspector-main-cam omx-inspector-cam");
    mainImg.alt = `${active.title} 실시간 메인 카메라`;
    mainImg.loading = "lazy";
    const stageBar = node("div", "", "omx-inspector-stage-bar");
    const mainCap = node("small", `[${activeCam.label}]`, "omx-inspector-cam-badge");
    const zoomBtn = node("ui-button", "크게 보기", "omx-inspector-zoom");
    zoomBtn.setAttribute("kind", "quiet");
    zoomBtn.setAttribute("type", "button");
    zoomBtn.setAttribute("data-work-read", "");
    zoomBtn.setAttribute("aria-expanded", "false");
    zoomBtn.setAttribute("aria-label", `${activeCam.label} 크게 보기`);
    const roiSvg = showRoi ? buildCamRoiSvg(activeCam, cameraRois) : null;
    const applyZoom = (zoomed) => {
      mainImg.classList.toggle("focused", zoomed);
      roiSvg?.setAttribute("preserveAspectRatio", zoomed ? "xMidYMid meet" : "xMidYMid slice");
      zoomBtn.setAttribute("aria-expanded", String(zoomed));
      zoomBtn.textContent = zoomed ? "원래 크기" : "크게 보기";
      zoomBtn.setAttribute("aria-label", `${activeCam.label} ${zoomed ? "원래 크기" : "크게 보기"}`);
    };
    zoomBtn.addEventListener("click", () => applyZoom(!mainImg.classList.contains("focused")));
    mainImg.addEventListener("click", () => applyZoom(!mainImg.classList.contains("focused")));
    stage.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && mainImg.classList.contains("focused")) {
        ev.stopPropagation();
        applyZoom(false);
        zoomBtn.focus?.();
      }
    });
    stageBar.append(mainCap, zoomBtn);
    cameraBindings.push([mainImg, activeCam, mainCap, `[${activeCam.label}]`]);
    wrap.append(buildInspectorCamFrame(mainImg, standbyText, roiSvg), stageBar);
    stage.append(wrap);
  }

  const pipGrid = node("div", "", "omx-inspector-pip-grid");
  for (const v of camViews) {
    const activeCamMatch = v.id === activeCam.id;
    const pip = node("button", "", `omx-inspector-pip${activeCamMatch ? " active" : ""}`);
    pip.type = "button";
    pip.setAttribute("data-work-read", "");
    pip.setAttribute("aria-pressed", String(activeCamMatch));
    pip.setAttribute("aria-label", `${v.label} 카메라 선택`);
    const pImg = node("img", "", "omx-inspector-cam");
    pImg.alt = "";
    pImg.setAttribute("aria-hidden", "true");
    pImg.loading = "lazy";
    cameraBindings.push([pImg, v]);
    pip.append(buildInspectorCamFrame(pImg, "대기"), node("small", v.label));
    pip.addEventListener("click", () => onSelectCam(active.id, v.id));
    pipGrid.append(pip);
  }
  stage.append(pipGrid);

  let detailNode;
  if (Array.isArray(active.telemetryRows) && active.telemetryRows.length) {
    detailNode = node("dl", "", "omx-inspector-readout");
    for (const [k, v] of active.telemetryRows) detailNode.append(node("dt", k), node("dd", v));
  } else {
    const taskBase = active.task ? `${active.task.task_id} · ${active.task.status} · ${active.task.arm_id || "—"}` : "";
    detailNode = node("p", [taskBase, active.jointLiveText || active.healthText || ""].filter(Boolean).join(" | "), "omx-inspector-meta");
  }

  const draft = draftChoices.get(active.id) || {};
  const saveDraft = (patch) => draftChoices.set(active.id, { ...draftChoices.get(active.id), ...patch });
  const tier = buildSelectField("적재 층", TIER_CHOICES, draft.tier ?? (active.id === "arm_b" ? "2" : "1"), (v) => saveDraft({ tier: v }));
  const disp = buildSelectField("복구 위치", DISP_CHOICES, draft.disp ?? "", (v) => saveDraft({ disp: v }));
  const targetArm = active.id.startsWith("arm_") ? active.id : (active.id === "cell_ab" ? "arm_a" : "arm_s");
  const targetCell = targetArm === "arm_s" ? "cell_s" : "cell_ab";
  const runBtn = node("ui-button", runButtonLabel || `${targetArm} 맞춤 실행`);
  runBtn.setAttribute("kind", "primary");
  runBtn.setAttribute("type", "button");
  runBtn.setAttribute("data-work-read", "");
  if (quickDispatchReason) setOffBy(runBtn, quickDispatchReason);
  runBtn.addEventListener("click", () => {
    if (runBtn.hasAttribute("disabled")) return;
    return onQuickDispatch({
      targetCell,
      targetArm,
      tier: Number(tier.select.value || 1),
      displacedTo: disp.select.value || null,
      robotId: active.robot_id || undefined,
      button: runBtn,
    });
  });
  const quickDispatchBar = node("div", "", "omx-inspector-quick-dispatch");
  quickDispatchBar.append(tier.field, disp.field, runBtn);

  const actions = node("div", "", actionsClass);
  const choices = actionChoices || active.buttons || [];
  for (const choice of choices) {
    const btn = node("ui-button", choice.label);
    btn.setAttribute("kind", "quiet");
    btn.setAttribute("type", "button");
    btn.setAttribute("data-work-read", "");
    onRenderAction?.(btn, choice, active);
    actions.append(btn);
  }

  const bindCameras = () => {
    if (!frames) return;
    for (const binding of cameraBindings) frames.bind(...binding);
  };

  if (disclosure) {
    const details = node("details", "", "omx-pipeline-disclosure");
    details.open = Boolean(disclosure.open);
    details.append(node("summary", disclosure.summaryText), tabs, head, stage, detailNode, quickDispatchBar, actions);
    details.addEventListener("toggle", () => onDisclosureToggle?.(details.open, bindCameras));
    container.replaceChildren(details);
    if (framesActive && details.open) bindCameras();
  } else {
    container.replaceChildren(tabs, head, stage, detailNode, quickDispatchBar, actions);
    if (framesActive) bindCameras();
  }
  return { bindCameras };
}
