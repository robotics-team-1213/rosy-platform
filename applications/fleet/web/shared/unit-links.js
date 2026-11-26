import { node, patchHidden } from "/common/control-dom.js";

// D-977: child unit cross-links only accept explicit HTTPS origins without credentials in the URL.
const SAFE_ORIGIN = /^https:\/\/[\w.:\[\]-]+$/;

export function childUnitLinks(summary, {
  target = null,
  includeConsole = false,
  includeCell = false,
  consoleLabel = "관제 화면 열기",
  cellLabel = (child) => `${child} 셀 관제 화면 열기`,
} = {}) {
  const origins = summary?.child_origins && typeof summary.child_origins === "object" ? summary.child_origins : {};
  const list = [];
  const arms = Array.isArray(summary?.child_arm_units) ? summary.child_arm_units : [];
  if (target) {
    const origin = origins[target];
    if (typeof origin !== "string" || !SAFE_ORIGIN.test(origin)) return list;
    if (includeConsole) list.push({ href: `${origin}/console`, label: consoleLabel });
    if (includeCell && arms.includes(target)) list.push({ href: `${origin}/console/cell`, label: cellLabel(target) });
    return list;
  }
  if (includeCell) {
    for (const child of arms) {
      const origin = origins[child];
      if (typeof origin !== "string" || !SAFE_ORIGIN.test(origin)) continue;
      list.push({ href: `${origin}/console/cell`, label: cellLabel(child) });
    }
  }
  return list;
}

export function renderUnitLinks(container, links, { sigCache = null, sigKey = "unit-links", hideWhenEmpty = false } = {}) {
  if (!container) return;
  const sig = JSON.stringify(links);
  if (sigCache && sigCache.get(sigKey) === sig && (container.childElementCount > 0 || !links.length)) {
    if (hideWhenEmpty) patchHidden(container, !links.length);
    return;
  }
  if (sigCache) sigCache.set(sigKey, sig);
  container.replaceChildren(...links.map((link) => {
    const anchor = node("a", link.label, "ui-action-link");
    anchor.dataset.kind = "quiet";
    anchor.rel = "noreferrer";
    anchor.href = link.href;
    return anchor;
  }));
  if (hideWhenEmpty) patchHidden(container, !links.length);
}
