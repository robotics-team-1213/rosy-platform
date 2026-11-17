import { createConfirmIrreversible } from "./confirmation.js";
import { disjointRectangles } from "./live-dialog-geometry.js";
import { describeBy } from "./cause-line.js";
import "./ui-wiring.js";
const KINDS = ["primary", "quiet", "irreversible", "segment", "toggle"];
const BUTTON_SIZES = ["secondary", "primary", "irreversible"];
const KIND_SIZES = { primary: "primary", irreversible: "irreversible" };
let reasonSerial = 0;

class UiButton extends HTMLElement {
  static formAssociated = true;
  static get observedAttributes() { return ["disabled", "kind", "size", "reason"]; }
  constructor() {
    super();
    this._internals = this.attachInternals();
    this._onKey = (event) => { if ((event.key === " " || event.key === "Enter") && event.target === this) { event.preventDefault(); this.click(); } };
    this._onClick = (event) => {
      if (this.disabled) { event.preventDefault(); event.stopImmediatePropagation(); return; }
      if (this.type === "submit" && this._internals.form) { event.preventDefault(); this._internals.form.requestSubmit(); }
    };
  }
  connectedCallback() {
    if (!KINDS.includes(this.getAttribute("kind"))) this.setAttribute("data-kind-missing", "true");
    if (!this.hasAttribute("type")) this.setAttribute("type", "button");
    if (!this.hasAttribute("role")) this.setAttribute("role", "button");
    this._sync(); this.addEventListener("keydown", this._onKey); this.addEventListener("click", this._onClick, true);
  }
  disconnectedCallback() { this.removeEventListener("keydown", this._onKey); this.removeEventListener("click", this._onClick, true); }
  attributeChangedCallback() { this._sync(); }
  get disabled() { return this.hasAttribute("disabled"); }
  set disabled(value) { this.toggleAttribute("disabled", Boolean(value)); }
  get type() { return this.getAttribute("type") || "button"; }
  set type(value) { this.setAttribute("type", value || "button"); }
  get reason() { return this.getAttribute("reason") || ""; }
  set reason(value) { if (value) this.setAttribute("reason", String(value)); else this.removeAttribute("reason"); }
  _sync() {
    const kind = this.getAttribute("kind"), size = this.getAttribute("size") || KIND_SIZES[kind] || "secondary", off = this.disabled;
    this.dataset.size = BUTTON_SIZES.includes(size) ? size : "secondary";
    if (BUTTON_SIZES.includes(size)) delete this.dataset.sizeMissing; else this.dataset.sizeMissing = "true";
    this.tabIndex = off || this.matches('[role="tab"][aria-selected="false"]') ? -1 : 0;
    this.setAttribute("aria-disabled", off ? "true" : "false"); this._syncReason();
  }
  _syncReason() {
    const text = (this.getAttribute("reason") || "").trim(), node = this._reasonNode;
    if (!text) { this._reasonWatch?.disconnect(); if (node) { node.remove(); this._describe(node.id, false); } return; }
    if (!node) {
      this._reasonNode = document.createElement("small"); this._reasonNode.dataset.reason = "";
      this._reasonNode.id = `ui-reason-${++reasonSerial}`; this._reasonNode.setAttribute("aria-hidden", "true");
    }
    const reason = this._reasonNode;
    if (reason.textContent !== text) reason.textContent = text;
    if (reason.parentNode !== this) this.append(reason);
    this._describe(reason.id, true);
    if (!this._reasonWatch) this._reasonWatch = new MutationObserver(() => { if (this.getAttribute("reason") && reason.parentNode !== this) this.append(reason); });
    this._reasonWatch.observe(this, { childList: true });
  }
  _describe(id, on) { describeBy(this, id, on); }
}
class UiField extends HTMLElement {
  connectedCallback() {
    if (this.querySelector("input, select, textarea")) return;
    const input = document.createElement("input");
    for (const name of ["type", "name", "placeholder", "autocomplete", "value", "required", "aria-label", "autocapitalize", "autocorrect", "spellcheck", "inputmode"]) {
      if (this.hasAttribute(name)) input.setAttribute(name, this.getAttribute(name));
    }
    if (this.hasAttribute("invalid")) input.setAttribute("aria-invalid", "true");
    this.append(input);
  }
  get input() { return this.querySelector("input, select, textarea"); }
  get value() { return this.input ? this.input.value : ""; }
  set value(next) { if (this.input) this.input.value = next; }
  get disabled() { return this.hasAttribute("disabled"); }
  set disabled(value) { this.toggleAttribute("disabled", Boolean(value)); if (this.input) this.input.disabled = Boolean(value); }
  focus() { this.input?.focus(); }
}
class UiTag extends HTMLElement { connectedCallback() { if (!this.hasAttribute("status")) this.setAttribute("status", "neutral"); } }
class UiText extends HTMLElement { connectedCallback() { if (!this.hasAttribute("scale")) this.setAttribute("scale", "body"); } }
const EVIDENCE = ["fresh", "delayed", "disconnected", "unavailable"];
const MARKS = ["neutral", "warn", "crit"];
class UiHead extends HTMLElement {
  connectedCallback() {
    if (this.querySelector("[data-rule]")) return;
    const rule = document.createElement("span"), last = this.lastElementChild;
    rule.dataset.rule = ""; rule.setAttribute("aria-hidden", "true");
    if (last && this.children.length > 1) this.insertBefore(rule, last); else this.append(rule);
  }
}
class UiGrid extends HTMLElement { connectedCallback() { if (!this.hasAttribute("columns")) this.setAttribute("columns", "3"); } }
class UiChip extends HTMLElement {}
class UiTriage extends HTMLElement { connectedCallback() { if (!MARKS.includes(this.getAttribute("status"))) this.setAttribute("status", "neutral"); } }
const GRAMMARS = ["spatial", "exception", "focal", "procedure"];
class UiShell extends HTMLElement { connectedCallback() { if (!GRAMMARS.includes(this.getAttribute("grammar"))) this.setAttribute("data-grammar-missing", "true"); } }
class UiTopbar extends HTMLElement {}
class UiBrand extends HTMLElement {
  connectedCallback() {
    const href = this.getAttribute("href");
    if (!href || this.querySelector("a")) return;
    const link = document.createElement("a"), label = this.getAttribute("aria-label");
    link.setAttribute("href", href);
    if (label) { link.setAttribute("aria-label", label); this.removeAttribute("aria-label"); }
    while (this.firstChild) link.append(this.firstChild);
    this.append(link);
  }
}
class UiSection extends HTMLElement { connectedCallback() { if (!this.hasAttribute("role")) this.setAttribute("role", "region"); } }
class UiEmpty extends HTMLElement {}
class UiActions extends HTMLElement {}
const STATUS_STATES = ["pending", "empty", "ready", "warning", "error", "unavailable", "forbidden"];
class UiStatus extends HTMLElement {
  static get observedAttributes() { return ["state"]; }
  connectedCallback() {
    if (!this.hasAttribute("role")) this.setAttribute("role", "status");
    if (!this.hasAttribute("aria-live") && this.getAttribute("role") !== "alert") this.setAttribute("aria-live", "polite");
    this._syncState();
  }
  attributeChangedCallback() { this._syncState(); }
  _syncState() {
    const state = this.getAttribute("state") || "pending";
    if (STATUS_STATES.includes(state)) { this.dataset.state = state; delete this.dataset.stateMissing; }
    else { delete this.dataset.state; this.dataset.stateMissing = "true"; }
  }
}
class UiEvidence extends HTMLElement { connectedCallback() { if (!EVIDENCE.includes(this.getAttribute("state"))) this.setAttribute("data-state-missing", "true"); } }
for (const [name, ctor] of [
  ["ui-button", UiButton], ["ui-field", UiField], ["ui-text", UiText], ["ui-tag", UiTag], ["ui-head", UiHead], ["ui-grid", UiGrid], ["ui-chip", UiChip], ["ui-triage", UiTriage],
  ["ui-evidence", UiEvidence], ["ui-shell", UiShell], ["ui-topbar", UiTopbar], ["ui-brand", UiBrand], ["ui-section", UiSection], ["ui-empty", UiEmpty], ["ui-actions", UiActions], ["ui-status", UiStatus],
]) { if (!customElements.get(name)) customElements.define(name, ctor); }

export const confirmIrreversible = createConfirmIrreversible(openLiveDialog);
const ALWAYS_LIVE = "[data-always-live]";
const DIALOG_FOCUSABLE = "input:not([type=hidden]), select, textarea, button, ui-button, a[href], [tabindex]:not([tabindex='-1'])";

export function openLiveDialog(dialog, { initialFocus = null, opener = document.activeElement, onClose } = {}) {
  dialog.classList.add("ui-live-dialog");
  const home = dialog.isConnected ? { parent: dialog.parentNode, next: dialog.nextSibling } : null;
  const scrim = document.createElement("div"); scrim.className = "ui-confirm-scrim"; scrim.setAttribute("aria-hidden", "true");
  const inerted = new Set(), liveNodes = () => [...document.querySelectorAll(ALWAYS_LIVE)], shown = (node) => node.getClientRects().length > 0 && !node.disabled;
  let byStop = false, finished = false;
  const seal = () => {
    const keep = [...liveNodes(), dialog];
    const walk = (parent) => {
      for (const child of parent.children) {
        const holds = keep.some((node) => child === node || child.contains(node));
        if (holds && inerted.has(child)) { child.inert = false; inerted.delete(child); }
        if (holds) { if (!keep.includes(child)) walk(child); continue; }
        if (child !== scrim && !child.inert) { child.inert = true; inerted.add(child); }
      }
    };
    walk(document.body);
  };
  const punch = () => {
    const holes = disjointRectangles(liveNodes().filter(node => node.getClientRects().length > 0).map(node => node.getBoundingClientRect()), innerWidth, innerHeight).map(
      r => `0 0, ${r.left}px ${r.top}px, ${r.right}px ${r.top}px, ${r.right}px ${r.bottom}px, ${r.left}px ${r.bottom}px, ${r.left}px ${r.top}px`
    );
    const polygon = holes.length ? `polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, ${holes.join(", ")}, 0 0)` : "";
    if (polygon) scrim.setAttribute("data-clip", polygon); else scrim.removeAttribute("data-clip");
  };
  const observer = new MutationObserver(() => { seal(); punch(); });
  const onKey = (event) => {
    if (event.key === "Escape") { event.preventDefault(); close("cancel"); return; }
    if (event.key !== "Tab") return;
    const ring = [...dialog.querySelectorAll(DIALOG_FOCUSABLE)].filter(shown).concat(liveNodes().filter(shown));
    if (!ring.length) return;
    const at = ring.findIndex((node) => node === document.activeElement || node.contains(document.activeElement)), step = event.shiftKey ? -1 : 1;
    event.preventDefault(); ring[at < 0 ? 0 : (at + step + ring.length) % ring.length].focus();
  };
  const onClick = (event) => { if (event.target.closest?.(ALWAYS_LIVE)) { byStop = true; close("cancel"); } };
  const finish = () => {
    if (finished) return;
    finished = true; dialog.removeEventListener("close", onNativeClose); observer.disconnect();
    document.removeEventListener("keydown", onKey, true); document.removeEventListener("click", onClick, true);
    removeEventListener("resize", punch); removeEventListener("scroll", punch, true);
    for (const node of inerted) node.inert = false;
    inerted.clear(); scrim.remove();
    if (home?.parent.isConnected) home.parent.insertBefore(dialog, home.next?.parentNode === home.parent ? home.next : null); else dialog.remove();
    if (!byStop) { const back = typeof opener === "function" ? opener() : opener; if (back?.isConnected && typeof back.focus === "function") back.focus(); }
    onClose?.(dialog.returnValue, { byStop });
  };
  const close = value => { if (finished) return; if (dialog.open) dialog.close(value); finish(); };
  const onNativeClose = () => { if (!dialog.open) finish(); };
  dialog.addEventListener("close", onNativeClose); document.body.append(scrim, dialog); seal(); punch();
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener("keydown", onKey, true); document.addEventListener("click", onClick, true);
  addEventListener("resize", punch); addEventListener("scroll", punch, { capture: true, passive: true });
  dialog.returnValue = ""; dialog.show();
  (initialFocus || [...dialog.querySelectorAll(DIALOG_FOCUSABLE)].find(shown))?.focus();
  return close;
}

const colourCache = new Map(), fontCache = new Map();
let colourProbe = null, colourRaster = null, colourSheet = null;
function probeColourValue(name) {
  if (name.startsWith("--")) return /^--[A-Za-z0-9_-]+$/.test(name) ? `var(${name})` : "";
  return !name || /[{};<>\\]|\/\*|\*\//.test(name) ? "" : name;
}
function paintColourProbe(value) {
  if (!colourSheet) { colourSheet = new CSSStyleSheet(); document.adoptedStyleSheets = [...document.adoptedStyleSheets, colourSheet]; }
  colourSheet.replaceSync(`[data-rosy-colour-probe] { color: ${value}; }`);
}
function probeElement() {
  if (!colourProbe || !colourProbe.isConnected) {
    colourProbe = document.createElement("span"); colourProbe.hidden = true;
    colourProbe.setAttribute("aria-hidden", "true"); colourProbe.dataset.rosyColourProbe = ""; document.documentElement.append(colourProbe);
  }
  return colourProbe;
}
function rasterContext() {
  if (!colourRaster) { const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1; colourRaster = canvas.getContext("2d", { willReadFrequently: true }); }
  return colourRaster;
}
export function readColour(name) {
  if (colourCache.has(name)) return colourCache.get(name);
  const declared = name.startsWith("--") ? getComputedStyle(document.documentElement).getPropertyValue(name).trim() : name, painted = probeColourValue(name);
  let rgba = [0, 0, 0, 0];
  if (declared && painted) {
    const probe = probeElement(), ctx = rasterContext(); paintColourProbe(painted);
    ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = getComputedStyle(probe).color; ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data; rgba = [r, g, b, Math.round((a / 255) * 1000) / 1000];
  }
  colourCache.set(name, rgba); return rgba;
}
export function readPalette(names) {
  const palette = {};
  for (const [key, name] of (Array.isArray(names) ? names.map((name) => [name, name]) : Object.entries(names))) palette[key] = readColour(name);
  return palette;
}
export function cssColor(name) { const [r, g, b, a] = readColour(name); return `rgba(${r}, ${g}, ${b}, ${a})`; }
export function canvasTextSize(role = "micro") {
  if (!["micro", "label", "body", "value", "title", "display"].includes(role)) throw new TypeError(`Unknown canvas text role: ${role}`);
  if (fontCache.has(`size:${role}`)) return fontCache.get(`size:${role}`);
  if (!getComputedStyle(document.documentElement).getPropertyValue(`--text-${role}`).trim()) throw new Error(`Missing canvas text token: --text-${role}`);
  const probe = document.createElement("span"), sheet = new CSSStyleSheet();
  probe.hidden = true; probe.dataset.rosyFontProbe = "";
  sheet.replaceSync(`[data-rosy-font-probe] { font-size: var(--text-${role}); }`);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet]; document.documentElement.append(probe);
  const size = parseFloat(getComputedStyle(probe).fontSize); probe.remove();
  document.adoptedStyleSheets = document.adoptedStyleSheets.filter((entry) => entry !== sheet);
  if (!Number.isFinite(size) || size <= 0) throw new Error(`Missing canvas text token: --text-${role}`);
  fontCache.set(`size:${role}`, size); return size;
}
export function canvasFont(role = "micro", family = "body", displayScale = 1) {
  const size = canvasTextSize(role), scale = Number(displayScale);
  if (!["body", "mono"].includes(family)) throw new TypeError(`Unknown canvas font family: ${family}`);
  if (!Number.isFinite(scale) || scale <= 0) throw new RangeError("Canvas display scale must be positive");
  if (!fontCache.has(family)) {
    const stack = getComputedStyle(document.documentElement).getPropertyValue(`--${family}`).trim();
    fontCache.set(family, stack || (family === "mono" ? "monospace" : "sans-serif"));
  }
  return `${Math.max(1, Math.round(size * scale))}px ${fontCache.get(family)}`;
}
export function clearPalette() { colourCache.clear(); fontCache.clear(); }
document.addEventListener("rosy:theme", clearPalette);
window.RosyPalette = { readColour, readPalette, cssColor, canvasFont, canvasTextSize, clear: clearPalette };

const HANGUL = /[ᄀ-ᇿ㄰-㆏가-힯]/;
function markHangul(element) {
  if (!(element instanceof Element)) return;
  const hangul = [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && HANGUL.test(node.data));
  if (element.hasAttribute("data-hangul") !== hangul) element.toggleAttribute("data-hangul", hangul);
}
function markHangulTree(root) { if (root instanceof Element) { markHangul(root); for (const element of root.querySelectorAll("*")) markHangul(element); } }
new MutationObserver((records) => {
  for (const record of records) {
    if (record.type === "characterData") { markHangul(record.target.parentElement); continue; }
    markHangul(record.target); for (const node of record.addedNodes) markHangulTree(node);
  }
}).observe(document.documentElement, { childList: true, characterData: true, subtree: true });
markHangulTree(document.documentElement);

// One glyph per name: 24 viewBox, stroke 2, round caps/joins, currentColor. A hoisted function, not a const: ui-wiring.js
// (imported above, circular) draws icons before this module body runs.
function icons() { return icons.table ??= {
  fleet: "M9 9h6v6H9zM3 3h4v4H3zM17 3h4v4h-4zM3 17h4v4H3zM17 17h4v4h-4zM7 7l2 2M15 9l2-2M7 17l2-2M15 15l2 2",
  map: "M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2zM9 3v16M15 5v16",
  install: "M15 12l-8.5 8.5a2.12 2.12 0 0 1-3-3L12 9M17.64 15 22 10.64M20.91 11.7l-1.25-1.25a3.2 3.2 0 0 1-.93-2.25v-.86L16 4.6a5.56 5.56 0 0 0-3.94-1.64H9l.92.82A6.18 6.18 0 0 1 12 8.4v1.56l2 2h2.47l2.26 1.91",
  cell: "M3 3h18v18H3zM3 15h18M9 15v-5h6v5",
  notification: "M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zM10 21h4M12 2v2",
  history: "M3 3v5h5M3 8a9 9 0 1 1-1 7M12 7v5l3 2",
  connect: "M9 15l6-6M7 13l-2 2a4 4 0 0 0 6 6l2-2M11 5l2-2a4 4 0 0 1 6 6l-2 2",
  login: "M3 12h12M11 8l4 4-4 4M19 4v16",
  account: "M12 3a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM20 21a8 8 0 0 0-16 0",
  logout: "M9 12h12M17 8l4 4-4 4M5 4v16",
  wifi: "M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0M8 16a6 6 0 0 1 8 0M12 20h.01",
  fit: "M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3M9 9h6v6H9z",
  expand: "M9 3H3v6M15 3h6v6M3 15v6h6M21 15v6h-6",
  tools: "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z",
  settings: "M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4",
  "theme-dark": "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  "theme-light": [{d: "M12,8 A4,4 0 1,1 12,16 A4,4 0 1,1 12,8 Z"}, {d: "M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"}],
  "theme-system": [{d: "M5 4H19A2 2 0 0 1 21 6V14A2 2 0 0 1 19 16H5A2 2 0 0 1 3 14V6A2 2 0 0 1 5 4Z"}, {d: "M8.5 20h7M12 16v4"}],
  estop: [{d: "M12 2 19.1 4.9 22 12 19.1 19.1 12 22 4.9 19.1 2 12 4.9 4.9Z"}, {d: "M9 8H15A1 1 0 0 1 16 9V15A1 1 0 0 1 15 16H9A1 1 0 0 1 8 15V9A1 1 0 0 1 9 8Z", fill: "currentColor", stroke: "none"}],
  pose: [{d: "M12,5 A7,7 0 1,1 12,19 A7,7 0 1,1 12,5 Z"}, {d: "M12 2v3M12 19v3M2 12h3M19 12h3"}],
  yaw: [{d: "M12,3 A9,9 0 1,1 12,21 A9,9 0 1,1 12,3 Z"}, {d: "m15.5 8.5-2.1 4.9-4.9 2.1 2.1-4.9z"}],
  battery: [{d: "M4.5 8H16.5A1.5 1.5 0 0 1 18 9.5V14.5A1.5 1.5 0 0 1 16.5 16H4.5A1.5 1.5 0 0 1 3 14.5V9.5A1.5 1.5 0 0 1 4.5 8Z"}, {d: "M21 10.5v3M6.5 10.5v3M10 10.5v3M13.5 10.5v3"}],
  safety: "M12 3l7 3v5c0 4.4-3 7.5-7 9-4-1.5-7-4.6-7-9V6z",
  back: "M15 5l-7 7 7 7",
  refresh: "M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 2M18 17a7 7 0 0 1-12 1l-2-2",
  download: "M12 3v12M7 10l5 5 5-5M4 17v4h16v-4",
  close: "M6 6l12 12M18 6L6 18",
  forward: "M12 20V4M5 11l7-7 7 7",
  reverse: "M12 4v16M5 13l7 7 7-7",
  left: "M4 8h9a7 7 0 0 1 7 7v4M9 3L4 8l5 5",
  right: "M20 8h-9a7 7 0 0 0-7 7v4M15 3l5 5-5 5",
  check: "M4 12l5 5L20 6",
  plus: "M12 4v16M4 12h16",
  minus: "M4 12h16",
  hand: "M8 12V6a1.5 1.5 0 0 1 3 0v4-1V4a1.5 1.5 0 0 1 3 0v6-1V6a1.5 1.5 0 0 1 3 0v5l.5-1a1.5 1.5 0 0 1 2.5 1.5L17 20H9l-5-7a1.5 1.5 0 0 1 2.5-1.5z",
  trash: "M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v6M14 11v6",
  undo: "M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-2",
  pencil: "M4 20l4-.8L20 7l-3-3L4.8 16zM15 6l3 3",
  image: "M4 4h16v16H4zM7 16l4-4 3 3 3-4 3 4M8 8h.01",
  contrast: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 3v18",
  robot: "M4 9h16v9H4zM7 9V6l3-2h4l3 2v3M8 18v2M16 18v2M8 13h.01M16 13h.01",
  cone: "M9 4h6l4 15H5zM3 20h18M8 13h8",
  "traffic-light": "M8 2h8v20H8zM12 6h.01M12 12h.01M12 18h.01",
  sign: "M5 3h14v11H5zM12 14v7M7 21h10",
  "person-feet": "M7 4c-2 2-2 5-1 7l3 1 1-7zM14 10c-1 2-1 5 1 7l3-1c1-3 0-5-2-7zM5 15l5 1M14 20l5-1",
  person: "M12 3a2 2 0 1 0 .01 0M8 22l1.5-7L7 11l5-2 5 2-2.5 4L16 22",
  obstacle: "M12 3 21 20H3zM12 9v5M12 17h.01",
  next: "M4 12h16m-7-7 7 7-7 7",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  // log: a ledger (bound sheet with entry lines) for record/log navigation; list is bullets, history is the delayed-status clock.
  log: "M5 3h14v18H5zM9 3v18M13 8h3M13 12h3M13 16h3",
  box: "M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16zM3.3 7 12 12l8.7-5M12 22V12",
  area: "M4 18 8 5l12 3-3 12zM4 18h.01M8 5h.01M20 8h.01M17 20h.01",
  pixels: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  folder: "M3 7V5h7l2 2h9v12H3z",
  warn: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  lock: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
  info: [{d: "M12,3 A9,9 0 1,1 12,21 A9,9 0 1,1 12,3 Z"}, {d: "M12 11v6M12 7.5h.01"}],
  // objects (robot = Pinky body, arm = OMX arm)
  arm: "M4 21h9v-3H4zM8.5 18v-7l8-5M16.5 6l3.5 1M16.5 6l1-3.5",
  station: "M3 20h18M6 20V9l6-5 6 5v11M10 20v-6h4v6",
  charger: "M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3",
  camera: "M3 8h4l2-3h6l2 3h4v12H3zM12 10.5a3.25 3.25 0 1 0 0 6.5 3.25 3.25 0 0 0 0-6.5z",
  lidar: "M4 20h16M6 20v-4h12v4M9 16v-3a3 3 0 0 1 6 0v3M12 3v2M4 7l1.5 1.5M20 7l-1.5 1.5",
  route: "M8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM21 8a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM6 16v-4a4 4 0 0 1 4-4h6",
  pin: "M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11zM12 7.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
  task: "M9 4h6v3H9zM7 5.5H5V21h14V5.5h-2M9 14l2 2 4-4",
  mission: "M5 21V4M5 4h13l-3 4 3 4H5",
  host: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  dataset: "M4 6c0 1.7 3.6 3 8 3s8-1.3 8-3-3.6-3-8-3-8 1.3-8 3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  model: "M12 3 3 7.5 12 12l9-4.5zM3 12l9 4.5 9-4.5M3 16.5 12 21l9-4.5",
  // actions (approve = check, reject = close, retry = refresh, delete = trash, edit = pencil, export = download)
  play: "M7 4l13 8-13 8z",
  pause: "M8 4v16M16 4v16",
  stop: "M5 5h14v14H5z",
  record: [{d: "M12,3 A9,9 0 1,1 12,21 A9,9 0 1,1 12,3 Z"}, {d: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", fill: "currentColor", stroke: "none"}],
  assign: "M10 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM2 21a8 8 0 0 1 14-5M19 14v6M16 17h6",
  upload: "M12 15V3M7 8l5-5 5 5M4 17v4h16v-4",
  search: "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15zM16 16l5 5",
  filter: "M3 4h18l-7 8v7l-4 2v-9z",
  more: [{d: "M5 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z", fill: "currentColor", stroke: "none"}, {d: "M12 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z", fill: "currentColor", stroke: "none"}, {d: "M19 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z", fill: "currentColor", stroke: "none"}],
  "chevron-down": "M5 9l7 7 7-7",
  "chevron-up": "M5 15l7-7 7 7",
  "chevron-right": "M9 5l7 7-7 7",
  copy: "M9 9h12v12H9zM15 9V3H3v12h6",
  external: "M14 3h7v7M21 3l-9 9M18 14v7H3V6h7",
  help: [{d: "M12,3 A9,9 0 1,1 12,21 A9,9 0 1,1 12,3 Z"}, {d: "M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01"}],
  save: "M4 4h13l3 3v13H4zM8 4v5h8V4M8 20v-6h8v6",
  // measurements (battery exists)
  charging: "M13 2 5 13h6l-1 9 8-11h-6z",
  temperature: "M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0zM12 9v8",
  speed: "M4 18a9 9 0 1 1 16 0M12 18l4-6",
  signal: "M5 20v-4M10 20v-8M15 20V8M20 20V4",
  time: [{d: "M12,3 A9,9 0 1,1 12,21 A9,9 0 1,1 12,3 Z"}, {d: "M12 7v5l3 2"}],
  distance: "M3 8v8M21 8v8M3 12h18M7 9l-4 3 4 3M17 9l4 3-4 3",
  cpu: "M7 7h10v10H7zM10 10h4v4h-4zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4",
  memory: "M3 7h18v10H3zM7 7v10M12 7v10M17 7v10M6 20v-3M10 20v-3M14 20v-3M18 20v-3",
  disk: "M3 5h18v14H3zM12.5 12a3.5 3.5 0 1 0-7 0 3.5 3.5 0 0 0 7 0zM16 12h2",
}; }
export const actionIconNames = () => Object.keys(icons());

// Catalog: category -> name -> Korean label (D-926 rules 7-8). status glyphs are 1:1 with a state; never reuse them for another meaning.
export const ICON_CATALOG = {
  nav: {fleet: "관제", map: "지도", install: "설치", cell: "셀", notification: "알림", settings: "설정", tools: "도구", account: "계정", login: "로그인", logout: "로그아웃", list: "목록", log: "기록", back: "뒤로", next: "다음"},
  object: {robot: "로봇", arm: "팔", station: "스테이션", charger: "충전기", camera: "카메라", lidar: "라이다", route: "경로", pin: "위치", task: "작업", mission: "임무", host: "호스트", dataset: "데이터셋", model: "모델", box: "화물", folder: "폴더", image: "이미지", area: "구역", obstacle: "장애물", person: "사람", "person-feet": "발", cone: "콘", sign: "표지", "traffic-light": "신호등", pixels: "픽셀", hand: "손"},
  status: {warn: "주의", safety: "위험", estop: "비상 정지", lock: "잠김", wifi: "연결 끊김", minus: "정보 없음", history: "지연"},
  measure: {battery: "배터리", charging: "충전 중", temperature: "온도", speed: "속도", signal: "신호 세기", time: "시간", distance: "거리", cpu: "CPU", memory: "메모리", disk: "디스크", pose: "자세", yaw: "방향"},
  action: {refresh: "새로고침", download: "내보내기", upload: "가져오기", close: "닫기", check: "승인", plus: "추가", undo: "되돌리기", pencil: "편집", trash: "삭제…", play: "시작", pause: "일시정지", stop: "정지", record: "녹화", assign: "배정", search: "검색", filter: "필터", more: "더보기", "chevron-up": "접기", "chevron-down": "펼치기", "chevron-right": "열기", copy: "복사", external: "바깥 열기", help: "도움말", info: "정보", save: "저장", expand: "전체 화면", fit: "맞춤", forward: "전진", reverse: "후진", left: "좌회전", right: "우회전", connect: "연결", "theme-dark": "어두운 테마", "theme-light": "밝은 테마", "theme-system": "시스템 테마", contrast: "대비"},
};

export function actionIcon(button, name) {
  const spec = icons()[name];
  if (!spec) throw new RangeError(`Unknown action icon: ${name}`);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", class: "ui-icon", "aria-hidden": "true", focusable: "false"})) svg.setAttribute(key, value);
  for (const part of Array.isArray(spec) ? spec : [{d: spec}]) {
    const path = document.createElementNS(svg.namespaceURI, "path"); path.setAttribute("d", part.d);
    if (part.fill) path.setAttribute("fill", part.fill); if (part.stroke) path.setAttribute("stroke", part.stroke); svg.append(path);
  }
  const details = [...button.querySelectorAll(":scope > small")], quiet = [...button.querySelectorAll(":scope > .sr-only")];
  const visible = [...button.childNodes].filter(node => node.nodeType === 3 || (node.nodeType === 1 && !node.matches(".ui-icon, small, .sr-only"))).map(node => node.textContent).join("").trim();
  const children = [svg];
  if (visible) { const label = document.createElement("span"); label.className = "ui-icon-label"; label.textContent = visible; children.push(label); }
  button.replaceChildren(...children, ...quiet, ...details);
  const label = button.getAttribute("aria-label") || visible || quiet.map(node => node.textContent).join(" ").trim();
  if (button.hasAttribute("data-icon-only") && !label) throw new TypeError("아이콘 단독 조작에는 접근성 이름이 필요합니다");
  if (!button.hasAttribute("data-ui-tooltip")) {
    const explanation = button.getAttribute("title") || ((button.hasAttribute("data-icon-only") || !visible) ? label : "");
    if (explanation) button.setAttribute("data-ui-tooltip", explanation);
  }
  return button;
}

// Toggletip: a click-opened note (live region) beside a button, for text that touch and keyboard users must reach
// (a data-ui-tooltip shows only on hover/focus). Escape or an outside click closes it. Returns the wrapper.
export function toggletip(button, text) {
  const wrap = document.createElement("span"), note = document.createElement("span");
  wrap.className = "ui-toggletip"; note.className = "ui-toggletip-note"; note.setAttribute("role", "status");
  button.removeAttribute("data-ui-tooltip"); button.replaceWith(wrap); wrap.append(button, note);
  const close = () => { note.textContent = ""; };
  button.addEventListener("click", () => { note.textContent = note.textContent ? "" : text; });
  document.addEventListener("click", event => { if (!wrap.contains(event.target)) close(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });
  return wrap;
}

let tooltip, tooltipOwner, tooltipHover = null, tooltipFocus = null, tooltipDismissed = null;
function hideTooltip() {
  if (tooltipOwner) {
    const ids = (tooltipOwner.getAttribute("aria-describedby") || "").split(/\s+/).filter(id => id && id !== "rosy-shared-tooltip");
    if (ids.length) tooltipOwner.setAttribute("aria-describedby", ids.join(" ")); else tooltipOwner.removeAttribute("aria-describedby");
  }
  if (tooltip) tooltip.hidden = true; tooltipOwner = null;
}
function tooltipTarget(node) { return node instanceof Element ? node.closest("[data-ui-tooltip]") : null; }
function tooltipOwnerVisible(owner) {
  return owner?.isConnected && !owner.closest("[hidden], [inert], [aria-hidden='true']") && owner.getClientRects().length && getComputedStyle(owner).visibility !== "hidden";
}
function overTooltip(event) {
  if (!tooltip || tooltip.hidden) return false;
  const box = tooltip.getBoundingClientRect();
  return event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom;
}
function placeTooltip() {
  if (!tooltip || tooltip.hidden) return;
  if (!tooltipOwnerVisible(tooltipOwner) || !tooltipOwner.getAttribute("data-ui-tooltip")?.trim()) { hideTooltip(); return; }
  const rect = tooltipOwner.getBoundingClientRect(), box = tooltip.getBoundingClientRect(), inset = parseFloat(getComputedStyle(tooltip).paddingTop);
  const x = Math.max(inset, Math.min(innerWidth - box.width - inset, rect.left + (rect.width - box.width) / 2)), below = rect.bottom + inset;
  const y = Math.max(inset, below + box.height <= innerHeight - inset ? below : rect.top - box.height - inset);
  for (const [axis, value] of [["x", x], ["y", y]]) {
    const key = `data-ui-tip-${axis}`, next = value.toFixed(2);
    if (tooltip.getAttribute(key) !== next) tooltip.setAttribute(key, next);
  }
}
function showTooltip() {
  const owner = tooltipHover || tooltipFocus;
  if (!tooltipOwnerVisible(owner) || owner === tooltipDismissed || !owner.getAttribute("data-ui-tooltip")?.trim()) { hideTooltip(); return; }
  if (!tooltip) {
    tooltip = document.createElement("div"); tooltip.className = "ui-tooltip"; tooltip.id = "rosy-shared-tooltip";
    tooltip.setAttribute("role", "tooltip"); document.body.append(tooltip);
  }
  if (tooltipOwner !== owner) hideTooltip();
  tooltipOwner = owner; tooltip.textContent = owner.getAttribute("data-ui-tooltip");
  const ids = new Set((owner.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
  ids.add(tooltip.id); owner.setAttribute("aria-describedby", [...ids].join(" ")); tooltip.hidden = false; placeTooltip();
}
document.addEventListener("pointerover", event => {
  if (overTooltip(event)) return;
  const owner = tooltipTarget(event.target);
  if (owner !== tooltipHover) { tooltipHover = owner; if (owner && owner !== tooltipFocus) tooltipDismissed = null; showTooltip(); }
});
document.addEventListener("pointerout", event => { if (tooltipHover && !tooltipHover.contains(event.relatedTarget) && !overTooltip(event)) { tooltipHover = null; showTooltip(); } });
document.addEventListener("pointermove", event => { if (tooltipHover && !tooltipHover.contains(event.target) && !overTooltip(event)) { tooltipHover = null; showTooltip(); } });
document.addEventListener("focusin", event => { tooltipFocus = tooltipTarget(event.target); tooltipDismissed = null; showTooltip(); });
document.addEventListener("focusout", () => { tooltipFocus = null; tooltipDismissed = null; showTooltip(); });
document.addEventListener("click", event => {
  const owner = tooltipTarget(event.target);
  if (!owner) {
    if (tooltipOwner) tooltipDismissed = tooltipOwner;
    tooltipHover = null;
    hideTooltip();
    return;
  }
  tooltipDismissed = owner;
  hideTooltip();
}, true);
document.addEventListener("keydown", event => { if (event.key === "Escape" && tooltip && !tooltip.hidden) { tooltipDismissed = tooltipOwner; hideTooltip(); } });
window.addEventListener("resize", placeTooltip);
document.addEventListener("scroll", placeTooltip, true);
new MutationObserver(placeTooltip).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["hidden", "inert", "class", "aria-hidden", "data-ui-tooltip"] });
for (const button of document.querySelectorAll("[data-action-icon]")) {
  if (!button.querySelector(":scope > .ui-icon")) actionIcon(button, button.getAttribute("data-action-icon"));
}
