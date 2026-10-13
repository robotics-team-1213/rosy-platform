import { enumLabel, LINE_STATE_LABEL } from "/common/core_ui_logic.js";
import { confirmIrreversible } from "/common/ui.js";

// D-359 US-009 — 추종 모드 열거값은 요청 본문과 title에만, 운용자 글은 한국어다.
const LINE_MODE_LABEL = Object.freeze({ OFF: "꺼짐", IR_LINE: "적외선 센서", CAMERA_LINE: "카메라" });
const PAINT_LABEL = {learned: "학습 모델", denoise: "OpenCV 반사 제거", threshold: "기존 검출"};
const ACTUAL_PAINT_LABEL = {...PAINT_LABEL, denoise_fallback: "학습 미사용 · 전처리 대체"};
function actualPaintText(config) {
  const source = ACTUAL_PAINT_LABEL[config.applied_paint_source];
  if (!source || !Number.isFinite(config.applied_source_age_s)
      || config.applied_source_age_s < 0 || config.applied_source_age_s > 2) return "확인 대기";
  const revision = config.applied_paint_source === "learned" && config.applied_model_revision
    ? ` · 모델 ${config.applied_model_revision}` : "";
  const age = Number.isFinite(config.applied_source_age_s)
    ? ` · ${config.applied_source_age_s.toFixed(1)}초 전` : "";
  return `${source}${revision}${age}`;
}

// D-525/D-551 — Fleet의 가상 신호 참고는 표시만 한다(J3 "표시 먼저"). 통과 허가는 관제 통행권(authority)의
// 몫이고 색이 허가가 아니다(D-337). 만료·응답 없음·모르는 등은 "신호 정보 없음"이지 녹색이 아니다.
const LAMP_WORD = Object.freeze({ green: "녹색", yellow: "황색", red: "적색" });
function seconds(value, exact) { return `${exact ? "" : "≥"}${Math.ceil(value)}초`; }
function signalAdviceView(advice, deadline, now) {
  const signal = advice?.signal;
  if (!signal || !LAMP_WORD[signal.lamp] || !(now < deadline)) {
    return { lamp: "unknown", name: "가상 신호", text: "신호 정보 없음", stop: "정지선 거리 모름" };
  }
  const time = signal.lamp === "red"
    ? (Number.isFinite(signal.green_in_s) ? ` · 녹색까지 ${seconds(signal.green_in_s, signal.exact)}` : "")
    : (Number.isFinite(signal.left_s) ? ` · ${seconds(signal.left_s, signal.exact)} 남음` : "");
  const stop = !Number.isFinite(signal.stop_m) ? "정지선 거리 모름"
    : signal.stop_m < 0 ? "정지선 안쪽" : `정지선까지 ${signal.stop_m.toFixed(2)} m`;
  return { lamp: signal.lamp, name: `가상 신호 ${signal.signal_id} · ${signal.approach}`,
    text: `${LAMP_WORD[signal.lamp]}${time}`, stop };
}

// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const lifetime = new AbortController(); let disposed = false; let confirming = false;
  const head = el("ui-head", "", "차선 추종");
  const modeStatus = el("ui-status", "", "차선 추종 상태를 읽는 중입니다.");
  const capabilityStatus = el("ui-status", "", "구동 준비를 확인하는 중입니다.");
  const actionStatus = el("ui-status");
  modeStatus.setAttribute("state", "pending"); capabilityStatus.setAttribute("state", "pending"); actionStatus.setAttribute("state", "ready");
  actionStatus.setAttribute("role", "status");
  actionStatus.setAttribute("aria-live", "polite");
  const facts = el("dl", "ui-readout");
  const form = el("div", "ui-form");
  const label = el("label", "ui-field-label", "추종 모드");
  const select = el("select", "ui-field"); select.setAttribute("aria-label", "차선 추종 모드");
  for (const [value, text] of Object.entries(LINE_MODE_LABEL).filter(([value]) => value !== "OFF")) {
    const option = el("option", "", text); option.value = value; select.append(option);
  }
  label.append(select);
  const start = el("ui-button", "", "추종 시작"); start.setAttribute("kind", "primary"); start.type = "button";
  const stop = el("ui-button", "", "추종 중지"); stop.setAttribute("kind", "quiet"); stop.type = "button";
  const advice = el("section", "line-signal"); advice.setAttribute("aria-label", "가상 신호 참고");
  const adviceKind = el("span", "line-signal-kind", "가상");
  const adviceLamp = el("i", "line-signal-lamp"); adviceLamp.setAttribute("aria-hidden", "true");
  const adviceName = el("span", "line-signal-name"); const adviceText = el("strong", "line-signal-text");
  const adviceStop = el("span", "line-signal-stop");
  const adviceNote = el("small", "line-signal-note", "참고 표시 · 통과 허가는 관제 authority(통행권)가 정합니다");
  adviceText.setAttribute("role", "status");
  advice.append(adviceKind, adviceLamp, adviceName, adviceText, adviceStop, adviceNote);
  form.append(label, start, stop); root.append(head, modeStatus, capabilityStatus, actionStatus, advice, facts, form);
  const perceptionLabel = el("label", "ui-field-label", "차선 인식 방식");
  const perceptionSelect = el("select", "ui-field"); perceptionSelect.setAttribute("aria-label", "차선 인식 방식");
  for (const [value, text] of Object.entries(PAINT_LABEL)) {
    const option = el("option", "", text); option.value = value; perceptionSelect.append(option);
  }
  perceptionLabel.append(perceptionSelect);
  const perceptionApply = el("ui-button", "", "인식 적용"); perceptionApply.type = "button";
  perceptionApply.setAttribute("kind", "quiet");
  const perceptionStatus = el("ui-status", "", "차선 인식 설정 확인 중"); perceptionStatus.setAttribute("role", "status");
  const perceptionReason = el("ui-status", "", ""); perceptionReason.id = "lane-perception-reason";
  perceptionSelect.setAttribute("aria-describedby", perceptionReason.id);
  const perceptionForm = el("div", "ui-form"); perceptionForm.append(perceptionLabel, perceptionApply, perceptionStatus, perceptionReason); root.append(perceptionForm);

  let current = null;
  let statusKnown = false;
  let driveAvailable = false;
  let pending = false;
  let perception = null, robot = null, robotAt = 0, perceptionDirty = false;
  let adviceDeadline = 0, adviceTimer = 0;
  perceptionSelect.addEventListener("change", () => { perceptionDirty = true; });
  function setStatus(target, text) { if (target.textContent !== text) target.textContent = text; }
  function renderAdvice() {
    const view = signalAdviceView(current?.advice, adviceDeadline, Date.now());
    advice.dataset.lamp = view.lamp;
    setStatus(adviceName, view.name); setStatus(adviceText, view.text); setStatus(adviceStop, view.stop);
  }
  function render() {
    renderAdvice();
    if (statusKnown && current) {
      const modeFact = el("dd", "", enumLabel(LINE_MODE_LABEL, current.mode || "OFF"));
      modeFact.title = current.mode || "OFF";
      facts.replaceChildren(el("dt", "", "모드"), modeFact,
        el("dt", "", "상태"), Object.assign(el("dd", "", enumLabel(LINE_STATE_LABEL, current.state)), {title: current.state || ""}),
        el("dt", "", "센서"), el("dd", "", current.source || "—"),
        el("dt", "", "추종 오차"), el("dd", "", current.error == null ? "—" : Number(current.error).toFixed(3)),
        el("dt", "", "신뢰도"), el("dd", "", current.confidence == null ? "—" : `${Math.round(Number(current.confidence) * 100)}%`),
        el("dt", "", "중지 사유"), Object.assign(el("dd", "", enumLabel(LINE_STATE_LABEL, current.reason)), {title: current.reason || ""}));
    } else facts.replaceChildren(el("dt", "", "상태"), el("dd", "", "확인 불가 · 다시 확인 중"));
    // 요청 중(pending)은 짧은 잠금이라 사유 없이 끈다.
    const known = pending ? "" : !statusKnown ? "상태 확인 중" : "";
    setOff(start, pending || !statusKnown || !driveAvailable || current?.mode !== "OFF",
      known || (pending ? "" : !driveAvailable ? "구동 준비가 확인되지 않음" : "이미 추종 중"));
    setOff(stop, pending || !statusKnown || current?.mode === "OFF", known || (pending ? "" : "추종 중 아님"));
    const velocity = robot?.velocity;
    const stationary = Date.now() - robotAt < 2000 && robot?.mode === "IDLE" && velocity?.linear === 0 && velocity?.angular === 0;
    const reason = !perception ? "서버에서 인식 설정을 확인할 수 없습니다" : ctx.role !== "administrator"
      ? "관리자 권한이 필요합니다" : !stationary || !statusKnown || current?.mode !== "OFF" ? "운전을 멈추고 대기 모드에서 적용하세요" : "";
    setOff(perceptionApply, pending || Boolean(reason), pending ? "인식 적용 중" : reason);
    setOff(perceptionSelect, pending || Boolean(reason), pending ? "인식 적용 중" : reason);
    perceptionReason.textContent = pending ? "인식 적용 중" : reason;
    perceptionReason.hidden = !perceptionReason.textContent;
  }
  const stopRobot = ctx.store.poll("/api/v1/robot/state", 1000, (data) => { robot = data; robotAt = Date.now(); render(); },
    () => { robot = null; render(); });
  const stopPerception = ctx.store.poll("/api/v1/line-follow/perception", 1000, (data) => {
    if (pending) return;
    perception = PAINT_LABEL[data?.paint_source] ? data : null;
    if (perception) {
      if (!perceptionDirty) perceptionSelect.value = perception.paint_source;
      perceptionStatus.textContent = `설정: ${PAINT_LABEL[perception.paint_source]} · 실제 추론: ${actualPaintText(perception)}`;
    }
    render();
  }, () => { perception = null; perceptionStatus.textContent = "이 서버에서는 차선 인식 설정을 확인할 수 없습니다"; render(); });
  perceptionApply.addEventListener("click", async () => {
    render(); if (perceptionApply.disabled || pending) return;
    const requested = perceptionSelect.value;
    pending = true; render(); perceptionStatus.textContent = "인식 설정 적용 중";
    try {
      const result = await ctx.api("/api/v1/line-follow/perception", {method: "PUT", body: JSON.stringify({paint_source: requested}), signal: lifetime.signal});
      if (disposed) return;
      if (result?.applied !== true) throw new Error("기기 적용 확인 없음");
      const readback = await ctx.api("/api/v1/line-follow/perception", {signal: lifetime.signal});
      if (disposed) return;
      if (readback?.paint_source !== requested) throw new Error("설정 readback 불일치");
      perception = readback;
      perceptionDirty = false;
      perceptionStatus.textContent = `설정 적용: ${PAINT_LABEL[readback.paint_source]} · 실제 추론: ${actualPaintText(readback)}`;
    } catch (error) { if (disposed) return; perception = null; perceptionStatus.textContent = `인식 적용 실패: ${error.message}`; }
    finally { if (!disposed) { pending = false; render(); } }
  });
  const stopState = ctx.store.poll("/api/v1/line-follow", 1_000, (data) => {
    current = data && typeof data === "object" ? data : null;
    statusKnown = typeof current?.mode === "string";
    // CORE가 남은 수명(expires_in_s)을 준다. 다음 응답이 늦어도 그 시각에 "신호 정보 없음"으로 바뀐다.
    const expiresIn = Number(current?.advice?.expires_in_s);
    adviceDeadline = Number.isFinite(expiresIn) && expiresIn > 0 ? Date.now() + expiresIn * 1000 : 0;
    clearTimeout(adviceTimer);
    if (adviceDeadline) adviceTimer = setTimeout(() => { if (!disposed) renderAdvice(); }, expiresIn * 1000 + 50);
    modeStatus.setAttribute("state", statusKnown ? "ready" : "unavailable");
    setStatus(modeStatus, statusKnown ? `차선 추종 ${enumLabel(LINE_MODE_LABEL, current.mode || "OFF")}` : "차선 추종 상태 응답이 불완전합니다. 다시 확인 중입니다."); render();
  }, (error) => {
    current = null; statusKnown = false; modeStatus.setAttribute("state", "error");
    setStatus(modeStatus, `차선 추종 상태를 읽지 못했습니다: ${error.message}`); render();
  });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 5_000, (data) => {
    driveAvailable = data?.teleop === true && data?.runtime?.drive === "ready";
    setStatus(capabilityStatus, driveAvailable
      ? "구동 준비가 확인되었습니다. 차선 추종은 Nav2 없이 사용할 수 있습니다."
      : "구동 준비가 확인되지 않았습니다. 현재 구동 상태와 조작 권한을 확인하세요.");
    capabilityStatus.setAttribute("state", driveAvailable ? "ready" : "warning");
    render();
  }, (error) => {
    driveAvailable = false;
    capabilityStatus.textContent = `구동 준비를 확인할 수 없습니다: ${error.message}`;
    capabilityStatus.setAttribute("state", "error"); render();
  });
  async function setMode(mode) {
    if (disposed || confirming || pending || !statusKnown || (mode !== "OFF" && (!driveAvailable || current?.mode !== "OFF"))) return;
    if (mode !== "OFF") {
      confirming = true; render();
      const confirmed = await confirmIrreversible({message: "차선 추종을 시작할까요? 주변 안전을 확인하세요.", action: "추종 시작", opener: start, signal: lifetime.signal});
      confirming = false;
      if (disposed) return;
      render();
      if (!confirmed || pending || !statusKnown || !driveAvailable || current?.mode !== "OFF" || select.value !== mode) return;
    }
    pending = true; render();
    setStatus(actionStatus, mode === "OFF" ? "차선 추종 중지 요청을 보내는 중입니다." : `${enumLabel(LINE_MODE_LABEL, mode)} 추종 시작 요청을 보내는 중입니다.`);
    actionStatus.setAttribute("state", "pending");
    if (mode !== "OFF") window.dispatchEvent(new Event("rosy:stop-motion"));
    try {
      const result = await ctx.api("/api/v1/line-follow/mode", {method: "PUT", body: JSON.stringify({mode})});
      if (disposed) return;
      if (result && typeof result.mode === "string") { current = result; statusKnown = true; }
      actionStatus.setAttribute("state", "ready");
      setStatus(actionStatus, mode === "OFF" ? "차선 추종 중지 요청을 CORE가 받았습니다. 현재 상태로 완료 여부를 확인하세요." : `${enumLabel(LINE_MODE_LABEL, mode)} 추종 시작 요청을 CORE가 받았습니다. 현재 상태로 시작 여부를 확인하세요.`);
    } catch (error) { if (!disposed) { actionStatus.setAttribute("state", "error"); setStatus(actionStatus, `차선 추종 요청 실패: ${error.message}`); } }
    finally { if (!disposed) { pending = false; render(); } }
  }
  start.addEventListener("click", () => setMode(select.value));
  stop.addEventListener("click", () => setMode("OFF"));
  render();
  return {
    beforeHide() {
      if (pending) return {message: "차선 추종 요청이 처리 중입니다. 상태 확인 뒤 조작 그룹을 바꾸세요."};
      if (!statusKnown) return {message: "차선 추종 상태를 확인할 수 없어 조작 그룹을 유지합니다."};
      if (current?.mode !== "OFF") return {message: "차선 추종을 중지한 뒤 조작 그룹을 바꾸세요."};
      return true;
    },
    unmount() { disposed = true; clearTimeout(adviceTimer); lifetime.abort(); stopState(); stopCapabilities(); stopRobot(); stopPerception(); },
  };
}
