// 대형 패널 (D-262 Fleet 분해). 리더·모양·간격·팔로워 폼과 시작·변경·재개·해제,
// 대기 요약을 가진다. 지도 오버레이(drawFormationOverlay)는 console.js에 남는다 —
// 그리는 것과 여는 것은 다른 일이다. 서버 기하를 복제하지 않는다.
// 운영자 말은 공용 표(core_ui_logic.js, D-540 6)에서 온다. 열거값은 title에만.
import { FORMATION_SHAPE_LABEL, FORMATION_STATE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { formationReason } from "./motion-readiness.js";

const stateLabel = (state) => enumLabel(FORMATION_STATE_LABEL, state);
const shapeLabel = (shape) => enumLabel(FORMATION_SHAPE_LABEL, shape);
const FORMATION_CAUSE_LABEL = {
  "nav.stuck": "주행 정체", "nav.failed": "주행 실패", "nav.blocked": "주행 경로 막힘",
  "swarm.aborted": "대형 추종 중단", "safety.estop": "비상 정지", stopped: "대형 해제",
};
function formatFormationCause([code, robot]) {
  const label = FORMATION_CAUSE_LABEL[code]
    || (code.startsWith("arming_failed:") ? "대형 준비 실패"
      : code.startsWith("relay_failed:") ? "대형 통신 실패" : "대형 상태 확인 필요");
  return robot ? `${robot} · ${label}` : label;
}
// D-540 6: 비활성 사유는 블록 한 줄(#formation-why)이고 꺼진 버튼은 모두 "위 사유"다.
const ABOVE = "위 사유";
// Many robots: name a few, count the rest (the form and the cards carry every id).
const fewIds = (ids, n = 5) => ids.length > n ? `${ids.slice(0, n).join(", ")} 외 ${ids.length - n}대` : ids.join(", ");
const AFTER_OPEN = "대형 변경·재개·해제는 대형을 시작한 뒤에 씁니다";

export function createFormation({ scope, el, view, log, call, render, namedReason = () => "" }) {
  // 모양 목록도 같은 표에서 온다. 값(열거값)은 요청 본문과 title에만.
  el("formation-shape").replaceChildren(...Object.entries(FORMATION_SHAPE_LABEL).map(([value, label]) =>
    Object.assign(new Option(label, value), { title: value })));
  // 꺼진 버튼은 "위 사유"이고 원인은 #formation-why 한 줄이 말한다.
  function setOff(id, off, reason) {
    const button = el(id);
    button.disabled = off;
    if (off) button.setAttribute("reason", reason);
    else button.removeAttribute("reason");
  }

  // D-540 9: 대형을 열고·바꾸고·재개하는 것은 움직임이다. 해제(formation-stop)는 멈춤이라 열려 있다.
  function setButtons(why, off) {
    const named = namedReason();
    for (const [id, value] of Object.entries(off)) setOff(id, value || (named !== "" && id !== "formation-stop"), ABOVE);
    el("formation-why").textContent = named ? [named, why].filter(Boolean).join(" · ") : why;
  }

  // 팔로워 칸은 리더를 뺀 로봇이다. 리더를 바꾸면 다시 그리되, 운영자가 푼 칸은 그대로 둔다.
  const unchecked = new Set();
  function fillMembers() {
    const leader = el("formation-leader").value;
    const ids = view.robots.map((r) => r.robot_id).filter((id) => id !== leader);
    const box = el("formation-members");
    if (box.dataset.ids === ids.join(",")) return;
    box.dataset.ids = ids.join(",");
    box.replaceChildren(...ids.map((id) => {
      const label = document.createElement("label");
      label.className = "ui-check";
      const input = document.createElement("input");
      input.className = "ui-field";
      input.type = "checkbox";
      input.value = id;
      input.checked = !unchecked.has(id);
      input.addEventListener("change", () => { if (input.checked) unchecked.delete(id); else unchecked.add(id); });
      // 좁은 칸에서는 줄임표로 자르고 전체 id 는 title 로 남긴다.
      const name = document.createElement("span");
      name.textContent = id;
      label.title = id;
      label.append(input, name);
      return label;
    }));
  }

  function fillLeaders() {
    const select = el("formation-leader");
    const ids = view.robots.map((r) => r.robot_id);
    const current = select.value;
    if (select.dataset.ids !== ids.join(",")) {
      select.dataset.ids = ids.join(",");
      select.replaceChildren(...ids.map((id) => new Option(id, id)));
      if (ids.includes(current)) select.value = current;
    }
    syncPendingSummary();
    filterRobots();
  }

  // 로봇이 많으면(10대, 100대) 고르기가 긴 목록이 된다. 찾기 칸 하나가 이 묶음의 모든 로봇 고르기를 거른다.
  // 고른 값은 숨기지 않는다(선택이 화면에서 사라지면 무엇을 보내는지 모른다).
  function filterRobots() {
    const text = el("formation-filter").value.trim().toLowerCase();
    const hit = (id) => !text || id.toLowerCase().includes(text);
    for (const select of document.querySelectorAll(".formation select[data-robot-picker]")) {
      for (const option of select.options) option.hidden = !hit(option.value) && option.value !== select.value;
    }
    for (const label of el("formation-members").children) label.hidden = !hit(label.title);
  }

  const followers = () => [...el("formation-members").querySelectorAll("input:checked")].map((b) => b.value);

  // D-252: 시작 전 확인 문장. 슬롯 좌표는 서버 기하가 쥐고 있어 클라이언트가
  // 미리 그릴 수 없으므로, 폼 현재값을 문장으로 미리 말한다.
  function syncPendingSummary() {
    fillMembers();
    if (view.formationUnavailable || (view.formation && view.formation.active)) return;
    const leader = el("formation-leader").value;
    const shape = el("formation-shape").value;
    const spacing = Number(el("formation-spacing").value);
    const members = followers();
    const reason = view.stateUnavailable ? "Fleet 상태 확인 불가" : formationReason(view.robots, leader, members);
    setButtons(reason ? `${reason} · ${AFTER_OPEN}` : AFTER_OPEN, {
      "formation-start": Boolean(reason), "formation-reform": true, "formation-resume": true, "formation-stop": true,
    });
    el("formation-detail").textContent = reason ? ""
      : `리더 ${leader} · 팔로워 ${members.length}대(${fewIds(members)}) · ${shapeLabel(shape)} · 간격 ${spacing} m`;
  }

  function renderFormation(status) {
    const stateEl = el("formation-state");
    stateEl.textContent = stateLabel(status.state);
    stateEl.title = status.state || "";
    stateEl.setAttribute("status", status.state === "RUNNING" ? "active"
      : status.state === "HOLDING" ? "warn" : "neutral");
    // 대형이 열려 있는 동안에는 리더·팔로워를 바꿀 수 없다 — 해제하고 다시 연다. 모양·간격은
    // 대형 변경이 보내는 값이라 열려 있어야 한다(숨기면 변경 버튼이 보이지 않는 값을 보낸다).
    el("formation-leader").disabled = status.active;
    el("formation-members").querySelectorAll("input").forEach((i) => { i.disabled = status.active; });
    el("formation-form-summary").textContent = status.active ? "모양·간격 바꾸기" : "대형 설정 · 리더와 팔로워";

    const detail = el("formation-detail");
    if (!status.active) {
      syncPendingSummary();
      return;
    }
    // D-359 §5.3 — 사유는 비활성 조건과 같은 식에서 나온다.
    // 재개는 HOLDING(멈춤)에서만 뜻이 있다. RUNNING에서 눌러 봐야 세션이 조용히 무시한다.
    const pending = status.pending_triggers || [];
    const holding = status.state === "HOLDING";
    setButtons(!holding ? "대형 진행 중 · 대형 재개는 대형이 멈췄을 때만 씁니다"
      : pending.length ? "추가 사건이 있습니다 · 대형 변경으로 다시 짜거나 해제하세요"
        : "대형 멈춤 · 대형 재개를 누르면 팔로워가 다시 따라갑니다", {
      "formation-start": true, "formation-reform": false,
      "formation-resume": !holding || pending.length > 0, "formation-stop": false,
    });
    const slots = Object.entries(status.assignment || {})
      .map(([id, slot]) => `${id} 뒤 ${slot.distance.toFixed(2)} m`
        + (Math.abs(slot.lateral) > 1e-6 ? ` · 옆 ${slot.lateral.toFixed(2)} m` : ""));
    const relay = status.relay;
    // D-417 — 요약을 구조화한다(진단 패널과 같은 격자).
    const items = [
      ["리더", status.leader],
      ["모양", `${shapeLabel(status.formation)} · 간격 ${status.spacing} m`],
      ["팔로워", slots.length ? fewIds(slots, 6) : "—"],
    ];
    if (relay) {
      items.push(["릴레이", relay.paused ? "일시정지" : `${relay.leader_rx_hz} Hz`
        + (relay.leader_last_error ? ` (${relay.leader_last_error})` : "")]);
      const errs = Object.entries(relay.follower_last_error || {}).filter(([, e]) => e);
      if (errs.length) items.push(["오류", errs.map(([id, e]) => `${id}: ${e}`).join(", ")]);
    }
    if (status.reason) items.push(["이유", formatFormationCause(status.reason)]);
    if (pending.length) {
      items.push(["재개 차단", pending.map(formatFormationCause).join(", ")]);
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
      el("formation-detail").textContent = "대형 상태를 읽지 못했습니다 · 새 상태를 기다리는 중. Fleet 연결을 확인하세요.";
      // 마지막 확인 상태가 활성일 때는 해제 요청만 남긴다. 최종 판정은 Fleet API다.
      setButtons("대형 상태 확인 불가", { "formation-start": true, "formation-reform": true,
        "formation-resume": true, "formation-stop": !wasActive });
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

  // FOR-001 Robot Selection — 팔로워 전원 체크는 전원 대형이다(members를 보내지 않는다).
  function selectedMembers() {
    const boxes = [...el("formation-members").querySelectorAll("input")];
    if (boxes.length && boxes.some((b) => !b.checked)) return [el("formation-leader").value, ...followers()];
    return null;
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
      formationCall("/api/fleet/formation/start", body, "시작");
    });

    scope.listen(el("formation-reform"), "click", () => formationCall(
      "/api/fleet/formation/reform",
      { formation: el("formation-shape").value, spacing: Number(el("formation-spacing").value) },
      "변경"));

    scope.listen(el("formation-resume"), "click", () =>
      formationCall("/api/fleet/formation/resume", null, "재개"));

    scope.listen(el("formation-stop"), "click", () =>
      formationCall("/api/fleet/formation/stop", null, "해제"));

    scope.listen(el("formation-filter"), "input", filterRobots);
    // D-252: 폼이 바뀌면 대기 요약을 갱신한다. 대형 중에는 서버 상태가 주인이므로 건드리지 않는다.
    for (const id of ["formation-leader", "formation-shape", "formation-spacing", "formation-members"]) {
      scope.listen(el(id), "change", syncPendingSummary);
      scope.listen(el(id), "input", syncPendingSummary);
    }
  }

  return { fillLeaders, renderFormation, applyFormation, refreshFormation, bind };
}
