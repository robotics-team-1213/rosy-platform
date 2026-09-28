// 접속 게이트 화면(D-323 T6): 토큰 → whoami → capabilities → assessGate.
// web_common 어휘만 쓴다(D-92): ui-field·ui-grid(값 격자)·ui-empty(증거·빈 상태).
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

// 값 격자의 칸: 라벨(값의 이름) + 기계 값.
function row(label, value) {
  const cell = el("div");
  cell.append(el("ui-text", label, {scale: "label"}), el("ui-text", value, {scale: "value"}));
  return cell;
}

// 묶음 제목 줄의 오른쪽 끝은 기계 값(WAIT/BLOCK/READY), 상단 태그는 표시어.
function gateValue(machine, word) {
  const value = document.querySelector("[data-gate-value]");
  if (value) value.textContent = machine;
  const tag = document.querySelector("[data-gate-state]");
  if (tag) tag.textContent = word;
}

function renderTokenForm(root, message) {
  root.replaceChildren();
  const form = el("form", null, {"data-pilot-token-form": ""});
  const field = el("ui-field", null, {
    placeholder: "운전 토큰", "aria-label": "운전 토큰", autocomplete: "off", name: "token",
  });
  const submit = el("ui-button", "연결", {kind: "primary", type: "button"});
  form.append(field, submit);
  const connect = () => {
    setToken(field.value);
    check(root);
  };
  // ui-button 은 커스텀 요소라 네이티브 submit 을 유발하지 않는다 —
  // 클릭과 Enter(내부 input 의 폼 제출) 둘 다 같은 경로로 묶는다.
  submit.addEventListener("click", connect);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    connect();
  });
  root.append(form);
  if (message) root.append(el("ui-empty", message));
}

async function check(root, onReady) {
  const gate = driverFor(DRIVER_KIND);
  gateValue("WAIT", "대기");
  root.replaceChildren(el("ui-empty", "연결을 확인하고 있습니다…"));
  const me = await whoami();
  if (me.status === 401) {
    clearToken();
    gateValue("BLOCK", "차단");
    renderTokenForm(root, "토큰이 유효하지 않습니다. 다시 입력해 주세요.");
    return;
  }
  const caps = await fetchCapabilities();
  const verdict = gate.assessGate({role: me.body?.role, capabilities: caps.body ?? {}});
  if (!verdict.allowed) {
    gateValue("BLOCK", "차단");
    const grid = el("ui-grid", null, {columns: "1"});
    verdict.reasons.forEach((reason, index) => grid.append(row(`사유 ${index + 1}`, reason)));
    const notes = verdict.reasons.map((reason) => el("ui-empty", gate.describeReason(reason)));
    const retry = el("ui-button", "다시 시도", {kind: "quiet", type: "button"});
    retry.addEventListener("click", () => check(root, onReady));
    const reset = el("ui-button", "토큰 초기화", {kind: "segment", type: "button"});
    reset.addEventListener("click", () => {
      clearToken();
      renderTokenForm(root);
    });
    root.replaceChildren(grid, ...notes, retry, reset);
    return;
  }
  gateValue("READY", "준비");
  const grid = el("ui-grid", null, {columns: "2"});
  grid.append(row("ROLE", me.body?.role ?? "operator"), row("MODE", "MANUAL 예정"));
  root.replaceChildren(grid, el("ui-empty", "조종 준비 완료"));
  onReady?.({role: me.body?.role});
}

export function mountConnect(root, {onReady} = {}) {
  if (!token()) {
    renderTokenForm(root);
    return;
  }
  check(root, onReady);
}
