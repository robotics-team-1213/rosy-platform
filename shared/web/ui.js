// 빌드 없는 공용 조작 부품. 그림자는 쓰지 않는다 — 자식 글자와 기존 리스너가
// 요소 자체에 남는다. 색과 크기는 components.css 가 tokens.css 로 그린다.

import { createConfirmIrreversible } from "/common/confirmation.js";
import { disjointRectangles } from "/common/live-dialog-geometry.js";
const KINDS = ["primary", "quiet", "irreversible", "segment", "toggle"];
const BUTTON_SIZES = ["secondary", "primary", "irreversible"];
const KIND_SIZES = { primary: "primary", irreversible: "irreversible" };
let reasonSerial = 0;

class UiButton extends HTMLElement {
  static formAssociated = true;

  static get observedAttributes() {
    return ["disabled", "kind", "size", "reason"];
  }

  constructor() {
    super();
    this._internals = this.attachInternals();
    this._onKey = (event) => {
      if (event.key !== " " && event.key !== "Enter") return;
      if (event.target !== this) return;
      event.preventDefault();
      this.click();
    };
    this._onClick = (event) => {
      if (this.disabled) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      if (this.type === "submit" && this._internals.form) {
        event.preventDefault();
        this._internals.form.requestSubmit();
      }
    };
  }

  connectedCallback() {
    if (!KINDS.includes(this.getAttribute("kind"))) {
      this.setAttribute("data-kind-missing", "true");
    }
    if (!this.hasAttribute("type")) this.setAttribute("type", "button");
    if (!this.hasAttribute("role")) this.setAttribute("role", "button");
    this._sync();
    this.addEventListener("keydown", this._onKey);
    this.addEventListener("click", this._onClick, true);
  }

  disconnectedCallback() {
    this.removeEventListener("keydown", this._onKey);
    this.removeEventListener("click", this._onClick, true);
  }

  attributeChangedCallback() {
    this._sync();
  }

  get disabled() {
    return this.hasAttribute("disabled");
  }

  set disabled(value) {
    this.toggleAttribute("disabled", Boolean(value));
  }

  get type() {
    return this.getAttribute("type") || "button";
  }

  set type(value) {
    this.setAttribute("type", value || "button");
  }

  /** D-359 §5.3 — 왜 누를 수 없는지. 빈 값은 속성을 지운다. title은 사유가 아니다
   *  (터치에서 보이지 않는다). */
  get reason() {
    return this.getAttribute("reason") || "";
  }

  set reason(value) {
    if (value) this.setAttribute("reason", String(value));
    else this.removeAttribute("reason");
  }

  _sync() {
    const kind = this.getAttribute("kind");
    const size = this.getAttribute("size") || KIND_SIZES[kind] || "secondary";
    this.dataset.size = BUTTON_SIZES.includes(size) ? size : "secondary";
    if (BUTTON_SIZES.includes(size)) delete this.dataset.sizeMissing;
    else this.dataset.sizeMissing = "true";
    const off = this.disabled;
    this.tabIndex = off ? -1 : 0;
    this.setAttribute("aria-disabled", off ? "true" : "false");
    this._syncReason();
  }

  // 사유는 버튼 안의 <small data-reason>이다(toggle·irreversible의 small 세부와 같은
  // 자리). 이름에서 빠지도록 aria-hidden이고, aria-describedby가 설명으로 읽는다.
  // 화면이 textContent로 글자를 갈아도 사유가 따라 붙도록 자식 목록을 지켜본다.
  _syncReason() {
    const text = (this.getAttribute("reason") || "").trim();
    const node = this._reasonNode;
    if (!text) {
      this._reasonWatch?.disconnect();
      if (node) {
        node.remove();
        this._describe(node.id, false);
      }
      return;
    }
    if (!node) {
      this._reasonNode = document.createElement("small");
      this._reasonNode.dataset.reason = "";
      this._reasonNode.id = `ui-reason-${++reasonSerial}`;
      this._reasonNode.setAttribute("aria-hidden", "true");
    }
    const reason = this._reasonNode;
    if (reason.textContent !== text) reason.textContent = text;
    if (reason.parentNode !== this) this.append(reason);
    this._describe(reason.id, true);
    if (!this._reasonWatch) {
      this._reasonWatch = new MutationObserver(() => {
        if (this.getAttribute("reason") && reason.parentNode !== this) this.append(reason);
      });
    }
    this._reasonWatch.observe(this, { childList: true });
  }

  _describe(id, on) {
    const ids = (this.getAttribute("aria-describedby") || "").split(/\s+/).filter((item) => item && item !== id);
    if (on) ids.push(id);
    if (ids.length) this.setAttribute("aria-describedby", ids.join(" "));
    else this.removeAttribute("aria-describedby");
  }
}

class UiField extends HTMLElement {
  connectedCallback() {
    if (this.querySelector("input, select, textarea")) return;
    const input = document.createElement("input");
    for (const name of ["type", "name", "placeholder", "autocomplete", "value", "required", "aria-label",
                        "autocapitalize", "autocorrect", "spellcheck", "inputmode"]) {
      if (this.hasAttribute(name)) input.setAttribute(name, this.getAttribute(name));
    }
    if (this.hasAttribute("invalid")) input.setAttribute("aria-invalid", "true");
    this.append(input);
  }

  get input() {
    return this.querySelector("input, select, textarea");
  }

  get value() {
    return this.input ? this.input.value : "";
  }

  set value(next) {
    if (this.input) this.input.value = next;
  }

  get disabled() {
    return this.hasAttribute("disabled");
  }

  set disabled(value) {
    this.toggleAttribute("disabled", Boolean(value));
    if (this.input) this.input.disabled = Boolean(value);
  }

  focus() {
    this.input?.focus();
  }
}

class UiTag extends HTMLElement {
  connectedCallback() {
    if (!this.hasAttribute("status")) this.setAttribute("status", "neutral");
  }
}

class UiText extends HTMLElement {
  connectedCallback() {
    if (!this.hasAttribute("scale")) this.setAttribute("scale", "body");
  }
}

const EVIDENCE = ["fresh", "delayed", "disconnected", "unavailable"];
const MARKS = ["neutral", "warn", "crit"];

class UiHead extends HTMLElement {
  connectedCallback() {
    if (this.querySelector("[data-rule]")) return;
    const rule = document.createElement("span");
    rule.dataset.rule = "";
    rule.setAttribute("aria-hidden", "true");
    const last = this.lastElementChild;
    if (last && this.children.length > 1) this.insertBefore(rule, last);
    else this.append(rule);
  }
}

class UiGrid extends HTMLElement {
  connectedCallback() {
    if (!this.hasAttribute("columns")) this.setAttribute("columns", "3");
  }
}

class UiChip extends HTMLElement {}

class UiTriage extends HTMLElement {
  connectedCallback() {
    if (!MARKS.includes(this.getAttribute("status"))) {
      this.setAttribute("status", "neutral");
    }
  }
}

const GRAMMARS = ["spatial", "exception", "focal", "procedure"];

class UiShell extends HTMLElement {
  connectedCallback() {
    if (!GRAMMARS.includes(this.getAttribute("grammar"))) {
      this.setAttribute("data-grammar-missing", "true");
    }
  }
}

class UiTopbar extends HTMLElement {}

class UiBrand extends HTMLElement {
  // D-335: href를 주면 자식을 하나의 링크로 감싼다. aria-label은 링크로
  // 옮겨 접근성 이름이 한 곳에만 붙는다. href가 없으면 평문 브랜드다.
  connectedCallback() {
    const href = this.getAttribute("href");
    if (!href || this.querySelector("a")) return;
    const link = document.createElement("a");
    link.setAttribute("href", href);
    const label = this.getAttribute("aria-label");
    if (label) {
      link.setAttribute("aria-label", label);
      this.removeAttribute("aria-label");
    }
    while (this.firstChild) link.append(this.firstChild);
    this.append(link);
  }
}

class UiSection extends HTMLElement {
  connectedCallback() {
    if (!this.hasAttribute("role")) this.setAttribute("role", "region");
  }
}

class UiEmpty extends HTMLElement {}

class UiActions extends HTMLElement {}

const STATUS_STATES = ["pending", "empty", "ready", "warning", "error", "unavailable", "forbidden"];

class UiStatus extends HTMLElement {
  static get observedAttributes() { return ["state"]; }

  connectedCallback() {
    if (!this.hasAttribute("role")) this.setAttribute("role", "status");
    if (!this.hasAttribute("aria-live")) this.setAttribute("aria-live", "polite");
    this._syncState();
  }

  attributeChangedCallback() { this._syncState(); }

  _syncState() {
    const state = this.getAttribute("state") || "pending";
    if (STATUS_STATES.includes(state)) {
      this.dataset.state = state;
      delete this.dataset.stateMissing;
    } else {
      delete this.dataset.state;
      this.dataset.stateMissing = "true";
    }
  }
}

class UiEvidence extends HTMLElement {
  connectedCallback() {
    if (!EVIDENCE.includes(this.getAttribute("state"))) {
      this.setAttribute("data-state-missing", "true");
    }
  }
}

for (const [name, ctor] of [
  ["ui-button", UiButton],
  ["ui-field", UiField],
  ["ui-text", UiText],
  ["ui-tag", UiTag],
  ["ui-head", UiHead],
  ["ui-grid", UiGrid],
  ["ui-chip", UiChip],
  ["ui-triage", UiTriage],
  ["ui-evidence", UiEvidence],
  ["ui-shell", UiShell],
  ["ui-topbar", UiTopbar],
  ["ui-brand", UiBrand],
  ["ui-section", UiSection],
  ["ui-empty", UiEmpty],
  ["ui-actions", UiActions],
  ["ui-status", UiStatus],
]) {
  if (!customElements.get(name)) customElements.define(name, ctor);
}

// D-371 — 목록 행의 되돌릴 수 없는 행동은 조용한 `삭제…`로 시작해 여기로 온다.
// 대화상자가 대상을 이름으로 묻고(D-218 어휘), 위험 채움은 실행 버튼 하나뿐이다.
// 취소·Esc는 false, 실행은 true. 닫히면 포커스는 누른 행 버튼으로 돌아간다. 목록은
// 대화상자가 열린 동안 폴링으로 다시 그려질 수 있어 opener는 함수로도 받는다
// (닫힐 때 불러 지금 화면에 있는 그 행의 버튼을 찾는다).
export const confirmIrreversible = createConfirmIrreversible(openLiveDialog);

// 모든 대화상자는 비모달이다(2026-09-30 US-010 측정: showModal()은 문서 전체를 inert로
// 만들어 비상 정지까지 막았다 — D-280 원칙 2 위반). 그래서 모달은 여기서 흉내 낸다:
// * `[data-always-live]`(각 표면 마크업이 정지 컨트롤에 단다)와 대화상자만 살리고
//   나머지 가지에 inert를 건다. 폴링이 새로 붙인 노드도 MutationObserver가 다시 건다.
// * 스크림(`--scrim`)은 정지 컨트롤 자리에 구멍을 낸다(clip-path) — 보이고 눌린다.
// * Esc는 취소, Tab은 대화상자 안의 컨트롤 → 보이는 정지 컨트롤을 돈다. 정지에는
//   단축키가 없으므로 새로 만들지 않고 포커스 순환에 넣었다.
// * 정지를 누르면 정지는 제 할 일을 하고 대화상자는 취소("cancel")로 닫힌다.
// * 마크업에 있던 대화상자는 열린 동안 body 끝으로 옮겨(조상의 쌓임 맥락을 벗어남)
//   닫히면 제자리로 돌아간다. 만들어 넘긴 대화상자는 닫히면 지운다.
// aria-modal은 달지 않는다: 달면 보조기기가 살아 있는 정지를 못 찾는다(inert가 나머지를 숨긴다).
// 반환한 close(value)는 즉시 정리한다. native close도 같은 정리를 거친다.
const ALWAYS_LIVE = "[data-always-live]";
const DIALOG_FOCUSABLE = "input:not([type=hidden]), select, textarea, button, ui-button, a[href], [tabindex]:not([tabindex='-1'])";

export function openLiveDialog(dialog, { initialFocus = null, opener = document.activeElement, onClose } = {}) {
  dialog.classList.add("ui-live-dialog");
  const home = dialog.isConnected ? { parent: dialog.parentNode, next: dialog.nextSibling } : null;
  const scrim = document.createElement("div");
  scrim.className = "ui-confirm-scrim";
  scrim.setAttribute("aria-hidden", "true");

  const inerted = new Set();
  let byStop = false, finished = false;
  const liveNodes = () => [...document.querySelectorAll(ALWAYS_LIVE)];
  const shown = (node) => node.getClientRects().length > 0 && !node.disabled;
  // 살릴 노드(정지·대화상자)의 조상 사슬만 타고 내려가며 곁가지를 inert로 만든다.
  const seal = () => {
    const keep = [...liveNodes(), dialog];
    const walk = (parent) => {
      for (const child of parent.children) {
        const holds = keep.some((node) => child === node || child.contains(node));
        if (holds && inerted.has(child)) { child.inert = false; inerted.delete(child); }
        if (holds) { if (!keep.includes(child)) walk(child); continue; }
        if (child === scrim || child.inert) continue;
        child.inert = true;
        inerted.add(child);
      }
    };
    walk(document.body);
  };
  // 겹치는 정지 컨트롤도 교집합이 다시 덮이지 않도록 서로 겹치지 않는 구멍을 낸다.
  const punch = () => {
    const holes = disjointRectangles(liveNodes().filter(node => node.getClientRects().length > 0).map(node => node.getBoundingClientRect()), innerWidth, innerHeight).map(r => {
      return `0 0, ${r.left}px ${r.top}px, ${r.right}px ${r.top}px, ${r.right}px ${r.bottom}px, ${r.left}px ${r.bottom}px, ${r.left}px ${r.top}px`;
    });
    const polygon = holes.length
      ? `polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, ${holes.join(", ")}, 0 0)`
      : "";
    if (polygon) scrim.setAttribute("data-clip", polygon);
    else scrim.removeAttribute("data-clip");
  };
  const observer = new MutationObserver(() => { seal(); punch(); });
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close("cancel");
      return;
    }
    if (event.key !== "Tab") return;
    const ring = [...dialog.querySelectorAll(DIALOG_FOCUSABLE)].filter(shown).concat(liveNodes().filter(shown));
    if (!ring.length) return;
    const at = ring.findIndex((node) => node === document.activeElement || node.contains(document.activeElement));
    event.preventDefault();
    const step = event.shiftKey ? -1 : 1;
    ring[at < 0 ? 0 : (at + step + ring.length) % ring.length].focus();
  };
  // 캡처 단계에서 표시만 하고 막지 않는다 — 정지 자신의 click 처리기는 그대로 돈다.
  const onClick = (event) => {
    if (!event.target.closest?.(ALWAYS_LIVE)) return;
    byStop = true;
    close("cancel");
  };

  const finish = () => {
    if (finished) return;
    finished = true;
    dialog.removeEventListener("close", onNativeClose);
    observer.disconnect();
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("click", onClick, true);
    removeEventListener("resize", punch);
    removeEventListener("scroll", punch, true);
    for (const node of inerted) node.inert = false;
    inerted.clear();
    scrim.remove();
    if (home?.parent.isConnected) home.parent.insertBefore(dialog, home.next?.parentNode === home.parent ? home.next : null);
    else dialog.remove();
    if (!byStop) {
      const back = typeof opener === "function" ? opener() : opener;
      if (back?.isConnected && typeof back.focus === "function") back.focus();
    }
    onClose?.(dialog.returnValue, { byStop });
  };
  const close = value => { if (finished) return; if (dialog.open) dialog.close(value); finish(); };
  const onNativeClose = () => { if (!dialog.open) finish(); };
  dialog.addEventListener("close", onNativeClose);
  document.body.append(scrim, dialog);
  seal();
  punch();
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("click", onClick, true);
  addEventListener("resize", punch);
  addEventListener("scroll", punch, { capture: true, passive: true });
  dialog.returnValue = "";
  dialog.show();
  (initialFocus || [...dialog.querySelectorAll(DIALOG_FOCUSABLE)].find(shown))?.focus();
  return close;
}

// D-359 §4 — 캔버스 색·글꼴. 캔버스는 CSS 변수를 못 쓰므로 여기서 한 번 풀어
// 캐시한다. 토큰은 hex·oklch·color-mix 무엇이든 될 수 있어서 글자로 파싱하지
// 않는다: 숨은 탐침 요소의 계산된 color(Chromium은 color-mix를 `color(srgb …)`나
// `oklab(…)`으로 준다)를 1×1 캔버스에 칠해 sRGB 바이트로 되읽는다.
// 테마가 바뀌면(`rosy:theme`) 캐시를 비운다 — 다시 그리는 일은 각 캔버스가 한다.
// 캔버스 파일은 `window.RosyPalette`로 부른다(camera-capture.js는 Node에서도
// import되므로 이 모듈을 정적으로 끌어올 수 없다, D-75 번들러 없음).
const colourCache = new Map();
const fontCache = new Map();
let colourProbe = null;
let colourRaster = null;
let colourSheet = null;

function probeColourValue(name) {
  if (name.startsWith("--")) return /^--[A-Za-z0-9_-]+$/.test(name) ? `var(${name})` : "";
  if (!name || /[{};<>\\]|\/\*|\*\//.test(name)) return "";
  return name;
}

function paintColourProbe(value) {
  if (!colourSheet) {
    colourSheet = new CSSStyleSheet();
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, colourSheet];
  }
  colourSheet.replaceSync(`[data-rosy-colour-probe] { color: ${value}; }`);
}

function probeElement() {
  if (!colourProbe || !colourProbe.isConnected) {
    colourProbe = document.createElement("span");
    colourProbe.hidden = true;
    colourProbe.setAttribute("aria-hidden", "true");
    colourProbe.dataset.rosyColourProbe = "";
    document.documentElement.append(colourProbe);
  }
  return colourProbe;
}

function rasterContext() {
  if (!colourRaster) {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    colourRaster = canvas.getContext("2d", { willReadFrequently: true });
  }
  return colourRaster;
}

/** `--token` 또는 CSS 색 → [r, g, b, a] (r·g·b 0–255, a 0–1). 못 풀면 투명. */
export function readColour(name) {
  if (colourCache.has(name)) return colourCache.get(name);
  const isToken = name.startsWith("--");
  let rgba = [0, 0, 0, 0];
  const declared = isToken
    ? getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    : name;
  const painted = probeColourValue(name);
  if (declared && painted) {
    const probe = probeElement();
    paintColourProbe(painted);
    const resolved = getComputedStyle(probe).color;
    const ctx = rasterContext();
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = resolved;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
    rgba = [r, g, b, Math.round((a / 255) * 1000) / 1000];
  }
  colourCache.set(name, rgba);
  return rgba;
}

/** 이름 배열이나 {키: 이름} 표를 받아 같은 키의 [r, g, b, a] 표를 준다. */
export function readPalette(names) {
  const entries = Array.isArray(names) ? names.map((name) => [name, name]) : Object.entries(names);
  const palette = {};
  for (const [key, name] of entries) palette[key] = readColour(name);
  return palette;
}

/** 캔버스 fillStyle/strokeStyle 용 `rgba(…)` 글자. */
export function cssColor(name) {
  const [r, g, b, a] = readColour(name);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/** `--body`·`--mono` 글꼴로 된 캔버스 font. 글자는 12px 아래로 내려가지 않는다. */
export function canvasFont(size, family = "body") {
  if (!fontCache.has(family)) {
    const stack = getComputedStyle(document.documentElement).getPropertyValue(`--${family}`).trim();
    fontCache.set(family, stack || (family === "mono" ? "monospace" : "sans-serif"));
  }
  return `${Math.max(12, Math.round(Number(size) || 12))}px ${fontCache.get(family)}`;
}

export function clearPalette() {
  colourCache.clear();
  fontCache.clear();
}

document.addEventListener("rosy:theme", clearPalette);
window.RosyPalette = { readColour, readPalette, cssColor, canvasFont, clear: clearPalette };

// D-359 US-008 — 자간 토큰은 라틴 대문자 라벨용이다. 한글은 음절 하나가 이미 한
// 글자 칸이라 0.06–0.12em을 더하면 "점유  지도"처럼 띄어 읽힌다. 페이지가 모두
// lang="ko"라 :lang()으로는 가를 수 없고 글자는 실행 중에 바뀐다. 그래서 자기
// 글자(직계 텍스트 노드)에 한글이 있는 요소에 `data-hangul`을 달고,
// components.css가 그 요소의 자간 토큰과 letter-spacing을 0으로 둔다.
// 섞인 글("COLUMN 종대")도 0이다 — 한 요소 안에서 글자별 자간은 CSS로 못 준다.
const HANGUL = /[ᄀ-ᇿ㄰-㆏가-힯]/;

function markHangul(element) {
  if (!(element instanceof Element)) return;
  let hangul = false;
  for (const node of element.childNodes) {
    if (node.nodeType === Node.TEXT_NODE && HANGUL.test(node.data)) {
      hangul = true;
      break;
    }
  }
  if (element.hasAttribute("data-hangul") !== hangul) element.toggleAttribute("data-hangul", hangul);
}

function markHangulTree(root) {
  if (!(root instanceof Element)) return;
  markHangul(root);
  for (const element of root.querySelectorAll("*")) markHangul(element);
}

const hangulObserver = new MutationObserver((records) => {
  for (const record of records) {
    if (record.type === "characterData") {
      markHangul(record.target.parentElement);
      continue;
    }
    markHangul(record.target);
    for (const node of record.addedNodes) markHangulTree(node);
  }
});
hangulObserver.observe(document.documentElement, { childList: true, characterData: true, subtree: true });
markHangulTree(document.documentElement);

// Shared labeled action icons. Keep handlers and button semantics on the original element.
// A string draws one stroke. An array draws one path per entry so a filled mark can sit
// on a stroked outline. .sr-only stays a screen-reader label and is not copied into the visible span.
export function actionIcon(button, name) {
  const paths = {
    wifi: "M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0M8 16a6 6 0 0 1 8 0M12 20h.01",
    fit: "M4 4h16v16H4zM8 8h8v8H8z",
    expand: "M9 3H3v6M15 3h6v6M3 15v6h6M21 15v6h-6",
    tools: "M4 6h16M4 12h16M4 18h16M9 3v6M15 9v6M8 15v6",
    settings: "M4 7h16M4 12h16M4 17h16M9 5v4M15 10v4M7 15v4",
    "theme-dark": "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
    "theme-light": [
      {d: "M12,8 A4,4 0 1,1 12,16 A4,4 0 1,1 12,8 Z"},
      {d: "M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"},
    ],
    "theme-system": [
      {d: "M5 4H19A2 2 0 0 1 21 6V14A2 2 0 0 1 19 16H5A2 2 0 0 1 3 14V6A2 2 0 0 1 5 4Z"},
      {d: "M8.5 20h7M12 16v4"},
    ],
    estop: [
      {d: "M12 2 19.1 4.9 22 12 19.1 19.1 12 22 4.9 19.1 2 12 4.9 4.9Z"},
      {d: "M9 8H15A1 1 0 0 1 16 9V15A1 1 0 0 1 15 16H9A1 1 0 0 1 8 15V9A1 1 0 0 1 9 8Z", fill: "currentColor", stroke: "none"},
    ],
    pose: [
      {d: "M12,5 A7,7 0 1,1 12,19 A7,7 0 1,1 12,5 Z"},
      {d: "M12 2v3M12 19v3M2 12h3M19 12h3"},
    ],
    yaw: [
      {d: "M12,3 A9,9 0 1,1 12,21 A9,9 0 1,1 12,3 Z"},
      {d: "m15.5 8.5-2.1 4.9-4.9 2.1 2.1-4.9z"},
    ],
    battery: [
      {d: "M4.5 8H16.5A1.5 1.5 0 0 1 18 9.5V14.5A1.5 1.5 0 0 1 16.5 16H4.5A1.5 1.5 0 0 1 3 14.5V9.5A1.5 1.5 0 0 1 4.5 8Z"},
      {d: "M21 10.5v3M6.5 10.5v3M10 10.5v3M13.5 10.5v3"},
    ],
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
    trash: "M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v6M14 11v6",
    undo: "M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-2",
    pencil: "M4 20l4-.8L20 7l-3-3L4.8 16zM15 6l3 3",
    next: "M4 12h16m-7-7 7 7-7 7",
    list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    box: "M4 4h16v16H4zM9 9h6v6H9z",
    pixels: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
    folder: "M3 7V5h7l2 2h9v12H3z",
  };
  const spec = paths[name];
  if (!spec) throw new RangeError(`Unknown action icon: ${name}`);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [key, value] of Object.entries({viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round", class: "ui-icon", "aria-hidden": "true", focusable: "false"})) svg.setAttribute(key, value);
  for (const part of Array.isArray(spec) ? spec : [{d: spec}]) {
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", part.d);
    if (part.fill) path.setAttribute("fill", part.fill);
    if (part.stroke) path.setAttribute("stroke", part.stroke);
    svg.append(path);
  }
  const details = [...button.querySelectorAll(":scope > small")];
  const quiet = [...button.querySelectorAll(":scope > .sr-only")];
  const visible = [...button.childNodes].filter(node => node.nodeType === 3 ||
    (node.nodeType === 1 && !node.matches(".ui-icon, small, .sr-only"))).map(node => node.textContent).join("").trim();
  const children = [svg];
  if (visible) {
    const label = document.createElement("span");
    label.textContent = visible;
    children.push(label);
  }
  button.replaceChildren(...children, ...quiet, ...details);
  return button;
}

for (const button of document.querySelectorAll("[data-action-icon]")) {
  if (!button.querySelector(":scope > .ui-icon")) actionIcon(button, button.getAttribute("data-action-icon"));
}
