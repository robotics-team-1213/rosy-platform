// 대형 패널 (D-262 Fleet 분해). 리더·모양·간격·멤버 폼과 무장·변경·재개·해제,
// 대기 요약을 가진다. 지도 오버레이(drawFormationOverlay)는 console.js에 남는다 —
// 그리는 것과 여는 것은 다른 일이다. 서버 기하를 복제하지 않는다.

export function createFormation({ el, view, log, call, render }) {
  function fillLeaders() {
    const select = el("formation-leader");
    const ids = view.robots.map((r) => r.robot_id);
    const current = select.value;
    if (select.dataset.ids === ids.join(",")) return;
    select.dataset.ids = ids.join(",");
    select.replaceChildren(...ids.map((id) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      return option;
    }));
    if (ids.includes(current)) select.value = current;
    // FOR-001 Robot Selection — 기본은 전원 체크다. 하나라도 풀면 선택 편성이다.
    const box = el("formation-members");
    box.replaceChildren(...ids.map((id) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = id;
      input.checked = true;
      label.append(input, document.createTextNode(id));
      return label;
    }));
    syncPendingSummary();
  }

  // D-252: 무장 전 확인 문장. 슬롯 좌표는 서버 기하가 쥐고 있어 클라이언트가
  // 미리 그릴 수 없으므로, 폼 현재값을 문장으로 미리 말한다.
  function syncPendingSummary() {
    if (view.formation && view.formation.active) return;
    const leader = el("formation-leader").value;
    const shape = el("formation-shape").value;
    const spacing = Number(el("formation-spacing").value);
    const members = [...el("formation-members").querySelectorAll("input:checked")]
      .map((b) => b.value);
    el("formation-detail").textContent = members.length
      ? `리더 ${leader} · ${shape} ${spacing}m · ${members.length}대 — 무장하면 슬롯으로 따라붙습니다.`
      : "포함 로봇을 고르세요.";
  }

  function renderFormation(status) {
    const stateEl = el("formation-state");
    stateEl.textContent = status.state;
    stateEl.className = `tag ${status.state === "RUNNING" ? "nav"
      : status.state === "HOLDING" ? "warn" : ""}`;
    el("formation-start").disabled = status.active;
    el("formation-reform").disabled = !status.active;
    // 재개는 HOLDING 에서만 뜻이 있다. RUNNING 에서 눌러 봐야 세션이 조용히 무시한다.
    el("formation-resume").disabled = status.state !== "HOLDING";
    el("formation-stop").disabled = !status.active;
    // 대형이 열려 있는 동안에는 멤버를 바꿀 수 없다 — 해제하고 다시 연다.
    el("formation-members").querySelectorAll("input").forEach((i) => { i.disabled = status.active; });

    const detail = el("formation-detail");
    if (!status.active) {
      syncPendingSummary();
      return;
    }
    const slots = Object.entries(status.assignment || {})
      .map(([id, slot]) => `${id} ${slot.distance.toFixed(2)}m/${slot.lateral.toFixed(2)}m`);
    const relay = status.relay;
    const lines = [`리더 ${status.leader} · ${status.formation} ${status.spacing}m`];
    if (slots.length) lines.push(slots.join(", "));
    if (relay) {
      // 릴레이가 0 Hz 인데 이유가 없으면 화면은 "그냥 멈춰 있다"로만 보인다.
      lines.push(`릴레이 ${relay.paused ? "일시정지" : `${relay.leader_rx_hz} Hz`}` +
        (relay.leader_last_error ? ` (${relay.leader_last_error})` : ""));
      const errs = Object.entries(relay.follower_last_error || {}).filter(([, e]) => e);
      if (errs.length) lines.push(errs.map(([id, e]) => `${id}: ${e}`).join(", "));
    }
    if (status.reason) lines.push(`이유: ${status.reason.join(" / ")}`);
    if (status.pending_triggers && status.pending_triggers.length) {
      lines.push(`재개 차단: ${status.pending_triggers.map((t) => t.join(":")).join(", ")}`);
    }
    detail.textContent = lines.join(" — ");
  }

  function applyFormation(status) {
    view.formation = status;
    renderFormation(status);
    render();   // 명렬 카드의 증거 태그도 대형 상태를 따라 다시 그린다
  }

  async function refreshFormation() {
    try {
      applyFormation(await call("/api/fleet/formation"));
    } catch (err) {
      el("formation-detail").textContent = `대형 상태를 읽지 못했습니다 — ${err.message}`;
    }
  }

  async function formationCall(path, body, label) {
    try {
      const status = await call(path, body ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      } : { method: "POST" });
      applyFormation(status);
      log(`대형 ${label} — ${status.state}`, "good");
    } catch (err) {
      log(`대형 ${label} 거절 — ${err.message}`, "bad");
      refreshFormation();
    }
  }

  function selectedMembers() {
    const leader = el("formation-leader").value;
    const boxes = [...el("formation-members").querySelectorAll("input")];
    if (boxes.length && boxes.some((b) => !b.checked)) {
      return [leader, ...boxes.filter((b) => b.checked).map((b) => b.value)
        .filter((id) => id !== leader)];
    }
    return null;  // 전원 체크는 전원 대형이다 — members를 보내지 않는다
  }

  function bind() {
    el("formation-start").addEventListener("click", () => {
      const body = {
        leader: el("formation-leader").value,
        formation: el("formation-shape").value,
        spacing: Number(el("formation-spacing").value),
      };
      const members = selectedMembers();
      if (members) body.members = members;
      formationCall("/api/fleet/formation/start", body, "무장");
    });

    el("formation-reform").addEventListener("click", () => formationCall(
      "/api/fleet/formation/reform",
      { formation: el("formation-shape").value, spacing: Number(el("formation-spacing").value) },
      "변경"));

    el("formation-resume").addEventListener("click", () =>
      formationCall("/api/fleet/formation/resume", null, "재개"));

    el("formation-stop").addEventListener("click", () =>
      formationCall("/api/fleet/formation/stop", null, "해제"));

    // D-252: 폼이 바뀌면 대기 요약을 갱신한다. 무장 중에는 서버 상태가 주인이므로 건드리지 않는다.
    for (const id of ["formation-leader", "formation-shape", "formation-spacing", "formation-members"]) {
      el(id).addEventListener("change", syncPendingSummary);
      el(id).addEventListener("input", syncPendingSummary);
    }
  }

  return { fillLeaders, renderFormation, applyFormation, refreshFormation, bind };
}
