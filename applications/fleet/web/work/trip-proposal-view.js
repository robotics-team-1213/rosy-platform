// D-908: a known external trip proposal keeps its neutral contract and an independent named operator admits it.
import { armAdmissionReason as admissionReason } from "/console/assets/arm-transfer-view.js";
const node = (tag, text = "", className = "") => Object.assign(document.createElement(tag), {textContent: text, className});
const states = {PROPOSED: "독립 운영자 승인 대기", ADMITTED: "승인됨 · 작업 생성"};
export function createTripProposalView({scope, call, anchor, active, approveReason, principal, confirm}) {
  const panel = node("section", "", "arm-transfer-work"), heading = node("h2", "외부 앱 이송 제안"),
    form = node("form", "", "ui-form"), label = node("label", "제안 식별자", "ui-field-label"),
    actions = node("div", "", "ui-actions"), state = node("p"), detail = node("dl", "", "work-detail");
  const input = document.createElement("input");
  input.className = "ui-field";
  const read = node("ui-button", "제안 조회"), admit = node("ui-button", "독립 운영자로 이송 승인");
  read.setAttribute("kind", "quiet"); read.setAttribute("type", "button");
  admit.setAttribute("kind", "primary"); admit.setAttribute("type", "button"); admit.hidden = true;
  panel.id = "trip-proposal-work"; heading.id = "trip-proposal-heading";
  panel.setAttribute("aria-labelledby", heading.id); panel.hidden = !active;
  input.id = "trip-proposal-id"; input.name = "proposal_id"; input.required = true; input.maxLength = 64;
  label.htmlFor = input.id; label.append(input);
  read.id = "trip-proposal-read"; admit.id = "trip-proposal-admit";
  state.id = "trip-proposal-state"; state.setAttribute("role", "status"); state.setAttribute("aria-live", "polite");
  admit.setAttribute("aria-describedby", state.id);
  actions.append(read, admit); form.append(label, actions);
  panel.append(heading, node("p", "인계받은 제안 식별자로 원본을 조회하세요. 조회와 승인은 별도입니다.", "hint"),
    form, state, detail, node("p", "승인하면 로봇 예약이 시작되고 이송이 실행될 수 있습니다. 화물 도착과 업무 완료는 외부 앱이 따로 판단합니다.", "hint"));
  anchor.before(panel);
  input.value = new URLSearchParams(location.search).get("trip_proposal") || "";
  let proposal = null, control = null, version = 0, busy = false, attempted = false, initial = false;
  const reasonNow = () => admissionReason(proposal, control, principal(), approveReason());
  function paint() {
    admit.hidden = !proposal;
    const reason = busy ? "요청 처리 중입니다" : !proposal ? "제안을 먼저 조회하세요" :
      attempted ? "승인 요청 후 원본을 다시 조회하세요" : reasonNow();
    admit.disabled = Boolean(reason); read.disabled = busy; input.readOnly = busy;
    if (reason) admit.setAttribute("reason", reason); else admit.removeAttribute("reason");
  }
  function field(title, value) { detail.append(node("dt", title), node("dd", String(value ?? "미확인"))); }
  function show() {
    detail.replaceChildren();
    if (proposal) {
      field("상태", states[proposal.status] || "상태 확인 필요"); field("제안 식별자", proposal.proposal_id);
      field("제안자", proposal.proposal_principal_id); field("승인자", proposal.approved_by);
      field("후보 로봇", proposal.candidate_robot_ids.join(", "));
      field("경로", proposal.steps.map(step => [...step.via, step.to].join(" → ")).join(" / "));
      field("제안 다이제스트", proposal.proposal_digest); field("조회한 실행 세대", control?.generation);
      field("승인된 실행 세대", proposal.dispatch_generation); field("생성된 작업", proposal.mission_id);
    }
    paint();
  }
  function reset() {
    version++; proposal = null; control = null; initial = false; attempted = false;
    state.textContent = "접속 후 제안을 조회하세요."; show();
  }
  async function lookup() {
    if (!active || busy) return;
    const id = input.value.trim();
    version++; proposal = null; control = null; attempted = false; show();
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(id)) { state.textContent = "인계받은 제안 식별자를 확인하세요."; return; }
    const current = version, life = scope.capture(); busy = true; paint(); state.textContent = "원본 조회 중";
    try {
      const result = await call(`/api/fleet/trip-proposals/${encodeURIComponent(id)}`); life.check();
      if (current !== version) return;
      if (result.proposal?.proposal_id !== id || !Array.isArray(result.proposal.steps) || !/^[a-f0-9]{64}$/.test(result.proposal.proposal_digest)) throw new Error("invalid trip proposal response");
      proposal = result.proposal;
      try { control = await call("/api/fleet/dispatch-control"); life.check(); }
      catch { control = null; }
      if (current !== version || !life.current()) return;
      state.textContent = `${states[proposal.status] || "상태 확인 필요"} · 원본을 조회했습니다. ${reasonNow()}`;
      show();
    } catch (error) {
      if (!life.current() || current !== version) return;
      proposal = null; control = null; show();
      state.textContent = error.status === 404 ? "해당 제안을 찾을 수 없습니다. 인계 식별자를 확인하세요." :
        [401, 403].includes(error.status) ? "이 제안의 조회 권한과 접속 계정을 확인하세요." :
        "이송 제안을 조회할 수 없습니다. 설치된 API와 연결 상태를 확인하세요.";
    } finally { busy = false; paint(); }
  }
  async function approve() {
    if (busy || attempted || reasonNow()) return;
    const snapshot = proposal, generation = control.generation, current = version;
    await confirm({message: `${snapshot.proposal_id}의 이송(${snapshot.steps.map(step => step.to).join(" → ")}) 실행을 승인할까요?`,
      opener: admit, kind: "trip-proposal",
      eligible: () => current === version && proposal === snapshot && !busy && !attempted && !reasonNow(),
      request: async owner => {
        busy = true; attempted = true; paint();
        try {
          const result = await call(`/api/fleet/trip-proposals/${encodeURIComponent(snapshot.proposal_id)}/admit`,
            {method: "POST", headers: {"Content-Type": "application/json"}, signals: [owner.signal],
              body: JSON.stringify({expected_proposal_digest: snapshot.proposal_digest, expected_generation: generation})});
          owner.check();
          if (current === version) {
            proposal = result.proposal; state.textContent = "승인 응답을 받았습니다. 원본을 다시 조회해 작업 상태를 확인하세요."; show();
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
  scope.listen(input, "input", () => { version++; proposal = null; control = null; attempted = false; state.textContent = "제안을 다시 조회하세요."; show(); });
  show();
  return {reset, refresh: async () => { if (active && input.value && !initial) { initial = true; await lookup(); } }};
}
