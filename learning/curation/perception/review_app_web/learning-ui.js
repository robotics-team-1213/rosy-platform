// Shared DOM, UUID, select, and URL helpers for Rosy Learning review web pages.

export function domEl(tag, text, cls) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (cls) element.className = cls;
  return element;
}

export function makeUuid() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function fillSelectOptions(select, rows, placeholder = null) {
  const list = Array.isArray(rows) ? rows : [];
  const signature = JSON.stringify([placeholder, list]);
  const previous = select.value;
  if (select.dataset.signature === signature || select.dataset.options === signature) return;
  select.dataset.signature = signature;
  select.dataset.options = signature;
  const entries = placeholder == null ? list : [["", placeholder], ...list];
  select.replaceChildren(...entries.map(([value, label]) => {
    const option = domEl("option", label);
    option.value = value;
    return option;
  }));
  if (list.some(([id]) => id === previous)) select.value = previous;
}

export function safeLocalUrl(value, baseOrigin = location.origin) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return null;
  try {
    const url = new URL(value, baseOrigin);
    return url.origin === baseOrigin ? url.pathname + url.search : null;
  } catch {
    return null;
  }
}
