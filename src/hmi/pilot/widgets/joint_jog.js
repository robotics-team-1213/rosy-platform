// D-411 B: joint jog widget — a two-axis pad mapped to two joints, plus ± buttons for one
// joint. Bounded goals only, one at a time (D-390 §2); no 100 ms stream for the arm.
// Releasing the pad stops new goals; the goal already sent (<= max_step_rad) finishes.
import {axesFromOffset, createArmJogger} from "../arm-stick.js";

const BUTTON_STEP_RAD = 0.02;   // legacy per-press step; the pad scales up to max_step_rad
const KEY_AXES = {ArrowRight: {x: 1, y: 0}, ArrowLeft: {x: -1, y: 0}, ArrowUp: {x: 0, y: 1}, ArrowDown: {x: 0, y: -1}};
const fmt = (value) => (Number.isFinite(value) ? value.toFixed(2) : "—");

function node(tag, attrs = {}, text = "") {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (text) element.textContent = text;
  return element;
}

function jointSelect(attrs, names, selected, allowNone) {
  const select = node("select", {class: "ui-field", ...attrs});
  if (allowNone) select.add(new Option("없음", ""));
  for (const name of names) select.add(new Option(name, name));
  select.value = selected;
  return select;
}

export function mountJointJog(slot, control, session) {
  const joints = control.joints ?? [];
  const names = joints.map((joint) => joint.name);
  const maxStep = Number(control.max_step_rad) || BUTTON_STEP_RAD;
  const buttonStep = Math.min(BUTTON_STEP_RAD, maxStep);
  const duration = Number(control.duration_s) || 0.4;
  const mapping = {x: names[0] ?? "", y: names[1] ?? ""};
  let joint = names[0] ?? "";
  let blocked = "조작 보류";
  let padPointer = null;

  // --- pad ------------------------------------------------------------------
  const padBox = node("div", {class: "arm-pad-box"});
  const pad = node("div", {"data-arm-pad": "", "data-disabled": "", role: "application", tabindex: "0",
                           "aria-describedby": `arm-pad-help-${control.id}`});
  const knob = node("div", {"data-arm-pad-knob": ""});
  const labels = {};
  for (const side of ["up", "down", "left", "right"]) {
    labels[side] = node("span", {"data-arm-pad-label": side, "aria-hidden": "true"});
    pad.append(labels[side]);
  }
  pad.append(knob);
  const padStatus = node("p", {"data-arm-pad-status": "", role: "status", "aria-live": "polite"}, "누르는 동안 이동");
  const help = node("p", {id: `arm-pad-help-${control.id}`, class: "arm-hint"},
                    `기울인 만큼, 한 번에 최대 ${maxStep} rad · 이전 목표가 끝나야 다음 목표를 보냅니다. ` +
                    "손을 떼면 새 목표를 멈추고 진행 중인 목표는 끝까지 갑니다. 방향키로도 움직입니다.");
  const axisRow = node("div", {class: "arm-axes"});
  const xLabel = node("label", {}, "좌우 축 ");
  const xSelect = jointSelect({"data-arm-axis": "x"}, names, mapping.x, true);
  xLabel.append(xSelect);
  const yLabel = node("label", {}, "상하 축 ");
  const ySelect = jointSelect({"data-arm-axis": "y"}, names, mapping.y, true);
  yLabel.append(ySelect);
  axisRow.append(xLabel, yLabel);
  padBox.append(pad, padStatus, axisRow, help);

  // --- buttons (fallback, keyboard, fine steps) -------------------------------
  const buttons = node("div", {class: "arm-buttons"});
  const jointLabel = node("label", {}, "관절 ");
  const select = jointSelect({"data-sim-joint": ""}, names, joint, false);
  jointLabel.append(select);
  const jog = node("div", {class: "sim-jog"});
  const minus = node("ui-button", {kind: "quiet", type: "button", "data-sim-delta": String(-buttonStep)}, `− ${buttonStep} rad`);
  const plus = node("ui-button", {kind: "quiet", type: "button", "data-sim-delta": String(buttonStep)}, `+ ${buttonStep} rad`);
  jog.append(minus, plus);
  const readout = node("p", {"data-jog-readout": "", class: "arm-readout"});
  buttons.append(jointLabel, jog, readout);

  slot.append(node("h3", {}, control.label || "팔"), padBox, buttons);

  const jogger = createArmJogger({
    submit: ({joint: name, delta}) => session.submitJog(name, delta, duration),
    mapping, maxStep,
  });

  function renderLabels() {
    labels.up.textContent = mapping.y ? `${mapping.y} +` : "";
    labels.down.textContent = mapping.y ? `${mapping.y} −` : "";
    labels.left.textContent = mapping.x ? `${mapping.x} −` : "";
    labels.right.textContent = mapping.x ? `${mapping.x} +` : "";
    pad.setAttribute("aria-label", `팔 조이스틱 — 좌우 ${mapping.x || "없음"}, 상하 ${mapping.y || "없음"}`);
  }
  function renderReadout(state) {
    const range = joints.find((item) => item.name === joint);
    const position = state?.positions?.[joint];
    const limits = range && range.lower != null ? ` · 한계 ${fmt(range.lower)}…${fmt(range.upper)}` : "";
    readout.textContent = `${joint} ${fmt(position)} rad${limits}`;
  }
  function render(state, error) {
    blocked = error ? "조작 보류" : !state?.ready ? "조작 보류" : "";
    const busy = session.busy();
    for (const button of [minus, plus]) {
      button.disabled = Boolean(blocked) || busy;
      if (button.disabled) button.setAttribute("reason", blocked || "명령 진행 중");
      else button.removeAttribute("reason");
    }
    const wasBlocked = pad.hasAttribute("data-disabled");
    pad.toggleAttribute("data-disabled", Boolean(blocked));
    pad.setAttribute("aria-disabled", String(Boolean(blocked)));
    if (blocked) { stop(); padStatus.textContent = blocked; }
    else if (wasBlocked) padStatus.textContent = "누르는 동안 이동";
    renderReadout(state);
  }
  function moveKnob(axes) {
    // the knob (38% wide) stays inside the ring: its centre travels at most 31% from the middle
    knob.style.left = `${50 + axes.x * 31}%`;
    knob.style.top = `${50 - axes.y * 31}%`;
  }
  function axesFor(event) {
    const box = pad.getBoundingClientRect();
    const radius = box.width / 2;
    return axesFromOffset(event.clientX - (box.left + radius), event.clientY - (box.top + box.height / 2), radius);
  }
  function stop() {
    padPointer = null;
    pad.classList.remove("active");
    moveKnob({x: 0, y: 0});
    const {inFlight} = jogger.release();
    if (!blocked) padStatus.textContent = inFlight ? "놓음 · 진행 중인 목표만 마칩니다" : "누르는 동안 이동";
  }
  function press(axes) {
    if (blocked) return;
    pad.classList.add("active");
    moveKnob(axes);
    padStatus.textContent = "이동 중";
    jogger.press(axes);
  }

  pad.addEventListener("pointerdown", (event) => {
    if (blocked || padPointer !== null) return;
    event.preventDefault();
    padPointer = event.pointerId;
    try { pad.setPointerCapture(event.pointerId); } catch { /* synthetic or inactive pointer */ }
    press(axesFor(event));
  });
  pad.addEventListener("pointermove", (event) => {
    if (event.pointerId !== padPointer) return;
    const axes = axesFor(event);
    moveKnob(axes);
    jogger.move(axes);
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    pad.addEventListener(name, (event) => { if (event.pointerId === padPointer) stop(); });
  }
  let heldKey = "";
  pad.addEventListener("keydown", (event) => {
    const axes = KEY_AXES[event.key];
    if (!axes) return;
    event.preventDefault();
    if (heldKey === event.key) return;
    heldKey = event.key;
    press(axes);
  });
  pad.addEventListener("keyup", (event) => { if (event.key === heldKey) { heldKey = ""; stop(); } });
  pad.addEventListener("blur", () => { if (heldKey) { heldKey = ""; stop(); } });
  function hidden() { if (document.hidden) stop(); }
  document.addEventListener("visibilitychange", hidden);

  xSelect.addEventListener("change", () => { stop(); mapping.x = xSelect.value; renderLabels(); });
  ySelect.addEventListener("change", () => { stop(); mapping.y = ySelect.value; renderLabels(); });
  select.addEventListener("change", () => { joint = select.value; renderReadout(session.state()); });
  for (const button of [minus, plus]) {
    button.addEventListener("click", () => session.submitJog(joint, Number(button.dataset.simDelta), duration));
  }

  const unsubscribe = session.onUpdate(({state, settled, error}) => {
    if (settled) jogger.settled(settled.state, settled.commandId);
    render(state, error);
  });
  renderLabels();
  render(session.state(), null);
  return () => {
    stop();
    unsubscribe();
    document.removeEventListener("visibilitychange", hidden);
  };
}
