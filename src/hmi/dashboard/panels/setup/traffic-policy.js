function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function field(labelText, name, type = "number") {
  const label = el("label", "surface-field", labelText); const control = el("input");
  control.name = name; control.type = type; control.autocomplete = "off"; label.append(control);
  return {label, control};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "교통 정책 준비");
  const state = el("dl", "traffic-policy-facts"); state.setAttribute("aria-label", "교통 정책 상태");
  const facts = {};
  for (const [key, title] of [["state", "판정"], ["reason", "판정 사유"], ["signal", "신호"], ["stop", "정지선"], ["scene", "scene"], ["revision", "policy"]]) {
    const row = el("div", ""); row.append(el("dt", "", title)); facts[key] = el("dd", "", "—"); row.append(facts[key]); state.append(row);
  }
  const form = el("form", "surface-form");
  const modeLabel = el("label", "surface-field", "정책 모드"); const mode = el("select"); mode.name = "mode";
  for (const value of ["DISABLED", "ADVISORY", "ENFORCED"]) { const option = el("option", "", value); option.value = value; mode.append(option); }
  modeLabel.append(mode);
  const revision = field("정책 revision", "policy_revision", "text"); revision.control.maxLength = 80;
  const approach = field("접근 거리 (m)", "approach_distance_m"); approach.control.min = "0.13"; approach.control.max = "3"; approach.control.step = "0.01";
  const stop = field("정지 거리 (m)", "stop_distance_m"); stop.control.min = "0.01"; stop.control.max = "2.9"; stop.control.step = "0.01";
  const dwell = field("정지 대기 (s)", "stop_dwell_s"); dwell.control.min = "0.1"; dwell.control.max = "10"; dwell.control.step = "0.1";
  const confidence = field("최소 신뢰도", "min_confidence"); confidence.control.min = "0.01"; confidence.control.max = "1"; confidence.control.step = "0.01";
  const stage = el("ui-button", "", "정책 검토본 저장"); stage.type = "button";
  const apply = el("ui-button", "", "정지 상태에서 적용"); apply.type = "button"; apply.disabled = true;
  const signals = el("div", "traffic-policy-actions"); signals.setAttribute("role", "group"); signals.setAttribute("aria-label", "시뮬레이션 신호등 제어");
  const signalButtons = ["RED", "YELLOW", "GREEN"].map((colour) => { const button = el("ui-button", "", colour); button.type = "button"; button.dataset.signal = colour; button.disabled = true; signals.append(button); return button; });
  const message = el("p", "surface-message", "정책 readback 대기"); message.setAttribute("role", "status");
  form.append(modeLabel, revision.label, approach.label, stop.label, dwell.label, confidence.label, stage, apply);
  root.append(head, state, form, signals, message);

  let current = null; let pending = false; let dirty = false;
  function render(readback = {}) {
    current = readback;
    const status = readback.status || {};
    facts.state.textContent = status.state || "DISABLED"; facts.reason.textContent = status.reason || "policy_disabled";
    facts.signal.textContent = status.signal_conflict ? "CONFLICT" : (status.signal_colour || "—");
    facts.stop.textContent = Number.isFinite(Number(status.stop_line_distance_m)) ? `${Number(status.stop_line_distance_m).toFixed(3)} m` : "—";
    facts.scene.textContent = status.scene_revision || "—"; facts.revision.textContent = status.policy_revision || "—";
    const draft = readback.staged || readback.active || {};
    if (!dirty) {
      mode.value = draft.mode || "DISABLED"; revision.control.value = draft.policy_revision || "";
      approach.control.value = draft.approach_distance_m ?? ""; stop.control.value = draft.stop_distance_m ?? "";
      dwell.control.value = draft.stop_dwell_s ?? ""; confidence.control.value = draft.min_confidence ?? "";
    }
    apply.disabled = pending || !readback.staged;
    signalButtons.forEach((button) => { button.disabled = pending || readback.simulation_signal?.available !== true; });
    if (!dirty) message.textContent = readback.staged ? `검토 대기: ${readback.staged.policy_revision}` : `적용됨: ${readback.active?.policy_revision || "—"}`;
  }
  const stopPoll = ctx.store.poll("/api/v1/traffic", 2_000, render, (error) => { message.textContent = `교통 정책을 읽지 못했습니다: ${error.message}`; });
  form.addEventListener("input", () => { dirty = true; });
  stage.addEventListener("click", async () => {
    if (pending) return;
    const body = {mode: mode.value, policy_revision: revision.control.value.trim(),
      approach_distance_m: Number(approach.control.value), stop_distance_m: Number(stop.control.value),
      stop_dwell_s: Number(dwell.control.value), min_confidence: Number(confidence.control.value)};
    pending = true; stage.disabled = true;
    try {
      const readback = await ctx.api("/api/v1/traffic/policy/stage", {method: "POST", body: JSON.stringify(body)});
      dirty = false; render(readback); message.textContent = `검토본 저장됨: ${body.policy_revision}`;
    } catch (error) { message.textContent = `정책 검증 실패: ${error.message}`; }
    finally { pending = false; render(current || {}); }
  });
  apply.addEventListener("click", async () => {
    if (pending || !current?.staged) return;
    if (!window.confirm("로봇이 완전히 정지했습니까? 검토 중인 교통 정책을 적용합니다.")) return;
    pending = true; apply.disabled = true;
    try { const readback = await ctx.api("/api/v1/traffic/policy/apply", {method: "POST"}); dirty = false; render(readback); message.textContent = "정지 상태에서 정책 적용을 요청했습니다."; }
    catch (error) { message.textContent = `정책 적용 실패: ${error.message}`; }
    finally { pending = false; render(current || {}); }
  });
  signalButtons.forEach((button) => button.addEventListener("click", async () => {
    if (pending || button.disabled) return;
    pending = true; button.disabled = true;
    try {
      await ctx.api("/api/v1/traffic/simulation/signal", {method: "PUT", body: JSON.stringify({colour: button.dataset.signal})});
      render(await ctx.api("/api/v1/traffic"));
    } catch (error) { message.textContent = `시뮬레이션 신호 변경 실패: ${error.message}`; }
    finally { pending = false; render(current || {}); }
  }));
  return () => stopPoll();
}
