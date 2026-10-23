// Control-unit candidates remain separate from local Task execution and physical stop evidence.
const labels = {PENDING: "현장 승인 대기", APPROVING: "승인 접수 · 작업 결속 확인 중", REQUESTED: "요청 접수",
  QUEUED: "실행 대기", ACCEPTED: "장치 수락", RUNNING: "실행 중", UNKNOWN: "실행 결과 미확인",
  HOLD: "보류", COMPLETED: "작업 완료", FAILED: "실패", CANCELED: "취소", EXPIRED: "만료"};
const terminal = new Set(["COMPLETED", "FAILED", "CANCELED", "EXPIRED"]);
const node = (tag, text, className) => Object.assign(document.createElement(tag),
  {textContent: text || "", ...(className ? {className} : {})});

export function createControlUnitView({scope, call, parent, active, approveReason, principal}) {
  const panel = node("section"), heading = node("h2", "관제 간 작업"), context = node("p"),
    state = node("p"), list = node("ul", "", "work-list"), notice = node("p");
  panel.id = "control-unit-work"; heading.id = "control-unit-heading";
  panel.setAttribute("aria-labelledby", heading.id); panel.hidden = true;
  notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite");
  const form = node("form", "", "ui-form"), fields = {};
  for (const [name, label, numeric] of [["target_unit", "대상 관제", false], ["robot_id", "담당 로봇", false],
    ["x", "목표 X (m)", true], ["y", "목표 Y (m)", true], ["yaw", "목표 방향 (rad)", true]]) {
    const field = node("label", label, "ui-field-label"), input = node("input", "", "ui-field");
    input.id = "control-unit-" + name; input.name = name; input.required = true;
    input.type = numeric ? "number" : "text";
    if (numeric) { input.step = "any"; input.value = "0"; }
    else { input.maxLength = 64; input.pattern = "[A-Za-z0-9][A-Za-z0-9_.:-]*"; }
    field.htmlFor = input.id; field.append(input); form.append(field); fields[name] = input;
  }
  function button(text, kind = "quiet") {
    const control = node("ui-button", text);
    control.setAttribute("kind", kind); control.setAttribute("type", "button"); return control;
  }
  function guard(control, reason) {
    control.disabled = Boolean(reason);
    if (reason) control.setAttribute("reason", reason); else control.removeAttribute("reason");
  }
  const send = button("대상 관제에 요청", "primary"), fresh = button("새 요청 작성"),
    actions = node("div", "", "ui-actions"), disclosure = node("details");
  actions.append(send, fresh); form.append(actions);
  disclosure.append(node("summary", "관제에 작업 요청"), form);
  panel.append(heading, context, state, list, disclosure, notice,
    node("p", "취소 요청은 실제 정지 확인과 별개입니다. 소유 관제의 작업 결과와 장치 근거를 확인하세요.", "hint"));
  parent.append(panel);
  let revision = 0, inFlight = false, busy = false, available = false, unit = null, identity = crypto.randomUUID();
  let draft = null, draftKey = null;
  function saveDraft() {
    sessionStorage.setItem(draftKey, JSON.stringify(draft));
  }
  function draftControls() {
    for (const field of Object.values(fields)) field.readOnly = Boolean(draft);
  }
  function loadDraft() {
    const owner = principal();
    if (!owner) throw new Error("named identity required");
    const key = "rosy.control-unit.pending:" + JSON.stringify([owner, unit.unit_id]);
    if (key === draftKey) return;
    draftKey = key; draft = null;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key));
      if (saved?.body && typeof saved.body.delegation_id === "string" && saved.body.goal
          && typeof saved.body.target_unit === "string" && typeof saved.body.robot_id === "string") {
        draft = saved; identity = saved.body.delegation_id;
        for (const name of ["target_unit", "robot_id"]) fields[name].value = saved.body[name];
        for (const name of ["x", "y", "yaw"]) fields[name].value = saved.body.goal[name];
        notice.textContent = saved.confirmed ? "이전 요청을 복원했습니다. 새 의도는 새 요청 작성으로 시작하세요."
          : "요청 결과 미확인 · 같은 요청을 다시 확인합니다.";
      }
    } catch { notice.textContent = "브라우저의 요청 저장 상태를 확인하세요."; }
    draftControls();
  }
  function reset() {
    revision++; available = false; unit = null; panel.hidden = true; list.replaceChildren(); notice.textContent = "";
    identity = crypto.randomUUID(); form.reset();
    draft = null; draftKey = null; draftControls();
  }
  function controls() {
    guard(send, busy ? "요청 결과를 확인하고 있습니다" : !available ? "관제 연결을 확인하세요" : approveReason());
    guard(fresh, busy ? "요청 결과를 확인하고 있습니다" : draft && !draft.confirmed ? "미확인 요청의 원장을 먼저 확인하세요" : "");
  }
  async function change(path, body, message) {
    if (busy || !available || approveReason()) return;
    const life = scope.capture(), version = revision; busy = true; controls();
    notice.textContent = "요청 결과를 확인하고 있습니다.";
    try {
      await call(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      life.check();
      if (version === revision) {
        if (path === "/api/fleet/control-unit/delegations" && draft) { draft.confirmed = true; saveDraft(); }
        notice.textContent = message;
      }
    } catch (error) {
      if (life.current() && version === revision) notice.textContent = error.status >= 400 && error.status < 500
        ? "요청이 거절됐습니다. 대상과 최신 원장을 확인하세요."
        : "요청 결과 미확인 · 자동으로 다시 보내지 않았습니다. 같은 요청의 원장을 확인하세요.";
    } finally {
      busy = false;
      if (life.current() && version === revision) { controls(); await refresh(); }
    }
  }
  scope.listen(send, "click", () => {
    if (!form.reportValidity()) return;
    if (!draft) draft = {confirmed: false, body: {delegation_id: identity,
      target_unit: fields.target_unit.value, robot_id: fields.robot_id.value,
      goal: {x: Number(fields.x.value), y: Number(fields.y.value), yaw: Number(fields.yaw.value)}}};
    try { saveDraft(); } catch { notice.textContent = "요청 식별을 보존하지 못했습니다. 브라우저 저장 설정을 확인하세요."; return; }
    draftControls(); controls();
    change("/api/fleet/control-unit/delegations", draft.body,
    "요청을 접수했습니다. 최종 대상 관제에서 별도로 승인합니다.");
  });
  scope.listen(form, "submit", event => event.preventDefault());
  scope.listen(fresh, "click", () => {
    if (busy || (draft && !draft.confirmed)) return;
    try { if (draftKey) sessionStorage.removeItem(draftKey); } catch { return; }
    draft = null; identity = crypto.randomUUID(); form.reset(); draftControls(); controls();
    notice.textContent = "새 요청을 작성하세요.";
  });
  function paint(replies) {
    const focused = document.activeElement?.closest("[data-delegation-action]")?.dataset.delegationAction;
    list.replaceChildren(); list.hidden = !replies.length;
    state.textContent = replies.length ? `${replies.length}건 · 최근 위임 기록` : "관제 간 작업 요청이 없습니다.";
    for (const reply of replies) {
      const row = reply.delegation, item = node("li"), actions = node("div", "", "ui-actions");
      item.append(node("h3", `${row.request.target_unit} · ${row.request.robot_id}`),
        node("p", `요청 관제 ${row.origin_id} · 실행 담당 관제 ${row.owner_unit}`),
        node("p", `목표 X ${row.request.goal.x} m · Y ${row.request.goal.y} m · 방향 ${row.request.goal.yaw} rad`),
        node("p", `위임 ${row.origin_id} / ${row.delegation_id}`, "hint"),
        node("p", `${labels[row.status] || "상태 확인 필요"}${row.cancel_requested ? " · 취소 요청 전달 중" : ""}`),
        node("p", reply.stale ? "소유 관제 연결을 확인하세요 · 이전 결과입니다." :
          `원장 확인 ${new Date(row.updated_at).toLocaleString()}`, "hint"));
      const path = `/api/fleet/control-unit/delegations/${encodeURIComponent(row.origin_id)}/${encodeURIComponent(row.delegation_id)}`;
      if (row.request.target_unit === unit.unit_id && !row.local_task_id && !terminal.has(row.status)) {
        const approve = button("이 관제에서 승인", "primary");
        approve.dataset.delegationAction = JSON.stringify([row.origin_id, row.delegation_id, "approve"]);
        guard(approve, reply.stale ? "소유 관제 연결을 확인하세요" : row.cancel_requested ? "취소 요청된 작업입니다" :
          busy ? "요청 결과를 확인하고 있습니다" : approveReason());
        approve.addEventListener("click", () => change(path + "/approve", {expected_revision: row.revision},
          "승인을 접수했습니다. 작업 원장에서 실행 결과를 확인하세요."));
        actions.append(approve);
      }
      if (!terminal.has(row.status)) {
        const cancel = button("취소 요청");
        cancel.dataset.delegationAction = JSON.stringify([row.origin_id, row.delegation_id, "cancel"]);
        guard(cancel, reply.stale ? "소유 관제 연결을 확인하세요" : row.cancel_requested ? "소유 관제의 결과를 기다립니다" :
          busy ? "요청 결과를 확인하고 있습니다" : approveReason());
        cancel.addEventListener("click", () => change(path + "/cancel", {}, "취소를 요청했습니다. 소유 관제의 결과를 기다립니다."));
        actions.append(cancel);
      }
      if (row.local_actor) item.append(node("p", `현장 승인 ${row.local_actor}`, "hint"));
      if (row.result?.task_id) item.append(node("p", `연결된 작업 ${row.result.task_id}`, "hint"));
      item.append(actions); list.append(item);
      for (const action of actions.children) if (action.dataset.delegationAction === focused) action.focus({preventScroll: true});
    }
  }
  async function refresh() {
    if (!active || inFlight || busy) return;
    const life = scope.capture(), version = revision; inFlight = true;
    try {
      const summary = await call("/api/fleet/control-unit"); life.check();
      const result = await call("/api/fleet/control-unit/delegations"); life.check();
      if (version !== revision) return;
      unit = summary; available = true; panel.hidden = false;
      loadDraft();
      if (draft && !draft.confirmed) {
        try {
          await call(`/api/fleet/control-unit/delegations/${encodeURIComponent(unit.unit_id)}/${encodeURIComponent(identity)}`);
          life.check(); if (version !== revision) return;
          draft.confirmed = true; saveDraft(); notice.textContent = "같은 요청의 원장을 확인했습니다.";
        } catch { life.check(); if (version !== revision) return; }
      }
      context.textContent = `${unit.unit_id} · ${unit.parent ? "상위 관제 " + unit.parent : "독립 관제"} · 하위 관제 ${unit.children.join(", ") || "없음"}`;
      if (!fields.target_unit.value) fields.target_unit.value = unit.unit_id;
      paint(result.delegations); controls();
    } catch (error) {
      if (life.current() && version === revision) {
        available = false; list.replaceChildren(); controls();
        if (!unit && error.status === 404) panel.hidden = true;
        else { panel.hidden = false; state.textContent = "관제 원장 조회 실패 · 접속 권한과 연결을 확인하세요."; }
      }
    } finally { inFlight = false; }
  }
  return {refresh, reset};
}
