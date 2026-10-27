// Known external proposals keep their neutral contract and independent admission.
const node = (tag, text = "", className = "") => Object.assign(document.createElement(tag), {textContent: text, className});
const states = {PROPOSED: "독립 운영자 승인 대기", READY: "승인됨 · 실행 준비", RUNNING: "실행 중",
  ACTION_SUCCEEDED: "동작 성공 · 물리 확인 대기", GOAL_CONFIRMED: "물리 목표 확인됨", HOLD: "보류 · 근거 확인 필요"};
export function armAdmissionReason(job, control, actor, roleReason = "") {
  if (!job) return "작업을 먼저 조회하세요";
  if (roleReason) return roleReason;
  if (!actor || actor === job.proposal_principal_id) return "제안한 사람과 다른 기명 운영자가 승인해야 합니다";
  if (job.status !== "PROPOSED") return "승인 전 제안만 승인할 수 있습니다";
  if (!control?.dispatch_enabled || !Number.isSafeInteger(control.generation) || control.generation < 0) return "사이트 실행 상태를 다시 조회하세요";
  return "";
}
export function createArmTransferView({scope, call, anchor, active, approveReason, principal, confirm}) {
  const panel = node("section", "", "arm-transfer-work"), heading = node("h2", "외부 앱 ARM 제안"),
    form = node("form", "", "ui-form"), label = node("label", "작업 식별자", "ui-field-label"),
    actions = node("div", "", "ui-actions"),
    state = node("p"), detail = node("dl", "", "work-detail");
  const input = document.createElement("input");
  input.className = "ui-field";
  const read = node("ui-button", "작업 조회");
  read.setAttribute("kind", "quiet"); read.setAttribute("type", "button");
  const admit = node("ui-button", "독립 운영자로 실행 승인");
  admit.setAttribute("kind", "primary"); admit.setAttribute("type", "button"); admit.hidden = true;
  panel.id = "arm-transfer-work"; heading.id = "arm-transfer-heading";
  panel.setAttribute("aria-labelledby", heading.id); panel.hidden = !active;
  input.id = "arm-transfer-id"; input.name = "mission_id"; input.required = true; input.maxLength = 192;
  label.htmlFor = input.id; label.append(input);
  read.id = "arm-transfer-read"; admit.id = "arm-transfer-admit";
  read.setAttribute("data-work-read", "");
  state.id = "arm-transfer-state"; state.setAttribute("role", "status"); state.setAttribute("aria-live", "polite");
  admit.setAttribute("aria-describedby", state.id);
  actions.append(read, admit); form.append(label, actions);
  panel.append(heading, node("p", "인계받은 작업 식별자로 원본을 조회하세요. 조회와 승인은 별도입니다.", "hint"),
    form, state, detail, node("p", "실행 승인 후 장치 동작이 시작될 수 있습니다. 물리 목표 확인과 외부 앱의 업무 완료는 별도 근거입니다.", "hint"));
  const recoveryPanel = node("section"), recoveryState = node("p"), review = node("p"),
    recoveryActions = node("ui-actions"), childState = node("dl", "", "work-detail"),
    technical = node("details"), bindings = node("dl", "", "work-detail");
  const requestRecovery = node("ui-button", "복구 관측 요청");
  requestRecovery.setAttribute("kind", "quiet");
  const approveRecovery = node("ui-button", "독립 운영자로 복구 1회 승인");
  approveRecovery.setAttribute("kind", "primary");
  recoveryPanel.id = "arm-transfer-recovery"; recoveryPanel.hidden = true;
  recoveryState.id = "arm-transfer-recovery-state";
  recoveryState.setAttribute("role", "status"); recoveryState.setAttribute("aria-live", "polite");
  requestRecovery.id = "arm-transfer-recovery-request"; approveRecovery.id = "arm-transfer-recovery-approve";
  childState.id = "arm-transfer-recovery-child";
  for (const button of [requestRecovery, approveRecovery]) {
    button.setAttribute("type", "button"); button.setAttribute("aria-describedby", recoveryState.id);
  }
  recoveryActions.append(requestRecovery, approveRecovery);
  technical.append(node("summary", "조회한 복구 근거"), bindings);
  recoveryPanel.append(node("h3", "시뮬레이션 · 실패 확인과 제한된 복구"), review, recoveryState, recoveryActions, childState,
    node("p", "원래 실패는 보존됩니다. 원래 제안자의 요청과 새 관측, 다른 운영자의 승인을 거쳐 복구 시도를 최대 1회 만듭니다.", "hint"), technical);
  panel.append(recoveryPanel);
  anchor.before(panel);
  const requested = new URLSearchParams(location.search).get("arm_transfer") || "";
  input.value = requested;
  let job = null, control = null, version = 0, busy = false, attempted = false, initial = false;
  let recovery = null, child = null, recoveryError = "", recoveryAttempted = false;
  function paint() {
    admit.hidden = !job;
    const reason = busy ? "요청 처리 중입니다" : !job ? "작업을 먼저 조회하세요" : attempted ? "승인 요청 후 원본을 다시 조회하세요" :
      armAdmissionReason(job, control, principal(), approveReason());
    admit.disabled = Boolean(reason); read.disabled = busy; input.readOnly = busy;
    if (reason) admit.setAttribute("reason", reason); else admit.removeAttribute("reason");
    const recoveryWait = busy ? "요청 처리 중입니다" : recovery?.child_mission_id ? "복구 횟수를 이미 사용했습니다" :
      recoveryAttempted ? "요청 후 작업을 다시 조회하세요" : "";
    const requestReason = recoveryWait || (!recovery?.can_request || !["AVAILABLE", "EXPIRED"].includes(recovery.status) ?
      "복구 관측을 요청할 수 있는 원본 실패 작업을 조회하세요" : "");
    requestRecovery.disabled = Boolean(requestReason);
    if (requestReason) requestRecovery.setAttribute("reason", requestReason); else requestRecovery.removeAttribute("reason");
    // The role closure is initialized after the first render; read it only for an eligible approval.
    const recoveryReason = recoveryWait || (!recovery?.can_approve ?
      "독립 생산자의 새 관측과 다른 운영자 승인이 필요합니다" : approveReason());
    approveRecovery.disabled = Boolean(recoveryReason);
    if (recoveryReason) approveRecovery.setAttribute("reason", recoveryReason); else approveRecovery.removeAttribute("reason");
  }
  function field(title, value, target = detail) { target.append(node("dt", title), node("dd", String(value ?? "미확인"))); }
  function showRecovery() {
    recoveryPanel.hidden = !job || (!recovery && !recoveryError);
    bindings.replaceChildren(); childState.textContent = ""; review.textContent = "";
    if (!recovery) { recoveryState.textContent = recoveryError; return; }
    const labels = {UNAVAILABLE: "현재 근거로 복구를 승인할 수 없습니다", AVAILABLE: "원래 제안자가 새 관측을 요청할 수 있습니다",
      WAITING_OBSERVATIONS: "독립 생산자의 새 관측 대기", READY_FOR_APPROVAL: "새 관측 확인됨 · 다른 운영자 승인 대기",
      EXPIRED: "근거 또는 권한이 변경됐습니다. 다시 조회하고 새 관측을 요청하세요", CHILD_CREATED: "복구 시도를 만들었습니다 · 추가 복구는 허용되지 않습니다"};
    recoveryState.textContent = recoveryError || labels[recovery.status] || "복구 상태를 다시 조회하세요";
    const result = recovery.execution_review;
    if (result) {
      const outcomes = {SUCCEEDED: "성공", FAILED: "실패", UNKNOWN: "미확인", HOLD: "보류", ACCEPTED: "접수", RUNNING: "실행 중", CANCEL_REQUESTED: "취소 요청"};
      const phases = {approach: "접근", grasp: "집기", transfer: "이송", release: "놓기"};
      review.textContent = `장치가 보고한 동작 결과: ${outcomes[result.action_outcome] || "미확인"}. ` +
        `작업 결과: ${{succeeded: "성공", failed: "실패", unknown: "미확인"}[result.task_outcome] || "미확인"}. ` +
        `보고된 단계: ${phases[result.failure_phase || result.last_reported_phase] || "미확인"}. 물리적 실패 원인은 미확인입니다.`;
      if (result.owner_reason) field("장치 보고 사유", result.owner_reason, bindings);
      for (const phase of result.phase_summaries) field(phases[phase.phase_id] || phase.phase_id, outcomes[phase.state] || "미확인", bindings);
    }
    for (const [key, title] of [["request_id", "복구 요청"], ["proposal_digest", "요청 다이제스트"],
      ["evidence_digest", "관측 다이제스트"], ["context_digest", "원본 근거 다이제스트"], ["expected_generation", "실행 세대"], ["reason", "판정 사유"]]) {
      field(title, recovery[key], bindings);
    }
    if (recovery.child_mission_id) {
      field("복구 시도", recovery.child_mission_id, childState);
      field("결과", child ? states[child.status] || "상태 확인 필요" :
        "결과를 조회할 수 없습니다. 다시 조회하세요. 복구 횟수는 이미 사용됐습니다.", childState);
    }
  }
  function show() {
    detail.replaceChildren();
    if (job) {
      field("상태", states[job.status] || "상태 확인 필요"); field("작업 식별자", job.mission_id);
      field("제안자", job.proposal_principal_id); field("승인자", job.approved_by);
      for (const [key, title] of [["workcell_id", "작업 공간"], ["instance_id", "장치"], ["object_ref", "물체 참조"], ["source", "출발 참조"], ["target", "목표 참조"]]) field(title, job.transfer[key]);
      field("제안 다이제스트", job.proposal_digest); field("조회한 실행 세대", control?.generation);
      field("승인된 실행 세대", job.dispatch_generation); field("사유", job.reason);
    }
    showRecovery(); paint();
  }
  function reset() {
    version++; job = null; control = null; initial = false; attempted = false;
    recovery = null; child = null; recoveryError = ""; recoveryAttempted = false;
    state.textContent = "접속 후 작업을 조회하세요."; show();
  }
  async function lookup() {
    if (!active || busy) return;
    const id = input.value.trim();
    version++; job = null; control = null; attempted = false; show();
    recovery = null; child = null; recoveryError = ""; recoveryAttempted = false;
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$/.test(id)) { state.textContent = "인계받은 작업 식별자를 확인하세요."; return; }
    const current = version, life = scope.capture(); busy = true; paint(); state.textContent = "원본 조회 중";
    try {
      const result = await call(`/api/fleet/arm-transfers/jobs/${encodeURIComponent(id)}`); life.check();
      if (current !== version) return;
      if (result.job?.mission_id !== id || result.job.action_kind !== "ARM_TRANSFER" || !result.job.transfer || !/^[a-f0-9]{64}$/.test(result.job.proposal_digest)) throw new Error("invalid ARM transfer response");
      job = result.job;
      try { control = await call("/api/fleet/dispatch-control"); life.check(); }
      catch { control = null; }
      if (current !== version || !life.current()) return;
      if (["RUNNING", "HOLD", "ACTION_SUCCEEDED", "GOAL_CONFIRMED"].includes(job.status)) {
        try {
          const result = await call(`/api/fleet/arm-transfers/jobs/${encodeURIComponent(id)}/recovery`); life.check();
          if (current !== version) return;
          if (result.recovery?.parent_mission_id !== id || result.recovery.execution_authorized !== false) throw new Error("invalid recovery response");
          recovery = result.recovery;
          if (recovery.child_mission_id) {
            try {
              const result = await call(`/api/fleet/arm-transfers/jobs/${encodeURIComponent(recovery.child_mission_id)}`); life.check();
              if (current !== version) return;
              if (result.job?.mission_id !== recovery.child_mission_id) throw new Error("invalid recovery child");
              child = result.job;
            } catch { child = null; }
          }
        } catch { recoveryError = "복구 근거를 조회할 수 없습니다. 원본 작업은 보존돼 있습니다. 다시 조회하세요."; }
      }
      if (current !== version || !life.current()) return;
      state.textContent = `${states[job.status] || "상태 확인 필요"} · 원본을 조회했습니다. ${armAdmissionReason(job, control, principal(), approveReason())}`;
      show();
    } catch (error) {
      if (!life.current() || current !== version) return;
      job = null; control = null; show();
      state.textContent = error.status === 404 ? "해당 작업을 찾을 수 없습니다. 인계 식별자를 확인하세요." :
        [401, 403].includes(error.status) ? "이 작업의 조회 권한과 접속 계정을 확인하세요." :
        "ARM 제안을 조회할 수 없습니다. 설치된 API와 연결 상태를 확인하세요.";
    } finally { busy = false; paint(); }
  }
  async function approve() {
    if (busy || attempted || armAdmissionReason(job, control, principal(), approveReason())) return;
    const snapshot = job, generation = control.generation, current = version;
    await confirm({message: `${snapshot.mission_id}의 ${snapshot.transfer.source} → ${snapshot.transfer.target} 실행을 승인할까요?`,
      opener: admit, kind: "arm-transfer",
      eligible: () => current === version && job === snapshot && !busy && !attempted &&
        !armAdmissionReason(job, control, principal(), approveReason()),
      request: async owner => {
        busy = true; attempted = true; paint();
        try {
          const result = await call(`/api/fleet/arm-transfers/jobs/${encodeURIComponent(snapshot.mission_id)}/admit`,
            {method: "POST", headers: {"Content-Type": "application/json"}, signals: [owner.signal],
              body: JSON.stringify({expected_proposal_digest: snapshot.proposal_digest, expected_generation: generation})});
          owner.check();
          if (current === version) {
            job = result.job; state.textContent = "승인 응답을 받았습니다. 원본을 다시 조회해 실행 상태를 확인하세요."; show();
          }
        } finally { busy = false; paint(); }
      }, onError: error => {
        if (current !== version) return;
        state.textContent = error.status >= 400 && error.status < 500 ? "승인이 거절됐습니다. 계정·제안·실행 세대의 원본을 다시 조회하세요. 자동 재전송하지 않았습니다." :
          "승인 결과 미확인 · 자동 재전송하지 않았습니다. 원본을 다시 조회하세요.";
        paint();
      }});
  }
  async function requestReset() {
    if (busy || recoveryAttempted || !recovery?.can_request || !["AVAILABLE", "EXPIRED"].includes(recovery.status)) return;
    const snapshot = recovery, parent = job, current = version, life = scope.capture();
    busy = true; recoveryAttempted = true; recoveryError = ""; paint();
    try {
      const result = await call(`/api/fleet/arm-transfers/jobs/${encodeURIComponent(parent.mission_id)}/recovery`,
        {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({request_key: crypto.randomUUID(), expected_context_digest: snapshot.context_digest})});
      life.check();
      if (current !== version) return;
      if (result.request?.context_digest !== snapshot.context_digest) throw new Error("invalid recovery request response");
      recovery = {...snapshot, ...result.request, status: "WAITING_OBSERVATIONS", can_approve: false, evidence_digest: null};
      show();
    } catch (error) {
      if (current !== version || !life.current()) return;
      recoveryError = error.status >= 400 && error.status < 500 ? "복구 요청이 거절됐습니다. 원본을 다시 조회하세요." :
        "복구 요청 결과 미확인 · 자동 재전송하지 않았습니다. 원본을 다시 조회하세요.";
      show();
    } finally { busy = false; paint(); }
  }
  async function approveReset() {
    if (busy || recoveryAttempted || !recovery?.can_approve || approveReason()) return;
    const snapshot = recovery, parent = job, current = version;
    await confirm({message: `${parent.mission_id}의 실패를 보존하고 새 근거로 복구 시도 1회를 만들까요?`,
      opener: approveRecovery, kind: "arm-transfer-recovery",
      eligible: () => current === version && recovery === snapshot && job === parent && !busy && !recoveryAttempted && snapshot.can_approve && !approveReason(),
      request: async owner => {
        busy = true; recoveryAttempted = true; recoveryError = ""; paint();
        try {
          const result = await call(`/api/fleet/arm-transfers/jobs/${encodeURIComponent(parent.mission_id)}/recovery/${encodeURIComponent(snapshot.request_id)}/approve`,
            {method: "POST", headers: {"Content-Type": "application/json"}, signals: [owner.signal], body: JSON.stringify({
              expected_proposal_digest: snapshot.proposal_digest, expected_evidence_digest: snapshot.evidence_digest, expected_generation: snapshot.expected_generation})});
          owner.check();
          if (current !== version) return;
          if (!result.job?.mission_id || result.job.mission_id === parent.mission_id) throw new Error("invalid recovery approval response");
          child = result.job;
          recovery = {...snapshot, status: "CHILD_CREATED", child_mission_id: child.mission_id, can_request: false, can_approve: false};
          show();
        } finally { busy = false; paint(); }
      }, onError: error => {
        if (current !== version) return;
        recoveryError = error.status >= 400 && error.status < 500 ? "복구 승인이 거절됐습니다. 근거와 권한을 다시 조회하세요. 자동 재전송하지 않았습니다." :
          "복구 승인 결과 미확인 · 자동 재전송하지 않았습니다. 원본을 다시 조회하세요.";
        show();
      }});
  }
  scope.listen(read, "click", lookup); scope.listen(admit, "click", approve);
  scope.listen(requestRecovery, "click", requestReset); scope.listen(approveRecovery, "click", approveReset);
  scope.listen(form, "submit", event => { event.preventDefault(); lookup(); });
  scope.listen(input, "input", () => { version++; job = null; control = null; attempted = false;
    recovery = null; child = null; recoveryError = ""; recoveryAttempted = false;
    state.textContent = "작업을 다시 조회하세요."; show(); });
  show();
  return {reset, refresh: async () => { if (active && requested && !initial) { initial = true; await lookup(); } }};
}
