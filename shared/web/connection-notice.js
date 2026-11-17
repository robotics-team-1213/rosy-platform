// C10 createConnectionNotice: one connection indicator (D-280, D-202). 2026-11-14 decision replaces D2: a disconnect is a
// warning, not an alarm; only a caller that knows the operating risk raises it to danger.
//   createConnectionNotice(element) -> {set(state, text, {danger})}
//   state: "fresh" | "delayed" | "auth-wait" | "unavailable" | "disconnected". A real "disconnected" is a warn
//   <ui-tag> with the wifi icon and text (statusTag). {danger: true} fills it with the crit colour (e.g. a robot that
//   keeps moving while disconnected); the flag is ignored for every other state. "auth-wait" and "unavailable"
//   stay plain calm text and carry their own data-evidence, so they are never mistaken for a fault.
//   text defaults to the shared evidence wording. element.dataset.evidence mirrors state for styling and tests.
//   The element becomes a polite status region (role="status" aria-live="polite") unless the caller already set a role or aria-live.
import {EVIDENCE_LABEL} from "./core_ui_logic.js";
import {statusTag} from "./status-tag.js";

export const CONNECTION_TEXT = Object.freeze({...EVIDENCE_LABEL, "auth-wait": "인증 대기"});

export function createConnectionNotice(element) {
  if (!element.hasAttribute("role") && !element.hasAttribute("aria-live")) {
    element.setAttribute("role", "status");  // a connection change is announced, not silent (WCAG 4.1.3); a caller's own region wins
    element.setAttribute("aria-live", "polite");
  }
  function set(state, text = CONNECTION_TEXT[state] ?? EVIDENCE_LABEL.unavailable, {danger = false} = {}) {
    if (!(state in CONNECTION_TEXT)) state = "unavailable";
    element.dataset.evidence = state;
    const chip = element.firstElementChild;
    if (state === "disconnected") {
      const status = danger ? "crit" : "warn";
      if (chip?.localName !== "ui-tag" || chip.getAttribute("status") !== status || chip.textContent !== text) {
        element.replaceChildren(statusTag("disconnected", text, {danger}));
      }
    } else if (chip || element.textContent !== text) {
      element.replaceChildren(text);
    }
  }
  return {set};
}
