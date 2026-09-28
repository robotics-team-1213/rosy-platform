// 접속 게이트 패널(D-323 T6 재구성). dashboard 패널 조립 문법을 따른다:
// ui-head(패널 제목) + dl.ui-readout(사실 dt/dd) + ui-actions(행동).
// 동적 문자열은 textContent 로만 넣는다.

import {token, setToken, clearToken, whoami, fetchCapabilities} from "../client.js";
import {driverFor} from "../drivers/registry.js";

const DRIVER_KIND = "pinky_core";

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

function setTag(word) {
  const tag = document.querySelector("[data-gate-state]");
  if (tag) tag.textContent = word;
}

function notice(text) {
  const node = document.querySelector("#pilot-notice");
  if (node) node.textContent = text;
}

function readoutPair(pairs) {
  const list = el("dl", null, {"class": "ui-readout", "data-gate-readout": ""});
  for (const [label, value, evidence] of pairs) {
    const dt = el("dt", label);
    const dd = el("dd", value);
    if (evidence) dd.dataset.evidence = evidence;
    list.append(dt, dd);
  }
  return list;
}

function tokenForm() {
  const form = el("form", null, {"data-pilot-token-form": ""});
  const field = el("ui-field", null, {
    placeholder: "운전 토큰", "aria-label": "운전 토큰", autocomplete: "off", name: "token",
  });
  const submit = el("ui-button", "연결", {kind: "primary", type: "button"});
  form.append(field, submit);
  return {form, field, submit};
}

function renderTokenForm(root, message, gate = "WAIT", tokenFact = "필요") {
  const head = el("ui-head", "접속 게이트", {id: "pilot-gate-heading"});
  const {form, field, submit} = tokenForm();
  const connect = () => {
    setToken(field.value);
    check(root);
  };
  // ui-button 은 커스텀 요소라 네이티브 submit 을 유발하지 않는다 — 클릭과
  // Enter(내부 input 의 폼 제출) 둘 다 같은 경로로 묶는다.
  submit.addEventListener("click", connect);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    connect();
  });
  root.replaceChildren(head, readoutPair([["게이트", gate], ["운전 토큰", tokenFact]]), form);
  if (message) root.append(el("ui-status", message, {role: "status"}));
}

async function check(root, onReady) {
  const gate = driverFor(DRIVER_KIND);
  setTag("확인 중");
  notice("");
  const facts = [["게이트", "WAIT"]];
  root.replaceChildren(
    el("ui-head", "접속 게이트", {id: "pilot-gate-heading"}),
    readoutPair(facts),
    el("ui-empty", "연결을 확인하고 있습니다…"),
  );

  const me = await whoami();
  if (me.status === 401) {
    clearToken();
    setTag("차단");
    notice("토큰이 유효하지 않습니다");
    renderTokenForm(root, "토큰이 유효하지 않습니다. 다시 입력해 주세요.", "BLOCK", "거부됨");
    return;
  }
  facts.push(["운전 역할", me.body?.role ?? "—"]);

  const caps = await fetchCapabilities();
  const verdict = gate.assessGate({role: me.body?.role, capabilities: caps.body ?? {}});
  if (!verdict.allowed) {
    setTag("차단");
    notice("진입이 차단되었습니다");
    const pairs = [["게이트", "BLOCK"], ...facts.slice(1),
                   ["수동 운전", caps.body?.teleop === true ? "보류" : "보류됨"],
                   ["구동", caps.body?.runtime?.drive === true ? "켜짐" : "꺼짐"]];
    const statuses = verdict.reasons.map((reason) =>
      el("ui-status", gate.describeReason(reason), {role: "status"}));
    const actions = el("ui-actions");
    const retry = el("ui-button", "다시 시도", {kind: "quiet", type: "button"});
    retry.addEventListener("click", () => check(root, onReady));
    const reset = el("ui-button", "토큰 초기화", {kind: "segment", type: "button"});
    reset.addEventListener("click", () => {
      clearToken();
      renderTokenForm(root);
    });
    actions.append(retry, reset);
    root.replaceChildren(
      el("ui-head", "접속 게이트", {id: "pilot-gate-heading"}),
      readoutPair(pairs), ...statuses, actions,
    );
    return;
  }

  setTag("준비");
  notice("조종 준비 완료");
  const pairs = [["게이트", "READY"], ...facts.slice(1),
                 ["수동 운전", "허용"], ["구동", "켜짐"]];
  root.replaceChildren(
    el("ui-head", "접속 게이트", {id: "pilot-gate-heading"}),
    readoutPair(pairs),
    el("ui-empty", "조종 준비 완료 — 주행 화면은 다음 단계(T7)에서 열립니다."),
  );
  onReady?.({role: me.body?.role});
}

export function mountConnect(root, {onReady} = {}) {
  if (!token()) {
    renderTokenForm(root);
    return;
  }
  check(root, onReady);
}
