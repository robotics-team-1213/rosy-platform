// The builder depends on the existing live-dialog owner, never on ui.js.
let serial = 0;
export function createConfirmIrreversible(openLiveDialog) {
  // With `note: {label, max}` the dialog also asks what the operator checked: the action stays disabled with a
  // reason until the trimmed text is 1..max characters, and the promise resolves to that text (else false).
  return function confirmIrreversible({message, action, opener = document.activeElement, signal, note = null} = {}) {
    if (signal?.aborted) return Promise.resolve(false);
    const dialog = document.createElement("dialog");
    dialog.className = "ui-confirm";
    const text = document.createElement("p");
    text.id = `ui-confirm-${++serial}`; text.textContent = message;
    dialog.setAttribute("aria-labelledby", text.id);
    const actions = document.createElement("ui-actions");
    const cancel = document.createElement("ui-button");
    let close;
    cancel.setAttribute("kind", "quiet"); cancel.textContent = "취소";
    cancel.addEventListener("click", () => close("cancel"));
    const run = document.createElement("ui-button");
    run.setAttribute("kind", "irreversible"); run.textContent = action;
    let field = null;
    run.addEventListener("click", () => close("confirm"));
    dialog.append(text);
    if (note) {
      const label = document.createElement("label");
      field = document.createElement("input");
      label.className = "ui-field-label"; label.textContent = note.label;
      field.className = "ui-field"; field.type = "text"; field.maxLength = note.max;
      const sync = () => {
        const filled = field.value.trim().length > 0;
        run.toggleAttribute("disabled", !filled);
        if (filled) run.removeAttribute("reason"); else run.setAttribute("reason", `${note.label}을(를) 적어야 합니다`);
      };
      field.addEventListener("input", sync); sync();
      label.append(field); dialog.append(label);
    }
    actions.append(cancel, run); dialog.append(actions);
    const asked = new Promise((resolve) => {
      const abort = () => close?.("cancel");
      signal?.addEventListener("abort", abort, {once: true});
      close = openLiveDialog(dialog, {initialFocus: field || cancel, opener, onClose: value => {
        signal?.removeEventListener("abort", abort);
        resolve(!signal?.aborted && value === "confirm");
      }});
      const closeLive = close;
      // An invalid note keeps the dialog open: confirm does nothing until the trimmed text is 1..max long.
      close = value => { if (value !== "confirm" || !field || (field.value.trim() && field.value.trim().length <= note.max)) closeLive(value); };
      if (signal?.aborted) abort();
    });
    return field ? asked.then(ok => (ok ? field.value.trim() : ok)) : asked;
  };
}
