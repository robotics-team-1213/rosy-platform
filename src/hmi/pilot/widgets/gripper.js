// D-411 C: gripper widget — 열기/반/닫기, an 열림 % slider and a state badge. Every action is
// one absolute, bounded goal (OmxSimGripperGoal); the slider sends once, on release.
import {gripperDuration, gripperPercent, gripperPosition, gripperStateLabel} from "../controls.js";

const PRESETS = [["open", "열기"], ["half", "반"], ["close", "닫기"]];
const BADGE_STATUS = {holding: "active", unknown: "warn"};

function node(tag, attrs = {}, text = "") {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (text) element.textContent = text;
  return element;
}

export function mountGripper(slot, control, session) {
  const g = {open: Number(control.open), closed: Number(control.closed)};
  if (!Number.isFinite(g.open) || !Number.isFinite(g.closed) || g.open === g.closed) {
    throw new Error("gripper open/closed must be finite and differ");
  }
  const presets = control.presets ?? {};
  let blocked = "조작 보류";
  let dragging = false;

  const head = node("div", {class: "gripper-head"});
  const badge = node("ui-tag", {"data-gripper-state": "", role: "status", "aria-live": "polite"});
  head.append(node("h3", {}, control.label || "그리퍼"), badge);
  const row = node("div", {class: "gripper-presets"});
  const buttons = PRESETS.filter(([key]) => Number.isFinite(Number(presets[key]))).map(([key, text]) => {
    const button = node("ui-button", {kind: key === "close" ? "primary" : "quiet", type: "button",
                                      "data-gripper-preset": key}, text);
    row.append(button);
    return button;
  });
  const sliderLabel = node("label", {class: "gripper-slider"});
  const caption = node("span", {}, "열림 ");
  const readout = node("output", {"data-gripper-readout": "", "aria-live": "off"});
  caption.append(readout);
  const slider = node("input", {type: "range", min: "0", max: "100", step: "5", value: "0",
                                "data-gripper-percent": "", "aria-describedby": `gripper-help-${control.id}`});
  sliderLabel.append(caption, slider);
  const help = node("p", {class: "arm-hint", id: `gripper-help-${control.id}`},
                    "놓으면 그 위치로 한 번 움직입니다. 쥐고 있음은 닫다가 물체에 걸려 멈춘 상태입니다(시뮬레이션 위치 판정, 힘 측정 아님).");
  slot.append(head, row, sliderLabel, help);

  const currentPosition = () => {
    const state = session.state();
    const reported = state?.gripper?.position;
    return Number.isFinite(reported) ? reported : state?.positions?.[control.joint];
  };
  function send(position) {
    if (blocked || session.busy()) return;
    session.submitGripper(position, gripperDuration(currentPosition(), position, g));
  }

  function render(state, error) {
    const running = state?.owner_state === "active";
    blocked = error || !state || (!state.ready && !running) ? "조작 보류" : "";
    const reason = blocked || (session.busy() ? "명령 진행 중" : "");
    for (const input of [...buttons, slider]) {
      input.disabled = Boolean(reason);
      if (reason) input.setAttribute("reason", reason); else input.removeAttribute("reason");
    }
    const grip = error || !state ? "unknown" : state.gripper?.state ?? "unknown";
    const label = gripperStateLabel(grip);
    if (badge.textContent !== label) badge.textContent = label;
    badge.dataset.state = grip;
    badge.setAttribute("status", BADGE_STATUS[grip] ?? "neutral");
    const percent = gripperPercent(currentPosition(), g);
    if (!dragging && percent !== null) slider.value = String(percent);
    const text = `${dragging ? slider.value : percent ?? "—"} %`;
    if (readout.textContent !== text) readout.textContent = text;
  }

  for (const button of buttons) {
    button.addEventListener("click", () => send(Number(presets[button.dataset.gripperPreset])));
  }
  slider.addEventListener("pointerdown", () => { dragging = true; });
  slider.addEventListener("input", () => { dragging = true; readout.textContent = `${slider.value} %`; });
  slider.addEventListener("change", () => {
    dragging = false;
    send(gripperPosition(slider.value, g));
  });
  // A press that does not change the value fires no "change": let the readback lead again.
  for (const name of ["pointerup", "pointercancel", "blur"]) {
    slider.addEventListener(name, () => setTimeout(() => { dragging = false; }, 0));
  }

  const unsubscribe = session.onUpdate(({state, error}) => render(state, error ?? null));
  render(session.state(), null);
  return () => unsubscribe();
}
