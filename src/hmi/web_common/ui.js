// 빌드 없는 공용 조작 부품. 그림자는 쓰지 않는다 — 자식 글자와 기존 리스너가
// 요소 자체에 남는다. 색과 크기는 components.css 가 tokens.css 로 그린다.

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
    for (const name of ["type", "name", "placeholder", "autocomplete", "value", "required", "aria-label"]) {
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
  if (declared) {
    const probe = probeElement();
    probe.style.color = "";
    probe.style.color = isToken ? `var(${name})` : name;
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
