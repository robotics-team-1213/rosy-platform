// The builder depends on the existing live-dialog owner, never on ui.js.
let serial = 0;
export function createConfirmIrreversible(openLiveDialog) {
  return function confirmIrreversible({message, action, opener = document.activeElement, signal} = {}) {
    if (signal?.aborted) return Promise.resolve(false);
    const dialog = document.createElement("dialog");
    dialog.className = "ui-confirm";
    const text = document.createElement("p");
    text.id = `ui-confirm-${++serial}`; text.textContent = message;
    dialog.setAttribute("aria-labelledby", text.id);
    const actions = document.createElement("ui-actions");
    const cancel = document.createElement("ui-button");
    cancel.setAttribute("kind", "quiet"); cancel.textContent = "취소";
    cancel.addEventListener("click", () => dialog.close("cancel"));
    const run = document.createElement("ui-button");
    run.setAttribute("kind", "irreversible"); run.textContent = action;
    run.addEventListener("click", () => dialog.close("confirm"));
    actions.append(cancel, run); dialog.append(text, actions);
    return new Promise((resolve) => {
      const abort = () => { if (dialog.open) dialog.close("cancel"); };
      signal?.addEventListener("abort", abort, {once: true});
      openLiveDialog(dialog, {initialFocus: cancel, opener, onClose: value => {
        signal?.removeEventListener("abort", abort);
        resolve(!signal?.aborted && value === "confirm");
      }});
      if (signal?.aborted) abort();
    });
  };
}
