/**
 * C2 busy scope: lock one screen region while a user action runs, then put every control back EXACTLY
 * as it was. Replaces the per-screen perform()/lock()/busy flags.
 *
 *   const scope = createBusyScope(mainEl, {status: statusEl, cause});   // cause: optional createCauseLine result(s), synced after each lock/restore
 *   await scope.run(async () => {...}, {label: "저장 결과를 확인하고 있습니다.", onError: showError});
 *   scope.busy                                  // true while run() is working
 *   scope.setDisabled(el, bool)                 // the one way to (un)lock a control; during run() it sets the target restored at the end
 *   await scope.refresh(read, apply, onError)   // background read: never locks, never blocks a click
 *
 * run(): a second call while busy is ignored (returns undefined). At start it snapshots `disabled` of
 * every button, ui-button, select, checkbox, radio and file input under root, and the `readOnly` of every text-like
 * input and textarea (`readonly` overrides that selector; `[data-busy-editable]` opts a field out), sets
 * aria-busy on root, writes `label` into the status line and points each locked control at it
 * (aria-describedby). While run() is active the scope OWNS `disabled` of the controls it locked: setDisabled()
 * (and a cause line given as `cause`, which routes its set() through it) records the wanted state instead of
 * touching the DOM, so nothing becomes usable while aria-busy is true. At the end each control gets its
 * recorded target, else its snapshot; controls that appeared meanwhile are left as built. Status text is put back only
 * if run() still owns it (the action did not write its own result). Focus that fell to <body> returns
 * to the control that started the action.
 *
 * Always exempt, by code, not by caller choice: stop and anything marked [data-always-live] or
 * [data-run-stop], also inside such a container. The caller cannot lock them.
 *
 * refresh(): a focus/poll read. While a run() is active refresh does not start, and if a run() starts
 * while a refresh is in flight the refresh result and error are dropped (the action reads fresh data
 * itself). It never touches `disabled`, so a user click is never swallowed.
 */
import { describeBy } from "./cause-line.js";

const EXEMPT = "[data-always-live], [data-run-stop], [data-busy-editable]";  // the last one opts a field out of the lock
const CONTROLS = "button, ui-button, select, input[type=checkbox], input[type=radio], input[type=file]";
// Text-like fields are locked read-only by default, so nothing typed during a run is lost or reset by load().
const TEXT = "input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=hidden]):not([type=button]):not([type=submit]):not([type=reset]), textarea";

export function createBusyScope(root, {status, readonly = TEXT, label = "처리 결과를 확인하고 있습니다.", cause} = {}) {
  const syncCauses = () => { for (const line of [].concat(cause ?? [])) line.sync(); };
  let locked = [];
  function setDisabled(el, value) {
    if (busy && locked.some(([control]) => control === el)) wanted.set(el, Boolean(value)); else el.disabled = Boolean(value);
  }
  for (const line of [].concat(cause ?? [])) line.bind?.(setDisabled);
  let busy = false, refreshing = false, runs = 0, wanted = new Map();
  const keep = (el) => !el.closest(EXEMPT);
  async function run(action, {label: text = label, onError} = {}) {
    if (busy) return undefined;
    busy = true; runs++; wanted = new Map();
    const opener = document.activeElement, previous = status && {text: status.textContent, state: status.getAttribute("state")};
    locked = [...root.querySelectorAll(CONTROLS)].filter(keep).map((el) => [el, el.disabled, null]);
    const seen = new Set(locked.map(([el]) => el));  // a control matching both selectors is locked once
    if (readonly) for (const el of root.querySelectorAll(readonly)) if (keep(el) && !seen.has(el)) locked.push([el, null, el.readOnly]);
    root.setAttribute("aria-busy", "true");
    if (status) { status.textContent = text; status.setAttribute("state", "pending"); }
    for (const [el, disabled] of locked) {
      if (disabled === null) el.readOnly = true; else el.disabled = true;
      if (status?.id) describeBy(el, status.id, true);
    }
    syncCauses();
    try { return await action(); }
    catch (error) { if (!onError) throw error; onError(error); return undefined; }
    finally {
      busy = false; root.removeAttribute("aria-busy"); const restoring = locked; locked = [];
      for (const [el, disabled, readOnly] of restoring) {
        if (status?.id) describeBy(el, status.id, false);
        if (!el.isConnected) continue;
        if (disabled === null) el.readOnly = readOnly;
        // a recorded target wins however the control was locked (disabled snapshot or readOnly)
        if (wanted.has(el)) el.disabled = wanted.get(el); else if (disabled !== null) el.disabled = disabled;
      }
      syncCauses();
      if (status && status.textContent === text) {
        status.textContent = previous.text;
        if (previous.state === null) status.removeAttribute("state"); else status.setAttribute("state", previous.state);
      }
      if (opener?.isConnected && !opener.disabled && (document.activeElement === document.body)) opener.focus({preventScroll: true});
    }
  }
  async function refresh(read, apply, onError) {
    if (busy || refreshing) return;
    refreshing = true; const generation = runs;
    try {
      const value = await read();
      if (generation === runs && !busy) apply?.(value);
    } catch (error) { if (generation === runs && !busy) onError?.(error); }
    finally { refreshing = false; }
  }
  return {run, refresh, setDisabled, get busy() { return busy; }, get refreshing() { return refreshing; }};
}
