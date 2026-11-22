/**
 * S1 one selection, one store. Every view that reads the same selection (map marker, row list, detail, inspector,
 * 3D view) subscribes to one createSelection(); no window event, no per-screen copy. Pure: no DOM, node can test it.
 *
 *   createSelection(initial = null) -> {get(), set(id, {source}?), subscribe(fn) -> off}
 *     get()         the selected id, or null
 *     set(id, opts) true when the value changed. The same value again notifies nobody. fn(id, {source}) runs once per
 *                   change, in subscribe order. `source` names the view that chose ("map", "roster", "3d"), so a view
 *                   can skip the echo of its own choice. A set() made inside a subscriber is notified first and stops
 *                   the outer round (the later subscribers already got the newest value).
 *     subscribe(fn) returns off(); off() during a round is safe.
 *   A view draws the selected mark from get() (see choice-controls.css, `--selection`); it never keeps its own copy.
 */
export function createSelection(initial = null) {
  let value = initial;
  const subscribers = new Set();
  return {
    get: () => value,
    set(id, {source} = {}) {
      if (id === value) return false;
      value = id;
      for (const fn of [...subscribers]) {
        if (value !== id) break;
        if (subscribers.has(fn)) fn(id, {source});
      }
      return true;
    },
    subscribe(fn) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  };
}
