// setGeometry(el, {x: 12, width: "40%", color: "var(--ink)"}) -- the ONE sanctioned element-style
// write on ROSY web surfaces (D1 in DESIGN.md). Everything else keeps `.style` out of scripts
// (test_no_element_style.py allows this file only).
//
// It writes custom properties named `--g-<name>` and nothing else, so a stylesheet decides
// what the value means: `width: var(--g-width, 100%)`. Every `var()` carries a safe default,
// which means a missing or rejected value falls back to the sheet. CSSOM writes are not
// blocked by `style-src 'self'` (only the style attribute and <style> text are).
//
// Custom properties inherit: give a parent and its child different names.
// Names: x y left top width height size fill scale color. Unknown name -> TypeError (a bug).
// Values: a finite number (px, or unitless for `scale`), a number with unit
// (px % rem em deg vw vh), `var(--token)` (any name), or #rrggbb / #rrggbbaa (`color` only).
// null/undefined removes the property. An invalid value (NaN, Infinity, free text) removes it too
// and returns false, so a bad computation shows the stylesheet default instead of garbage.
// Returns true when the value was written or removed on request.
const NAMES = new Set(["x", "y", "left", "top", "width", "height", "size", "fill", "scale", "color"]);
const WITH_UNIT = /^-?(?:\d+\.?\d*|\.\d+)(?:px|%|rem|em|deg|vw|vh)$/;
const TOKEN = /^var\(--[a-z][a-z0-9-]*\)$/;
const HEX = /^#(?:[0-9a-f]{6}|[0-9a-f]{8})$/i;

function cssValue(name, value) {
  if (typeof value === "number") { // rounded: JS prints 1e-7, which a CSS length rejects
    const n = Math.round(value * 1000) / 1000;
    return Number.isFinite(n) ? (name === "scale" ? String(n) : `${n}px`) : null;
  }
  if (typeof value !== "string") return null;
  if (WITH_UNIT.test(value)) return value;
  if (TOKEN.test(value)) return value;
  if (name === "color" && HEX.test(value)) return value;
  return null;
}

export function setGeometry(el, values) {
  let ok = true;
  for (const [name, value] of Object.entries(values)) {
    if (!NAMES.has(name)) throw new TypeError(`setGeometry: unknown name "${name}"`);
    const css = value == null ? null : cssValue(name, value);
    if (css === null) { el.style.removeProperty(`--g-${name}`); ok = ok && value == null; }
    else el.style.setProperty(`--g-${name}`, css);
  }
  return ok;
}
