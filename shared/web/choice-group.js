/**
 * One group of choices, three kinds (concept rules K1, K5, K6). Pick by what the choice does, not by looks:
 *   single  K1  short exclusive choice (2-5) outside a form that acts at once (speed step, view mode, tool): native
 *               radios in a fieldset, painted as chips. The browser gives exclusivity, arrow keys and form values.
 *   toggle  K5  independent show/hide flags with immediate effect (map layers, filters), up to 8: ui-button kind=toggle
 *               with aria-pressed. Never for an exclusive choice (aria-pressed cannot say "one of").
 *   check   K6  form values or more than 8: fieldset + label.ui-check + checkbox.
 *
 *   createChoiceGroup({id, label, mode, items, value, onChange, max, maxReason, master})
 *     items   [{value, label, reason?, disabled?}]   reason = why it is disabled, shown (never a tooltip only)
 *     value   single: the value (default: the first enabled item, so exactly one is always chosen)
 *             toggle/check: array of values, in item order
 *   A single value may sit on a disabled item (the current mode that cannot be clicked now): it stays checked and keeps its
 *   --selection edge and tick, muted, with its reason visible on the chip. Only a value no item has falls back (first item or none).
 *   allowEmpty  single only, default false: "no value" is a state (an intermediate fit/fill, an unknown mode, a click mode that is
 *             not allowed). value null or omitted, an unknown or disabled value, and a setItems that drops the value all leave
 *             NO radio checked (value null) instead of falling back to the first item. APG: with none checked Tab enters the
 *             group on its first radio and an arrow checks the next one; there is no user gesture back to none, so onChange
 *             never gets null: only the owner returns to none, with set(null) or setItems.
 *     max     toggle/check: at most this many on; the rest are disabled with `maxReason` ("최대 N개까지 고를 수 있습니다")
 *     master  toggle only: {label = "전체"}; a first button that turns all on / all off, aria-pressed true|false|mixed
 *   -> {element, set(value), setItems(items), get value, dispose()}   value: single -> string or null; others -> array
 *     set(value)  sets the value without calling onChange (onChange(value) is the user's choice only)
 *     setItems    replaces the items; the value keeps the entries that still exist (single falls back to the first, or to none
 *                 with allowEmpty). Items that draw the same (value, label, reason, disabled) change nothing, and a real change
 *                 keeps the focused control, so a poll may call setItems() every few seconds with fresh objects.
 *   A group has a visible label (legend / aria-labelledby). Selected state: the --selection edge plus a check mark, so
 *   it never relies on colour alone (choice-controls.css, S3). The theme choice (#71) stays a documented K1 exception.
 */
import {node} from "./control-dom.js";
import {actionIcon} from "./ui.js";
import {toggleValue, masterState, masterValues, sameChoiceItems} from "./choice-logic.js";

const MODES = ["single", "toggle", "check"];

export function createChoiceGroup({id, label, mode, items = [], value, onChange = () => {}, max = 0, maxReason, master = null, allowEmpty = false}) {
  if (!MODES.includes(mode)) throw new RangeError(`Unknown choice group mode: ${mode}`);
  if (master && mode !== "toggle") throw new RangeError("master is for mode toggle only");
  if (allowEmpty && mode !== "single") throw new RangeError("allowEmpty is for mode single only");
  const box = mode === "toggle";
  const element = node(box ? "div" : "fieldset", "", "choice-group"); element.id = id; element.dataset.mode = mode;
  let title;
  if (box) { title = node("div", label, "choice-label"); title.id = `${id}-label`; element.setAttribute("role", "group"); element.setAttribute("aria-labelledby", title.id); }
  else title = node("legend", label, "choice-label");
  const body = node("div", "", "choice-items");
  element.append(title, body);
  let current = items, on = [], disposed = false, parts = [], masterButton = null;
  const values = () => current.map(item => item.value);
  const free = item => !item.disabled;
  const limit = maxReason ?? `최대 ${max}개까지 고를 수 있습니다`;

  function sanitize(next) {
    if (mode === "single") return current.some(item => item.value === next) ? [next] : allowEmpty ? [] : [current.find(free)?.value].filter(v => v !== undefined);
    const wanted = [].concat(next ?? []);
    const kept = current.filter(item => free(item) && wanted.includes(item.value)).map(item => item.value);
    return max > 0 ? kept.slice(0, max) : kept;
  }
  function paint() {
    const full = max > 0 && on.length >= max;
    parts.forEach(({item, control}, at) => {
      const pressed = on.includes(item.value);
      const blocked = Boolean(item.disabled) || (box || mode === "check") && full && !pressed;
      const why = item.disabled ? item.reason : blocked ? limit : "";
      if (box) {
        control.setAttribute("aria-pressed", String(pressed)); control.toggleAttribute("disabled", blocked);
        if (why) control.setAttribute("reason", why); else control.removeAttribute("reason");
      } else {
        control.input.checked = pressed; control.input.disabled = blocked;
        control.label.toggleAttribute("data-disabled", blocked); control.note.textContent = why ?? ""; control.note.hidden = !why;
      }
    });
    if (masterButton) masterButton.setAttribute("aria-pressed", masterState(on.length, current.filter(free).length));
  }
  function build() {
    parts = []; masterButton = null;
    const out = [];
    if (master) {
      masterButton = node("ui-button", master.label ?? "전체"); masterButton.setAttribute("kind", "toggle"); masterButton.setAttribute("type", "button");
      masterButton.dataset.master = ""; masterButton.append(checkMark());
      masterButton.addEventListener("click", () => change(masterValues(on, current.filter(free).map(item => item.value), max)));
      out.push(masterButton);
    }
    for (const item of current) {
      if (box) {
        const button = node("ui-button", item.label); button.setAttribute("kind", "toggle"); button.setAttribute("type", "button");
        button.dataset.value = item.value; button.append(checkMark());
        button.addEventListener("click", () => change(toggleValue(on, item.value, values(), max)));
        parts.push({item, control: button}); out.push(button);
      } else {
        const label = node("label", "", mode === "single" ? "choice-chip" : "ui-check");
        const input = node("input", "", mode === "single" ? "choice-radio ui-field" : "ui-field");
        input.type = mode === "single" ? "radio" : "checkbox"; input.name = id; input.value = item.value;
        const text = node("span", item.label), note = node("small", "", "choice-reason"); note.id = `${id}-why-${parts.length}`; note.hidden = true;
        input.setAttribute("aria-describedby", note.id);
        if (mode === "single") label.append(input, checkMark(), text, note); else label.append(input, text, note);
        input.addEventListener("change", () => change(mode === "single" ? [item.value] : toggleValue(on, item.value, values(), max)));
        parts.push({item, control: {label, input, note}}); out.push(label);
      }
    }
    body.replaceChildren(...out);
  }
  // which control holds focus: an item value, or the master; restored by value after a rebuild (skipped when it is gone or disabled)
  function focusedKey() {
    const active = document.activeElement;
    if (!body.contains(active)) return null;
    if (masterButton === active) return {master: true};
    const part = parts.find(({control}) => control === active || control.input === active);
    return part ? {value: part.item.value} : null;
  }
  function refocus(held) {
    if (!held) return;
    const part = held.master ? null : parts.find(({item}) => item.value === held.value);
    const target = held.master ? masterButton : part && (box ? part.control : part.control.input);
    if (target && !target.disabled && !target.hasAttribute("disabled")) target.focus();
  }
  function checkMark() { const mark = node("span", "", "choice-check"); mark.setAttribute("aria-hidden", "true"); actionIcon(mark, "check"); return mark; }
  function change(next) {
    if (disposed) return;
    const same = next.length === on.length && next.every((v, at) => v === on[at]);
    on = next; paint();
    if (!same) onChange(mode === "single" ? on[0] : [...on]);
  }

  current = items; build(); on = sanitize(value); paint();
  return {
    element,
    set(next) { if (disposed) return; on = sanitize(next); paint(); },
    setItems(next) {
      if (disposed) return;
      if (sameChoiceItems(current, next, "group")) { current = next; parts.forEach((part, at) => { part.item = next[at]; }); return; }
      const keep = mode === "single" ? on[0] : on, held = focusedKey();
      current = next; build(); on = sanitize(keep); paint(); refocus(held);
    },
    get value() { return mode === "single" ? on[0] ?? null : [...on]; },
    dispose() { disposed = true; },
  };
}
