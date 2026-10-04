// D-411 B: build a control surface from rosy.controls/1. Unknown kinds are shown, never fatal.
// An empty list is "no controls right now" (API Ref §9.1), not an old server.
import {widgetPlan} from "../controls.js";

export function composeControls(root, items, widgets, context) {
  const disposers = [];
  const plan = widgetPlan(items, Object.keys(widgets));
  if (!plan.length) {
    const empty = document.createElement("p");
    empty.dataset.controlsEmpty = "";
    empty.textContent = "이 기기가 지금 알리는 조작부가 없습니다";
    root.append(empty);
  }
  for (const {control, supported} of plan) {
    const slot = document.createElement("section");
    slot.dataset.control = control.kind;
    slot.dataset.controlId = control.id;
    root.append(slot);
    if (!supported) {
      slot.dataset.controlUnsupported = "";
      slot.textContent = `지원하지 않는 조작부 · ${control.label || control.kind}`;
      continue;
    }
    slot.setAttribute("aria-label", control.label || control.kind);
    try {
      const dispose = widgets[control.kind](slot, control, context);
      if (typeof dispose === "function") disposers.push(dispose);
    } catch (error) {
      // A descriptor this widget cannot draw (bad fields) is shown like an unknown kind.
      console.warn("control widget failed", control.kind, error);
      slot.replaceChildren();
      slot.removeAttribute("aria-label");
      slot.dataset.controlUnsupported = "";
      slot.textContent = `그릴 수 없는 조작부 · ${control.label || control.kind}`;
    }
  }
  return () => { disposers.forEach((dispose) => dispose()); root.replaceChildren(); };
}
