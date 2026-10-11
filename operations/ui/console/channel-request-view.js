// Fleet binds the current review and existing Task creation in one transaction.
export function createChannelRequestView({scope, call, el, robots, canSubmit, confirm}) {
  let receipt = null, review = null, version = 0, busy = false;
  const panel = el("channel-review"), state = el("channel-review-state");
  const path = () => `/api/fleet/channel-requests/${encodeURIComponent(receipt.request_id)}`;
  function reset() {
    version++; receipt = review = null; panel.hidden = true;
    el("channel-review-reason").value = "";
  }
  function paint() {
    state.textContent = `${review.state}${review.work_status ? " · " + review.work_status : ""} · ${review.reason || "검토 사유를 입력하세요."}`;
    for (const name of ["ready", "hold", "reject"])
      el(`channel-review-${name}`).disabled = busy || review.state === "LINKED";
    el("channel-review-submit-holder").hidden = review.state !== "READY";
    el("channel-review-submit").disabled = busy || !canSubmit(review.candidate?.robot_id);
  }
  async function select(row) {
    const current = ++version, life = scope.capture(); panel.hidden = true;
    try {
      const result = await call(`/api/fleet/channel-requests/${encodeURIComponent(row.request_id)}/review`);
      life.check(); if (current !== version) return;
      receipt = row; review = result;
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
  return {select, reset};
}
