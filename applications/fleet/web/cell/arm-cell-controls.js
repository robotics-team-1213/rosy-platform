// Direct ARM-CELL interactive object staging, camera overlay sync, and arm commands (/console & drawer).
import { setOffBy } from "/common/cause-line.js";
import { node } from "/common/control-dom.js";
import { OPERATOR_REASON } from "/console/assets/authorization.js";
import { randomUUID } from "/console/assets/uuid.js";
import { INCIDENT_CAUSES, INCIDENT_BASES } from "/console/assets/cell-frames.js";
import { armIncidentClearPlan, clearArmIncident } from "/console/assets/arm-incident-clear.js";
import { syncCamRoiOverlay } from "/console/assets/cell-cam-roi.js";
import { OBJECT_STALE_MS, syncCamObjectsOverlay } from "/console/assets/cell-cam-objects.js";
import { buildInspectorStagingBar } from "/console/assets/cell-pick-place-staging.js";

const ARM_PRESETS = {
  arm_s: [
    ["s3_shuttle", "S3 셔틀 (Pinky→Belt)"],
    ["s3_recover_belt_far", "Belt-Far 이탈 복구"],
    ["s3_recover_floor_front", "Floor-Front 바닥 복구"],
    ["s3_auto_recover_or_shuttle", "자동 감지·복구 셔틀"],
  ],
  arm_a: [["s5_tier1_arm_a", "S5 1층 적재 (arm_a)"], ["s5_tier3_arm_a", "S5 3층 적재 (arm_a)"]],
  arm_b: [["s5_tier2_arm_b", "S5 2층 적재 (arm_b)"]],
};

export function createCellObjectStager({
  scope, call, auth, objectHighlight = null, confirmedAction = null,
  isOperator = () => false, namedReason = () => "", log = null,
  onChange = () => {}, onDispatched = () => {},
}) {
  let selectedRef = null, selectedDest = null, busy = false, statusText = "";
  if (objectHighlight?.subscribe) scope?.onDispose?.(objectHighlight.subscribe(() => onChange()));
  const opReason = () => (auth?.locked ? "관제에 다시 접속하세요." : !isOperator() ? OPERATOR_REASON : namedReason() || "");

  return {
    sig(cellObjects) {
      const fresh = Boolean(cellObjects?.fetchedAtMs && (Date.now() - cellObjects.fetchedAtMs) <= OBJECT_STALE_MS);
      return [cellObjects?.observed_at ?? null, fresh, selectedRef, selectedDest, busy, statusText, objectHighlight?.get?.() ?? null, opReason()];
    },
    overlayOpts(cam, zoomed = false) {
      return {
        selectedRef,
        aiHighlightRef: objectHighlight?.get?.() ?? null,
        zoomed,
        onSelectObject: (obj) => {
          selectedRef = obj.object_ref;
          statusText = "";
          objectHighlight?.set?.(obj.object_ref, { source: "camera" });
          onChange();
        },
      };
    },
    renderStagingBar(hostEl, cams, cellObjects) {
      if (!hostEl) return;
      const list = (Array.isArray(cams) ? cams : [cams]).filter(Boolean);
      const bar = cellObjects && list.length ? buildInspectorStagingBar(list, cellObjects, {
        selectedRef, selectedDest, opReason: opReason(), busy, statusText,
        onSelectDest: (dst) => { selectedDest = dst; },
        onClear: () => { selectedRef = null; statusText = ""; onChange(); },
        onDispatch: async ({ object: obj, destSite, button, buildTaskBody }) => {
          if (opReason() || !confirmedAction) return;
          return confirmedAction.run({
            message: `선택 객체(${obj.catalog_id})를 ${destSite}로 1회 집기·놓기 실행할까요?`,
            opener: button,
            eligible: () => !opReason(),
            request: async () => {
              busy = true; statusText = "1회 집기·놓기 작업 등록 중…"; onChange();
              try {
                const res = await call("/api/fleet/pipeline/cell-tasks", {
                  method: "POST",
                  headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
                  body: JSON.stringify(buildTaskBody()),
                });
                statusText = `등록 완료: ${res.task?.task_id || "ok"} (${obj.catalog_id} → ${destSite})`;
                log?.(`ARM-CELL 1회 집기·놓기 등록: ${obj.catalog_id} → ${destSite}`, "good");
                onDispatched();
              } catch (err) {
                statusText = `요청 거부: ${err.message}`;
              } finally {
                busy = false; onChange();
              }
            },
          });
        },
      }) : null;
      hostEl.replaceChildren(...(bar ? [bar] : []));
    },
  };
}

export function createArmCommandSection({
  call, confirmedAction = null, isOperator = () => false, namedReason = () => "", log = null, onChanged = () => {},
}) {
  const box = node("div", "", "ui-control-stack");
  const statusEl = node("p", "", "hint");
  statusEl.setAttribute("role", "status");
  let busy = false, lastStatus = "", lastSig = "";

  const baseReason = () => (!isOperator() ? OPERATOR_REASON : namedReason() || (busy ? "요청 처리 중입니다." : ""));

  function sync(armId, obsArm) {
    const inc = obsArm?.openIncidents?.[0] || obsArm?.homeRecoveries?.[0] || null;
    const lock = baseReason();
    const sig = `${armId}|${lock}|${inc?.incident_id || ""}|${lastStatus}`;
    if (sig === lastSig && box.childElementCount) return box;
    lastSig = sig;
    statusEl.textContent = lastStatus;
    statusEl.className = "hint arm-cmd-status";
    const nodes = [];

    if (inc) {
      const plan = armIncidentClearPlan(inc);
      const wrap = node("div", "", "cell-context-clear arm-cmd-incident");
      const incHead = node("div", "", "arm-cmd-head");
      const incTag = node("ui-tag", "보류·사건");
      incTag.setAttribute("variant", "inline");
      incTag.setAttribute("status", "warn");
      incHead.append(node("strong", "열린 사건 · 보류 해제"), incTag);
      wrap.append(incHead);
      if (plan.mode === "next_step") {
        wrap.append(node("p", `다음 단계 · ${plan.step}`, "hint"));
      } else {
        const chkLab = node("label", "", "ui-check");
        const chk = document.createElement("input");
        chk.className = "ui-field";
        chk.type = "checkbox";
        chkLab.append(chk, ` 현장에서 직접 확인했습니다: ${plan.checks.join(" · ")}`);
        const noteIn = document.createElement("input");
        noteIn.className = "ui-field";
        noteIn.type = "text"; noteIn.value = plan.note || ""; noteIn.setAttribute("aria-label", "확인한 내용");
        const clrBtn = node("ui-button", "확인했습니다 · 보류 해제");
        clrBtn.setAttribute("kind", "primary"); clrBtn.setAttribute("type", "button");
        clrBtn.setAttribute("data-work-read", ""); clrBtn.setAttribute("data-arm-clear-incident", "true");
        const syncChk = () => setOffBy(clrBtn, lock || (!chk.checked ? "확인 항목을 직접 확인하고 체크하세요." : ""));
        syncChk();
        chk.addEventListener("change", syncChk);
        clrBtn.addEventListener("click", () => {
          const r = lock || (!chk.checked ? "확인 항목을 직접 확인하고 체크하세요." : !noteIn.value.trim() ? "확인한 내용을 적어야 해제할 수 있습니다." : "");
          if (r || !confirmedAction) return;
          void confirmedAction.run({
            message: `${armId} 팔의 보류·열린 사건을 해제할까요?`,
            opener: clrBtn,
            eligible: () => !baseReason() && chk.checked && Boolean(noteIn.value.trim()),
            request: async () => {
              busy = true; lastStatus = "보류 해제 중…"; lastSig = ""; sync(armId, obsArm);
              try {
                const res = await clearArmIncident(call, obsArm, inc, { note: noteIn.value.trim(), cause: INCIDENT_CAUSES[0][0], basis: INCIDENT_BASES[0][0] });
                lastStatus = res?.nextStep ? `해제 보류: ${res.nextStep}` : res?.holdCleared ? "팔 보류와 사건을 해제했습니다." : "사건을 해제했습니다.";
                log?.(`${armId} 보류·사건 해제 완료`, "good");
                onChanged();
              } catch (err) {
                lastStatus = `해제 실패: ${err.message}`;
              } finally { busy = false; lastSig = ""; sync(armId, obsArm); }
            },
          });
        });
        wrap.append(chkLab, noteIn, clrBtn);
      }
      nodes.push(wrap);
    }

    const row = node("div", "", "arm-cmd-presets");
    const presets = ARM_PRESETS[armId] || ARM_PRESETS.arm_a;
    for (const [idx, [preset, label]] of presets.entries()) {
      const btn = node("ui-button", label);
      btn.setAttribute("kind", "quiet");
      if (idx === 0) btn.setAttribute("kind", "primary");
      btn.setAttribute("type", "button");
      btn.setAttribute("data-work-read", ""); btn.setAttribute("data-arm-preset", preset);
      if (lock) setOffBy(btn, lock);
      btn.addEventListener("click", () => {
        if (baseReason() || !confirmedAction) return;
        void confirmedAction.run({
          message: `${armId} 팔에 '${label}' 작업을 실행할까요?`,
          opener: btn,
          eligible: () => !baseReason(),
          request: async () => {
            busy = true; lastStatus = `'${label}' 작업 등록 중…`; lastSig = ""; sync(armId, obsArm);
            try {
              const res = await call("/api/fleet/pipeline/cell-tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
                body: JSON.stringify({ cell_id: armId === "arm_s" ? "cell_s" : "cell_ab", arm_id: armId, preset, propose: false }),
              });
              lastStatus = `등록 완료: ${res.task?.task_id || "ok"} (${label})`;
              log?.(`${armId} 작업 등록: ${label}`, "good");
              onChanged();
            } catch (err) {
              lastStatus = `작업 등록 거부: ${err.message}`;
            } finally { busy = false; lastSig = ""; sync(armId, obsArm); }
          },
        });
      });
      row.append(btn);
    }
    nodes.push(row);
    if (lastStatus) nodes.push(statusEl);
    const links = node("div", "", "arm-cmd-links");
    const obsLink = node("a", "팔 관측·사건 보기", "ui-action-link");
    obsLink.dataset.kind = "quiet";
    obsLink.href = obsArm?.sourceId ? `/console/cell?focus=arm:${encodeURIComponent(obsArm.sourceId)}#observation-heading` : "/console/cell#observation-heading";
    const workLink = node("a", "팔레트 적재 화면 열기", "ui-action-link");
    workLink.dataset.kind = "quiet"; workLink.href = "/console/cell";
    links.append(obsLink, workLink);
    nodes.push(links);
    box.replaceChildren(...nodes);
    return box;
  }

  return { element: box, sync };
}

export function syncArmCameraOverlay(frameEl, stagingHostEl, camView, sitePointsCameras, cellObjects, stager) {
  syncCamRoiOverlay(frameEl, camView, sitePointsCameras, true, false);
  syncCamObjectsOverlay(frameEl, camView, cellObjects, stager ? stager.overlayOpts(camView, false) : {});
  stager?.renderStagingBar(stagingHostEl, camView ? [camView] : [], cellObjects);
}
