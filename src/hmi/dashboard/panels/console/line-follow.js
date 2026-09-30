import { enumLabel } from "/common/core_ui_logic.js";
import { setOff } from "/assets/dom.js";

// D-359 US-009 — 추종 모드 열거값은 요청 본문과 title에만, 운용자 글은 한국어다.
const LINE_MODE_LABEL = Object.freeze({ OFF: "꺼짐", IR_LINE: "적외선 센서", CAMERA_LINE: "카메라" });

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "차선 추종");
  const modeStatus = el("ui-status", "", "차선 추종 상태를 읽는 중입니다.");
  const capabilityStatus = el("ui-status", "", "내비게이션 기능을 확인하는 중입니다.");
  const actionStatus = el("ui-status");
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
  form.append(label, start, stop); root.append(head, modeStatus, capabilityStatus, actionStatus, facts, form);

  let current = null;
  let statusKnown = false;
  let navigationAvailable = false;
  let pending = false;
  function setStatus(target, text) { if (target.textContent !== text) target.textContent = text; }
  function render() {
    if (statusKnown && current) {
      facts.replaceChildren(el("dt", "", "모드"), el("dd", "", enumLabel(LINE_MODE_LABEL, current.mode || "OFF")),
        el("dt", "", "상태"), el("dd", "", current.state || "OFF"),
        el("dt", "", "센서"), el("dd", "", current.source || "—"),
        el("dt", "", "추종 오차"), el("dd", "", current.error == null ? "—" : Number(current.error).toFixed(3)),
        el("dt", "", "신뢰도"), el("dd", "", current.confidence == null ? "—" : `${Math.round(Number(current.confidence) * 100)}%`),
        el("dt", "", "중지 사유"), el("dd", "", current.reason || "—"));
    } else facts.replaceChildren(el("dt", "", "상태"), el("dd", "", "확인 불가 · 다시 확인 중"));
    // 요청 중(pending)은 짧은 잠금이라 사유 없이 끈다.
    const known = pending ? "" : !statusKnown ? "상태 확인 중" : "";
    setOff(start, pending || !statusKnown || !navigationAvailable || current?.mode !== "OFF",
      known || (pending ? "" : !navigationAvailable ? "내비게이션을 쓸 수 없음" : "이미 추종 중"));
    setOff(stop, pending || !statusKnown || current?.mode === "OFF", known || (pending ? "" : "추종 중 아님"));
  }
  const stopState = ctx.store.poll("/api/v1/line-follow", 1_000, (data) => {
    current = data && typeof data === "object" ? data : null;
    statusKnown = typeof current?.mode === "string";
    setStatus(modeStatus, statusKnown ? `차선 추종 ${enumLabel(LINE_MODE_LABEL, current.mode || "OFF")}` : "차선 추종 상태 응답이 불완전합니다. 다시 확인 중입니다."); render();
  }, (error) => {
    current = null; statusKnown = false;
    setStatus(modeStatus, `차선 추종 상태를 읽지 못했습니다: ${error.message}`); render();
  });
  const stopCapabilities = ctx.store.poll("/api/v1/system/capabilities", 5_000, (data) => {
    navigationAvailable = data?.navigation?.goal_navigation === true;
    setStatus(capabilityStatus, navigationAvailable
      ? "내비게이션 기능을 쓸 수 있습니다."
      : `내비게이션을 쓸 수 없습니다.${data?.navigation?.reason ? ` ${data.navigation.reason}` : " 현재 실행 모드에서 막혔거나 이 로봇에 없는 기능입니다."}`);
    capabilityStatus.setAttribute("state", navigationAvailable ? "ready" : "warning");
    render();
  }, (error) => {
    navigationAvailable = false;
    capabilityStatus.textContent = `내비게이션 기능을 확인할 수 없습니다: ${error.message}`;
    capabilityStatus.setAttribute("state", "error"); render();
  });
  async function setMode(mode) {
    if (pending || !statusKnown || (mode !== "OFF" && !navigationAvailable)) return;
    if (mode !== "OFF" && !window.confirm("차선 추종을 시작할까요? 주변 안전을 확인하세요.")) return;
    pending = true; render();
    setStatus(actionStatus, mode === "OFF" ? "차선 추종 중지 요청을 보내는 중입니다." : `${enumLabel(LINE_MODE_LABEL, mode)} 추종 시작 요청을 보내는 중입니다.`);
    if (mode !== "OFF") window.dispatchEvent(new Event("rosy:stop-motion"));
    try {
      const result = await ctx.api("/api/v1/line-follow/mode", {method: "PUT", body: JSON.stringify({mode})});
      if (result && typeof result.mode === "string") { current = result; statusKnown = true; }
      setStatus(actionStatus, mode === "OFF" ? "차선 추종 중지 요청을 CORE가 받았습니다. 현재 상태로 완료 여부를 확인하세요." : `${enumLabel(LINE_MODE_LABEL, mode)} 추종 시작 요청을 CORE가 받았습니다. 현재 상태로 시작 여부를 확인하세요.`);
    } catch (error) { setStatus(actionStatus, `차선 추종 요청 실패: ${error.message}`); }
    finally { pending = false; render(); }
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
    unmount() { stopState(); stopCapabilities(); },
  };
}
