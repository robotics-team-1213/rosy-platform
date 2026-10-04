import { confirmIrreversible } from "/common/ui.js";
import { enumLabel, TRAFFIC_MODE_LABEL, TRAFFIC_STATE_LABEL, TRAFFIC_REASON_LABEL,
  TRAFFIC_SIGNAL_LABEL, TRAFFIC_SOURCE_LABEL, TRAFFIC_RULE_LABEL } from "/common/core_ui_logic.js";

// D-359: short request locks have live feedback; lasting locks give a reason.
function setOff(control, off, reason = "") {
  control.disabled = Boolean(off);
  if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason");
}
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function field(labelText, name, type = "number") {
  const label = el("label", "ui-field-label", labelText); const control = el("input", "ui-field");
  control.name = name; control.type = type; control.autocomplete = "off"; label.append(control);
  return {label, control};
}
function select(labelText, name, labels) {
  const label = el("label", "ui-field-label", labelText); const control = el("select", "ui-field");
  control.name = name; control.append(new Option("정보 없음", ""));
  for (const [value, title] of Object.entries(labels)) control.append(new Option(title, value));
  label.append(control); return {label, control};
}
function selected(control, value) {
  const key = value ?? "";
  if (![...control.options].some(option => option.value === key)) control.append(new Option(String(key), key));
  control.value = key;
}
function result() { const node = el("ui-status", "", ""); node.hidden = true; node.setAttribute("state", "ready"); return node; }
function section(title, cls) { const node = el("section", `ui-readback ${cls}`); node.append(el("h3", "", title)); return node; }

export function mount(root, ctx) {
  let confirming = false;
  const lifetime = new AbortController(); let disposed = false;
  const listen = (node, name, handler) => node.addEventListener(name, handler, {signal: lifetime.signal});
  const head = el("ui-head", "", "교통 정책 준비");
  const currentSection = section("현재 정책", "traffic-policy-current");
  const state = el("dl", "traffic-policy-facts"); state.setAttribute("aria-label", "교통 정책 상태");
  const facts = {};
  for (const [key, title] of [["state", "판정"], ["reason", "판정 사유"], ["signal", "신호"],
    ["stop", "정지선"], ["rule", "정지선 규칙"], ["source", "신호원"], ["scene", "도로 장면"], ["revision", "적용 정책"]]) {
    const row = el("div", ""); row.append(el("dt", "", title)); facts[key] = el("dd", "", "—"); row.append(facts[key]); state.append(row);
  }
  const pollStatus = result(); pollStatus.hidden = false; pollStatus.textContent = "현재 정책 정보 대기";
  currentSection.append(state, pollStatus);
  const form = el("form", "ui-form traffic-policy-draft"); form.setAttribute("aria-label", "정책 입력");
  const mode = select("정책 모드", "mode", TRAFFIC_MODE_LABEL);
  const rule = select("정지선 규칙", "junction_rule", TRAFFIC_RULE_LABEL);
  const revision = field("정책 이름", "policy_revision", "text"); revision.control.maxLength = 80;
  const approach = field("접근 거리 (m)", "approach_distance_m"); approach.control.min = "0.13"; approach.control.max = "3"; approach.control.step = "0.01";
  const stop = field("정지 거리 (m)", "stop_distance_m"); stop.control.min = "0.01"; stop.control.max = "2.9"; stop.control.step = "0.01";
  const dwell = field("정지 대기 (s)", "stop_dwell_s"); dwell.control.min = "0.1"; dwell.control.max = "10"; dwell.control.step = "0.1";
  const confidence = field("최소 신뢰도", "min_confidence"); confidence.control.min = "0.01"; confidence.control.max = "1"; confidence.control.step = "0.01";
  const inputs = [mode, rule, revision, approach, stop, dwell, confidence];
  const stage = el("ui-button", "", "정책 검토본 저장"); stage.setAttribute("kind", "primary"); stage.type = "button";
  const stageResult = result(); const stageActions = el("ui-actions", ""); stageActions.append(stage);
  form.append(el("h3", "", "정책 입력"), ...inputs.map(input => input.label), stageActions, stageResult);
  const review = section("저장된 검토본 적용", "traffic-policy-review");
  const reviewed = el("p", "", "저장된 검토본 없음");
  const apply = el("ui-button", "", "정지 상태에서 적용"); apply.setAttribute("kind", "quiet"); apply.type = "button";
  const applyResult = result(); const applyActions = el("ui-actions", ""); applyActions.append(apply);
  review.append(reviewed, el("p", "", "검토본 저장 후 로봇의 정지를 확인하고 적용하세요."), applyActions, applyResult);
  const simulation = section("시뮬레이션 신호", "traffic-policy-simulation");
  const signals = el("ui-actions", "traffic-policy-actions"); signals.setAttribute("role", "group"); signals.setAttribute("aria-label", "시뮬레이션 신호등 제어");
  const signalButtons = ["RED", "YELLOW", "GREEN"].map(colour => {
    const button = el("ui-button", "", enumLabel(TRAFFIC_SIGNAL_LABEL, colour));
    button.setAttribute("kind", "quiet"); button.type = "button"; button.dataset.signal = colour; signals.append(button); return button;
  });
  const signalResult = result(); simulation.append(signals, signalResult);
  root.append(head, currentSection, form, review, simulation);

  let current = {}; let pending = false; let dirty = false; let readbackKnown = false;
  function feedback(node, text, value = "ready") { node.textContent = text; node.hidden = !text; node.setAttribute("state", value); }
  function renderControls() {
    inputs.forEach(input => setOff(input.control, pending, ""));
    setOff(stage, pending, "");
    const applyReason = dirty ? "입력 변경: 검토본을 다시 저장하세요"
      : !readbackKnown ? "현재 정책 정보를 확인할 수 없습니다" : !current.staged ? "저장된 검토본 없음" : "";
    setOff(apply, pending || Boolean(applyReason), pending ? "" : applyReason);
    signalButtons.forEach(button => setOff(button, pending || !readbackKnown || current.simulation_signal?.available !== true,
      pending ? "" : !readbackKnown ? "현재 정책 정보를 확인할 수 없습니다" : "시뮬레이션 신호 없음"));
    root.setAttribute("aria-busy", String(pending));
  }
  function renderDraft() {
    if (dirty || pending) return;
    const draft = current.staged || current.active || {};
    selected(mode.control, draft.mode); selected(rule.control, draft.junction_rule);
    revision.control.value = draft.policy_revision ?? "";
    for (const input of [approach, stop, dwell, confidence]) input.control.value = draft[input.control.name] ?? "";
  }
  function render(readback = {}) {
    if (disposed) return;
    current = readback || {};
    readbackKnown = Boolean(current.active && typeof current.active === "object" && !Array.isArray(current.active)
      && current.status && typeof current.status === "object" && !Array.isArray(current.status));
    const status = current.status || {};
    for (const [key, labels, value] of [["state", TRAFFIC_STATE_LABEL, status.state], ["reason", TRAFFIC_REASON_LABEL, status.reason],
      ["signal", TRAFFIC_SIGNAL_LABEL, status.signal_conflict === true ? "CONFLICT" : status.signal_colour],
      ["rule", TRAFFIC_RULE_LABEL, status.junction_rule], ["source", TRAFFIC_SOURCE_LABEL, status.signal_source_kind]]) {
      facts[key].textContent = enumLabel(labels, value); facts[key].title = value ?? "";
    }
    if (status.signal_head_frozen === true) facts.source.textContent += " · 갱신 중단";
    facts.stop.textContent = typeof status.stop_line_distance_m === "number" && Number.isFinite(status.stop_line_distance_m)
      ? `${status.stop_line_distance_m.toFixed(3)} m` : "—";
    facts.scene.textContent = status.scene_revision || "—"; facts.revision.textContent = status.policy_revision || "—";
    reviewed.textContent = current.staged ? `검토본: ${current.staged.policy_revision ?? "—"}` : "저장된 검토본 없음";
    feedback(pollStatus, readbackKnown ? "" : "현재 정책 정보를 확인할 수 없습니다", "unavailable");
    renderDraft(); renderControls();
  }
  renderControls();
  let pollGeneration = 0; let stopPoll = () => {};
  function pausePoll() { pollGeneration++; stopPoll(); stopPoll = () => {}; }
  function startPoll() {
    if (disposed) return;
    const attempt = ++pollGeneration;
    stopPoll = ctx.store.poll("/api/v1/traffic", 2_000, readback => {
      if (!disposed && attempt === pollGeneration) render(readback);
    }, error => {
      if (disposed || attempt !== pollGeneration) return;
      readbackKnown = false;
      feedback(pollStatus, `현재 정책 정보를 확인할 수 없습니다: ${error.message}`, "error"); renderControls();
    });
  }
  startPoll();
  listen(form, "submit", event => event.preventDefault());
  listen(form, "input", () => { if (!pending) { dirty = true; renderControls(); } });
  async function request(node, waiting, failure, action) {
    pausePoll();
    pending = true; renderControls(); feedback(node, waiting, "pending");
    try { await action(); }
    catch (error) {
      if (!disposed) {
        readbackKnown = false;
        feedback(node, `${failure}: ${error.message}`, "error");
        feedback(pollStatus, "변경 후 현재 정책 정보를 확인하고 있습니다.", "pending");
      }
    }
    finally { if (!disposed) { pending = false; renderDraft(); renderControls(); startPoll(); } }
  }
  listen(stage, "click", () => {
    if (pending) return;
    const body = {mode: mode.control.value, junction_rule: rule.control.value, policy_revision: revision.control.value.trim(),
      approach_distance_m: Number(approach.control.value), stop_distance_m: Number(stop.control.value),
      stop_dwell_s: Number(dwell.control.value), min_confidence: Number(confidence.control.value)};
    request(stageResult, "검토본을 저장하고 있습니다.", "정책 검증 실패", async () => {
      const readback = await ctx.api("/api/v1/traffic/policy/stage", {method: "POST", body: JSON.stringify(body), signal: lifetime.signal});
      if (disposed) return;
      dirty = false; render(readback); feedback(stageResult, `검토본 저장됨: ${body.policy_revision}`);
    });
  });
  listen(apply, "click", async () => {
    if (pending || dirty || !readbackKnown || !current.staged) return;
    if (confirming) return;
    confirming = true;
    const review = JSON.stringify(current.staged);
    const confirmed = await confirmIrreversible({message: "로봇이 완전히 정지했습니까? 검토 중인 교통 정책을 적용합니다.", action: "정책 적용", opener: apply, signal: lifetime.signal});
    confirming = false;
    if (!confirmed || disposed || pending || dirty || !readbackKnown || !current.staged || review !== JSON.stringify(current.staged)) return;
    request(applyResult, "정책 적용을 요청하고 있습니다.", "정책 적용 실패", async () => {
      const readback = await ctx.api("/api/v1/traffic/policy/apply", {method: "POST", signal: lifetime.signal});
      if (disposed) return;
      render(readback); feedback(applyResult, "정지 상태에서 정책 적용을 요청했습니다.");
    });
  });
  signalButtons.forEach(button => listen(button, "click", () => {
    if (pending || !readbackKnown || current.simulation_signal?.available !== true) return;
    request(signalResult, "신호 변경을 요청하고 있습니다.", "시뮬레이션 신호 변경 실패", async () => {
      await ctx.api("/api/v1/traffic/simulation/signal", {method: "PUT", body: JSON.stringify({colour: button.dataset.signal}), signal: lifetime.signal});
      if (disposed) return;
      render(await ctx.api("/api/v1/traffic", {signal: lifetime.signal}));
      if (!disposed) feedback(signalResult, "시뮬레이션 신호 변경을 요청했습니다.");
    });
  }));
  return () => { disposed = true; lifetime.abort(); pausePoll(); };
}
