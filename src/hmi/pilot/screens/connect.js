// 접속 게이트(D-323): 게임식 "계속하기" UX.
// 최근 접속 관리는 인라인(모듈 404 방지 — allowlist 동기화 이슈).
// 최근 접속은 호스트·이름만 기억한다. 토큰은 영구 저장하지 않는다(D-193) — 이전 판은
// 토큰을 localStorage 에 평문으로 남겼다.

const RECENT_KEY = "rosy.pilot.recent";

function getRecent() {
  let list = [];
  try { list = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]"); }
  catch { return []; }
  if (list.some((entry) => "token" in entry)) {
    // 이전 판이 남긴 평문 토큰을 걷어낸다.
    list = list.map(({host, label}) => ({host, label}));
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch { /* 저장 불가 */ }
  }
  return list;
}
function addRecentEntry({host, label}) {
  const list = getRecent().filter((r) => r.host !== host).map(({host: h, label: l}) => ({host: h, label: l}));
  list.unshift({host, label});
  localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 5)));
}
function removeRecentEntry(host) {
  localStorage.setItem(RECENT_KEY, JSON.stringify(getRecent().filter((r) => r.host !== host)));
}

import {token, setToken, clearToken, whoami, fetchCapabilities, LOGIN_CODE, pairWithCode} from "../client.js";
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
    const button = el("ui-button", entry.label || entry.host, {type: "button", "data-recent-connect": entry.host});
    button.setAttribute("kind", "primary");
    button.addEventListener("click", () => {
      // 이 탭에 토큰이 있으면 바로 확인, 없으면 코드·토큰 입력으로.
      if (token()) onConnect();
      else renderTokenForm(root, onConnect, `${entry.label || entry.host} — 로그인 코드를 입력하세요.`);
    });
    const remove = el("ui-button", "✕", {type: "button", "data-recent-remove": entry.host, "aria-label": "최근 접속에서 지우기"});
    remove.setAttribute("kind", "quiet");
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
    placeholder: "로그인 코드(ABCD-EFGH) 또는 토큰", "aria-label": "로그인 코드 또는 운전 토큰",
    autocomplete: "off", name: "token",
    // 태블릿 실측: 안드로이드 키보드가 첫 글자를 대문자로 바꿔 유효한 토큰이 401 이 됐다.
    autocapitalize: "off", autocorrect: "off", spellcheck: "false", inputmode: "text",
  });
  const submit = el("ui-button", "연결", {type: "button"});
  submit.setAttribute("kind", "primary");
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
  const connect = async () => {
    const value = field.value.trim();
    if (!value) {
      notice("로그인 코드나 토큰을 입력하세요");
      return;
    }
    if (LOGIN_CODE.test(value)) {
      notice("로그인 코드 확인 중…");
      const paired = await pairWithCode(value).catch(() => null);
      if (!paired || paired.status !== 201) {
        const burned = paired?.body?.error?.detail?.burned;
        const message = !paired ? "로봇에 연결할 수 없습니다."
          : paired.status === 429 ? "시도가 너무 많습니다. 잠시 뒤 다시 입력하세요."
          : burned ? "이 코드는 더 쓸 수 없습니다. 로봇에서 새 코드를 받으세요."
          : "코드가 맞지 않거나 만료됐습니다.";
        renderTokenForm(root, onConnect, message);
        return;
      }
    } else {
      setToken(value);
    }
    // 최근에 추가 (호스트는 same-origin이므로 location.host). 토큰은 넣지 않는다.
    addRecentEntry({host: location.host, label: location.hostname.replace(/\.local$/, "")});
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
  const retry = el("ui-button", "다시 시도", {type: "button"});
  retry.setAttribute("kind", "quiet");
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
    const retry = el("ui-button", "다시 시도", {type: "button"});
    retry.setAttribute("kind", "quiet");
    retry.addEventListener("click", () => check(root, onReady, onEnter));
    const reset = el("ui-button", "토큰 초기화", {type: "button"});
    reset.setAttribute("kind", "segment");
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
  const enter = el("ui-button", "주행 시작", {type: "button", "data-drive-enter": ""});
  enter.setAttribute("kind", "primary");
  enter.addEventListener("click", () => onEnter?.({role: me.body?.role, capabilities: caps.body ?? {}}));
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
