// Timestamped operator log row writer shared across Fleet Console documents.
export function appendLogEntry(box, text, kind, maxEntries = 120) {
  if (!box) return;
  const line = document.createElement("div");
  if (kind) line.className = kind;
  const now = new Date().toTimeString().slice(0, 8);
  line.textContent = `${now}  ${text}`;
  box.querySelector("ui-empty")?.remove();
  box.prepend(line);
  while (box.childElementCount > maxEntries) box.lastElementChild.remove();
}
