// 접속 게이트(D-323): 게임식 "계속하기" UX.
// 최근 접속 관리는 인라인(모듈 404 방지 — allowlist 동기화 이슈).

const RECENT_KEY = "rosy.pilot.recent";

function getRecent() {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]"); }
  catch { return []; }
}
function addRecentEntry(entry) {
  const list = getRecent().filter((r) => r.host !== entry.host);
  list.unshift(entry);
  localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 5)));
}
function removeRecentEntry(host) {
  localStorage.setItem(RECENT_KEY, JSON.stringify(getRecent().filter((r) => r.host !== host)));
}

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
  for (const [label, value] of pairs) {
    list.append(el("dt", label), el("dd", value));
  }
  return list;
}

// --- 최근 접속 목록 (게임 "계속하기") ---
function renderRecentList(root, onConnect) {
  const recent = getRecent();
  if (recent.length === 0) return null;

  const section = el("div", null, {"data-recent-list": ""});
  const heading = el("ui-text", "최근 접속", {scale: "label"});
  section.append(heading);

  for (const entry of recent.slice(0, 3)) {
    const row = el("div", null, {"data-recent-item": ""});
    const button = el("ui-button", entry.label || entry.host, {
      kind: "primary", type: "button", "data-recent-connect": entry.host,
    });
    button.style.width = "100%";
    button.style.minHeight = "3rem";
    button.addEventListener("click", () => {
      if (entry.token) setToken(entry.token);
      onConnect();
    });
    const remove = el("ui-button", "✕", {
      kind: "quiet", type: "button", "data-recent-remove": entry.host,
    });
    remove.style.minWidth = "2.5rem";
    remove.style.minHeight = "2.5rem";
    remove.addEventListener("click", (e) => {
      e.stopPropagation();
      removeRecentEntry(entry.host);
      renderTokenForm(root, onConnect);
    });
    row.append(button, remove);
    section.append(row);
  }
  return section;
}

// --- 새 연결 폼 (접기 가능) ---
function tokenForm() {
  const form = el("form", null, {"data-pilot-token-form": ""});
  const field = el("ui-field", null, {
    placeholder: "운전 토큰 입력", "aria-label": "운전 토큰", autocomplete: "off", name: "token",
  });
  const submit = el("ui-button", "연결", {kind: "primary", type: "button"});
  form.append(field, submit);
  return {form, field, submit};
}

function renderTokenForm(root, onConnect, message) {
  const head = el("ui-head", "접속", {id: "pilot-gate-heading"});
  root.replaceChildren(head);

  // 최근 접속 목록
  const recent = renderRecentList(root, onConnect);
  if (recent) root.append(recent);

  // 새 연결
  const divider = el("ui-text", "새 연결", {scale: "label"});
  const {form, field, submit} = tokenForm();
  const connect = () => {
    if (!field.value.trim()) {
      notice("토큰을 입력하세요");
      return;
    }
    setToken(field.value.trim());
    // 최근에 추가 (호스트는 same-origin이므로 location.host)
    addRecentEntry({host: location.host, label: "Pinky", token: field.value.trim()});
    onConnect();
  };
  submit.addEventListener("click", connect);
  form.addEventListener("submit", (e) => { e.preventDefault(); connect(); });

  root.append(divider, form);
  if (message) root.append(el("ui-status", message, {role: "status"}));
}

function renderOffline(root, onConnect) {
  setTag("오프라인");
  notice("CORE 에 연결할 수 없습니다");
  root.replaceChildren(
    el("ui-head", "접속", {id: "pilot-gate-heading"}),
    el("ui-status", "네트워크와 로봇 전원을 확인하세요.", {role: "status"}),
  );
  const retry = el("ui-button", "다시 시도", {kind: "quiet", type: "button"});
  retry.addEventListener("click", () => onConnect());
  root.append(retry);
}

async function check(root, onReady, onEnter) {
  const gate = driverFor(DRIVER_KIND);
  setTag("확인 중");
  notice("");
  root.replaceChildren(
    el("ui-head", "접속", {id: "pilot-gate-heading"}),
    el("ui-empty", "연결 확인 중…"),
  );

  let me;
  try { me = await whoami(); } catch { return renderOffline(root, () => check(root, onReady, onEnter)); }
  if (me.status === 401) {
    clearToken();
    setTag("차단");
    notice("토큰이 유효하지 않습니다");
    renderTokenForm(root, () => check(root, onReady, onEnter), "토큰이 유효하지 않습니다. 다시 입력해 주세요.");
    return;
  }

  const caps = await fetchCapabilities();
  const verdict = gate.assessGate({role: me.body?.role, capabilities: caps.body ?? {}});
  if (!verdict.allowed) {
    setTag("차단");
    notice("진입이 차단되었습니다");
    const pairs = [["게이트", "BLOCK"], ["운전 역할", me.body?.role ?? "—"],
                   ["수동 운전", caps.body?.teleop === true ? "보류" : "보류됨"],
                   ["구동", caps.body?.runtime?.drive === true ? "켜짐" : "꺼짐"]];
    const statuses = verdict.reasons.map((r) => el("ui-status", gate.describeReason(r), {role: "status"}));
    const actions = el("ui-actions");
    const retry = el("ui-button", "다시 시도", {kind: "quiet", type: "button"});
    retry.addEventListener("click", () => check(root, onReady, onEnter));
    const reset = el("ui-button", "토큰 초기화", {kind: "segment", type: "button"});
    reset.addEventListener("click", () => {
      clearToken();
      renderTokenForm(root, () => check(root, onReady, onEnter));
    });
    actions.append(retry, reset);
    root.replaceChildren(
      el("ui-head", "접속", {id: "pilot-gate-heading"}),
      readoutPair(pairs), ...statuses, actions,
    );
    return;
  }

  setTag("준비");
  notice("조종 준비 완료");
  const enter = el("ui-button", "주행 시작", {kind: "primary", type: "button", "data-drive-enter": ""});
  enter.addEventListener("click", () => onEnter?.({role: me.body?.role}));
  root.replaceChildren(
    el("ui-head", "접속", {id: "pilot-gate-heading"}),
    readoutPair([["게이트", "READY"], ["역할", me.body?.role ?? "operator"]]),
    enter,
  );
  onReady?.({role: me.body?.role});
}

export function mountConnect(root, {onReady, onEnter} = {}) {
  const run = () => check(root, onReady, onEnter);
  root.__pilotRunCheck = run;
  root.__pilotForm = () => renderTokenForm(root, run);
  if (!token()) {
    renderTokenForm(root, run);
    return;
  }
  run();
}
