/**
 * K3 single choice from a list whose items carry status, a thumbnail or a second line and have NO action inside the
 * row (photos, frames, AI candidates, promotion candidates, runs). A row with an action (robot, task) is not this: it
 * is a row list plus a 선택 toggle (K4, robot-row.js). WAI-ARIA APG listbox: role=listbox, role=option aria-selected,
 * nothing interactive inside an option. Selection never follows focus (one rule): Enter or Space chooses.
 *
 *   createChoiceList({id, label, items, value, onChange, labelHidden = false, emptyText = "항목이 없습니다"})
 *     items  [{id, label, secondary?, status?, icon?, thumb?, disabled?}]
 *            status = a statusTag state string ("delayed", "caution"...) or {state, text?, icon?, danger?} so the item
 *            carries its own wording and icon through statusTag; icon = an actionIcon name; thumb = image URL string
 *            (alt empty: the label is the name); disabled = visible, focusable, not choosable (aria-disabled)
 *   -> {element, set(items), select(id), get value, focus(), dispose()}
 *     set(items)   replaces the items and keeps the value and the focused item when they still exist. Items that draw the
 *                  same (field by field) rebuild nothing, so a poll may call set() every few seconds with fresh objects
 *     select(id)   sets the value without calling onChange (onChange is for the user's choice); unknown id -> null
 *     value        the chosen id or null
 *   Keys: Up/Down/Home/End move focus (roving tabindex; one Tab stop), a letter jumps to the next label starting with
 *   it, Enter/Space chooses. The chosen item carries data-selected and a check mark (never colour alone, S3).
 */
import {node} from "./control-dom.js";
import {actionIcon} from "./ui.js";
import {statusTag} from "./status-tag.js";
import {moveIndex, findByPrefix, statusSpec, sameChoiceItems} from "./choice-logic.js";

export function createChoiceList({id, label, items = [], value = null, onChange = () => {}, labelHidden = false, emptyText = "항목이 없습니다"}) {
  const element = node("div", "", "choice-list"); element.id = id;
  const title = node("div", label, labelHidden ? "sr-only" : "choice-label"); title.id = `${id}-label`;
  const list = node("ul", "", "choice-options"); list.setAttribute("role", "listbox"); list.setAttribute("aria-labelledby", title.id);
  const empty = node("ui-empty", emptyText);
  element.append(title, list, empty);
  let built = false, current = items, chosen = null, active = 0, typed = "", typedAt = 0, disposed = false;
  const options = () => [...list.children];
  const optionId = item => `${id}-opt-${item.id}`;

  function paint() {
    options().forEach((option, at) => {
      const on = current[at].id === chosen;
      option.setAttribute("aria-selected", String(on)); option.toggleAttribute("data-selected", on);
      option.tabIndex = at === active ? 0 : -1;
    });
  }
  function build(item) {
    const option = node("li", "", "choice-option"); option.id = optionId(item); option.setAttribute("role", "option");
    option.dataset.id = item.id;
    if (item.disabled) option.setAttribute("aria-disabled", "true");
    const mark = node("span", "", "choice-check"); mark.setAttribute("aria-hidden", "true"); actionIcon(mark, "check");
    const body = node("span", "", "choice-body");
    if (item.thumb) { const image = node("img", "", "choice-thumb"); image.alt = ""; image.src = item.thumb; body.append(image); }
    if (item.icon) { const holder = node("span"); actionIcon(holder, item.icon); body.append(holder.firstElementChild); }
    body.append(node("span", item.label, "choice-name"));
    if (item.secondary) body.append(node("small", item.secondary, "choice-secondary"));
    const status = statusSpec(item.status);
    if (status) body.append(statusTag(status.state, status.text, {icon: status.icon, danger: status.danger}));
    option.append(mark, body);
    return option;
  }
  function render(next) {
    if (built && sameChoiceItems(current, next, "list")) { current = next; return; }
    built = true;
    const hadFocus = list.contains(document.activeElement), focusedId = document.activeElement?.closest?.(".choice-option")?.dataset.id;
    current = next;
    if (chosen !== null && !current.some(item => item.id === chosen)) chosen = null;
    active = Math.max(0, current.findIndex(item => item.id === (focusedId ?? chosen)));
    if (!hadFocus) active = Math.max(0, current.findIndex(item => item.id === chosen));
    list.replaceChildren(...current.map(build));
    list.hidden = !current.length; empty.hidden = Boolean(current.length);
    paint();
    if (hadFocus) options()[active]?.focus();
  }
  function choose(at) {
    const item = current[at];
    if (disposed || !item || item.disabled || item.id === chosen) return;
    chosen = item.id; paint(); onChange(chosen);
  }
  const usable = id => current.some(item => item.id === id && !item.disabled);
  function focusAt(at) { active = at; paint(); options()[at]?.focus(); }

  list.addEventListener("focusin", event => {  // roving follows real focus, also when a script or a click moved it
    const at = options().indexOf(event.target.closest(".choice-option"));
    if (at >= 0 && at !== active) { active = at; paint(); }
  });
  list.addEventListener("click", event => {
    const at = options().indexOf(event.target.closest(".choice-option"));
    if (at < 0) return;
    focusAt(at); choose(at);
  });
  list.addEventListener("keydown", event => {
    if (disposed || event.altKey || event.ctrlKey || event.metaKey) return;
    const at = options().indexOf(event.target.closest(".choice-option"));
    if (at < 0) return;
    const to = moveIndex(event.key, at, current.length);
    if (to !== null) { event.preventDefault(); focusAt(to); return; }
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(at); return; }
    if (event.key.length === 1) {
      typed = event.timeStamp - typedAt < 700 ? typed + event.key : event.key; typedAt = event.timeStamp;
      const found = findByPrefix(current.map(item => item.label), typed, at);
      if (found >= 0) { event.preventDefault(); focusAt(found); }
    }
  });

  chosen = usable(value) ? value : null;
  render(current);
  return {
    element,
    set(next) { if (!disposed) render(next); },
    select(next) {
      if (disposed) return;
      chosen = usable(next) ? next : null;
      if (!list.contains(document.activeElement)) active = Math.max(0, current.findIndex(item => item.id === chosen));
      paint();
    },
    get value() { return chosen; },
    focus() { options()[active]?.focus(); },
    dispose() { disposed = true; },
  };
}
