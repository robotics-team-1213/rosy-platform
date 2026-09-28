// 접속 게이트 화면(D-323 T6): 토큰 → whoami → capabilities → assessGate.
// 동적 문자열은 textContent 로만 넣는다(서버 텍스트로 HTML 을 만들지 않는다).

import {token, setToken, clearToken, whoami, fetchCapabilities} from "../client.js";
import {driverFor} from "../drivers/registry.js";

const DRIVER_KIND = "pinky_core";

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

function renderTokenForm(root, message) {
  root.replaceChildren();
  const form = el("form", null, {"data-pilot-token-form": ""});
  const field = el("input", null, {
    type: "password", "aria-label": "운전 토큰", placeholder: "운전 토큰",
    autocomplete: "off", name: "token",
  });
  const submit = el("ui-button", "연결", {kind: "primary", type: "submit"});
  form.append(field, submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    setToken(field.value);
    check(root);
  });
  root.append(form);
  if (message) root.append(el("ui-empty", message, {"data-pilot-message": ""}));
}

async function check(root, onReady) {
  const gate = driverFor(DRIVER_KIND);
  const state = document.querySelector('[data-gate-state]');
  root.replaceChildren(el("ui-empty", "연결을 확인하고 있습니다…", {"data-pilot-message": ""}));
  const me = await whoami();
  if (me.status === 401) {
    clearToken();
    if (state) state.textContent = "토큰 무효";
    renderTokenForm(root, "토큰이 유효하지 않습니다. 다시 입력해 주세요.");
    return;
  }
  const caps = await fetchCapabilities();
  const verdict = gate.assessGate({role: me.body?.role, capabilities: caps.body ?? {}});
  if (!verdict.allowed) {
    if (state) state.textContent = "진입 차단";
    const list = el("ui-grid", null, {columns: "1"});
    for (const reason of verdict.reasons) {
      list.append(el("div", gate.describeReason(reason)));
    }
    const retry = el("ui-button", "다시 시도", {kind: "quiet", type: "button"});
    retry.addEventListener("click", () => check(root, onReady));
    const reset = el("ui-button", "토큰 초기화", {kind: "segment", type: "button"});
    reset.addEventListener("click", () => {
      clearToken();
      renderTokenForm(root);
    });
    root.replaceChildren(list, retry, reset);
    return;
  }
  if (state) state.textContent = "준비 완료";
  const ready = el("ui-empty", `조종 준비 완료 — 역할: ${me.body?.role ?? "operator"}`,
    {"data-pilot-message": ""});
  root.replaceChildren(ready);
  onReady?.({role: me.body?.role});
}

export function mountConnect(root, {onReady} = {}) {
  if (!token()) {
    renderTokenForm(root);
    return;
  }
  check(root, onReady);
}
