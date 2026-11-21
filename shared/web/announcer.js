// C25 getAnnouncer: the one polite and the one assertive live region of a document (D-1117 alerts spec).
//   getAnnouncer(doc = document, {throttleMs = 2000}) -> {announce(text, {urgent = false})}   one per document, reused
//   announce never moves focus and never touches anything but the two hidden regions.
//   normal  -> polite region (role="status"): the same text as the last one is ignored (change-only); updates are spaced
//              throttleMs apart, the newest waiting text wins.
//   urgent  -> assertive region (role="alert"): written at once, never delayed or dropped, even when it repeats.
// Callers that already show the text (toast cards, queue rows) carry no aria-live of their own; this is the one voice.
const SINGLETONS = new WeakMap();

export function createAnnouncer(doc, {throttleMs = 2000, now = () => Date.now(),
                                      setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = (id) => clearTimeout(id)} = {}) {
  function region(role, live) {
    const el = doc.createElement("div");
    el.className = "sr-only";
    el.setAttribute("role", role);
    el.setAttribute("aria-live", live);
    el.setAttribute("aria-atomic", "true");
    doc.body.append(el);
    return el;
  }
  let polite = null, assertive = null;  // created on first use, once
  let lastPolite = "", lastWriteAt = -Infinity, pending = null, timer = null;

  function writePolite(text) {
    polite ??= region("status", "polite");
    polite.textContent = text;
    lastPolite = text;
    lastWriteAt = now();
  }
  function flush() {
    timer = null;
    const text = pending;
    pending = null;
    if (text !== null && text !== lastPolite) writePolite(text);
  }
  function announce(text, {urgent = false} = {}) {
    text = String(text ?? "").trim();
    if (!text) return;
    if (urgent) {
      assertive ??= region("alert", "assertive");
      assertive.textContent = "";  // an identical repeat still re-reads: clear, then write
      assertive.textContent = text;
      return;
    }
    if (text === (pending ?? lastPolite)) return;  // change-only
    const wait = lastWriteAt + throttleMs - now();
    if (wait <= 0 && timer === null) { writePolite(text); return; }
    pending = text;
    if (timer === null) timer = setTimer(flush, Math.max(wait, 0));
  }
  return {announce, _stop() { if (timer !== null) clearTimer(timer); timer = null; pending = null; }};
}

export function getAnnouncer(doc = globalThis.document, options) {
  let announcer = SINGLETONS.get(doc);
  if (!announcer) SINGLETONS.set(doc, announcer = createAnnouncer(doc, options));
  return announcer;
}
