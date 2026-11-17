/** Pure rules behind choice-list.js and choice-group.js (keyboard motion, typeahead, toggle values). No DOM. */

/** Focus index after a listbox key (APG: Up/Down move by one without wrapping, Home/End jump); null = not a motion key. */
export function moveIndex(key, index, count) {
  if (!count) return null;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === "ArrowDown") return Math.min(count - 1, index + 1);
  if (key === "ArrowUp") return Math.max(0, index - 1);
  return null;
}

/** Typeahead: the next index at or after `from` (wrapping) whose label starts with `prefix`; -1 when none.
 *  A repeated single letter ("aaa") cycles through the labels that start with it. */
export function findByPrefix(labels, prefix, from) {
  const word = prefix.toLocaleLowerCase();
  const cycle = word.length > 1 && [...word].every(letter => letter === word[0]);
  const needle = cycle ? word[0] : word;
  const start = cycle || word.length === 1 ? from + 1 : from;
  for (let step = 0; step < labels.length; step++) {
    const at = (start + step) % labels.length;
    if (labels[at].toLocaleLowerCase().startsWith(needle)) return at;
  }
  return -1;
}

/** Toggle `value` in `values` (item order kept). A max (>0) refuses to add past it; returns the same array then. */
export function toggleValue(values, value, order, max) {
  if (values.includes(value)) return order.filter(item => values.includes(item) && item !== value);
  if (max > 0 && values.length >= max) return values;
  return order.filter(item => values.includes(item) || item === value);
}

/** The master toggle's aria-pressed word: "true" all on, "false" none, "mixed" some. */
export function masterState(on, total) {
  return !on ? "false" : on >= total ? "true" : "mixed";
}

/** Master press: all on (or max reached) turns all off; otherwise everything turns on (up to max). `enabled` = the values it may touch. */
export function masterValues(values, enabled, max) {
  const cap = max > 0 ? Math.min(max, enabled.length) : enabled.length;
  if (cap && values.length >= cap && values.every(item => enabled.includes(item))) return [];
  return enabled.slice(0, cap);
}

/** A list item's status as {state, text?, icon?, danger?}: a plain string is the state alone; anything else is no status. */
export function statusSpec(status) {
  if (!status) return null;
  if (typeof status === "string") return {state: status};
  return typeof status === "object" && status.state ? {state: status.state, text: status.text, icon: status.icon, danger: Boolean(status.danger)} : null;
}

const same = (a, b) => (a ?? "") === (b ?? "");
/** True when two item arrays draw the same DOM (field by field; poll-driven callers pass fresh objects every time). */
export function sameChoiceItems(a, b, kind) {
  if (a.length !== b.length) return false;
  return a.every((item, at) => {
    const other = b[at];
    if (kind === "group") return item.value === other.value && same(item.label, other.label) && same(item.reason, other.reason) && Boolean(item.disabled) === Boolean(other.disabled);
    const [first, second] = [statusSpec(item.status), statusSpec(other.status)];
    return item.id === other.id && same(item.label, other.label) && same(item.secondary, other.secondary) && same(item.icon, other.icon)
      && same(item.thumb, other.thumb) && Boolean(item.disabled) === Boolean(other.disabled)
      && (first === null ? second === null : second !== null && first.state === second.state && same(first.text, second.text) && same(first.icon, second.icon) && first.danger === second.danger);
  });
}
