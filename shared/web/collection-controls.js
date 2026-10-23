import {node, action, input, select} from "./control-dom.js";

export function createListToolbar({id, filters = [], onChange}) {
  const element = node("div", "", "ui-list-toolbar");
  const search = input(`${id}-search`, "검색", "search");
  const filter = select(`${id}-filter`, "필터", [{value: "", label: "모두"}, ...filters]);
  const sort = select(`${id}-sort`, "이름 정렬", [{value: "ascending", label: "오름차순"},
    {value: "descending", label: "내림차순"}]);
  const count = node("ui-status"); count.id = `${id}-count`; count.setAttribute("state", "ready");
  const changed = () => onChange({query: search.control.value, filter: filter.control.value, sort: sort.control.value});
  const reset = action("검색·필터 초기화", () => {search.control.value = ""; filter.control.value = ""; changed();});
  element.append(search.element, filter.element, sort.element, reset, count);
  for (const [control, event] of [[search.control, "input"], [filter.control, "change"], [sort.control, "change"]]) control.addEventListener(event, changed);
  return {element, search: search.control, filter: filter.control, sort: sort.control, count,
    dispose() {for (const [control, event] of [[search.control, "input"], [filter.control, "change"], [sort.control, "change"]]) control.removeEventListener(event, changed);}};
}

// Explicit page facts come from the owner; a cursor-backed collection need not invent a total.
export function createPagination({id, onChange}) {
  let page = 1, last = 1, hasNext = false;
  const element = node("nav", "", "ui-pagination"); element.setAttribute("aria-label", "목록 페이지");
  const label = node("span"); label.id = `${id}-page`; label.setAttribute("aria-live", "polite");
  const previous = action("이전 페이지", () => onChange(page - 1)); previous.id = `${id}-previous`;
  const next = action("다음 페이지", () => onChange(page + 1)); next.id = `${id}-next`;
  element.append(previous, label, next);
  return {element, set({page: current, totalPages = null, hasNext: more = false}) {
    if (!Number.isInteger(current) || current < 1 || (totalPages !== null && (!Number.isInteger(totalPages) || totalPages < current))) {
      throw new RangeError("Invalid page facts");
    }
    page = current; last = totalPages; hasNext = last === null ? more : page < last;
    label.textContent = last === null ? `${page}페이지 · 전체 미확인` : `${page} / ${last}`;
    previous.disabled = page <= 1; next.disabled = !hasNext;
  }};
}

export function createDataTable({id, columns, onOpen, onSelection = () => {}, onActiveRemoved = () => {}}) {
  const element = node("div", "", "ui-table-scroll"); element.id = id;
  const table = node("table", "", "ui-data-table");
  const caption = node("caption", "자료 목록");
  const head = node("thead"), row = node("tr");
  for (const text of ["선택", ...columns.map(column => column.label), "동작"]) {
    const cell = node("th", text); cell.scope = "col"; row.append(cell);
  }
  head.append(row);
  const body = node("tbody"); table.append(caption, head, body);
  const empty = node("ui-empty", "검색 결과가 없습니다");
  element.append(table, empty);
  const selected = new Set();
  let visible = [], activeId = null;
  function paint() {
    const focused = document.activeElement;
    const focusId = focused?.dataset?.open || focused?.dataset?.select;
    const selectFocus = focused?.matches?.("input[data-select]");
    body.replaceChildren(...visible.map(item => {
      const tr = node("tr"); tr.dataset.key = item.id;
      tr.setAttribute("aria-selected", String(activeId === item.id));
      const choose = input(`${id}-${item.id}`, `${item.label} 선택`, "checkbox");
      choose.control.dataset.select = item.id; choose.control.checked = selected.has(item.id);
      choose.control.addEventListener("change", () => {
        if (choose.control.checked) selected.add(item.id); else selected.delete(item.id);
        onSelection(new Set(selected));
      });
      const cell = node("td"); cell.append(choose.element); tr.append(cell);
      for (const column of columns) tr.append(node("td", column.text(item)));
      const openCell = node("td");
      const open = action("상세 보기", () => {activeId = item.id; paint(); onOpen(item, () => body.querySelector(`[data-open="${CSS.escape(item.id)}"]`));});
      open.dataset.open = item.id; open.setAttribute("aria-label", `${item.label} 상세 보기`);
      openCell.append(open); tr.append(openCell);
      return tr;
    }));
    table.hidden = !visible.length; empty.hidden = Boolean(visible.length);
    if (focusId) body.querySelector(`[data-${selectFocus ? "select" : "open"}="${CSS.escape(focusId)}"]`)?.focus({preventScroll: true});
  }
  return {element,
    set(items, {allIds = items.map(item => item.id), label = "자료 목록"} = {}) {
      if (new Set(allIds).size !== allIds.length || allIds.some(value => typeof value !== "string" || !value)) throw new TypeError("Rows need unique stable string ids");
      const known = new Set(allIds);
      if (new Set(items.map(item => item.id)).size !== items.length || items.some(item => !known.has(item.id))) {
        throw new TypeError("Visible rows must have unique known ids");
      }
      const removed = [...selected].some(value => !known.has(value));
      for (const value of selected) if (!known.has(value)) selected.delete(value);
      const missingActive = activeId && !known.has(activeId) ? activeId : null;
      if (missingActive) activeId = null;
      visible = items; caption.textContent = label; paint();
      if (removed) onSelection(new Set(selected));
      if (missingActive) onActiveRemoved(missingActive);
    },
    selectPage(value) {for (const item of visible) {if (value) selected.add(item.id); else selected.delete(item.id);} paint(); onSelection(new Set(selected));},
    clearSelection() {selected.clear(); paint(); onSelection(new Set(selected));},
    get selection() {return new Set(selected);},
  };
}

export function createSelectionBar({id, onClear, actions = []}) {
  const element = node("div", "", "ui-selection-bar"); element.id = id;
  const label = node("ui-status"); label.setAttribute("state", "ready");
  const clear = action("선택 해제", onClear);
  const commands = actions.map(({label: text, onClick}) => action(text, onClick));
  element.append(label, ...commands, clear);
  return {element, set(count, {scope = "현재 페이지"} = {}) {
    label.textContent = `${count}개 선택 · ${scope}`;
    clear.hidden = !count;
    commands.forEach(button => {
      button.disabled = count === 0;
      if (!count) button.setAttribute("reason", "항목을 먼저 선택하세요"); else button.removeAttribute("reason");
    });
  }};
}

export function createPrimaryDetail({id, label, list}) {
  const element = node("div", "", "ui-primary-detail"); element.id = id;
  const primary = node("section"), detail = node("section", "", "ui-control-stack"); detail.id = `${id}-detail`;
  primary.tabIndex = -1; primary.setAttribute("aria-label", "자료 목록");
  detail.setAttribute("aria-label", label);
  const heading = node("h3"); heading.tabIndex = -1;
  const content = node("div");
  let opener = null, scrollY = 0;
  const back = action("목록으로 돌아가기", () => {
    element.removeAttribute("data-open"); detail.hidden = true;
    const target = typeof opener === "function" ? opener() : opener;
    (target?.isConnected ? target : primary).focus({preventScroll: true}); window.scrollTo(0, scrollY);
  });
  primary.append(list); detail.append(back, heading, content); detail.hidden = true;
  element.append(primary, detail);
  return {element, detail,
    unavailable(message = "선택한 자료가 목록에서 없어졌습니다") {
      heading.textContent = "대상 확인 필요"; content.replaceChildren(node("p", message));
    },
    open({title, body}, source = document.activeElement) {
      opener = source; scrollY = window.scrollY; heading.textContent = title;
      content.replaceChildren(body); detail.hidden = false; element.dataset.open = ""; heading.focus();
    },
  };
}
