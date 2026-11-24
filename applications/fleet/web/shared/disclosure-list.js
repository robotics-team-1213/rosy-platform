import { node, patchHidden, patchText } from "/common/control-dom.js";

function partitionActiveHistory(items, isActive) {
  const active = [], history = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (isActive(item)) active.push(item);
    else history.push(item);
  }
  return { active, history };
}

/**
 * Active-first list renderer: keeps open/active items at the top container and folds completed/resolved items
 * into a separate <details class="history-fold"> without resetting its `.open` state across polls.
 */
export function renderActiveHistoryList({
  container,
  historyFold = null,
  historySummary = null,
  historyContainer = null,
  items,
  isActive,
  renderItem,
  emptyActiveText,
  emptyHistoryOnlyText = emptyActiveText,
  historyLabel = (count) => `이전 기록 ${count}건`,
  renderEmpty = (text) => node("li", text),
  sigMap,
  sigKey,
  sigInput = items,
}) {
  if (!container) return { active: [], history: [] };
  const { active, history } = partitionActiveHistory(items, isActive);
  const sig = JSON.stringify(sigInput);
  if (sigMap?.get(sigKey) === sig && container.firstElementChild) {
    return { active, history };
  }
  sigMap?.set(sigKey, sig);

  const emptyText = active.length ? "" : history.length ? emptyHistoryOnlyText : emptyActiveText;
  container.replaceChildren(...(active.length ? active.map(renderItem) : [renderEmpty(emptyText)]));

  if (historyFold && historyContainer) {
    const hasHistory = history.length > 0;
    patchHidden(historyFold, !hasHistory);
    if (historySummary) patchText(historySummary, hasHistory ? historyLabel(history.length) : "");
    historyContainer.replaceChildren(...(hasHistory ? history.map(renderItem) : []));
  }
  return { active, history };
}
