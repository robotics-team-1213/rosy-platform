// ARM-CELL /console right-hand context panel: inline open-incident clearance, active cell work, and links.
import { html, render as renderDom, useState } from "/common/vendor/htm-preact.esm.min.js";
import { UiButton } from "/common/preact-ui.js";
import { patchHidden } from "/common/control-dom.js";
import { INCIDENT_CAUSES, INCIDENT_BASES } from "/console/assets/cell-frames.js";
import { OPERATOR_REASON } from "/console/assets/authorization.js";
import { createPollGate } from "/console/assets/poll-gate.js";
import { isHomeRecovery } from "/console/assets/cell-obs-model.js";

const WORK_REFRESH_MS = 5000;
const ENDED_WORK_STATES = new Set(["COMPLETED", "FAILED", "CANCELED", "EXPIRED", "CLOSED"]);
const CELL_WORK_SOURCES = new Set(["cell_job", "mission"]);
const WORK_STATUS_LABELS = {
  REQUESTED: "요청 접수",
  UNKNOWN: "결과 미확인",
  PROPOSED: "승인 대기",
  READY: "실행 준비",
  QUEUED: "대기",
  DISPATCHING: "전달 중",
  ACCEPTED: "장치 수락",
  RUNNING: "실행 중",
  ACTION_SUCCEEDED: "동작 완료",
  GOAL_CONFIRMED: "확인 완료",
  HOLD: "보류",
  CLAIMED: "확인 중",
};
const workStatusLabel = (status) => WORK_STATUS_LABELS[status] || "진행 중";

export function activeCellWorkRows(rows) {
  return (Array.isArray(rows) ? rows : []).filter((row) => (
    row
    && CELL_WORK_SOURCES.has(row.source)
    && row.visible_state !== "ended"
    && !ENDED_WORK_STATES.has(row.status)
  ));
}

function IncidentClearForm({ arm, incident, clearReason, onClearIncident }) {
  const [expanded, setExpanded] = useState(false);
  const [cause, setCause] = useState(INCIDENT_CAUSES[0][0]);
  const [basis, setBasis] = useState(INCIDENT_BASES[0][0]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");

  async function submitClear() {
    const text = note.trim();
    if (!text) {
      setFeedback("확인한 내용을 적어야 해제할 수 있습니다.");
      return;
    }
    setBusy(true);
    setFeedback("");
    try {
      await onClearIncident(arm.sourceId, incident.incident_id, { note: text, cause, basis });
      setNote("");
      setExpanded(false);
      setFeedback("해제했습니다.");
    } catch (err) {
      setFeedback(err?.status === 403 ? "이름 있는 운영자만 해제할 수 있습니다."
        : err?.status === 409 ? "이미 해제된 사건입니다."
        : "해제하지 못했습니다. 다시 시도하세요.");
    } finally {
      setBusy(false);
    }
  }

  const reasonText = busy ? "해제 요청을 처리하는 중입니다." : clearReason;
  const summaryText = typeof incident?.decision?.reason === "string"
    ? incident.decision.reason
    : "사람 확인이 필요한 팔 정지 사건입니다.";
  return html`<li class="cell-context-item" data-incident-id=${incident.incident_id}>
    <div class="cell-context-item-head">
      <strong>${arm.label}</strong>
      <ui-tag status=${!isHomeRecovery(incident) && incident?.decision?.hold !== false ? "crit" : "warn"}>
        ${isHomeRecovery(incident) ? "홈 복구 대기" : incident?.decision?.hold !== false ? "보류 · 해제 필요" : "원인 기록 대기"}
      </ui-tag>
    </div>
    <p class="cell-context-reason">${summaryText}</p>
    <div class="cell-context-item-actions">
      <${UiButton} kind="quiet" type="button" data-work-read="" aria-expanded=${expanded ? "true" : "false"}
        onClick=${() => setExpanded((prev) => !prev)}>${expanded ? "해제 접기" : "원인 적고 해제"}</${UiButton}>
      <a class="ui-action-link" data-kind="quiet" href=${`/console/cell?focus=arm:${encodeURIComponent(arm.sourceId)}#observation-heading`}>상세</a>
    </div>
    ${expanded ? html`<div class="cell-context-clear">
      <select class="ui-field" aria-label="정지 원인" value=${cause} onChange=${(e) => setCause(e.target.value)}>
        ${INCIDENT_CAUSES.map(([v, label]) => html`<option key=${v} value=${v}>${label}</option>`)}
      </select>
      <select class="ui-field" aria-label="판단 근거" value=${basis} onChange=${(e) => setBasis(e.target.value)}>
        ${INCIDENT_BASES.map(([v, label]) => html`<option key=${v} value=${v}>${label}</option>`)}
      </select>
      <input class="ui-field" type="text" maxLength=${400} value=${note} aria-label="확인한 내용"
        placeholder="팔과 집게를 확인한 내용 (필수)" onInput=${(e) => setNote(e.target.value)} />
      <${UiButton} kind="primary" type="button" disabled=${Boolean(reasonText)} reason=${reasonText}
        onClick=${submitClear}>확인했습니다 · 해제</${UiButton}>
      ${feedback ? html`<p class="hint" role="status">${feedback}</p>` : null}
    </div>` : null}
  </li>`;
}

export function createCellContextPanel({
  scope,
  call,
  view,
  auth,
  host,
  isStageActive,
  isOperator = () => false,
  namedReason = () => "",
  onClearIncident,
}) {
  const workGate = createPollGate();
  let workInFlight = false;
  let workCheckedAt = 0;
  let workRows = [];
  let workLoaded = false;
  let workError = "";
  let admittingId = "";
  let admitFeedback = "";
  let lastContextSig = "";

  scope.onDispose?.(() => {
    lastContextSig = "";
    if (host) renderDom(null, host);
  });

  async function refresh(signal, { force = false } = {}) {
    if (auth.locked || !isStageActive() || workInFlight) return;
    if (!force && !workGate.due()) return;
    const now = Date.now();
    if (!force && now - workCheckedAt < WORK_REFRESH_MS) return;
    workCheckedAt = now;
    workInFlight = true;
    try {
      const res = await call("/api/fleet/work", { signal });
      workGate.ok();
      workRows = Array.isArray(res?.rows) ? res.rows : [];
      workLoaded = true;
      workError = "";
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (typeof err?.status === "number") workGate.fail(err.status, err.code);
      workError = err?.status === 401 || err?.status === 403
        ? "작업 조회 권한을 확인하세요."
        : "작업 목록을 확인하지 못했습니다.";
    } finally {
      workInFlight = false;
      render();
    }
  }

  async function admitWork(row) {
    if (!row?.source_id || admittingId) return;
    const opReason = !isOperator() ? OPERATOR_REASON : namedReason?.() || "";
    if (opReason) {
      admitFeedback = opReason;
      render();
      return;
    }
    admittingId = row.source_id;
    admitFeedback = "";
    render();
    try {
      const control = await call("/api/fleet/dispatch-control", { timeoutMs: 2000 });
      if (control?.paused) {
        admitFeedback = "발행이 일시정지되어 승인할 수 없습니다. 정지 해제를 먼저 확인하세요.";
        return;
      }
      await call(`/api/fleet/missions/${encodeURIComponent(row.source_id)}/admit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_generation: control?.generation ?? 0 }),
        timeoutMs: 3000,
      });
      admitFeedback = `${row.device_id || "셀"} 작업을 실행 승인했습니다.`;
      workCheckedAt = 0;
      await refresh(scope.capture().signal, { force: true });
    } catch (err) {
      admitFeedback = typeof err?.status === "number" && err.status >= 400 && err.status < 500
        ? `승인이 거절됐습니다 · ${err?.message || "상태 확인 필요"}`
        : "승인 결과 미확인 · 다시 보내지 않았습니다. 작업 원장을 확인하세요.";
    } finally {
      admittingId = "";
      render();
    }
  }

  function render() {
    if (!host) return;
    const show = isStageActive();
    patchHidden(host, !show);
    if (!show) {
      lastContextSig = "";
      return;
    }
    const obs = view.workcellObs;
    const opOk = isOperator();
    const lockReason = !opOk ? OPERATOR_REASON : namedReason?.() || "";
    const openIncidents = [];
    for (const arm of obs?.arms || []) {
      for (const incident of [...(arm.openIncidents || []), ...(arm.homeRecoveries || [])]) {
        openIncidents.push({ arm, incident });
      }
    }
    const activeWork = activeCellWorkRows(workRows);
    const contextSig = JSON.stringify([
      openIncidents.map(({ arm, incident }) => [arm.sourceId, incident.incident_id, incident.state, incident.event_kind, incident.decision?.hold]),
      activeWork.map((r) => [r.source, r.source_id, r.device_id, r.status, r.visible_state, r.updated_at]),
      workLoaded, workError, admittingId, admitFeedback, lockReason, Boolean(auth.locked),
    ]);
    if (contextSig === lastContextSig) return;
    lastContextSig = contextSig;

    const proposedWork = activeWork.filter((r) => r.status === "PROPOSED");
    const runningWork = activeWork.filter((r) => r.status !== "PROPOSED");
    const attentionCount = openIncidents.length + proposedWork.length;
    const allQuiet = !auth.locked && workLoaded && !workError && attentionCount === 0 && runningWork.length === 0;
    const physicalIncidents = openIncidents.filter(({ incident }) => !isHomeRecovery(incident));
    const headTagStatus = physicalIncidents.some((x) => x.incident?.decision?.hold !== false)
      ? "crit"
      : attentionCount ? "warn" : runningWork.length ? "active" : "neutral";
    const headTagText = physicalIncidents.length
      ? `사건 ${physicalIncidents.length}건`
      : openIncidents.length ? "홈 복구 대기" : proposedWork.length
        ? `승인 대기 ${proposedWork.length}건`
        : runningWork.length ? `진행 ${runningWork.length}건` : "이상 없음";

    const renderWorkRow = (row) => {
      const rowBusy = admittingId === row.source_id;
      const btnReason = rowBusy ? "승인 요청을 처리하는 중입니다." : lockReason;
      return html`<li class="cell-context-item" key=${`${row.source}:${row.source_id}`}>
        <div class="cell-context-item-head">
          <strong>${row.device_id || "작업 셀"} · ${workStatusLabel(row.status)}</strong>
          <ui-tag status=${row.status === "PROPOSED" ? "warn" : "active"}>${workStatusLabel(row.status)}</ui-tag>
        </div>
        ${row.reason ? html`<p class="cell-context-reason">${row.reason}</p>` : null}
        ${row.status === "PROPOSED" ? html`<div class="cell-context-item-actions">
          <${UiButton} kind="primary" type="button" disabled=${Boolean(btnReason)} reason=${btnReason}
            onClick=${() => admitWork(row)}>실행 승인</${UiButton}>
        </div>` : null}
      </li>`;
    };

    renderDom(html`
      <div class="cell-stage-head">
        <h2 id="cell-context-heading">셀 작업 · 열린 사건</h2>
        <ui-tag status=${headTagStatus}>${headTagText}</ui-tag>
      </div>
      ${allQuiet
        ? html`<div class="cell-context-section">
            ${admitFeedback ? html`<p class="hint" role="status">${admitFeedback}</p>` : null}
            <p class="hint">확인할 사건이나 진행 중인 셀 작업이 없습니다.</p>
          </div>`
        : html`
          ${attentionCount > 0 ? html`<div class="cell-context-section">
            <h3>지금 확인 · 승인 필요</h3>
            ${admitFeedback ? html`<p class="hint" role="status">${admitFeedback}</p>` : null}
            <ul class="cell-context-list">
              ${openIncidents.map(({ arm, incident }) => html`<${IncidentClearForm}
                key=${`${arm.sourceId}:${incident.incident_id}`}
                arm=${arm}
                incident=${incident}
                clearReason=${lockReason}
                onClearIncident=${onClearIncident} />`)}
              ${proposedWork.map(renderWorkRow)}
            </ul>
          </div>` : null}
          ${(auth.locked || workError || !workLoaded || runningWork.length > 0) ? html`<div class="cell-context-section">
            <h3>진행 중인 셀 작업</h3>
            ${!attentionCount && admitFeedback ? html`<p class="hint" role="status">${admitFeedback}</p>` : null}
            ${workError
              ? html`<p class="hint">${workError}</p>`
              : !workLoaded
                ? html`<p class="hint">${auth.locked ? "접속 후 셀 작업을 확인합니다." : "셀 작업 목록을 확인하는 중입니다."}</p>`
                : html`<ul class="cell-context-list">${runningWork.map(renderWorkRow)}</ul>`}
          </div>` : null}
        `}
      <div class="cell-context-section">
        <h3>목적별 화면 이동</h3>
        <div class="cell-context-links">
          <a class="ui-action-link" data-kind="quiet" href="/console/cell#observation-heading">팔 관측·사건</a>
          <a class="ui-action-link" data-kind="quiet" href="/console/cell#real2sim-heading">셀 태스크·시뮬</a>
          <a class="ui-action-link" data-kind="quiet" href="/console/cell#saved-heading">팔레트 적재 준비</a>
          <a class="ui-action-link" data-kind="quiet" href="/console?view=work">전체 작업 목록</a>
        </div>
      </div>
    `, host);
  }

  function pause() {
    workCheckedAt = 0;
    workLoaded = false;
    workRows = [];
    workError = "";
    admittingId = "";
    admitFeedback = "";
    lastContextSig = "";
    workGate.reset();
    render();
  }

  return { refresh, render, pause };
}
