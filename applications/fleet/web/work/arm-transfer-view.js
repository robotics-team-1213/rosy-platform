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
  state.id = "arm-transfer-state"; state.setAttribute("role", "status"); state.setAttribute("aria-live", "polite");
  admit.setAttribute("aria-describedby", state.id);
  actions.append(read, admit); form.append(label, actions);
  panel.append(heading, node("p", "인계받은 작업 식별자로 원본을 조회하세요. 조회와 승인은 별도입니다.", "hint"),
    form, state, detail, node("p", "실행 승인 후 장치 동작이 시작될 수 있습니다. 물리 목표 확인과 외부 앱의 업무 완료는 별도 근거입니다.", "hint"));
  anchor.before(panel);
  const requested = new URLSearchParams(location.search).get("arm_transfer") || "";
  input.value = requested;
  let job = null, control = null, version = 0, busy = false, attempted = false, initial = false;
  function paint() {
    admit.hidden = !job;
    const reason = busy ? "요청 처리 중입니다" : !job ? "작업을 먼저 조회하세요" : attempted ? "승인 요청 후 원본을 다시 조회하세요" :
      armAdmissionReason(job, control, principal(), approveReason());
    admit.disabled = Boolean(reason); read.disabled = busy; input.readOnly = busy;
    if (reason) admit.setAttribute("reason", reason); else admit.removeAttribute("reason");
  }
  function field(title, value) { detail.append(node("dt", title), node("dd", String(value ?? "미확인"))); }
  function show() {
    detail.replaceChildren();
    if (job) {
      field("상태", states[job.status] || "상태 확인 필요"); field("작업 식별자", job.mission_id);
      field("제안자", job.proposal_principal_id); field("승인자", job.approved_by);
      for (const [key, title] of [["workcell_id", "작업 공간"], ["instance_id", "장치"], ["object_ref", "물체 참조"], ["source", "출발 참조"], ["target", "목표 참조"]]) field(title, job.transfer[key]);
      field("제안 다이제스트", job.proposal_digest); field("조회한 실행 세대", control?.generation);
      field("승인된 실행 세대", job.dispatch_generation); field("사유", job.reason);
    }
    paint();
  }
  function reset() {
    version++; job = null; control = null; initial = false; attempted = false;
    state.textContent = "접속 후 작업을 조회하세요."; show();
  }
  async function lookup() {
    if (!active || busy) return;
    const id = input.value.trim();
    version++; job = null; control = null; attempted = false; show();
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
  scope.listen(read, "click", lookup); scope.listen(admit, "click", approve);
  scope.listen(form, "submit", event => { event.preventDefault(); lookup(); });
  scope.listen(input, "input", () => { version++; job = null; control = null; attempted = false; state.textContent = "작업을 다시 조회하세요."; show(); });
  show();
  return {reset, refresh: async () => { if (active && requested && !initial) { initial = true; await lookup(); } }};
}
