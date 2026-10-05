// 대형 패널 (D-262 Fleet 분해). 리더·모양·간격·멤버 폼과 무장·변경·재개·해제,
// 대기 요약을 가진다. 지도 오버레이(drawFormationOverlay)는 console.js에 남는다 —
// 그리는 것과 여는 것은 다른 일이다. 서버 기하를 복제하지 않는다.

// D-359 US-009 — 대형 세션 상태(fleet/swarm/session.py SessionState)의 운용자 말. 열거값은 title에만.
export const FORMATION_STATE_LABEL = {
  IDLE: "대기", ARMING: "무장 중", RUNNING: "진행 중", HOLDING: "유지 중", STOPPED: "해제됨",
};
const stateLabel = (state) => FORMATION_STATE_LABEL[state] || state || "—";
import { formationReason } from "./motion-readiness.js";

export function createFormation({ scope, el, view, log, call, render }) {
  function setOff(id, off, reason) {
    const button = el(id);
    button.disabled = off;
    if (off) button.setAttribute("reason", reason);
    else button.removeAttribute("reason");
  }

  function fillLeaders() {
    const select = el("formation-leader");
    const ids = view.robots.map((r) => r.robot_id);
    const current = select.value;
    if (select.dataset.ids === ids.join(",")) { syncPendingSummary(); return; }
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
      label.className = "ui-check";
      const input = document.createElement("input");
      input.className = "ui-field";
      input.type = "checkbox";
      input.value = id;
      input.checked = true;
      // 좁은 칸에서는 줄임표로 자르고 전체 id 는 title 로 남긴다.
      const name = document.createElement("span");
      name.textContent = id;
      label.title = id;
      label.append(input, name);
      return label;
    }));
    syncPendingSummary();
  }

  // D-252: 무장 전 확인 문장. 슬롯 좌표는 서버 기하가 쥐고 있어 클라이언트가
  // 미리 그릴 수 없으므로, 폼 현재값을 문장으로 미리 말한다.
  function syncPendingSummary() {
    if (view.formationUnavailable || (view.formation && view.formation.active)) return;
    const leader = el("formation-leader").value;
    const shape = el("formation-shape").value;
    const spacing = Number(el("formation-spacing").value);
    const members = [...el("formation-members").querySelectorAll("input:checked")]
      .map((b) => b.value);
    const reason = view.stateUnavailable ? "Fleet 상태 확인 불가" : formationReason(view.robots, leader, members);
    setOff("formation-start", Boolean(reason), reason);
    if (reason) {
      el("formation-detail").textContent = reason;
      return;
    }
    el("formation-detail").textContent = members.length
      ? `리더 ${leader} · ${shape} ${spacing}m · ${members.length}대 — 무장하면 슬롯으로 따라붙습니다.`
      : "포함 로봇을 고르세요.";
  }

  function renderFormation(status) {
    const stateEl = el("formation-state");
    stateEl.textContent = stateLabel(status.state);
    stateEl.title = status.state || "";
    stateEl.setAttribute("status", status.state === "RUNNING" ? "active"
      : status.state === "HOLDING" ? "warn" : "neutral");
    // D-359 §5.3 — 사유는 비활성 조건과 같은 식에서 나온다.
    setOff("formation-start", status.active, "이미 대형 중");
    setOff("formation-reform", !status.active, "열린 대형 없음");
    // 재개는 HOLDING(유지 중)에서만 뜻이 있다. RUNNING에서 눌러 봐야 세션이 조용히 무시한다.
    setOff("formation-resume", status.state !== "HOLDING", "대형 유지 중일 때만");
    setOff("formation-stop", !status.active, "열린 대형 없음");
    // 대형이 열려 있는 동안에는 멤버를 바꿀 수 없다 — 해제하고 다시 연다.
    el("formation-members").querySelectorAll("input").forEach((i) => { i.disabled = status.active; });

    // D-416/D-417 — 대형 모니터링 모드: RUNNING/HOLDING일 때 폼을 접고 요약만 보인다.
    // IDLE일 때도 폼은 기본 접힘 — 설정이 필요할 때 펼친다.
    const formWrap = document.querySelector(".formation-form-wrap");
    if (formWrap) {
      formWrap.open = !status.active && formWrap.open; // 활성 중엔 접힘
    }
    const form = document.querySelector(".formation-form");
    if (form) form.hidden = status.active;

    const detail = el("formation-detail");
    if (!status.active) {
      if (form) form.hidden = false;
      syncPendingSummary();
      return;
    }
    const slots = Object.entries(status.assignment || {})
      .map(([id, slot]) => `${id} ${slot.distance.toFixed(2)}m/${slot.lateral.toFixed(2)}m`);
    const relay = status.relay;
    // D-417 — 요약을 구조화한다(진단 패널과 같은 격자).
    const items = [
      ["리더", status.leader],
      ["모양", `${status.formation} ${status.spacing}m`],
      ["멤버", slots.length ? slots.join(", ") : "—"],
    ];
    if (relay) {
      items.push(["릴레이", relay.paused ? "일시정지" : `${relay.leader_rx_hz} Hz`
        + (relay.leader_last_error ? ` (${relay.leader_last_error})` : "")]);
      const errs = Object.entries(relay.follower_last_error || {}).filter(([, e]) => e);
      if (errs.length) items.push(["오류", errs.map(([id, e]) => `${id}: ${e}`).join(", ")]);
    }
    if (status.reason) items.push(["이유", status.reason.join(" / ")]);
    if (status.pending_triggers && status.pending_triggers.length) {
      items.push(["재개 차단", status.pending_triggers.map((t) => t.join(":")).join(", ")]);
    }
    const dl = document.createElement("dl");
    dl.className = "diag-readout";
    for (const [term, desc] of items) {
      const dt = document.createElement("dt"); dt.textContent = term;
      const dd = document.createElement("dd"); dd.textContent = desc;
      dl.append(dt, dd);
    }
    detail.replaceChildren(dl);
  }

  function applyFormation(status) {
    view.formationUnavailable = false;
    view.formation = status;
    renderFormation(status);
    render();   // 명렬 카드의 증거 태그도 대형 상태를 따라 다시 그린다
  }

  async function refreshFormation() {
    const life = scope.capture();
    life.check();
    try {
      const status = await call("/api/fleet/formation");
      life.check();
      applyFormation(status);
    } catch (err) {
      if (err.name === "AbortError") return;
      const wasActive = view.formation?.active === true;
      view.formation = null;
      view.formationUnavailable = true;
      const state = el("formation-state");
      state.textContent = "확인 불가";
      state.removeAttribute("title");
      state.setAttribute("status", "warn");
      el("formation-detail").textContent = `대형 상태를 읽지 못했습니다 · 새 상태를 기다리는 중 — ${err.message}`;
      for (const id of ["formation-start", "formation-reform", "formation-resume"]) {
        setOff(id, true, "상태 확인 불가");
      }
      // 마지막 확인 상태가 활성일 때는 해제 요청만 남긴다. 최종 판정은 Fleet API다.
      setOff("formation-stop", !wasActive, "상태 확인 불가");
      render();
    }
  }

  async function formationCall(path, body, label) {
    const life = scope.capture();
    life.check();
    try {
      const status = await call(path, body ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      } : { method: "POST" });
      life.check();
      applyFormation(status);
      log(`대형 ${label} — ${stateLabel(status.state)}`, "good");
    } catch (err) {
      if (err.name === "AbortError") return;
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
    scope.listen(el("formation-start"), "click", () => {
      const body = {
        leader: el("formation-leader").value,
        formation: el("formation-shape").value,
        spacing: Number(el("formation-spacing").value),
      };
      const members = selectedMembers();
      if (members) body.members = members;
      formationCall("/api/fleet/formation/start", body, "무장");
    });

    scope.listen(el("formation-reform"), "click", () => formationCall(
      "/api/fleet/formation/reform",
      { formation: el("formation-shape").value, spacing: Number(el("formation-spacing").value) },
      "변경"));

    scope.listen(el("formation-resume"), "click", () =>
      formationCall("/api/fleet/formation/resume", null, "재개"));

    scope.listen(el("formation-stop"), "click", () =>
      formationCall("/api/fleet/formation/stop", null, "해제"));

    // D-252: 폼이 바뀌면 대기 요약을 갱신한다. 무장 중에는 서버 상태가 주인이므로 건드리지 않는다.
    for (const id of ["formation-leader", "formation-shape", "formation-spacing", "formation-members"]) {
      scope.listen(el(id), "change", syncPendingSummary);
      scope.listen(el(id), "input", syncPendingSummary);
    }
  }

  return { fillLeaders, renderFormation, applyFormation, refreshFormation, bind };
}
