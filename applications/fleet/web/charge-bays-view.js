// D-941 5/7: the charge-bay plan remains display-only; task buttons use pipeline APIs.
import { setOffBy } from "/common/cause-line.js";
import { patchHidden, patchText, uiTag } from "/common/control-dom.js";
import { isRouteAbsent } from "/console/assets/poll-gate.js";
import { owns } from "/console/assets/unit-scope.js";
import { randomUUID } from "/console/assets/uuid.js";
import { chargeBayRows, inspectorTargetsFromRows } from "/console/assets/charge-bays-model.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";
import { renderOmxInspector } from "/console/assets/omx-inspector.js";
import { armIncidentRowFor } from "/console/assets/arm-incident-clear.js";

export { chargeBayRows, inspectorTargetsFromRows, formatArmLiveJointText } from "/console/assets/charge-bays-model.js";

/** Choices that target a docked vehicle need the server's occupant; cell-wide emergency stops are always enabled. */
const needsRobot = (choice) => Boolean(choice.cableGuardToggle || choice.zoneId);
const needsConfirm = (choice) => !choice.humanSafetyCell && !choice.visionCheckCell && !choice.cableGuardToggle
  && !choice.armIncident && !choice.cancelTaskId;

export const armIncidentRowKey = (target, obs) => armIncidentRowFor(target, obs)?.key || null;

function markNoRobot(button, choice, card) {
  if (!needsRobot(choice) || card.robot_id) return;
  setOffBy(button, "대상 로봇 없음");
}

export function createChargeBaysView({ scope, el, call, auth, confirmedAction = null, selection = null, objectHighlight = null, namedReason = () => "", readWorkcellObs = null, openArmIncident = null }) {
  const opReason = () => (auth.locked ? "세션 잠김" : namedReason());
  const state = el("charge-bays-state");
  const list = el("charge-bay-rows");
  const hint = el("charge-bays-hint");
  const inspector = typeof el === "function" ? el("omx-right-inspector") : null;
  // 셀 카메라는 Vision 임대 프레임으로만 본다(D-136). Fleet은 바이트를 중계하지 않는다.
  const frames = createCellFrameFeed({ call, scope });
  let inFlight = false;
  let unavailable = false;
  const liveStreamOn = true;
  let inspectorOpen = false;
  let activeInspectorId = null;
  // Choosing a robot only inspects it (no Vision lease); frames start after a click inside the cards or inspector.
  let framesOn = false;
  let bindCurrentCameras = null;
  for (const box of [list, inspector]) if (box) scope.listen(box, "click", () => {
    const activating = !framesOn;
    framesOn = true;
    if (activating && inspectorOpen) bindCurrentCameras?.();
  }, true);
  const selectedInspectorCam = {};
  let dualCamMode = false;
  let showRoi = true, sitePointsCameras = null, cellObjects = null, selectedObjectRef = null, selectedObjectDest = null, objectBusy = false, objectStatusText = "", lastRows = null;
  let lastInspectorSig = "";
  let lastListSig = "";
  let unconfirmedStopWarning = "";
  let stopGen = 0;
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
  if (objectHighlight?.subscribe) scope.onDispose?.(objectHighlight.subscribe(() => { lastInspectorSig = ""; if (lastRows) renderInspector(lastRows); }));

  async function executeChoice(choice, card, button, confirmed = false) {
    if (auth.locked || button.hasAttribute("disabled")) return;
    if (needsRobot(choice) && !card.robot_id) return;  // no occupant from the server: never guess one
    if (choice.armIncident) {  // clearing lives in the alert drawer's shared row; a Fleet-only hold is cleared on the cell page
      const key = armIncidentRowKey(choice.armIncident, readWorkcellObs?.());
      if (!key || !openArmIncident?.(key)) location.assign("/console/cell#real2sim-heading");
      return;
    }
    if (choice.cancelTaskId && !confirmed) {  // irreversible: the shared confirmation, or nothing (fail closed)
      if (!confirmedAction) return;
      return confirmedAction.run({message: `태스크(${choice.cancelTaskId})를 즉시 취소하고 셀 인터락을 해제할까요?`, opener: button,
        eligible: () => !auth.locked, request: () => executeChoice(choice, card, button, true)});
    }
    if (needsConfirm(choice) && !confirmed) {
      if (!confirmedAction || opReason()) return;
      return confirmedAction.run({
        message: `${choice.label || choice.preset || choice.zoneId || "셀 작업"}을(를) 실행할까요?`,
        opener: button,
        eligible: () => !auth.locked && !opReason(),
        request: () => executeChoice(choice, card, button, true),
      });
    }
    const isStop = Boolean(choice.humanSafetyCell || choice.visionCheckCell);
    const myStopGen = isStop ? ++stopGen : 0;
    const origLabel = button.textContent;
    setOffBy(button, "요청 처리 중");
    button.textContent = `${origLabel} (처리 중…)`;
    let stopRes = null;
    try {
      if (choice.cancelTaskId) {
        await call(`/api/fleet/pipeline/cell-tasks/${choice.cancelTaskId}/cancel`, {method: "POST"});
      } else if (choice.retryTaskId) {
        await call(`/api/fleet/pipeline/cell-tasks/${choice.retryTaskId}/retry`, {method: "POST"});
      } else if (choice.visionCheckCell) {
        stopRes = await call("/api/fleet/pipeline/vision-auto-check", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            cell_id: choice.visionCheckCell,
            robot_id: card.robot_id || undefined,
            human_detected: true,
            intrusion_score: 1.0,
            evidence_source: "operator_camera_inspection",
          }),
        });
      } else if (choice.cableGuardToggle) {
        await call("/api/fleet/pipeline/cable-guard", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({toggle: true, robot_id: card.robot_id}),
        });
      } else if (choice.humanSafetyCell) {
        stopRes = await call("/api/fleet/pipeline/human-safety-gate", {
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
          method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": randomUUID()},
          body: JSON.stringify({preset: choice.preset, propose: false, ...(card.robot_id ? {robot_id: card.robot_id} : {})}),
        });
      }
      if (isStop && myStopGen === stopGen) {
        const unconfirmed = Array.isArray(stopRes?.unconfirmed_pinky_stops) ? stopRes.unconfirmed_pinky_stops : [];
        const stopConfirmed = stopRes?.stop_confirmed === true && stopRes?.ok !== false && unconfirmed.length === 0;
        if (!stopConfirmed) {
          unconfirmedStopWarning = `비상정지 경고(${choice.humanSafetyCell || choice.visionCheckCell}): 정지 미확인(${unconfirmed.join(", ") || "확인 필요"}) — 수동 확인 필요`;
        } else {
          unconfirmedStopWarning = "";
        }
      }
      await refresh();
      if (isStop && myStopGen === stopGen && unconfirmedStopWarning) {
        patchText(hint, unconfirmedStopWarning);
        patchHidden(hint, false);
      } else if (choice.requiresPresence) {
        patchText(hint, "ACT 정책 작업이 대기열에 등록되었습니다. 셀 워크스페이스(/console/cell#real2sim-heading)에서 이름 있는 운영자의 입회 표시(D-911)를 눌러 실행을 시작하세요.");
        patchHidden(hint, false);
      }
    } catch (error) {
      if (isStop && myStopGen === stopGen) {
        unconfirmedStopWarning = `비상정지 요청 실패 (정지 미확인 — 수동 확인 필요): ${error.message}`;
        patchText(hint, unconfirmedStopWarning);
        patchHidden(hint, false);
      } else {
        patchText(hint, `작업 요청 실패: ${error.message}`);
        patchHidden(hint, false);
      }
    } finally {
      button.textContent = origLabel;
      setOffBy(button, needsConfirm(choice) ? opReason() : "");
    }
  }

  function renderInspector(rows) {
    if (!inspector) return;
    // No choice yet still shows the first cell's tabs (frames stay off until a click, framesOn).
    if (!rows?.cards?.length) {
      lastInspectorSig = "";
      bindCurrentCameras = null;
      if (inspector.childElementCount) inspector.replaceChildren();
      return;
    }
    const targets = inspectorTargetsFromRows(rows, readWorkcellObs?.());
    const active = targets.find((t) => t.id === activeInspectorId) || targets[0];
    if (!active) return;

    const camViews = active.cameraViews || [];
    const activeCamId = selectedInspectorCam[active.id] || camViews[0]?.id || "arm_s_top";
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
      showRoi, Boolean(sitePointsCameras), cellObjects?.observed_at ?? null,
      Boolean(cellObjects?.fetchedAtMs && Date.now() - cellObjects.fetchedAtMs < 5000),
      selectedObjectRef, selectedObjectDest, objectBusy, objectStatusText,
      objectHighlight?.get?.() ?? null, opReason(),
    ]);
    if (nextSig === lastInspectorSig && inspector.firstElementChild) return;
    lastInspectorSig = nextSig;

    const rendered = renderOmxInspector(inspector, {
      targets, activeId: active.id, dualCamMode, selectedCamByTarget: selectedInspectorCam,
      draftChoices, frames, framesActive: framesOn && inspectorOpen,
      cameraRois: sitePointsCameras, showRoi, cellObjects, selectedObjectRef,
      aiHighlightRef: objectHighlight?.get?.() ?? null, selectedObjectDest, objectBusy, objectStatusText,
      standbyText: "영상 대기 · 클릭하여 연결",
      tagText: active.text || "대기 중",
      tagStatus: active.status || "neutral",
      quickDispatchReason: opReason(),
      actionsClass: "omx-card-actions",
      actionChoices: [...(active.buttons || []), ...(active.quickControls || [])],
      disclosure: {
        open: inspectorOpen,
        summaryText: `셀 파이프라인 제어 · ${active.title || active.id} (${active.text || "대기 중"})`,
      },
      onSelectTarget: (targetId) => {
        activeInspectorId = targetId;
        lastInspectorSig = "";
        selection?.set?.(targetId, { source: "inspector" });
        renderInspector(rows);
      },
      onToggleDual: () => {
        dualCamMode = !dualCamMode;
        lastInspectorSig = "";
        renderInspector(rows);
      },
      onToggleRoi: () => {
        showRoi = !showRoi;
        lastInspectorSig = "";
        renderInspector(rows);
      },
      onSelectCam: (targetId, camId) => {
        selectedInspectorCam[targetId] = camId;
        lastInspectorSig = "";
        renderInspector(rows);
      },
      onQuickDispatch: async ({ targetCell, targetArm, tier, displacedTo, robotId, button }) => {
        const reason = opReason();
        if (auth.locked || button.hasAttribute("disabled") || reason || !confirmedAction) return;
        return confirmedAction.run({
          message: `${targetArm} 맞춤 작업(${targetCell} · ${tier}층${displacedTo ? " · " + displacedTo : ""})을 대기열에 등록할까요?`,
          opener: button,
          eligible: () => !auth.locked && !opReason(),
          request: async () => {
            setOffBy(button, "요청 처리 중");
            const orig = button.textContent;
            button.textContent = "등록 중…";
            try {
              await call("/api/fleet/pipeline/cell-tasks", {
                method: "POST",
                headers: {"Content-Type": "application/json", "Idempotency-Key": randomUUID()},
                body: JSON.stringify({
                  cell_id: targetCell,
                  arm_id: targetArm,
                  tier,
                  displaced_to: displacedTo,
                  robot_id: robotId,
                  propose: false,
                }),
              });
              await refresh();
            } catch (err) {
              patchText(hint, `맞춤 실행 실패: ${err.message}`);
              patchHidden(hint, false);
            } finally {
              button.textContent = orig;
              setOffBy(button, opReason());
            }
          },
        });
      },
      onRenderAction: (button, choice, item) => {
        markNoRobot(button, choice, item);
        if (!button.hasAttribute("disabled") && needsConfirm(choice) && opReason()) setOffBy(button, opReason());
        button.addEventListener("click", () => executeChoice(choice, item, button));
      },
      onDisclosureToggle: (open, bindCameras) => { inspectorOpen = open; if (open) framesOn = true; frames.setRunning(!document.hidden && liveStreamOn && inspectorOpen && owns("drive")); if (open && framesOn) bindCameras?.(); },
      onSelectObject: (obj) => { selectedObjectRef = obj.object_ref; objectStatusText = ""; objectHighlight?.set?.(obj.object_ref, { source: "camera" }); lastInspectorSig = ""; renderInspector(rows); },
      onSelectObjectDest: (dst) => { selectedObjectDest = dst; },
      onClearObject: () => { selectedObjectRef = null; objectStatusText = ""; lastInspectorSig = ""; renderInspector(rows); },
      onDispatchTargetObject: async ({ object: obj, destSite, button, buildTaskBody }) => {
        if (auth.locked || opReason() || !confirmedAction) return;
        return confirmedAction.run({
          message: `선택 객체(${obj.catalog_id})를 ${destSite}로 1회 집기·놓기 실행할까요?`,
          opener: button,
          eligible: () => !auth.locked && !opReason(),
          request: async () => {
            objectBusy = true; objectStatusText = "1회 집기·놓기 작업 등록 중…"; lastInspectorSig = ""; renderInspector(rows);
            try {
              const res = await call("/api/fleet/pipeline/cell-tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
                body: JSON.stringify(buildTaskBody(active.robot_id)),
              });
              objectStatusText = `등록 완료: ${res.task?.task_id || "ok"} (${obj.catalog_id} → ${destSite})`; await refresh();
            } catch (err) {
              objectStatusText = `요청 거부: ${err.message}`;
            } finally {
              objectBusy = false; lastInspectorSig = ""; if (lastRows) renderInspector(lastRows);
            }
          },
        });
      },
    });
    bindCurrentCameras = rendered?.bindCameras || null;
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
    const displayNote = unconfirmedStopWarning || note;
    patchText(hint, displayNote);
    patchHidden(hint, !displayNote);
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable || auth.locked || document.hidden || !owns("drive")) return;
    inFlight = true;
    try {
      const [planRes, spRes, objRes] = await Promise.allSettled([
        call("/api/fleet/charge-bays", { signals: [life.signal] }),
        sitePointsCameras ? Promise.resolve(null) : call("/api/fleet/site-points?view=full", { signals: [life.signal] }),
        call("/api/fleet/pipeline/cell-objects", { signals: [life.signal] }),
      ]);
      if (spRes.status === "fulfilled" && spRes.value?.cameras) sitePointsCameras = spRes.value.cameras;
      if (objRes.status === "fulfilled" && objRes.value) cellObjects = { ...objRes.value, fetchedAtMs: Date.now() };
      if (planRes.status === "rejected") throw planRes.reason;
      const plan = planRes.value;
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
