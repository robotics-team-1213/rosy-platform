// 문서 단위 공용 배선 — 요소 하나가 아니라 문서 전체에 거는 동작이다. ui.js가 싣는다.

import { actionIcon } from "./ui.js";

// D-405: `[data-theme-cycle]` 아이콘 단추 하나가 RosyTheme 선택지를 차례로 돈다. 얼굴은 지금 선택이다.
// 모든 앱이 이 배선을 쓴다 — 표면마다 테마 select·저장 코드를 따로 두지 않는다.
function themeCycleStep() {
  const theme = window.RosyTheme, choices = theme.choices;
  const index = Math.max(0, choices.findIndex(choice => choice.value === theme.get()));
  return [choices[index], choices[(index + 1) % choices.length]];
}

function renderThemeCycles() {
  if (!window.RosyTheme) return;
  const [now, next] = themeCycleStep(), label = `테마: ${now.label} · 클릭하면 ${next.label}`;
  for (const button of document.querySelectorAll("[data-theme-cycle]")) {
    button.setAttribute("aria-label", label);
    button.setAttribute("data-ui-tooltip", label);
    button.setAttribute("data-action-icon", now.icon);
    actionIcon(button, now.icon);
  }
}

document.addEventListener("click", event => {
  const button = event.target instanceof Element ? event.target.closest("[data-theme-cycle]") : null;
  if (button && !button.disabled && window.RosyTheme) window.RosyTheme.set(themeCycleStep()[1].value);
});
document.addEventListener("rosy:theme", renderThemeCycles);
renderThemeCycles();

// A custom element is not a submit button, so the browser skips implicit submission (Enter in a field).
// The form's first submit-type ui-button stands in as its default button.
const NOT_TEXT = new Set(["checkbox", "radio", "button", "submit", "reset", "file", "image", "range", "color"]);
document.addEventListener("keydown", event => {
  if (event.key !== "Enter" || event.isComposing || event.defaultPrevented) return;
  const field = event.target;
  if (!(field instanceof HTMLInputElement) || NOT_TEXT.has(field.type) || !field.form) return;
  const button = field.form.querySelector('ui-button[type="submit"]');
  if (!button) return;
  event.preventDefault();
  if (!button.disabled) field.form.requestSubmit();
});

// A narrow sub-navigation scrolls sideways; centre the current item so the scroll does not hide where the user is.
// Sideways only: the page never scrolls, and a nav that fits is left alone.
const NAV = ".ui-rail-nav, .ui-subnav-nav";
const CURRENT = '[aria-current], [aria-selected="true"]';
function revealCurrent(root) {
  const nav = root.closest?.(NAV) ?? null;
  const navs = nav ? [nav] : root.querySelectorAll?.(NAV) ?? [];
  for (const each of navs) {
    const item = each.matches(CURRENT) ? null : each.querySelector(CURRENT);
    if (!item || each.scrollWidth <= each.clientWidth) continue;
    const gap = item.getBoundingClientRect().left - each.getBoundingClientRect().left;
    each.scrollLeft += gap - (each.clientWidth - item.offsetWidth) / 2;
  }
}
new MutationObserver(records => {
  for (const record of records) {
    if (record.type === "attributes") revealCurrent(record.target);
    else for (const added of record.addedNodes) if (added.nodeType === 1) revealCurrent(added);
  }
}).observe(document, {subtree: true, childList: true, attributeFilter: ["aria-current", "aria-selected"]});
revealCurrent(document);

// Say which sides of a sideways-scrolling nav still hide items, so the CSS can fade that edge.
function markMore(nav) {
  const more = [nav.scrollLeft > 1 && "start", nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 1 && "end"].filter(Boolean).join(" ");
  if (more) nav.setAttribute("data-more", more); else nav.removeAttribute("data-more");
}
const markAll = () => document.querySelectorAll(NAV).forEach(markMore);
document.addEventListener("scroll", event => { if (event.target instanceof Element && event.target.matches(NAV)) markMore(event.target); }, {capture: true, passive: true});
window.addEventListener("resize", markAll);
new MutationObserver(markAll).observe(document, {subtree: true, childList: true});
markAll();
