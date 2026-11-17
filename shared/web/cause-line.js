/**
 * C1 cause line: one visible "why is this disabled" line per control group.
 *
 *   const cause = createCauseLine(groupEl, {line});   // line: optional existing element, else a <ui-status data-cause>
 *   cause.set([saveBtn, roleSelect], "이미 있는 로그인 ID라 승인할 수 없습니다");  // disables + records the reason
 *   cause.set([saveBtn], "");                          // releases the control and forgets its reason
 *   cause.sync();                                      // call after ANY other code changes `disabled` in the group;
 *                                                      // it also forgets controls that left the document (rebuilt rows)
 *   cause.size                                         // how many controls are tracked
 *   cause.dispose();
 *
 * Which API wins (decision): `<ui-button reason>` owns a SINGLE button (it draws its own <small> inside
 * the button). createCauseLine owns every group of two or more controls, or any non-button control
 * (select, input). Never give a control in a group a `reason` attribute. Both use describeBy() below, so
 * aria-describedby is edited in one place only.
 *
 * Sync rule: the line shows the distinct reasons of tracked controls that are disabled right now and
 * each of those controls points at the line by aria-describedby. Nothing watches the DOM: set() syncs,
 * createBusyScope({cause}) syncs after every lock and restore, and any other code that enables or
 * disables a tracked control calls sync() itself. A control that was enabled stops being described and an
 * empty line is hidden with the shared [hidden] rule. A forgotten sync() leaves a stale line; the browser
 * tests fail on that instead of the module repairing it.
 * A control disabled with no recorded reason is not described by this line (busy-scope points those at
 * its status line).
 */
let serial = 0;

/** Add or remove one id in an element's aria-describedby; other ids are kept. */
export function describeBy(el, id, on) {
  const ids = (el.getAttribute("aria-describedby") || "").split(/\s+/).filter((item) => item && item !== id);
  if (on) ids.push(id);
  if (ids.length) el.setAttribute("aria-describedby", ids.join(" ")); else el.removeAttribute("aria-describedby");
}

export function createCauseLine(group, {line} = {}) {
  const owned = !line;
  if (!line) {
    line = document.createElement("ui-status"); line.dataset.cause = ""; group.append(line);
  }
  if (!line.id) line.id = `cause-${++serial}`;
  let reasons = new Map();
  let write = (control, disabled) => { control.disabled = disabled; };  // createBusyScope({cause}) rebinds this
  function sync() {
    const shown = new Set();
    const attached = (control) => control.isConnected || (Boolean(group) && !group.isConnected && group.contains(control));
    reasons = new Map([...reasons].filter(([control]) => attached(control)));  // rebuilt rows must not pile up
    for (const [control, text] of reasons) {
      const live = Boolean(text) && attached(control) && control.disabled;
      describeBy(control, line.id, live);
      if (live) shown.add(text);
    }
    line.textContent = [...shown].join(" · ");
    line.hidden = !shown.size;
  }
  sync();
  return {
    element: line,
    set(controls, text) {
      for (const control of [].concat(controls)) {
        reasons.set(control, text || ""); write(control, Boolean(text));  // "" keeps the control listed but silent
      }
      sync();
    },
    sync,
    get size() { return reasons.size; },
    /** Route every disabled write through fn(control, disabled); createBusyScope uses it so a run owns `disabled`. */
    bind(fn) { write = fn; },
    dispose() {
      for (const control of reasons.keys()) describeBy(control, line.id, false);
      reasons.clear(); if (owned) line.remove(); else { line.textContent = ""; line.hidden = true; }
    },
  };
}
