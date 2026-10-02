// D-411 B: joint jog widget — a two-axis pad mapped to two joints, plus ± buttons for one
// joint. Bounded goals only, one at a time (D-390 §2); no 100 ms stream for the arm.
// Releasing the pad stops new goals; the goal already sent (<= max_step_rad) finishes.
import {axesFromOffset, createArmJogger, limitStep} from "../arm-stick.js";

const BUTTON_STEP_RAD = 0.02;   // legacy per-press step; the pad scales up to max_step_rad
const KEY_AXES = {ArrowRight: {x: 1, y: 0}, ArrowLeft: {x: -1, y: 0}, ArrowUp: {x: 0, y: 1}, ArrowDown: {x: 0, y: -1}};
const fmt = (value) => (Number.isFinite(value) ? value.toFixed(2) : "—");
const PAD_IDLE = "누르는 동안 이동";

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
  const limits = Object.fromEntries(joints.map((joint) => [joint.name, joint]));
  const maxStep = Number(control.max_step_rad) || BUTTON_STEP_RAD;
  const buttonStep = Math.min(BUTTON_STEP_RAD, maxStep);
  const duration = Number(control.duration_s) || 0.4;
  const mapping = {x: names[0] ?? "", y: names[1] ?? ""};
  const idPart = String(control.id ?? "arm").replace(/[^A-Za-z0-9_-]/g, "_");
  let joint = names[0] ?? "";
  let blocked = "조작 보류";
  let padPointer = null;

  // --- pad ------------------------------------------------------------------
  const padBox = node("div", {class: "arm-pad-box"});
  const pad = node("div", {"data-arm-pad": "", "data-disabled": "", role: "application", tabindex: "0",
                           "aria-describedby": `arm-pad-help-${idPart}`});
  const knob = node("div", {"data-arm-pad-knob": ""});
  const labels = {};
  pad.append(knob);
  for (const side of ["up", "down", "left", "right"]) {
    labels[side] = node("span", {"data-arm-pad-label": side, "aria-hidden": "true"});
    pad.append(labels[side]);
  }
  const padStatus = node("p", {"data-arm-pad-status": "", role: "status", "aria-live": "polite"}, PAD_IDLE);
  const help = node("p", {id: `arm-pad-help-${idPart}`, class: "arm-hint"},
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

  const positionOf = (name) => session.state()?.positions?.[name];
  const jogger = createArmJogger({
    submit: async ({joint: name, delta}) => {
      const sent = await session.submitJog(name, delta, duration);
      if (sent === null) session.requestPoll();     // busy or not ready yet: try on the next readback
      return sent;
    },
    mapping, maxStep, limits, positionOf,
  });

  function setPadStatus(text) { if (padStatus.textContent !== text) padStatus.textContent = text; }
  function renderLabels() {
    labels.up.textContent = mapping.y ? `${mapping.y} +` : "";
    labels.down.textContent = mapping.y ? `${mapping.y} −` : "";
    labels.left.textContent = mapping.x ? `${mapping.x} −` : "";
    labels.right.textContent = mapping.x ? `${mapping.x} +` : "";
    pad.setAttribute("aria-label", `팔 조이스틱 — 좌우 ${mapping.x || "없음"}, 상하 ${mapping.y || "없음"}`);
  }
  function renderReadout(state) {
    const range = limits[joint];
    const position = state?.positions?.[joint];
    const known = range && Number.isFinite(range.lower) && Number.isFinite(range.upper);
    const text = `${joint} ${fmt(position)} rad${known ? ` · 한계 ${fmt(range.lower)}…${fmt(range.upper)}` : ""}`;
    if (readout.textContent !== text) readout.textContent = text;
  }
  function renderPadStatus() {
    if (blocked) return setPadStatus(blocked);
    const {pressed, inFlight} = jogger.state();
    if (!pressed) return setPadStatus(PAD_IDLE);
    if (jogger.atLimit()) return setPadStatus("관절 한계 · 반대쪽으로만 움직입니다");
    if (!inFlight && session.busy()) return setPadStatus("명령 진행 중 · 끝나면 이어서 움직입니다");
    setPadStatus("이동 중");
  }
  function render(state, error) {
    // The owner reports ready:false / owner_state "active" while a goal executes: that is busy
    // (wait for it), not blocked. Blocked = error, hold, or no readback.
    const running = state?.owner_state === "active";
    blocked = error || !state || (!state.ready && !running) ? "조작 보류" : "";
    const pressed = jogger.state().pressed;
    for (const button of [minus, plus]) {
      const reason = blocked || (pressed ? "조이스틱 사용 중" : session.busy() ? "명령 진행 중" : "");
      button.disabled = Boolean(reason);
      if (reason) button.setAttribute("reason", reason); else button.removeAttribute("reason");
    }
    pad.toggleAttribute("data-disabled", Boolean(blocked));
    pad.setAttribute("aria-disabled", String(Boolean(blocked)));
    if (blocked) releasePad();
    renderPadStatus();
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
  function releasePad() {
    padPointer = null;
    pad.classList.remove("active");
    moveKnob({x: 0, y: 0});
    return jogger.release();
  }
  function stop() {
    const {inFlight} = releasePad();
    render(session.state(), null);
    if (!blocked && inFlight) setPadStatus("놓음 · 진행 중인 목표만 마칩니다");
  }
  function press(axes) {
    if (blocked) return;
    pad.classList.add("active");
    moveKnob(axes);
    jogger.press(axes);
    render(session.state(), null);
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
    button.addEventListener("click", () => {
      const step = limitStep({joint, delta: Number(button.dataset.simDelta)}, limits[joint], positionOf(joint));
      if (!step) { setPadStatus(`${joint} 관절 한계`); return; }
      session.submitJog(step.joint, step.delta, duration);
    });
  }

  const unsubscribe = session.onUpdate(({state, settled, error}) => {
    if (settled) jogger.settled(settled.state, settled.commandId);
    render(state, error);
    if (!blocked && !session.busy()) jogger.poke();     // a held stick resumes once the arm is free
  });
  renderLabels();
  render(session.state(), null);
  return () => {
    unsubscribe();
    jogger.release();
    document.removeEventListener("visibilitychange", hidden);
  };
}
