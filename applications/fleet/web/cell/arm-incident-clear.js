// The clear step of one open arm incident, shared by the alert drawer (queues.js rows) and the ARM-CELL context panel.
// Clearing stays a named operator's action through the existing clear POST; the server keeps every check.
import { html, useState } from "/common/vendor/htm-preact.esm.min.js";
import { UiButton } from "/common/preact-ui.js";
import { INCIDENT_CAUSES, INCIDENT_BASES } from "/console/assets/cell-frames.js";
import { OBS_BASE, isHomeRecovery } from "/console/assets/cell-obs-model.js";

// The person-check items the cell wrote into its own hold reason ("a person checks the arm (jaws, contacts, …)").
const CHECK_WORDS = { jaws: "집게", contacts: "닿은 곳", "wedged objects": "끼인 물체" };
const DEFAULT_CHECKS = ["팔과 집게", "이동 경로에 걸린 물체"];
const FOLD_FIRST = /guarded fold required|arm extended/i;
const CHECK_FIRST_REASON = "확인 항목을 직접 확인하고 체크하세요.";

/** Pure: "next_step" when the arm needs a physical recovery first (no clear button, only that step);
 * "clear" with the incident's own person-check list and a note prefilled from it. */
export function armIncidentClearPlan(incident) {
  const reason = typeof incident?.decision?.reason === "string" ? incident.decision.reason : "";
  if (isHomeRecovery(incident)) {
    return { mode: "next_step", step: "USB가 끊겨 팔이 홈 밖에 있습니다. 셀 화면의 미해결 복구에서 자동 폴드로 팔을 홈에 접으세요. 접기가 확인되면 보류가 풀립니다." };
  }
  if (FOLD_FIRST.test(reason)) {
    return { mode: "next_step", step: "팔을 뻗은 채 토크가 꺼졌습니다. 셀 화면의 미해결 복구에서 가드 홈 복귀로 팔을 먼저 접으세요. 해제는 접은 다음입니다." };
  }
  const listed = /a person checks the arm \(([^)]+)\)/i.exec(reason);
  const checks = listed
    ? listed[1].split(",").map((word) => word.trim()).filter(Boolean).map((word) => CHECK_WORDS[word.toLowerCase()] || word)
    : DEFAULT_CHECKS;
  return { mode: "clear", checks, note: `현장 확인: ${checks.join(", ")} 이상 없음` };
}

export const armIncidentKey = (sourceId, incidentId) => `${sourceId}|arm-incident-${incidentId}`;

const CELL_ARMS = { cell_s: ["arm_s"], cell_ab: ["arm_a", "arm_b"] };
export const cellArms = (target) => CELL_ARMS[target] || [target];
const PIPELINE_STATUS = "/api/fleet/pipeline/status";
const ARM_HOLDS_CLEAR = "/api/fleet/pipeline/arm-holds/clear";
const HOLD_STEPS = {
  STAGED_HOMING_VISUAL_VERIFY_REQUIRED: "팔 보류는 단계별 홈 복귀의 카메라 접힘 확인이 끝나야 풀립니다. 셀 화면의 미해결 복구에서 카메라 확인을 마치세요.",
  NAMED_OPERATOR_REQUIRED: "팔 보류는 이름 있는 운영자만 풀 수 있습니다. 이름 있는 계정으로 다시 해제하세요.",
};

/** The drawer row of the first open incident on a cell's or an arm's arms (held first), or null. */
export function armIncidentRowFor(target, obs) {
  const arms = cellArms(target);
  const rows = armIncidentAlertRows(obs);
  return [...rows.crit, ...rows.warn].find((row) => arms.includes(row.arm.id)) || null;
}

/** The Fleet pipeline hold on one arm, cleared with the caller's note only when the server says it is held.
 * {} when there is none, {holdCleared} when cleared, {nextStep} when the server keeps it (its rules are unchanged). */
export async function clearPipelineArmHold(call, armId, payload) {
  let held;
  try {
    held = (await call(PIPELINE_STATUS, { timeoutMs: 3000 }))?.arm_holds?.[armId]?.held === true;
  } catch (err) {
    if (err?.status === 404) return {};  // no pipeline on this Fleet: no hold to clear
    return { nextStep: "팔 보류 상태를 읽지 못했습니다. 연결을 확인하고 다시 해제하세요." };
  }
  if (!held) return {};
  try {
    await call(ARM_HOLDS_CLEAR, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ arm_id: armId, ...payload }), timeoutMs: 3000 });
    return { holdCleared: true };
  } catch (err) {
    return { nextStep: HOLD_STEPS[err?.code] || `팔 보류를 풀지 못했습니다(${err?.code || err?.status || "오류"}). 셀 화면에서 팔 홀드를 확인하세요.` };
  }
}

/** One confirm with one note, cause and basis: the arm's Fleet pipeline hold first (the server clears that arm's held
 * incidents with it), then this incident. A hold the server keeps clears nothing, so the row stays with its next step. */
export async function clearArmIncident(call, arm, incident, payload) {
  // The hold clear releases every held incident of this arm, so one that needs a physical step first blocks it all.
  const blocker = [...(arm.openIncidents || []), ...(arm.homeRecoveries || [])]
    .map(armIncidentClearPlan).find((plan) => plan.mode === "next_step");
  if (blocker) return { nextStep: `같은 팔의 다른 사건이 먼저입니다. ${blocker.step}` };
  const hold = await clearPipelineArmHold(call, arm.id, payload);
  if (hold.nextStep) return hold;
  try {
    await call(`${OBS_BASE}/arms/${encodeURIComponent(arm.sourceId)}/incidents/${encodeURIComponent(incident.incident_id)}/clear`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), timeoutMs: 3000 });
  } catch (err) {
    if (!(hold.holdCleared && err?.status === 409)) throw err;  // already cleared by the hold clear
  }
  return hold;
}

/** Pure: the alert drawer's rows, {crit, warn}; one D-540 3 decision row per open arm incident. */
export function armIncidentAlertRows(obs) {
  const rows = { crit: [], warn: [] };
  for (const arm of obs?.arms || []) {
    for (const incident of [...(arm.openIncidents || []), ...(arm.homeRecoveries || [])]) {
      if (!incident?.incident_id) continue;
      const held = !isHomeRecovery(incident) && incident.decision?.hold !== false;
      const text = isHomeRecovery(incident) ? ": 홈 복구 대기 — 자동 폴드 필요"
        : held ? ": 팔 보류 — 사람 확인 후 해제해야 작업이 시작됩니다" : ": 팔 정지 원인 기록 대기";
      rows[held ? "crit" : "warn"].push({ severity: held ? "crit" : "warn", decision: "arm-incident", robotId: arm.label,
        key: armIncidentKey(arm.sourceId, incident.incident_id), text, arm, incident });
    }
  }
  return rows;
}

export function IncidentClearBody({ arm, incident, clearReason, onClearIncident }) {
  const plan = armIncidentClearPlan(incident);
  const [checked, setChecked] = useState(false);
  const [cause, setCause] = useState(INCIDENT_CAUSES[0][0]);
  const [basis, setBasis] = useState(INCIDENT_BASES[0][0]);
  const [note, setNote] = useState(plan.note || "");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const detailHref = `/console/cell?focus=arm:${encodeURIComponent(arm.sourceId)}#observation-heading`;

  if (plan.mode === "next_step") {
    return html`<div class="cell-context-clear" data-arm-incident-step="">
      <p><strong>다음 단계</strong> · ${plan.step}</p>
      <a class="ui-action-link" data-kind="primary" href=${detailHref}>셀 화면에서 복구 열기</a>
    </div>`;
  }

  async function submitClear() {
    const text = note.trim();
    if (!checked) { setFeedback(CHECK_FIRST_REASON); return; }
    if (!text) { setFeedback("확인한 내용을 적어야 해제할 수 있습니다."); return; }
    setBusy(true);
    setFeedback("");
    try {
      const result = await onClearIncident(arm, incident, { note: text, cause, basis });
      setChecked(false);
      setFeedback(result?.nextStep ? `해제하지 않았습니다. 다음 단계 · ${result.nextStep}`
        : result?.holdCleared ? "해제했습니다. 팔 보류도 풀었습니다." : "해제했습니다.");
    } catch (err) {
      setFeedback(err?.status === 403 ? "이름 있는 운영자만 해제할 수 있습니다."
        : err?.status === 409 ? "이미 해제된 사건입니다."
        : "해제하지 못했습니다. 다시 시도하세요.");
    } finally {
      setBusy(false);
    }
  }

  const reasonText = busy ? "해제 요청을 처리하는 중입니다." : clearReason || (checked ? "" : CHECK_FIRST_REASON);
  return html`<div class="cell-context-clear" data-arm-incident-clear="">
    <label class="ui-check">
      <input type="checkbox" class="ui-field" checked=${checked} disabled=${Boolean(clearReason) || busy}
        onChange=${(e) => setChecked(e.target.checked)} />
      ${" "}현장에서 직접 확인했습니다: ${plan.checks.join(" · ")}
    </label>
    <input class="ui-field" type="text" maxLength=${400} value=${note} aria-label="확인한 내용"
      placeholder="팔과 집게를 확인한 내용 (필수)" onInput=${(e) => setNote(e.target.value)} />
    <details>
      <summary class="ui-disclosure-row">원인 기록 (선택)</summary>
      <select class="ui-field" aria-label="정지 원인" value=${cause} onChange=${(e) => setCause(e.target.value)}>
        ${INCIDENT_CAUSES.map(([v, label]) => html`<option key=${v} value=${v}>${label}</option>`)}
      </select>
      <select class="ui-field" aria-label="판단 근거" value=${basis} onChange=${(e) => setBasis(e.target.value)}>
        ${INCIDENT_BASES.map(([v, label]) => html`<option key=${v} value=${v}>${label}</option>`)}
      </select>
    </details>
    <${UiButton} kind="primary" type="button" disabled=${Boolean(reasonText)} reason=${reasonText}
      onClick=${submitClear}>확인했습니다 · 해제</${UiButton}>
    ${feedback ? html`<p class="hint" role="status">${feedback}</p>` : null}
  </div>`;
}
