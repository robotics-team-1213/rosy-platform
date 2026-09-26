// 빌드 없는 공용 조작 부품. 그림자는 쓰지 않는다 — 자식 글자와 기존 리스너가
// 요소 자체에 남는다. 색과 크기는 components.css 가 tokens.css 로 그린다.

const KINDS = ["primary", "quiet", "irreversible", "segment", "toggle"];
const BUTTON_SIZES = ["secondary", "primary", "irreversible"];
const KIND_SIZES = { primary: "primary", irreversible: "irreversible" };

class UiButton extends HTMLElement {
  static formAssociated = true;

  static get observedAttributes() {
    return ["disabled", "kind", "size"];
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

  _sync() {
    const kind = this.getAttribute("kind");
    const size = this.getAttribute("size") || KIND_SIZES[kind] || "secondary";
    this.dataset.size = BUTTON_SIZES.includes(size) ? size : "secondary";
    if (BUTTON_SIZES.includes(size)) delete this.dataset.sizeMissing;
    else this.dataset.sizeMissing = "true";
    const off = this.disabled;
    this.tabIndex = off ? -1 : 0;
    this.setAttribute("aria-disabled", off ? "true" : "false");
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

class UiBrand extends HTMLElement {}

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
