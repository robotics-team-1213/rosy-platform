// 빌드 없는 공용 조작 부품. 그림자는 쓰지 않는다 — 자식 글자와 기존 리스너가
// 요소 자체에 남는다. 색과 크기는 components.css 가 tokens.css 로 그린다.

const KINDS = ["primary", "quiet", "irreversible", "segment", "toggle"];

class UiButton extends HTMLElement {
  static formAssociated = true;

  static get observedAttributes() {
    return ["disabled"];
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
    const off = this.disabled;
    this.tabIndex = off ? -1 : 0;
    this.setAttribute("aria-disabled", off ? "true" : "false");
  }
}

class UiField extends HTMLElement {
  connectedCallback() {
    if (this.querySelector("input, select, textarea")) return;
    const input = document.createElement("input");
    for (const name of ["type", "name", "placeholder", "autocomplete", "value", "required"]) {
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

for (const [name, ctor] of [
  ["ui-button", UiButton],
  ["ui-field", UiField],
  ["ui-tag", UiTag],
  ["ui-text", UiText],
]) {
  if (!customElements.get(name)) customElements.define(name, ctor);
}
