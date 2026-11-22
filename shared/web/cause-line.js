/**
 * C1 cause line: disabled controls with a visible `reason` and `aria-describedby`.
 *
 * `<ui-button reason>` owns a single button (it draws its own `<small>` inside the button) via `setOff` / `setOffBy`,
 * which delegate `aria-describedby` updates to `describeBy()`.
 */

/** Add or remove one id in an element's aria-describedby; other ids are kept. */
export function describeBy(el, id, on) {
  const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter((item) => item && item !== id);
  if (on) ids.push(id);
  if (ids.length) el.setAttribute("aria-describedby", ids.join(" ")); else el.removeAttribute("aria-describedby");
}

/** One disabled control + the visible reason it is off (a <ui-button reason> draws it). describedBy: id of a state line to point at. */
export function setOff(control, off, reason = "", describedBy = "") {
  control.disabled = Boolean(off);
  if (off) control.setAttribute("reason", reason); else control.removeAttribute("reason");
  if (describedBy) control.setAttribute("aria-describedby", describedBy);
}

/** setOff whose reason is also the switch: "" enables and forgets the reason, any text disables and shows it. */
export function setOffBy(control, reason) {
  setOff(control, reason, reason);
}
