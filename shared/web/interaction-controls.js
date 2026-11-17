import {node, action} from "./control-dom.js";
import {actionIcon} from "./ui.js";
import {describeBy} from "./cause-line.js";

/**
 * K9 tabs: panels of one subject at one level (not screen navigation, not a sequence: that is ui-stage-track).
 *   createTabs({id, tabs, label = "맥락 선택", onChange, beforeChange, activation = "manual"})
 *     -> {element, select(key), setDisabled(key, reason), get value, dispose()}
 *     tabs          [{label, content, panelId?, id?, icon?, iconOnly?, disabled?, reason?}]; a tab's key is `id`, else `panelId`,
 *                   else `${id}-panel-${index}`. icon = an actionIcon name; iconOnly draws the icon alone and `label` becomes the
 *                   accessible name and tooltip (icon required). disabled + reason: the tab cannot be activated, the reason
 *                   shows on one cause line under the tab bar (ui-status[data-cause], aria-describedby; never a reason attribute), arrows skip it.
 *     activation    "manual" (default, APG): arrows/Home/End move focus, Enter or Space activates.
 *                   "automatic": arrows/Home/End also activate, through the same guarded path.
 *     beforeChange  beforeChange(nextKey, currentKey) -> boolean | Promise<boolean>, may veto a switch (a confirm gate).
 *                   false, a rejection or a throw cancels. While a promise is pending the bar has aria-busy="true" and other
 *                   activations are ignored. A synchronous answer commits synchronously.
 *     onChange      onChange(key) once per committed user switch. select(key) is silent, skips the veto, and does nothing for
 *                   a disabled or unknown tab; it also drops a pending veto's result.
 *     setDisabled   setDisabled(key, reason): a non-empty reason disables the tab, "" enables it. The selected tab stays selected.
 *   No enabled tab: nothing is selected (value null). dispose() stops pending switches from committing.
 */
export function createTabs({id, tabs, label = "맥락 선택", onChange = () => {}, beforeChange = () => true, activation = "manual"}) {
  if (!["manual", "automatic"].includes(activation)) throw new RangeError(`Unknown tab activation: ${activation}`);
  const element = node("div", "", "ui-control-stack");
  const bar = node("div", "", "ui-tab-bar"); bar.setAttribute("role", "tablist"); bar.setAttribute("aria-label", label);
  // The one cause line of C1 (ui-status[data-cause], aria-describedby via describeBy). createCauseLine itself forgets controls that are
  // not in the document yet, and a tab bar is built before it is mounted, so the tabs keep their own reasons and sync the line.
  const line = node("ui-status"); line.dataset.cause = ""; line.id = `${id}-cause`; line.hidden = true;
  const reasons = new Map();
  const buttons = [], panels = [];
  const panelIds = tabs.map((tab, index) => tab.panelId ?? `${id}-panel-${index}`);
  const keys = tabs.map((tab, index) => tab.id ?? panelIds[index]);
  let current = -1, pending = false, token = 0, disposed = false;
  const usable = index => index >= 0 && !buttons[index].disabled;
  function activate(index) {
    current = index;
    buttons.forEach((button, at) => {
      button.setAttribute("aria-selected", String(at === index)); button.tabIndex = at === index ? 0 : -1;
      panels[at].hidden = at !== index;
    });
  }
  function request(index) {
    if (disposed || pending || index === current || !usable(index)) return;
    const mine = ++token;
    const commit = ok => { if (!disposed && mine === token && ok && usable(index)) { activate(index); onChange(keys[index]); } };
    let verdict;
    try { verdict = beforeChange(keys[index], current < 0 ? null : keys[current]); } catch { return; }
    if (verdict && typeof verdict.then === "function") {
      pending = true; bar.setAttribute("aria-busy", "true");
      const done = ok => { if (mine === token) { pending = false; bar.removeAttribute("aria-busy"); } commit(Boolean(ok)); };
      verdict.then(done, () => done(false));
    } else commit(Boolean(verdict));
  }
  const step = (from, delta) => {  // the next enabled tab; at most one lap, so all-disabled cannot loop
    for (let n = 1; n <= tabs.length; n++) { const at = (from + delta * n + tabs.length * n) % tabs.length; if (usable(at)) return at; }
    return -1;
  };
  tabs.forEach(({label: text, content, icon, iconOnly}, index) => {
    const button = action(iconOnly ? "" : text, () => request(index), "segment"); button.id = `${id}-tab-${index}`;
    button.setAttribute("role", "tab"); button.setAttribute("aria-controls", panelIds[index]);
    if (iconOnly) { button.setAttribute("aria-label", text); button.setAttribute("data-ui-tooltip", text); button.setAttribute("data-icon-only", ""); }
    if (icon) actionIcon(button, icon); else if (iconOnly) throw new TypeError("An icon-only tab needs an icon");
    const panel = node("section"); panel.id = panelIds[index]; panel.setAttribute("role", "tabpanel"); panel.tabIndex = 0;
    panel.setAttribute("aria-labelledby", button.id); panel.append(content);
    button.addEventListener("keydown", event => {
      const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!delta && !["Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? (usable(0) ? 0 : step(0, 1)) : event.key === "End" ? (usable(tabs.length - 1) ? tabs.length - 1 : step(tabs.length - 1, -1)) : step(index, delta);
      if (next < 0) return;
      buttons[next].focus();
      if (activation === "automatic") request(next);
    });
    buttons.push(button); panels.push(panel); bar.append(button);
  });
  element.append(bar, line, ...panels);
  const setDisabled = (key, reason) => {
    const at = keys.indexOf(key);
    if (at < 0) return;
    if (reason) reasons.set(key, reason); else reasons.delete(key);
    buttons[at].disabled = Boolean(reason); describeBy(buttons[at], line.id, Boolean(reason));
    buttons[at].tabIndex = at === current ? 0 : -1;
    line.textContent = [...new Set(reasons.values())].join(" · "); line.hidden = !reasons.size;
    if (reasons.size) line.setAttribute("state", "empty"); else line.removeAttribute("state");
  };
  tabs.forEach((tab, index) => { if (tab.disabled || tab.reason) setDisabled(keys[index], tab.reason || "지금은 쓸 수 없습니다"); });
  activate(buttons.findIndex((_, index) => usable(index)));
  return {
    element,
    select(key) {
      const at = keys.indexOf(key);
      if (!usable(at)) return;
      token++; pending = false; bar.removeAttribute("aria-busy");  // a pending veto's answer is dropped, so it must not keep the bar locked
      activate(at);
    },
    setDisabled,
    get value() { return current < 0 ? null : keys[current]; },
    dispose() { disposed = true; buttons.forEach(button => describeBy(button, line.id, false)); },
  };
}

export function createDisclosure({label, content, open = false}) {
  const element = node("details", "", "ui-disclosure"); element.open = open;
  element.append(node("summary", label), content);
  return element;
}

// A disclosure of ordinary actions keeps native tab order; it is not an ARIA menu.
export function createActionMenu({id, label, actions}) {
  const element = node("div", "", "ui-action-menu");
  const list = node("div", "", "ui-control-stack"); list.id = `${id}-items`; list.hidden = true;
  const trigger = action(label, () => toggle(list.hidden)); trigger.id = id;
  trigger.setAttribute("aria-expanded", "false"); trigger.setAttribute("aria-controls", list.id);
  function toggle(open, restore = false) {
    list.hidden = !open; trigger.setAttribute("aria-expanded", String(open));
    if (open) list.querySelector("ui-button")?.focus(); else if (restore) trigger.focus();
  }
  for (const {label: text, onClick} of actions) list.append(action(text, () => {onClick(); toggle(false, list.contains(document.activeElement));}));
  element.addEventListener("keydown", event => {
    if (event.key === "Escape" && !list.hidden) {event.preventDefault(); toggle(false, true);}
  });
  element.addEventListener("focusout", event => {if (!element.contains(event.relatedTarget)) toggle(false);});
  element.append(trigger, list);
  return {element, trigger};
}

export function createSupplementPanel({id, title, content, beforeClose = () => true}) {
  const element = node("section", "", "ui-supplement-panel"); element.id = id; element.hidden = true;
  const heading = node("h3", title); heading.id = `${id}-title`; heading.tabIndex = -1;
  element.setAttribute("aria-labelledby", heading.id);
  let opener = null, pending = false, disposed = false;
  const close = async () => {
    if (pending || disposed) return;
    pending = true;
    try {
      if (!await beforeClose()) return;
      if (disposed) return;
      element.hidden = true; opener?.focus();
    } finally {pending = false;}
  };
  const dismiss = action("상세 닫기", close);
  element.addEventListener("keydown", event => {if (event.key === "Escape") {event.preventDefault(); close();}});
  element.append(heading, dismiss, content);
  return {element, open(source = document.activeElement) {if (disposed) return; opener = source; element.hidden = false; heading.focus();}, close,
    dispose() {disposed = true; element.hidden = true;}};
}
