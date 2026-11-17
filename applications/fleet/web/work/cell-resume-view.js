import {createCauseLine} from "/common/cause-line.js";
import {statusTag} from "/common/status-tag.js";
import {isRouteAbsent} from "/console/assets/poll-gate.js";

const PAUSE_REASONS = Object.freeze({
  HUMAN_DETECTED_ESTOP: "사람 감지 비상정지",
  VISION_HUMAN_DETECTED_ESTOP: "비전 사람 감지로 일시중지",
  HUMAN_CLEARED_AWAITING_RESUME: "홀드 해제됨 · 작업별 재개 대기",
});

export const RESUME_REFUSALS = Object.freeze({
  HUMAN_HOLD_ACTIVE: "셀 안전 홀드가 활성 상태입니다 · 홀드 해제 후 재개하세요",
  NOT_PAUSED_HUMAN: "일시중지(PAUSED_HUMAN) 상태가 아닌 작업입니다",
  UNKNOWN_TASK: "작업을 찾을 수 없습니다",
  PROPOSER_IS_APPROVER: "제안자는 자기 제안을 승인할 수 없습니다",
  UNKNOWN_OR_EXPIRED_PROPOSAL: "만료되었거나 찾을 수 없는 제안입니다",
  OPERATOR_GUARD_MISSING: "기명 운영자 권한이 필요합니다",
  CELL_ABORTED_HOLD: "셀이 중단(ABORTED) 홀드 상태입니다 · 셀 복구 후 재개하세요",
  ARM_HOLD_ACTIVE: "팔 홀드가 활성 상태입니다 · 팔 홀드 해제 후 재개하세요",
  NOTE_REQUIRED: "사유 메모(1~200자)가 필요합니다",
});

export const NOTE_MAX = 200;
export const NOTE_INPUT = Object.freeze({label: "사유 메모", max: NOTE_MAX});
export const RESTART_MESSAGE = "실행 중에 멈춘 작업입니다. 처음부터 다시 시작합니다";

// Server contract: clear and resume both carry `note`; resume adds restart_from_start only after the 409 confirm.
export const clearBody = (cellId, note) => ({cell_id: cellId, note});
export const resumeBody = (note, restart = false) => (restart ? {note, restart_from_start: true} : {note});
export const needsRestartConfirm = error => error?.code === "RESUME_NEEDS_RESTART_CONFIRM";

export function cellHoldActive(data, cellId) {
  const hs = data?.human_safety;
  const gate = cellId ? data?.cells?.[cellId]?.gate : null;
  if (cellId) {
    return Boolean(hs?.human_detected?.[cellId] || hs?.human_detected?.all || hs?.active_estop || gate?.phase === "HUMAN_HOLD");
  }
  return Boolean(hs?.active_estop || hs?.human_detected?.all || hs?.human_detected?.cell_s || hs?.human_detected?.cell_ab);
}

export function pauseSummary(task, data) {
  const gate = data?.cells?.[task?.cell_id]?.gate || {};
  const who = task?.paused_by || gate.paused_by || "안전 감시";
  const rawReason = task?.paused_reason || gate.reason || task?.health_summary?.substage || "";
  const why = PAUSE_REASONS[rawReason] || rawReason || "안전 보류";
  const from = task?.paused_from_status ? ` · 이전 ${task.paused_from_status}` : "";
  return `일시중지: ${who} · 사유: ${why}${from}`;
}

export function resumeLockReason(task, data, {busy = false, approveReason = "", refusal = ""} = {}) {
  if (busy) return "요청 처리 중입니다";
  if (refusal) return refusal;
  if (cellHoldActive(data, task?.cell_id)) return "셀 홀드 활성 중 · 홀드 해제 후 재개할 수 있습니다";
  return approveReason || "";
}

export function decisionLockReason(proposal, {busy = false, principal = "", approveReason = "", refusal = ""} = {}) {
  if (busy) return "요청 처리 중입니다";
  if (refusal) return refusal;
  if (proposal?.proposed_by && principal && proposal.proposed_by === principal) {
    return RESUME_REFUSALS.PROPOSER_IS_APPROVER;
  }
  return approveReason || "";
}

const node = (tag, text, className) =>
  Object.assign(document.createElement(tag), {textContent: text || "", ...(className ? {className} : {})});

export function createCellResumeView({scope, call, anchor, active, approveReason, principal, confirm, onChanged = null}) {
  const panel = node("section", "", "work-cell-resume");
  panel.id = "cell-resume-work";
  panel.setAttribute("aria-labelledby", "cell-resume-heading");
  panel.hidden = true;
  const heading = node("h3", "일시중지 셀 작업 · 작업별 재개");
  heading.id = "cell-resume-heading";
  const status = node("p", "", "hint");
  status.id = "cell-resume-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const holdsBox = node("div", "", "cell-resume-holds");
  const list = node("ul", "", "work-list");
  list.id = "cell-resume-list";
  const proposalsBox = node("ul", "", "work-list");
  proposalsBox.id = "cell-decision-proposals";
  panel.append(heading, status, holdsBox, list, proposalsBox);
  anchor.after(panel);

  let latest = null, absent = false, busyKey = "", statusNotice = "";
  const refusals = new Map();

  function errorText(error) {
    if (isRouteAbsent(error?.status, error?.code)) return "서버 제어 경로가 아직 활성화되지 않았습니다 (404)";
    return RESUME_REFUSALS[error?.code] || error?.message || "요청을 처리하지 못했습니다";
  }

  function paint() {
    if (!active || absent || !latest) { panel.hidden = true; return; }
    const paused = (latest.tasks || []).filter(t => t.status === "PAUSED_HUMAN");
    const heldCells = ["cell_s", "cell_ab"].filter(cid => cellHoldActive(latest, cid));
    const proposals = Array.isArray(latest.decision_proposals) ? latest.decision_proposals : [];
    const anything = paused.length > 0 || heldCells.length > 0 || proposals.length > 0 || Boolean(statusNotice);
    panel.hidden = !anything;
    if (!anything) return;

    status.textContent = statusNotice || (paused.length
      ? `일시중지 작업 ${paused.length}건 · 홀드가 풀린 뒤 작업마다 재개합니다.`
      : heldCells.length ? "셀 안전 홀드가 활성 상태입니다." : "");

    const pendingCauses = [];
    const queueCause = (parent, btn, reason) => {
      const line = document.createElement("ui-status");
      const cause = createCauseLine(parent, {line});
      pendingCauses.push([cause, btn, reason]);
      return line;
    };

    const cellLink = (cid, armId = null) => {
      const target = armId === "arm_s" ? "cell_s"
        : armId === "arm_a" ? "cell_a"
        : armId === "arm_b" ? "cell_b"
        : (cid === "cell_s" || cid === "cell_ab") ? cid : null;
      if (!target) return null;
      const label = target === "cell_s" ? "Cell S 작업대 열기"
        : target === "cell_a" ? "Cell A 작업대 열기"
        : target === "cell_b" ? "Cell B 작업대 열기"
        : "Cell A/B 작업대 열기";
      return Object.assign(node("a", label, "ui-action-link"), {
        href: `/console/cell?cell=${encodeURIComponent(target)}#observation-heading`,
      });
    };

    holdsBox.replaceChildren(...heldCells.map(cid => {
      const row = node("div", "", "cell-hold-row");
      row.dataset.cellId = cid;
      const cellTitle = cid === "cell_s" ? "Cell S (cell_s)" : cid === "cell_ab" ? "Cell A/B (cell_ab)" : cid;
      const label = node("span", `${cellTitle} 안전 홀드 `);
      label.append(statusTag("caution", "홀드 중"));
      if (cid === "cell_ab") {
        for (const armId of ["arm_a", "arm_b"]) {
          const armLink = cellLink(cid, armId);
          if (armLink) { armLink.dataset.kind = "quiet"; label.append(" ", armLink); }
        }
      }
      const link = cellLink(cid);
      if (link) { link.dataset.kind = "quiet"; label.append(" ", link); }
      const btn = node("ui-button", "사람 이탈 · 정지 해제");
      btn.setAttribute("kind", "quiet");
      btn.setAttribute("type", "button");
      const key = `hold:${cid}`;
      const reason = busyKey === key ? "요청 처리 중입니다" : (refusals.get(key) || approveReason() || "");
      const causeLine = queueCause(row, btn, reason);
      scope.listen(btn, "click", () => void clearHold(cid, key, btn));
      row.append(label, btn, causeLine);
      return row;
    }));

    list.replaceChildren(...paused.map(task => {
      const li = node("li");
      li.dataset.pausedTask = task.task_id;
      const head = node("p");
      head.append(node("strong", `${task.task_id} · ${task.cell_id} (${task.arm_id || "—"}) `),
        statusTag("caution", cellHoldActive(latest, task.cell_id) ? "홀드 중" : "재개 대기"));
      const link = cellLink(task.cell_id, task.arm_id);
      if (link) { link.dataset.kind = "quiet"; head.append(" ", link); }
      const meta = node("p", pauseSummary(task, latest), "hint");
      const btn = node("ui-button", "작업 재개");
      btn.setAttribute("kind", "primary");
      btn.setAttribute("type", "button");
      const key = `task:${task.task_id}`;
      const reason = resumeLockReason(task, latest, {
        busy: busyKey === key, approveReason: approveReason(), refusal: refusals.get(key) || "",
      });
      const causeLine = queueCause(li, btn, reason);
      scope.listen(btn, "click", () => void resumeTask(task, btn, key));
      li.append(head, meta, btn, causeLine);
      return li;
    }));

    proposalsBox.replaceChildren(...proposals.map(prop => {
      const li = node("li");
      li.dataset.decisionProposal = prop.decision_id;
      const head = node("p");
      head.append(node("strong", `제안 ${prop.decision_id} · ${prop.cell || ""} `));
      const link = cellLink(prop.cell, prop.arm_id || prop.instance_id);
      if (link) { link.dataset.kind = "quiet"; head.append(" ", link); }
      const lock = decisionLockReason(prop, {
        busy: busyKey === `dec:${prop.decision_id}`,
        principal: principal?.() || "",
        approveReason: approveReason(),
        refusal: refusals.get(`dec:${prop.decision_id}`) || "",
      });
      if (prop.proposed_by && principal?.() && prop.proposed_by === principal()) head.append(statusTag("locked"));
      const btn = node("ui-button", "제안 실행 승인");
      btn.setAttribute("kind", "primary");
      btn.setAttribute("type", "button");
      const causeLine = queueCause(li, btn, lock);
      scope.listen(btn, "click", () => void executeProposal(prop, btn));
      li.append(head, btn, causeLine);
      return li;
    }));

    for (const [cause, btn, reason] of pendingCauses) cause.set([btn], reason);
  }

  async function clearHold(cellId, key, opener) {
    if (busyKey || approveReason()) return;
    await confirm({
      message: `${cellId} 안전 홀드를 해제할까요? 사람이 셀 밖에 있는지 확인한 뒤 사유를 남깁니다.`,
      opener, kind: "human-hold-clear", note: NOTE_INPUT,
      eligible: () => !busyKey && !approveReason(),
      request: async (owner, note) => {
        busyKey = key; refusals.delete(key); paint();
        try {
          await call("/api/fleet/pipeline/human-safety-gate/clear", {
            method: "POST", headers: {"Content-Type": "application/json"}, signals: [owner.signal],
            body: JSON.stringify(clearBody(cellId, note)),
          });
          owner.check();
          refusals.clear();
          statusNotice = "홀드 해제됨 · 작업은 각각 재개";
        } finally { busyKey = ""; }
      },
      onError: error => { refusals.set(key, errorText(error)); paint(); },
    });
    if (scope.capture().current()) { await refresh(); onChanged?.(); }
  }

  async function resumeTask(task, opener, key) {
    if (busyKey || resumeLockReason(task, latest, {approveReason: approveReason()})) return;
    const url = `/api/fleet/pipeline/cell-tasks/${encodeURIComponent(task.task_id)}/resume`;
    const eligible = () => !busyKey && !resumeLockReason(task, latest, {approveReason: approveReason()});
    const send = (owner, note, restart) => async () => {
      busyKey = key; refusals.delete(key); paint();
      try {
        await call(url, {method: "POST", headers: {"Content-Type": "application/json"}, signals: [owner.signal],
          body: JSON.stringify(resumeBody(note, restart))});
        owner.check();
        statusNotice = `${task.task_id} 작업 재개됨`;
      } finally { busyKey = ""; }
    };
    let askRestart = null;
    await confirm({
      message: `${task.task_id} (${task.arm_id || task.cell_id}) 일시중지 작업을 재개할까요? 재개 후 팔이 움직일 수 있습니다.`,
      opener, kind: "cell-task-resume", note: NOTE_INPUT, eligible,
      request: (owner, note) => send(owner, note, false)().catch(error => {
        if (!needsRestartConfirm(error)) throw error;
        askRestart = note; paint();
      }),
      onError: error => { refusals.set(key, errorText(error)); paint(); },
    });
    if (askRestart !== null) {
      const note = askRestart;
      await confirm({
        message: RESTART_MESSAGE, opener, kind: "cell-task-resume", eligible,
        request: owner => send(owner, note, true)(),
        onError: error => { refusals.set(key, errorText(error)); paint(); },
      });
    }
    if (scope.capture().current()) { await refresh(); onChanged?.(); }
  }

  async function executeProposal(prop, opener) {
    const key = `dec:${prop.decision_id}`;
    const blocked = () => decisionLockReason(prop, {principal: principal?.() || "", approveReason: approveReason()});
    if (busyKey || blocked()) return;
    await confirm({
      message: `${prop.decision_id} (${prop.cell || "셀"}) 판단 제안을 실행 승인할까요?`,
      opener, kind: "decision-gate-execute",
      eligible: () => !busyKey && !blocked(),
      request: async owner => {
        busyKey = key; refusals.delete(key); paint();
        try {
          await call("/api/fleet/pipeline/decision-gate/execute", {
            method: "POST", headers: {"Content-Type": "application/json"}, signals: [owner.signal],
            body: JSON.stringify({decision_id: prop.decision_id}),
          });
          owner.check();
          statusNotice = `${prop.decision_id} 제안 실행 승인됨`;
        } finally { busyKey = ""; }
      },
      onError: error => { refusals.set(key, errorText(error)); paint(); },
    });
    if (scope.capture().current()) { await refresh(); onChanged?.(); }
  }

  async function refresh() {
    if (!active || absent) return;
    const life = scope.capture();
    try {
      const body = await call("/api/fleet/pipeline/cell-tasks", {signals: [life.signal]});
      life.check();
      latest = body;
      paint();
    } catch (error) {
      if (!life.current() || error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) { absent = true; panel.hidden = true; }
    }
  }

  function reset() {
    latest = null; statusNotice = ""; refusals.clear(); panel.hidden = true;
    holdsBox.replaceChildren(); list.replaceChildren(); proposalsBox.replaceChildren();
  }

  return {element: panel, refresh, reset};
}
