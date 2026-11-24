// Shared signature-guarded slot filler and card builder for decision queues (replan, deadlock, recovery, person-request).
import { setOffBy } from "/common/cause-line.js";
import { node } from "/common/control-dom.js";

function decisionButton(label, primary, reason, scope, onClick) {
  const button = document.createElement("ui-button");
  button.setAttribute("kind", "quiet");
  if (primary) button.setAttribute("kind", "primary");
  button.type = "button";
  button.textContent = label;
  setOffBy(button, reason || "");
  button.addEventListener("click", scope.guard(onClick));
  return button;
}

export function buildDecisionBox({ scope, lines = [], groupLabel = "", buttons = [], result = null }) {
  const box = node("div", "", "stuck-item");
  for (const text of lines) box.append(node("p", text, "stuck-resolver"));
  if (buttons.length) {
    const actions = node("div", "", "stuck-actions ui-action-bar");
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", groupLabel);
    for (const spec of buttons) {
      const button = decisionButton(spec.label, Boolean(spec.primary), spec.reason, scope, spec.onClick);
      if (spec.dataset) Object.assign(button.dataset, spec.dataset);
      actions.append(button);
    }
    box.append(actions);
  }
  if (result) {
    const line = node("p", result.text, "stuck-result");
    line.dataset.kind = result.kind;
    line.setAttribute("role", result.kind === "bad" ? "alert" : "status");
    box.append(line);
  }
  return box;
}

export function createDecisionSlotFiller({ focusAttr = "" } = {}) {
  const signatures = new Map();
  const dataAttr = focusAttr ? `data-${focusAttr.replace(/[A-Z]/g, (ch) => `-${ch.toLowerCase()}`)}` : "";

  return function fill(key, signature, make) {
    const slot = document.querySelector(`[data-decision-slot="${CSS.escape(key)}"]`);
    if (!slot || (slot.firstElementChild && signatures.get(key) === signature)) return;
    const active = dataAttr && slot.contains(document.activeElement) ? document.activeElement : null;
    const focusVal = active?.dataset?.[focusAttr] ?? null;
    slot.replaceChildren(make());
    signatures.set(key, signature);
    if (focusVal) slot.querySelector(`[${dataAttr}="${CSS.escape(focusVal)}"]`)?.focus({ preventScroll: true });
  };
}
