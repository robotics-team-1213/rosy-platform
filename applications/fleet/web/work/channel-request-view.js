// Fleet binds the current review and existing Task creation in one transaction.
import {enumLabel} from "/common/core_ui_logic.js";
import {workStatus} from "/console/assets/work-view.js";
const reviewStates = {REQUESTED: "요청 접수", READY: "이동 후보 준비", HOLD: "보류", REJECTED: "거절됨", LINKED: "작업 연결"};
const deliberationState = {PENDING: "대기", RUNNING: "진행 중", ANSWERED: "응답", HOLD: "보류", UNKNOWN: "확인 불가", SUPERSEDED: "대체됨"};
export function createChannelRequestView({scope, call, el, robots, canSubmit, canManage, confirm}) {
  let receipt = null, review = null, version = 0, busy = false, incidentRows = [], modelState = "";
  const panel = el("channel-review"), state = el("channel-review-state");
  const path = () => `/api/fleet/channel-requests/${encodeURIComponent(receipt.request_id)}`;
  function reset() {
    version++; receipt = review = null; modelState = ""; panel.hidden = true;
    el("channel-review-reason").value = "";
  }
  function paint() {
    const reason = busy ? "요청 처리 중입니다" : review.state === "LINKED" ? "이미 작업과 연결된 요청입니다" : !canManage() ? "이름 있는 운영자 로그인이 필요합니다" : "로봇 연결과 안전 상태를 확인하세요";
    setOff(el("channel-review-incident"), busy || review.state === "LINKED" || !canManage(), reason);
    setOff(el("channel-review-incident-claim"), busy || review.state === "LINKED" || !canManage(), reason);
    const incident = review.incident;
    el("channel-review-incident-link-holder").hidden = !incident;
    if (incident) el("channel-review-incident-link").href = `/console?inbox=1&robot=${encodeURIComponent(incident.robot_id)}&incident=${encodeURIComponent(incident.stuck_id)}`;
    setOff(el("channel-review-mission"), busy || review.state === "LINKED" || !canManage(), reason);
    setOff(el("channel-review-mission-prepare"), busy || review.state === "LINKED" || !canManage(), reason);
    el("channel-review-mission-admit-holder").hidden = !(review.state === "LINKED" && review.work_kind === "mission" && review.work_status === "PROPOSED");
    setOff(el("channel-review-mission-admit"), busy || !canManage(), reason);
    el("channel-review-cell-holder").hidden = review.state === "LINKED" && review.work_kind !== "cell_job";
    el("channel-review-cell").href = `/console/cell?channel_request=${encodeURIComponent(receipt.request_id)}`;
    state.textContent = `${reviewStates[review.state] || "검토 상태 확인 필요"}${review.work_status ? " · " + workStatus(review.work_status) : ""} · ${review.reason || "검토 사유를 입력하세요."} · ${reason}`;
    if (modelState) state.textContent += ` · ${modelState}`;
    for (const name of ["ready", "hold", "reject"])
      setOff(el(`channel-review-${name}`), busy || review.state === "LINKED", reason);
    el("channel-review-submit-holder").hidden = review.state !== "READY";
    setOff(el("channel-review-submit"), busy || !canSubmit(review.candidate?.robot_id), reason);
  }
  function setOff(control, off, reason) {
    control.disabled = off;
    if (off) control.setAttribute("reason", reason); else control.removeAttribute("reason");
    control.setAttribute("aria-describedby", "channel-review-state");
  }
  async function select(row) {
    const current = ++version, life = scope.capture(); panel.hidden = true;
    try {
      const result = await call(`/api/fleet/channel-requests/${encodeURIComponent(row.request_id)}/review`);
      life.check(); if (current !== version) return;
      receipt = row; review = result; modelState = "숙고 결과 조회 안 됨 · 실행 승인 아님";
      try {
        const model = await call(`/api/fleet/channel-requests/${encodeURIComponent(row.request_id)}/deliberation`);
        life.check(); if (current !== version) return;
        const models = model.result?.models?.map(item => item.model_id).join(", ") || model.result?.reason || "";
        modelState = `숙고 ${enumLabel(deliberationState, model.state)} · ${models} · 실행 승인 아님`;
      } catch { life.check(); if (current !== version) return; }
      el("channel-review-original").textContent = row.content;
      const picker = el("channel-review-robot"); picker.replaceChildren();
      const empty = new Option("로봇 선택", ""); picker.append(empty);
      for (const robot of robots()) picker.append(new Option(robot.robot_id, robot.robot_id));
      picker.value = result.candidate?.robot_id || "";
      for (const name of ["x", "y", "yaw"]) el(`channel-review-${name}`).value = result.candidate?.[name] ?? 0;
      el("channel-review-reason").value = result.reason || "";
      panel.hidden = false; paint();
    } catch (error) {
      if (life.current() && current === version) {
        reset(); el("channel-requests-state").textContent = "요청 검토 조회 실패 · 권한과 최신 요청을 확인하세요.";
      }
    }
  }
  async function refresh() {
    if (!receipt || !review || busy) return;
    if (review.state !== "LINKED") { paint(); return; }
    const current = version, snapshot = review, life = scope.capture();
    try {
      const result = await call(path() + "/review");
      life.check();
      if (current === version && review === snapshot && !busy) { review = result; paint(); }
    } catch (error) {
      if (life.current() && current === version) reset();
    }
  }
  function setSources(rows) {
    const picker = el("channel-review-mission"), previous = picker.value;
    picker.replaceChildren(new Option("후보 선택", ""));
    for (const row of rows.filter(row => row.source === "mission" && row.status === "PROPOSED"))
      picker.append(new Option(`${row.source_id} · ${row.workcell_id}`, row.source_id));
    picker.value = previous;
  }
  function setIncidents(reports) {
    incidentRows = reports.filter(row => row.closed_at == null && row.judgment_revision && row.robot_ids?.length === 1);
    const picker = el("channel-review-incident"), previous = picker.value;
    picker.replaceChildren(new Option("사건 선택", ""));
    for (const row of incidentRows) {
      const key = `${row.robot_ids[0]}/${row.stuck_id}`;
      picker.append(new Option(`${row.robot_ids[0]} · ${row.stuck_id}`, key));
    }
    picker.value = previous;
  }
  async function claimIncident() {
    if (!receipt || !review || busy || review.state === "LINKED" || !canManage()) return;
    const key = el("channel-review-incident").value, reason = el("channel-review-reason").value.trim();
    const incident = incidentRows.find(row => `${row.robot_ids[0]}/${row.stuck_id}` === key);
    if (!incident || !reason) { state.textContent = "현재 열린 사건과 검토 사유를 확인하세요."; return; }
    const current = version, snapshot = review, base = path();
    await confirm({message: `${incident.robot_ids[0]}의 사건 ${incident.stuck_id}를 맡을까요? 조치·해소는 별도 확인합니다.`,
      opener: el("channel-review-incident-claim"), kind: "channel-incident",
      eligible: () => current === version && review === snapshot && !busy && canManage()
        && incidentRows.some(row => row.robot_ids[0] === incident.robot_ids[0] && row.stuck_id === incident.stuck_id
          && row.judgment_revision === incident.judgment_revision),
      request: async owner => {
        busy = true; paint();
        try {
          const result = await call(base + "/incident", {method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({expected_hash: snapshot.content_hash, expected_revision: snapshot.revision,
              robot_id: incident.robot_ids[0], stuck_id: incident.stuck_id,
              judgment_revision: incident.judgment_revision, reason}), signals: [owner.signal]});
          owner.check(); if (current === version) review = result;
        } finally { busy = false; if (current === version && review) paint(); }
      }, onError: error => {
        if ([401, 403].includes(error.status)) reset();
        else state.textContent = "인수 결과 미확인 · 자동 재전송하지 않습니다. 현재 사건 기록을 확인하세요.";
      }});
  }
  async function prepareMission() {
    if (!receipt || !review || busy || review.state === "LINKED" || !canManage()) return;
    const sourceId = el("channel-review-mission").value, reason = el("channel-review-reason").value.trim();
    if (!sourceId || !reason) { state.textContent = "내 팔 작업 후보와 검토 사유를 확인하세요."; return; }
    const current = version, snapshot = review, base = path(), life = scope.capture(); let failure = ""; busy = true; paint();
    try {
      const source = await call(`/api/fleet/proposals/${encodeURIComponent(sourceId)}`); life.check();
      if (current !== version) return;
      if (!source.mission) throw new Error("Mission candidate unavailable");
      const result = await call(base + "/prepare", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({kind: "mission", source_proposal_id: sourceId,
          workcell_id: source.mission.workcell_id, instance_id: source.mission.instance_id, reason,
          expected_hash: snapshot.content_hash, expected_revision: snapshot.revision})});
      life.check(); if (current === version) review = result;
    } catch (error) {
      if (life.current() && current === version) {
        if ([401, 403].includes(error.status)) reset();
        else failure = "후보 준비 결과 미확인 · 요청을 다시 선택해 원장을 확인하세요.";
      }
    } finally { busy = false; if (current === version && review) { paint(); if (failure) state.textContent = failure; } }
  }
  async function admitMission() {
    if (!receipt || !review || busy || review.work_kind !== "mission" || review.work_status !== "PROPOSED" || !canManage()) return;
    const current = version, snapshot = review, base = path(), life = scope.capture();
    try {
      const control = await call("/api/fleet/dispatch-control"); life.check();
      if (!control.dispatch_enabled || current !== version || review !== snapshot) {
        state.textContent = "사이트 정지 상태와 현재 작업을 확인하세요."; return;
      }
      await confirm({message: `팔 작업 ${snapshot.work_id}의 실행을 승인할까요?`,
        opener: el("channel-review-mission-admit"), kind: "channel-mission",
        eligible: () => current === version && review === snapshot && !busy && canManage(),
        request: async owner => {
          busy = true; paint();
          try {
            const result = await call(base + "/admit", {method: "POST", headers: {"Content-Type": "application/json"},
              body: JSON.stringify({expected_hash: snapshot.content_hash, expected_revision: snapshot.revision,
                expected_generation: control.generation}), signals: [owner.signal]});
            owner.check(); if (current === version) review = result;
          } finally { busy = false; if (current === version && review) paint(); }
        }, onError: error => {
          if ([401, 403].includes(error.status)) reset();
          else state.textContent = "승인 결과 미확인 · 자동 재전송하지 않습니다. 원장을 확인하세요.";
        }});
    } catch (error) { if (life.current() && current === version) reset(); }
  }
  async function save(next) {
    if (!receipt || !review || busy || review.state === "LINKED") return;
    const reason = el("channel-review-reason").value.trim();
    if (!reason) { state.textContent = "검토 사유를 입력하세요."; el("channel-review-reason").focus(); return; }
    let candidate = null;
    if (next === "READY") {
      candidate = {robot_id: el("channel-review-robot").value};
      for (const name of ["x", "y", "yaw"]) {
        const input = el(`channel-review-${name}`);
        if (!input.value || !input.checkValidity()) { input.reportValidity(); return; }
        candidate[name] = Number(input.value);
      }
      if (!candidate.robot_id) { el("channel-review-robot").focus(); return; }
    }
    const current = version, life = scope.capture(); let failure = ""; busy = true; paint();
    try {
      const result = await call(path() + "/review", {method: "PUT", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({expected_hash: review.content_hash, expected_revision: review.revision, state: next, candidate, reason})});
      life.check(); if (current === version) review = result;
    } catch (error) {
      if (life.current() && current === version) {
        if ([401, 403].includes(error.status)) reset();
        else failure = "검토 저장 실패 · 요청을 다시 선택해 최신 상태를 확인하세요.";
      }
    } finally {
      busy = false;
      if (current === version && review) { paint(); if (failure) state.textContent = failure; }
    }
  }
  async function submit() {
    if (!review || busy || review.state !== "READY") return;
    const current = version, snapshot = review, goal = snapshot.candidate, base = path();
    await confirm({message: `${goal.robot_id}에게 목표 (${goal.x}, ${goal.y}) m를 요청할까요?`,
      opener: el("channel-review-submit"), kind: "channel-request",
      eligible: () => current === version && review === snapshot && !busy && canSubmit(goal.robot_id),
      request: async owner => {
        busy = true; paint();
        try {
          const linked = await call(base + "/submit", {method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({expected_hash: snapshot.content_hash,
              expected_revision: snapshot.revision}), signals: [owner.signal]});
          owner.check(); if (current === version) review = linked;
        } finally { busy = false; if (current === version && review) paint(); }
      }, onError: error => {
        if ([401, 403].includes(error.status)) reset();
        else state.textContent = "요청 결과 미확인 · 자동 재전송하지 않습니다. Fleet 작업 원장을 확인하세요.";
      }});
  }
  scope.listen(el("channel-review-ready"), "click", () => save("READY"));
  scope.listen(el("channel-review-hold"), "click", () => save("HOLD"));
  scope.listen(el("channel-review-reject"), "click", () => save("REJECTED"));
  scope.listen(el("channel-review-submit"), "click", submit);
  scope.listen(el("channel-review-mission-prepare"), "click", prepareMission);
  scope.listen(el("channel-review-mission-admit"), "click", admitMission);
  scope.listen(el("channel-review-incident-claim"), "click", claimIncident);
  return {select, refresh, reset, setSources, setIncidents};
}
