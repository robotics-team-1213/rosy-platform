import {node, action} from "./control-dom.js";

export function createTabs({id, tabs}) {
  const element = node("div", "", "ui-control-stack");
  const bar = node("div", "", "ui-tab-bar"); bar.setAttribute("role", "tablist"); bar.setAttribute("aria-label", "맥락 선택");
  const buttons = [], panels = [];
  function activate(index) {
    buttons.forEach((button, at) => {
      button.setAttribute("aria-selected", String(at === index)); button.tabIndex = at === index ? 0 : -1;
      panels[at].hidden = at !== index;
    });
  }
  tabs.forEach(({label, content, panelId}, index) => {
    const button = action(label, () => activate(index), "segment"); button.id = `${id}-tab-${index}`;
    button.setAttribute("role", "tab"); button.setAttribute("aria-controls", panelId);
    const panel = node("section"); panel.id = panelId; panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", button.id); panel.append(content);
    button.addEventListener("keydown", event => {
      const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (delta || ["Home", "End"].includes(event.key)) {
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + delta + tabs.length) % tabs.length;
        buttons[next].focus();
      }
    });
    buttons.push(button); panels.push(panel); bar.append(button);
  });
  element.append(bar, ...panels); activate(0);
  return {element};
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
