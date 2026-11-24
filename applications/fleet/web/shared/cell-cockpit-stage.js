// D-960 / D-136 — ARM-CELL Primary Stage & shared Workcell Observation Normalizer.
// Fetches read-only /api/fleet/workcell-observations on both R and ARM-CELL and renders the primary
// workcell camera wall + 3-arm EICAS strip when this control unit owns arms without drive (!owns("drive") && owns("arms")).
// DOM construction is declarative htm/preact; only the host <section> is created imperatively.
import { html, render as renderDom, useLayoutEffect, useRef } from "/common/vendor/htm-preact.esm.min.js";
import { UiButton } from "/common/preact-ui.js";
import { patchHidden } from "/common/control-dom.js";
import { createMotorHealthState, renderMotorHealthSummary } from "/common/motor-health.js";
import { createCellContextPanel } from "/console/assets/cell-context-panel.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";
import {
  OBS_BASE,
  JOINT_SHORT,
  canonicalArmId,
  isArmAttentionOrLive,
  normalizeWorkcellObservations,
  obsSignature,
} from "/console/assets/cell-obs-model.js";
import { createPollGate } from "/console/assets/poll-gate.js";
import { owns } from "/console/assets/unit-scope.js";

export { isArmAttentionOrLive, canonicalArmId, normalizeWorkcellObservations };

/** One camera tile. frames.bind runs once per camera identity; the feed keeps painting between polls. */
function CameraTile({ cam, frames, liveOn, hidden }) {
  const imgRef = useRef(null);
  const statusRef = useRef(null);
  const standbyRef = useRef(null);
  useLayoutEffect(() => {
    frames.bind(imgRef.current, { source: cam.source_id }, statusRef.current, cam.label);
  }, [cam.source_id, cam.label, frames]);
  useLayoutEffect(() => {
    frames.repaint?.({ source: cam.source_id });
  }, [liveOn, cam.source_id, frames]);
  const toggleZoom = (ev) => {
    const img = imgRef.current;
    if (!img?.getAttribute("src")) return;
    ev.stopPropagation();
    img.classList.toggle("focused");
  };
  const onKeyDown = (ev) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      toggleZoom(ev);
    } else if (ev.key === "Escape") {
      imgRef.current?.classList.remove("focused");
    }
  };
  return html`<article class="cell-stage-cam" data-camera-source=${cam.source_id} hidden=${hidden} tabIndex=${0} onKeyDown=${onKeyDown}>
    <div class="cell-stage-cam-head">
      <strong>${cam.stream === "depth" ? `${cam.label} · 깊이` : cam.label}</strong>
      <small ref=${statusRef} class="omx-inspector-cam-badge" />
    </div>
    <div class="omx-inspector-cam-frame">
      <img ref=${imgRef} class="omx-inspector-main-cam omx-inspector-cam" alt=${`${cam.label} 실시간 카메라`}
        onClick=${toggleZoom} />
      <span ref=${standbyRef} class="omx-inspector-cam-standby" role="status" />
    </div>
  </article>`;
}

/** One arm card. mhState is created once per arm id by the stage and accepted again on every render. */
function ArmCard({ arm, selected, mhState, selection, receivedAtMs }) {
  const mhRef = useRef(null);
  useLayoutEffect(() => {
    mhState.accept(arm.motorHealth, { receivedAtMs });
    renderMotorHealthSummary(mhRef.current, mhState.read(Date.now()));
  });
  const badge = arm.held ? { status: "crit", text: `보류 ${arm.heldIncidents.length}건` }
    : arm.openIncidents.length ? { status: "warn", text: `사건 ${arm.openIncidents.length}건` }
    : arm.fresh ? { status: "active", text: "실시간" }
    : { status: "warn", text: "대기 · 만료" };
  return html`<button type="button" class=${`cell-stage-arm${selected ? " selected" : ""}`} data-arm-id=${arm.id}
    onClick=${() => selection?.set?.(arm.id, { source: "roster" })}>
    <div class="cell-stage-arm-head">
      <strong>${arm.label}</strong>
      <ui-tag status=${badge.status}>${badge.text}</ui-tag>
    </div>
    <p ref=${mhRef} />
    ${arm.jointsDeg && arm.jointsDeg.some((v) => v !== null)
      ? html`<dl class="cell-stage-joints-grid">
          ${JOINT_SHORT.map((name, idx) => {
            const deg = arm.jointsDeg[idx];
            return html`<div class="cell-stage-joint" key=${name}><dt>${name}</dt><dd>${deg === null ? "—" : `${deg.toFixed(1)}°`}</dd></div>`;
          })}
        </dl>`
      : html`<p class="cell-stage-joints">엔코더 최신 피드백 없음</p>`}
  </button>`;
}

export function createCellCockpitStage({
  scope,
  call,
  view,
  auth,
  selection,
  contextHost = null,
  isOperator = () => false,
  namedReason = () => "",
  onChanged,
  onVisionSample,
}) {
  const gate = createPollGate({ slowCodes: { WORKCELL_OBSERVATIONS_UNAVAILABLE: 30000 } });
  const camStates = new Map();
  let renderingStage = false;
  let notifyQueued = false;
  const frames = createCellFrameFeed({
    call,
    scope,
    intervalMs: 2000,
    onSourcesSample,
    onStateChange(_key, state) {
      if (!state || state.roiTarget) return;
      const prev = camStates.get(state.source);
      if (prev && prev.live === state.live && prev.hasFrame === state.hasFrame
          && prev.phase === state.phase && prev.kind === state.kind
          && (state.hasFrame || prev.label === state.label)) return;
      camStates.set(state.source, state);
      const obsCams = view.workcellObs?.cameras || [];
      const liveCount = obsCams.filter((c) => camStates.get(c.source_id)?.live).length;
      const checked = obsCams.some((c) => {
        const st = camStates.get(c.source_id);
        return st && st.kind !== "neutral";
      });
      const summaryChanged = view.cellLiveCamCount !== liveCount || Boolean(view.cellCamChecked) !== checked;
      view.cellLiveCamCount = liveCount;
      view.cellCamChecked = checked;
      if (state.kind === "neutral" && !prev) return;
      if (summaryChanged || prev?.live !== state.live || prev?.hasFrame !== state.hasFrame
          || prev?.phase !== state.phase || (!state.hasFrame && prev?.label !== state.label)) {
        if (renderingStage) {
          if (!notifyQueued) {
            notifyQueued = true;
            queueMicrotask(() => {
              notifyQueued = false;
              render();
              onChanged?.();
            });
          }
          return;
        }
        render();
        onChanged?.();
      }
    },
  });
  const section = document.createElement("section");
  section.className = "panel cell-cockpit-stage";
  section.id = "cell-cockpit-stage";
  section.setAttribute("aria-labelledby", "cell-stage-heading");
  section.hidden = true;

  // One motor-health state per arm id, kept across polls so evidence age is continuous.
  const mhStates = new Map();
  const mhStateFor = (id) => {
    let state = mhStates.get(id);
    if (!state) mhStates.set(id, (state = createMotorHealthState()));
    return state;
  };

  let areaHidden = false;
  let inFlight = false;
  let liveOn = true;
  let showAllCams = false;
  let showAllArms = false;
  let controlUnitFetched = false;
  let lastStageSig = "";
  let lastObsSig = "";
  let notifiedOnce = false;

  const isStageActive = () => !areaHidden && !owns("drive") && owns("arms");
  const isCamActive = (cam) => Boolean(camStates.get(cam.source_id)?.live || camStates.get(cam.source_id)?.hasFrame || cam.fresh);

  function onSourcesSample(sample) {
    if (!owns("drive") && owns("arms")) onVisionSample?.(sample);
  }

  async function clearIncident(sourceId, incidentId, payload) {
    await call(`${OBS_BASE}/arms/${encodeURIComponent(sourceId)}/incidents/${encodeURIComponent(incidentId)}/clear`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: 3000,
    });
    gate.reset();
    await refresh();
  }

  const contextPanel = contextHost ? createCellContextPanel({
    scope,
    call,
    view,
    auth,
    host: contextHost,
    isStageActive,
    isOperator,
    namedReason,
    onClearIncident: clearIncident,
  }) : null;

  const syncFeedState = () => {
    frames.setRunning(isStageActive() && !auth.locked && !document.hidden);
    frames.setPaused(!liveOn);
  };

  const onToggleLive = () => {
    liveOn = !liveOn;
    syncFeedState();
    render();
  };

  const offSel = selection?.subscribe?.(() => render());
  scope.onDispose?.(offSel);
  scope.onDispose?.(() => {
    lastStageSig = "";
    lastObsSig = "";
    renderDom(null, section);
  });
  scope.listen(document, "visibilitychange", syncFeedState);

  function render() {
    const show = isStageActive();
    patchHidden(section, !show);
    contextPanel?.render();
    syncFeedState();
    if (!show) {
      lastStageSig = "";
      return;
    }
    const obs = view.workcellObs;
    const cu = view.controlUnit;
    const sum = obs?.summary;
    const unitId = cu?.unit_id || "ARM-CELL";
    const parentText = cu?.parent ? `상위 관제: ${cu.parent}` : "독립 셀 관제";
    const revText = cu?.config_revision ? `구성 ${cu.config_revision}` : "";
    const camStat = sum
      ? (view.cellCamChecked ? `카메라 ${view.cellLiveCamCount ?? 0}/${sum.camsTotal} 실시간` : `카메라 ${sum.camsTotal}대`)
      : "";
    const statText = sum ? `팔 ${sum.armsFresh}/${sum.armsTotal} 실시간 · ${camStat}` : "관측 대기";
    let liveStatus = "neutral";
    let liveText = "수신 대기";
    if (sum?.armsTotal) {
      if (sum.heldCount > 0 || sum.faultArmCount > 0) {
        liveStatus = "crit";
        liveText = sum.heldCount ? `보류 ${sum.heldCount}건` : "고장 확인";
      } else if (sum.armsFresh > 0) {
        liveStatus = "active";
        liveText = `팔 ${sum.armsFresh}/${sum.armsTotal} 실시간`;
      } else {
        liveStatus = "warn";
        liveText = "피드백 대기";
      }
    }
    const cams = obs?.cameras || [];
    const activeCams = cams.filter(isCamActive);
    const hiddenCamCount = cams.length - activeCams.length;
    const camDiag = cams.map((c) => camStates.get(c.source_id)?.label).find(Boolean) || "영상 연결 확인 중";
    const arms = obs?.arms || [];
    const selectedId = selection?.get?.() ?? null;
    const alertArms = arms.filter((arm) => arm.held || arm.openIncidents.length > 0 || arm.hwFaultMotors > 0 || arm.motorHealth?.status === "fault");
    const activeArms = arms.filter((arm) => isArmAttentionOrLive(arm, selectedId));
    const idleArmCount = arms.length - activeArms.length;
    const visibleArms = showAllArms ? arms : activeArms;
    const stageSig = JSON.stringify([
      unitId, parentText, revText, statText, liveStatus, liveText,
      view.fleet?.name === "샘플 현장", liveOn, selectedId, Boolean(auth.locked),
      showAllCams, showAllArms, activeCams.map((c) => c.source_id), camDiag, obsSignature(obs),
    ]);
    if (stageSig === lastStageSig) return;
    lastStageSig = stageSig;
    renderingStage = true;
    try {
      renderDom(html`
        <div class="cell-stage-head">
          <div>
            <h2 id="cell-stage-heading">${unitId} 작업 셀 관제</h2>
            <p class="cell-stage-meta">${[parentText, revText, statText].filter(Boolean).join(" · ")}</p>
          </div>
          <div class="cell-stage-actions">
            <ui-tag class="cell-stage-sample-tag" status="warn" hidden=${view.fleet?.name !== "샘플 현장"}>샘플 데이터</ui-tag>
            <ui-tag status=${liveStatus}>${liveText}</ui-tag>
            <${UiButton} kind="segment" type="button" data-work-read="" aria-pressed=${liveOn ? "true" : "false"} onClick=${onToggleLive}
            >${liveOn ? "영상 일시정지" : "영상 다시 보기"}</${UiButton}>
            <a class="ui-action-link" data-kind="quiet" href="/console/cell">셀 작업 화면</a>
          </div>
        </div>
        ${alertArms.length
          ? html`<div class="cell-stage-alert" role="status">
              <p><strong>${alertArms.map((a) => a.label).join(", ")}</strong> · 확인이 필요한 정지·고장 상태입니다. 오른쪽 ‘셀 작업 · 열린 사건’에서 원인을 적고 해제하세요.</p>
              <a class="ui-action-link" data-kind="quiet" href=${`/console/cell?focus=arm:${encodeURIComponent(alertArms[0].sourceId)}#observation-heading`}>팔 관측 상세</a>
            </div>`
          : null}
        ${cams.length && (hiddenCamCount > 0 || showAllCams)
          ? html`<div class="cell-stage-cam-banner">
              <p class="hint">
                ${showAllCams
                  ? `전체 셀 카메라 ${cams.length}대 표시 중`
                  : `실시간 카메라 ${activeCams.length}/${cams.length}대${!activeCams.length ? ` · ${camDiag}` : ` · 대기 ${hiddenCamCount}대 숨김`}`}
              </p>
              <${UiButton} kind="quiet" type="button" data-work-read="" onClick=${() => { showAllCams = !showAllCams; render(); }}>
                ${showAllCams ? "실시간 카메라만 보기" : `대기 카메라 ${hiddenCamCount}대 보기`}
              </${UiButton}>
            </div>`
          : null}
        <div class="cell-stage-cameras" role="region" aria-label="셀 실시간 카메라">
          ${cams.length
            ? cams.map((cam) => html`<${CameraTile} key=${cam.source_id} cam=${cam} frames=${frames} liveOn=${liveOn} hidden=${!showAllCams && !isCamActive(cam)} />`)
            : html`<p class="hint">등록된 셀 카메라가 없습니다.</p>`}
        </div>
        ${arms.length && idleArmCount > 0
          ? html`<div class="cell-stage-standby">
              <p class="hint">
                ${showAllArms
                  ? `전체 팔 ${arms.length}대 표시 중`
                  : activeArms.length
                    ? `활성·주의 팔 ${activeArms.length}대 표시 · 대기 팔 ${idleArmCount}대 숨김`
                    : `활성·주의 팔 없음 · 대기 팔 ${idleArmCount}대`}
              </p>
              <${UiButton} kind="quiet" type="button" data-work-read="" onClick=${() => { showAllArms = !showAllArms; render(); }}>
                ${showAllArms ? "활성·주의 팔만 보기" : `대기 팔 ${idleArmCount}대 보기`}
              </${UiButton}>
            </div>`
          : null}
        <div class="cell-stage-arms" role="region" aria-label="셀 팔 상태 요약">
          ${arms.length
            ? visibleArms.map((arm) => html`<${ArmCard} key=${arm.id} arm=${arm} selected=${selectedId === arm.id} mhState=${mhStateFor(arm.id)} selection=${selection} receivedAtMs=${obs.receivedAtMs} />`)
            : html`<p class="hint">${auth.locked ? "접속 후 팔 관측을 표시합니다." : "관측 중인 팔이 없습니다."}</p>`}
        </div>
      `, section);
    } finally {
      renderingStage = false;
    }
  }

  async function refreshControlUnit(signal) {
    if (controlUnitFetched || owns("drive")) return;
    try {
      view.controlUnit = await call("/api/fleet/control-unit", { signal });
      controlUnitFetched = true;
    } catch (err) {
      if (err?.name !== "AbortError") view.controlUnit = view.controlUnit || null;
    }
  }

  async function refresh() {
    if (auth.locked || inFlight || !gate.due() || !owns("arms")) return;
    const life = scope.capture();
    inFlight = true;
    try {
      const [payload] = await Promise.all([
        call("/api/fleet/workcell-observations", { signal: life.signal }),
        refreshControlUnit(life.signal),
        isStageActive() ? frames.checkSources(life.signal) : Promise.resolve(),
        isStageActive() && contextPanel ? contextPanel.refresh(life.signal) : Promise.resolve(),
      ]);
      life.check();
      gate.ok();
      const nextObs = normalizeWorkcellObservations(payload, Date.now());
      view.workcellObs = nextObs;
      for (const arm of nextObs.arms) mhStateFor(arm.id).accept(arm.motorHealth, { receivedAtMs: nextObs.receivedAtMs });
      const nextSig = obsSignature(nextObs);
      if (!notifiedOnce || nextSig !== lastObsSig) {
        lastObsSig = nextSig;
        notifiedOnce = true;
        render();
        onChanged?.();
      }
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (typeof err?.status === "number") gate.fail(err.status, err.code);
      if (err?.status === 503 || err?.status === 404) {
        lastObsSig = "";
        notifiedOnce = false;
        view.workcellObs = null;
        render();
      }
    } finally {
      inFlight = false;
    }
  }

  return {
    element: section,
    refresh,
    render,
    setAreaHidden(nextHidden) {
      areaHidden = Boolean(nextHidden);
      render();
    },
    pause() {
      controlUnitFetched = false;
      lastObsSig = "";
      notifiedOnce = false;
      gate.reset();
      syncFeedState();
      contextPanel?.pause();
    },
  };
}
