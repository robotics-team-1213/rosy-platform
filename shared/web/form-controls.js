import {node, input, select} from "./control-dom.js";
import {confirmIrreversible} from "/common/ui.js";

// Errors augment existing native fields; the caller still owns validation and saving.
export function createFormErrors(form, summary) {
  const owned = new Map();
  function clear() {
    for (const [control, detail] of owned) {
      control.removeAttribute("aria-invalid");
      const ids = (control.getAttribute("aria-describedby") || "").split(/\s+/).filter(id => id && id !== detail.id);
      if (ids.length) control.setAttribute("aria-describedby", ids.join(" "));
      else control.removeAttribute("aria-describedby");
      detail.remove();
    }
    owned.clear();
    summary.replaceChildren();
    summary.hidden = true;
  }
  return {
    clear,
    show(errors, {focus = true} = {}) {
      clear();
      const list = node("ul");
      let firstControl = null;
      for (const [name, message] of Object.entries(errors)) {
        const field = form.elements.namedItem(name);
        const controls = field instanceof RadioNodeList ? [...field] : field instanceof HTMLElement ? [field] : [];
        if (!controls.length) throw new TypeError(`Unknown form field: ${name}`);
        if (controls.some(control => !control.id)) throw new TypeError("Validation fields need stable ids");
        const target = controls.find(control => !control.matches(":disabled"));
        firstControl ||= target;
        const detail = node("small", message, "ui-field-error");
        detail.id = `${controls[0].id}-error`;
        for (const control of controls) {
          control.setAttribute("aria-invalid", "true");
          const ids = new Set((control.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
          ids.add(detail.id);
          control.setAttribute("aria-describedby", [...ids].join(" "));
          owned.set(control, detail);
        }
        const last = controls.at(-1);
        const anchor = controls.length > 1 ? last.closest("fieldset") || last : last;
        anchor.insertAdjacentElement("afterend", detail);
        const item = node("li");
        const link = node("a", message);
        link.href = `#${target?.id || controls[0].id}`;
        link.addEventListener("click", event => {event.preventDefault(); (target || summary).focus();});
        item.append(link); list.append(item);
      }
      summary.hidden = !owned.size;
      summary.setAttribute("role", "alert");
      summary.append(list);
      summary.tabIndex = -1;
      if (focus && owned.size) (firstControl || summary).focus();
      return !owned.size;
    },
  };
}

export function createFilePicker({id, label, accept = ".json", maxBytes = 1024 * 1024, onChange = () => {}}) {
  const field = input(id, label, "file");
  field.control.accept = accept;
  const result = node("ui-status", "선택한 파일 없음");
  result.setAttribute("state", "empty");
  const element = node("div", "", "ui-control-stack");
  element.append(field.element, result);
  const suffixes = accept.split(",").map(value => value.trim().toLowerCase());
  const change = () => {
    const file = field.control.files[0] || null;
    let error = "";
    if (file && !suffixes.some(value => value.startsWith(".") ? file.name.toLowerCase().endsWith(value) :
      value.endsWith("/*") ? file.type.startsWith(value.slice(0, -1)) : file.type === value)) error = `${accept.replaceAll(".", "").toUpperCase()} 파일을 선택하세요`;
    if (file && file.size > maxBytes) error = `파일 크기는 ${maxBytes}바이트 이하여야 합니다`;
    field.control.setAttribute("aria-invalid", String(Boolean(error)));
    result.textContent = error || (file ? `${file.name} · ${file.size}바이트 · 서버 검증 전` : "선택한 파일 없음");
    result.setAttribute("state", error ? "error" : file ? "ready" : "empty");
    onChange(error ? null : file, error);
  };
  field.control.addEventListener("change", change);
  return {element, control: field.control, result, dispose: () => field.control.removeEventListener("change", change)};
}

// Search + native select avoids an incomplete custom combobox keyboard implementation.
export function createSearchSelect({id, label, choices, onChange = () => {}}) {
  const search = input(`${id}-search`, `${label} 검색`, "search");
  const options = select(`${id}-options`, label, []);
  const empty = node("ui-status", ""); empty.setAttribute("state", "empty");
  const element = node("div", "", "ui-control-stack");
  element.append(search.element, options.element, empty);
  let value = "";
  function paint() {
    const query = search.control.value.trim().toLocaleLowerCase();
    const matches = choices.filter(item => item.label.toLocaleLowerCase().includes(query));
    options.control.replaceChildren(...matches.map(item => new Option(item.label, item.value)));
    options.control.value = matches.some(item => item.value === value) ? value : "";
    empty.hidden = matches.length > 0;
    empty.textContent = matches.length ? "" : "검색 결과가 없습니다";
    options.control.disabled = !matches.length;
  }
  const change = () => {value = options.control.value; onChange(value);};
  search.control.addEventListener("input", paint);
  options.control.addEventListener("change", change);
  paint();
  return {element, search: search.control, control: options.control,
    update(next) {choices = next; if (!choices.some(item => item.value === value)) {value = ""; onChange(value);} paint();},
    dispose() {search.control.removeEventListener("input", paint); options.control.removeEventListener("change", change);}};
}

export function createDateRange({id, label, onChange = () => {}}) {
  const element = node("fieldset", "", "ui-control-stack");
  element.append(node("legend", `${label} · 현지 달력 날짜`));
  const start = input(`${id}-start`, "시작일", "date");
  const end = input(`${id}-end`, "종료일", "date");
  const result = node("ui-status", "기간을 선택하세요"); result.setAttribute("state", "empty");
  element.append(start.element, end.element, result);
  const change = () => {
    const error = start.control.value && end.control.value && start.control.value > end.control.value
      ? "종료일은 시작일 이후여야 합니다" : "";
    end.control.setCustomValidity(error);
    end.control.setAttribute("aria-invalid", String(Boolean(error)));
    result.setAttribute("state", error ? "error" : "ready");
    result.textContent = error || `${start.control.value || "시작 미지정"} ~ ${end.control.value || "종료 미지정"}`;
    onChange({start: start.control.value, end: end.control.value, error});
  };
  start.control.addEventListener("input", change); end.control.addEventListener("input", change);
  return {element, start: start.control, end: end.control, result,
    dispose() {start.control.removeEventListener("input", change); end.control.removeEventListener("input", change);}};
}

// Save/reset baselines are explicit; a failed save must never silently clear dirty state.
export function createDirtyGuard(form, {message = "저장하지 않은 변경을 버리고 이동할까요?"} = {}) {
  const snapshot = () => JSON.stringify([...new FormData(form)].map(([key, value]) => [key,
    value instanceof File ? value.name ? [value.name, value.size, value.lastModified] : null : value]));
  let baseline = snapshot(), pending = null, disposed = false;
  const controller = new AbortController();
  const dirty = () => snapshot() !== baseline;
  const beforeUnload = event => {if (dirty()) {event.preventDefault(); event.returnValue = "";}};
  window.addEventListener("beforeunload", beforeUnload);
  return {
    get dirty() {return dirty();},
    reset() {baseline = snapshot();},
    async canLeave(opener = document.activeElement) {
      if (disposed) return false;
      if (!dirty()) return true;
      if (!pending) pending = confirmIrreversible({message, action: "변경 버리기", opener, signal: controller.signal})
        .finally(() => {pending = null;});
      return pending;
    },
    dispose() {disposed = true; controller.abort(); window.removeEventListener("beforeunload", beforeUnload);},
  };
}
