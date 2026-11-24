// D-793 /console/policy: 학습 정책 단계·승인 창·확인 요청·사고 잠금. 규칙은 서버가 판단한다.
import { setOffBy } from "/common/cause-line.js";
import { action as actionButton, node, patchAttr, patchHidden, patchText, uiTag } from "/common/control-dom.js";
import { createFleetClient } from "/common/fleet-client.js";
import { createPageScope } from "/common/scope.js";
import { confirmIrreversible } from "/common/ui.js";
import { developmentToken } from "/console/assets/development-auth.js";
import { renderActiveHistoryList } from "/console/assets/disclosure-list.js";
import { bindEstop, bindTopbarToggle, showSession, showSignedOut, tickClock, watchFleet } from "/console/assets/fleet-header.js";
import { bindTokenAccess, classifyAuthFailure, writeStoredToken } from "/console/assets/fleet-session.js";
import { loginHref } from "/console/assets/login-return.js";
import {
  ADMIN_REASON, OPERATOR_REASON, REASON_LABELS, RESOLUTION_LABELS, STAGE_LABELS, WINDOW_LABELS,
  errorText, executionVerdict, incidentLock, nextStage, policyFigures, proposalLock, remaining, roles, windowLock,
} from "/console/assets/policy-model.js";

const $ = (id) => document.getElementById(id);
const pageScope = createPageScope();
const request = createFleetClient({ credential: () => access.getToken(), origin: location.origin });
const access = bindTokenAccess({
  scope: pageScope,
  onCredential: () => { void connect(true); },
});

$("fleet-login").href = loginHref(location);  // Fallback login entry when topbar menu is folded.
// D-926 2: the same app bar as the other work screens, so the emergency stop and account stay in reach here.
bindEstop(request, { listen: (target, type, fn) => pageScope.listen(target, type, fn), life: () => pageScope.capture() });
bindTopbarToggle((target, type, fn) => pageScope.listen(target, type, fn));
tickClock();
pageScope.interval(tickClock, 1000);
watchFleet(request, { scope: pageScope });

let who = roles(null), state = null, busy = false, refreshing = false, authRoleKey = null;
const workcell = () => $("policy-workcell").value;
const base = () => `/api/fleet/workcells/${encodeURIComponent(workcell())}/policy`;
const renderedSigs = new Map();
pageScope.onDispose(() => { renderedSigs.clear(); refreshing = false; });

function gatedButton(label, lock, onClick, kind = "quiet") {
  const button = actionButton(label, () => onClick(button), kind);
  if (lock) setOffBy(button, lock);
  return button;
}

function message(text, kind = "warning") {
  patchHidden($("policy-message"), !text);
  patchText($("policy-message"), text || "");
  patchAttr($("policy-message"), "state", kind);
}

async function post(path, body, success) {
  if (busy) return;
  busy = true;
  try {
    await request(base() + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    message(success, "ready");
  } catch (error) { message(errorText(error)); }
  finally { busy = false; await refresh(); }
}

async function confirmed(opener, text, actionLabel, path, body, success) {
  if (await confirmIrreversible({ message: text, action: actionLabel, opener })) await post(path, body, success);
}

function renderIncident(item) {
  const row = node("li");
  row.append(
    uiTag(item.cleared_ns === null ? "잠금" : "해제됨", item.cleared_ns === null ? "crit" : "neutral"),
    node("span", ` ${item.description} — 신고 ${item.reported_by}`),
  );
  if (item.cleared_ns === null) {
    row.append(gatedButton("잠금 해제…", incidentLock(item, who), (btn) => confirmed(btn,
      `"${item.description}" 사고 잠금을 해제할까요? 원인을 확인한 뒤에만 해제하세요.`, "잠금 해제",
      `/incidents/${item.incident_id}/clear`, { operator_confirmed: true, note: "원인 확인 후 해제" }, "사고 잠금을 해제했습니다.")));
  }
  return row;
}

function renderConfirmation(item) {
  const row = node("li");
  const open = !item.resolution;
  row.append(
    uiTag(open ? "대기" : RESOLUTION_LABELS[item.resolution], open ? "warn" : "neutral"),
    node("span", ` ${REASON_LABELS[item.reason] || item.reason}${item.policy_revision ? ` · ${item.policy_revision}` : ""} — ${item.created_by}`),
  );
  const evidencePre = node("pre", JSON.stringify(item.evidence, null, 2), "policy-evidence");
  if (open) {
    const fold = node("details");
    const summary = node("summary", "판단 근거 보기", "ui-disclosure-row");
    fold.append(summary, evidencePre);
    const actions = node("ui-actions");
    for (const resolution of state.rules.resolutions) {
      actions.append(gatedButton(`${RESOLUTION_LABELS[resolution]}…`, who.admin ? "" : ADMIN_REASON, (btn) => confirmed(btn,
        `"${REASON_LABELS[item.reason] || item.reason}" 확인 요청을 ${RESOLUTION_LABELS[resolution]}으로 처리할까요?`
          + (resolution === "resume" ? " 팔 제어 보류는 관제의 팔 복구에서 따로 풉니다." : " 열린 승인 창이 닫힙니다."),
        RESOLUTION_LABELS[resolution], `/confirmations/${item.confirmation_id}/resolve`,
        { operator_confirmed: true, resolution, note: `${RESOLUTION_LABELS[resolution]} (콘솔)` }, "확인 요청을 처리했습니다.")));
    }
    row.append(fold, actions);
  } else {
    row.append(evidencePre);
  }
  return row;
}

function renderWindow(item) {
  const row = node("li");
  const status = item.active ? "열림" : item.approved_by ? "닫힘" : item.closed_ns ? "취소됨" : "승인 대기";
  row.append(
    uiTag(status, item.active ? "active" : item.approved_by || item.closed_ns ? "neutral" : "warn"),
    node("span", ` ${WINDOW_LABELS[item.kind]} · ${item.policy_revision} · ${item.scope} — 요청 ${item.requested_by}`
      + (item.active ? ` · ${remaining(item.expires_ns, state.now_ns)} 남음` : "")),
  );
  if (!item.approved_by && !item.closed_ns) {
    row.append(gatedButton("승인…", windowLock(item, state.rules, who), (btn) => confirmed(btn,
      `${item.policy_revision}의 ${WINDOW_LABELS[item.kind]} 승인 창을 열까요? ${item.minutes}분 동안 "${item.scope}" 범위로 실행될 수 있습니다.`,
      "승인 창 열기", `/windows/${item.window_id}/approve`, { operator_confirmed: true }, "승인 창을 열었습니다.")));
  }
  if (item.active || (!item.approved_by && !item.closed_ns)) {
    row.append(gatedButton("닫기", who.operator ? "" : OPERATOR_REASON, () => post(`/windows/${item.window_id}/close`,
      { operator_confirmed: true, reason: "콘솔에서 닫음" }, "승인 창을 닫았습니다.")));
  }
  return row;
}

function renderStage(item) {
  return node("li", `${item.policy_revision} — ${STAGE_LABELS[item.stage]} · 작업대 ${item.rig_revision} · 보정 ${item.calibration_revision}`);
}

function cell(...children) {
  const td = node("td");
  td.append(...children);
  return td;
}

function renderProposal(item) {
  const row = node("tr");
  const actions = node("ui-actions");
  row.append(
    cell(uiTag(item.state === "PENDING" ? "대기" : item.state === "APPROVED" ? "승인됨" : "거절됨",
      item.state === "PENDING" ? "warn" : "neutral")),
    cell(item.policy_revision),
    cell(`${STAGE_LABELS[item.from_stage] || "미등록"} → ${STAGE_LABELS[item.to_stage]}`),
    cell(item.proposed_by),
    cell(item.note),
    cell(actions),
  );
  if (item.state === "PENDING") {
    actions.append(
      gatedButton("승인…", proposalLock(item, state.rules, who), (btn) => confirmed(btn,
        `${item.policy_revision}을(를) ${STAGE_LABELS[item.to_stage]}로 올릴까요? 근거 ${item.evidence_sha256.slice(0, 12)}…`,
        "단계 승인", `/proposals/${item.proposal_id}/decision`, { operator_confirmed: true, approve: true }, "단계를 승인했습니다.")),
      gatedButton("거절…", who.admin ? "" : ADMIN_REASON, (btn) => confirmed(btn,
        `"${item.policy_revision}"의 ${STAGE_LABELS[item.to_stage]} 제안을 거절할까요?`, "제안 거절",
        `/proposals/${item.proposal_id}/decision`, { operator_confirmed: true, approve: false }, "제안을 거절했습니다.")),
    );
  }
  return row;
}

function syncWriteFolds() {
  const key = `${who.admin}:${who.operator}`;
  if (authRoleKey === key) return;
  authRoleKey = key;
  $("policy-incident-fold").open = Boolean(who.operator);
  patchText($("policy-incident-summary"), who.operator ? "사고·파손 신고" : `사고·파손 신고 (${OPERATOR_REASON})`);
  for (const [foldId, summaryId, title] of [
    ["policy-window-fold", "policy-window-summary", "승인 창 요청"],
    ["policy-proposal-fold", "policy-proposal-summary", "다음 단계 제안"],
  ]) {
    $(foldId).open = Boolean(who.admin);
    patchText($(summaryId), who.admin ? title : `${title} (${ADMIN_REASON})`);
  }
}

function render() {
  patchHidden($("policy-content"), false);
  const verdict = executionVerdict(state);
  patchText($("policy-verdict"), verdict.text); patchAttr($("policy-verdict"), "state", verdict.state);
  const figures = policyFigures(state);
  const figSig = JSON.stringify(figures);
  const figBox = $("policy-figures");
  if (renderedSigs.get("policy-figures") !== figSig || !figBox.firstElementChild) {
    renderedSigs.set("policy-figures", figSig);
    figBox.replaceChildren(...figures.map((item) => {
      const box = node("div");
      if (item.alert) box.setAttribute("data-alert", "");
      box.append(node("dt", item.label), node("dd", item.value), Object.assign(node("dd", item.note), { }));
      box.lastChild.setAttribute("data-note", "");
      return box;
    }));
  }
  renderActiveHistoryList({
    container: $("policy-incidents"),
    historyFold: $("policy-incidents-history"),
    historySummary: $("policy-incidents-history-summary"),
    historyContainer: $("policy-incidents-past"),
    items: state.incidents,
    isActive: (item) => item.cleared_ns === null,
    renderItem: renderIncident,
    emptyActiveText: "사고 기록이 없습니다.",
    emptyHistoryOnlyText: "열린 사고 잠금이 없습니다.",
    historyLabel: (n) => `해제된 사고 ${n}건`,
    sigMap: renderedSigs,
    sigKey: "policy-incidents",
    sigInput: [state.incidents, who, state.rules],
  });
  renderActiveHistoryList({
    container: $("policy-confirmations"),
    historyFold: $("policy-confirmations-history"),
    historySummary: $("policy-confirmations-history-summary"),
    historyContainer: $("policy-confirmations-past"),
    items: state.confirmations,
    isActive: (item) => !item.resolution,
    renderItem: renderConfirmation,
    emptyActiveText: "확인 요청이 없습니다.",
    emptyHistoryOnlyText: "대기 중인 확인 요청이 없습니다.",
    historyLabel: (n) => `처리된 확인 요청 ${n}건`,
    sigMap: renderedSigs,
    sigKey: "policy-confirmations",
    sigInput: [state.confirmations, who, state.rules],
  });
  renderActiveHistoryList({
    container: $("policy-windows"),
    historyFold: $("policy-windows-history"),
    historySummary: $("policy-windows-history-summary"),
    historyContainer: $("policy-windows-past"),
    items: state.windows,
    isActive: (item) => Boolean(item.active || (!item.approved_by && !item.closed_ns)),
    renderItem: renderWindow,
    emptyActiveText: "승인 창 기록이 없습니다.",
    emptyHistoryOnlyText: "열리거나 대기 중인 승인 창이 없습니다.",
    historyLabel: (n) => `지난 승인 창 ${n}건`,
    sigMap: renderedSigs,
    sigKey: "policy-windows",
    sigInput: [state.windows.map((w) => (w.active ? [w, remaining(w.expires_ns, state.now_ns)] : w)), who, state.rules],
  });
  const stageBox = $("policy-stages"), stageSig = JSON.stringify(state.policies);
  if (renderedSigs.get("policy-stages") !== stageSig || !stageBox.firstElementChild) {
    renderedSigs.set("policy-stages", stageSig);
    stageBox.replaceChildren(...(state.policies.length
      ? state.policies.map(renderStage)
      : [node("li", "등록된 정책이 없습니다. 학습 결과를 0단계로 등록하세요.")]));
  }
  const emptyPropRow = (text) => {
    const tr = node("tr"), td = node("td", text);
    td.setAttribute("colspan", "6"); tr.append(td); return tr;
  };
  renderActiveHistoryList({
    container: $("policy-proposals"),
    historyFold: $("policy-proposals-history"),
    historySummary: $("policy-proposals-history-summary"),
    historyContainer: $("policy-proposals-past"),
    items: state.proposals,
    isActive: (item) => item.state === "PENDING",
    renderItem: renderProposal,
    emptyActiveText: "단계 제안 기록이 없습니다.",
    emptyHistoryOnlyText: "대기 중인 단계 제안이 없습니다.",
    historyLabel: (n) => `처리된 단계 제안 ${n}건`,
    renderEmpty: emptyPropRow,
    sigMap: renderedSigs,
    sigKey: "policy-proposals",
    sigInput: [state.proposals, who, state.rules],
  });
  const policies = $("policy-window-policy");
  const polOptsSig = JSON.stringify(state.policies.map((item) => [item.policy_revision, item.stage]));
  if (renderedSigs.get("policy-window-policy") !== polOptsSig) {
    renderedSigs.set("policy-window-policy", polOptsSig);
    const chosen = policies.value;
    policies.replaceChildren(...state.policies.map((item) => {
      const opt = node("option", `${item.policy_revision} (${STAGE_LABELS[item.stage] || item.stage})`);
      opt.value = item.policy_revision;
      return opt;
    }));
    if (chosen) policies.value = chosen;
  }
  if (!$("policy-window-kind").options.length) {
    for (const [kind, rule] of Object.entries(state.rules.windows)) {
      const opt = node("option", `${WINDOW_LABELS[kind]} · ${rule.min_stage} 이상 · 기본 ${rule.default_minutes}분, 최대 ${rule.max_minutes}분`);
      opt.value = kind;
      $("policy-window-kind").append(opt);
    }
  }
  for (const id of ["policy-window-request", "policy-proposal-submit"]) {
    setOffBy($(id), who.admin ? "" : ADMIN_REASON);
  }
  for (const id of ["policy-incident-report", "policy-sync-owner"]) {
    setOffBy($(id), who.operator ? "" : OPERATOR_REASON);
  }
  syncWriteFolds();
}

async function refresh() {
  if (!workcell() || refreshing) return;
  refreshing = true;
  const life = pageScope.capture();
  try {
    state = await request(base(), { signals: [life.signal] });
    life.check();
    render();
  } catch (error) {
    if (error?.name === "AbortError" || !life.current()) return;
    patchHidden($("policy-content"), true);
    patchText($("policy-verdict"), errorText(error));
    patchAttr($("policy-verdict"), "state", "unavailable");
  } finally { refreshing = false; }
}

$("policy-incident-report").addEventListener("click", async () => {
  const text = $("policy-incident-text").value.trim();
  if (!text) { message("사고 내용을 적어 주세요."); return; }
  await confirmed($("policy-incident-report"), `"${text}" 사고를 신고할까요? 이 작업셀의 승인 창이 모두 닫힙니다.`, "사고 신고",
    "/incidents", { operator_confirmed: true, description: text }, "사고를 신고했습니다. 승인 창이 닫혔습니다.");
  $("policy-incident-text").value = "";
});
$("policy-sync-owner").addEventListener("click", () => post("/confirmations/sync-owner", undefined, "팔 제어 상태를 가져왔습니다."));
$("policy-window-request").addEventListener("click", () => {
  const minutes = $("policy-window-minutes").value;
  const policy = state?.policies.find((item) => item.policy_revision === $("policy-window-policy").value);
  if (!policy || !$("policy-window-scope").value.trim()) { message("정책과 허용 범위를 고르세요."); return; }
  post("/windows", {
    operator_confirmed: true, policy_revision: policy.policy_revision, kind: $("policy-window-kind").value,
    minutes: minutes ? Number(minutes) : null, scope: $("policy-window-scope").value.trim(),
    rig_revision: policy.rig_revision, calibration_revision: policy.calibration_revision,
  }, "승인 창을 요청했습니다. 다른 관리자의 승인이 필요할 수 있습니다.");
});
$("policy-proposal-submit").addEventListener("click", () => {
  const revision = $("policy-proposal-revision").value.trim();
  const current = state?.policies.find((item) => item.policy_revision === revision);
  const target = nextStage(state.rules, current?.stage);
  if (!target) { message("이미 마지막 단계입니다."); return; }
  if (!$("policy-proposal-form").reportValidity()) return;
  post("/proposals", {
    operator_confirmed: true, policy_revision: revision, to_stage: target,
    rig_revision: $("policy-proposal-rig").value.trim(), calibration_revision: $("policy-proposal-cal").value.trim(),
    evidence_sha256: $("policy-proposal-evidence").value.trim(), note: $("policy-proposal-note").value.trim(),
  }, `${STAGE_LABELS[target]} 제안을 올렸습니다.`);
});
for (const form of ["policy-incident-form", "policy-window-form", "policy-proposal-form"]) {
  $(form).addEventListener("submit", (event) => event.preventDefault());
}
$("policy-workcell").addEventListener("change", refresh);

async function connect(credentialChange = false) {
  const life = pageScope.capture();
  try {
    const session = await request("/api/fleet/auth/session", { signals: [life.signal] });
    life.check();
    who = roles(session);
    document.documentElement.toggleAttribute("data-read-only", Boolean(!who.operator && !who.admin));
    patchHidden($("policy-login"), true);
    showSession(session, { credentialChange });
    access.refreshLogin(false);
    const { workcells } = await request("/api/fleet/policy-governance/workcells", { signals: [life.signal] });
    life.check();
    $("policy-workcell").replaceChildren(...workcells.map((id) => {
      const opt = node("option", id); opt.value = id; return opt;
    }));
    $("policy-workcell").hidden = !workcells.length;
    document.querySelector('[for="policy-workcell"]').hidden = !workcells.length;
    if (!workcells.length) {
      patchHidden($("policy-content"), true);
      patchText($("policy-verdict"), "설정된 OMX 작업셀이 없습니다. 사이트 설치 담당자에게 작업셀 등록을 요청하세요.");
      patchAttr($("policy-verdict"), "state", "empty");
      return;
    }
    await refresh();
  } catch (error) {
    if (error?.name === "AbortError" || !life.current()) return;
    const failure = classifyAuthFailure(error);
    patchHidden($("policy-content"), true);
    patchText($("policy-verdict"), errorText(error));
    patchAttr($("policy-verdict"), "state", "unavailable");
    patchHidden($("policy-login"), !failure.offerLogin);
    if (failure.signOut) {
      if (failure.offerLogin) writeStoredToken("");
      showSignedOut({ refused: failure.refused });
      if (failure.offerLogin) access.refreshLogin(true);
    }
  }
}

pageScope.interval(() => { if (!document.hidden) void refresh(); }, 2000);
pageScope.listen(document, "visibilitychange", () => { if (!document.hidden) void refresh(); });
pageScope.onResume(() => { void connect(false); });
void access.bootstrap({
  developmentToken,
  connect: (changed) => connect(changed),
  onSignedOut: () => {
    patchHidden($("policy-content"), true);
    patchHidden($("policy-login"), false);
    showSignedOut();
    access.refreshLogin(true);
  },
});
