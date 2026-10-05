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

import {token, setToken, clearToken, whoami, fetchCapabilities, LOGIN_CODE, pairWithCode, requestEnrollmentCode, api, authHeaders} from "../client.js";
import {driverFor} from "../drivers/registry.js";
import {createVisionPreview} from "../vision.js";
import {mountDriveView, actionIcon} from "./drive-view.js";

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

// --- 이웃 방 (D-343 2.2 — 이 기기가 대신 찾아 준 이웃 로봇) ---
async function refreshLobby(host) {
  if (host.__lobbyBusy) return;
  host.__lobbyBusy = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  host.setAttribute("aria-live", "polite");
  host.replaceChildren(el("ui-text", "같은 LAN의 로봇을 찾는 중…", {scale: "label"}));
  try {
    const result = await api("/api/v1/site/rooms", {signal: controller.signal});
    if (!result.ok || !Array.isArray(result.body?.rooms)) throw new Error("discovery unavailable");
    const list = el("ui-actions");
    const seen = new Set();
    for (const room of result.body.rooms.slice(0, 64)) {
      if (!room || room.kind !== "robot" || typeof room.hostname !== "string") continue;
      const hostname = room.hostname.toLowerCase();
      const fqdn = hostname.endsWith(".local") ? hostname : `${hostname}.local`;
      if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$/.test(fqdn)
          || !Number.isInteger(room.port) || room.port < 1 || room.port > 65535) continue;
      let target;
      try { target = new URL(room.url); } catch { continue; }
      if (!["http:", "https:"].includes(target.protocol) || target.hostname !== fqdn
          || target.username || target.password || target.search || target.pathname !== "/pilot/"
          || target.hash !== "#join"
          || Number(target.port || (target.protocol === "https:" ? 443 : 80)) !== room.port) continue;
      const currentPort = Number(location.port || (location.protocol === "https:" ? 443 : 80));
      if (room.port === currentPort && [fqdn, room.address].includes(location.hostname)) continue;
      if (seen.has(fqdn)) continue;
      seen.add(fqdn);
      const go = el("ui-button", hostname, {type: "button", "data-lobby-room": room.hostname,
        "data-lobby-url": target.href});
      go.setAttribute("kind", "segment");
      go.addEventListener("click", () => location.assign(target.href));
      list.append(go);
    }
    host.replaceChildren(el("ui-text", seen.size ? "같은 LAN의 로봇 · 선택 후 연결 확인"
      : "같은 LAN에서 발견한 다른 로봇이 없습니다", {scale: "label"}));
    if (seen.size) host.append(list, el("p", "발견 목록입니다. 선택한 로봇에서 승인·로그인을 확인합니다."));
  } catch {
    host.replaceChildren(el("ui-text", "로봇 목록을 가져오지 못했습니다. LAN 연결을 확인하고 다시 찾아주세요.", {scale: "label"}));
  } finally {
    clearTimeout(timer);
    host.__lobbyBusy = false;
    const retry = el("ui-button", "다시 찾기", {type: "button", "data-lobby-retry": ""});
    retry.setAttribute("kind", "quiet");
    retry.addEventListener("click", () => refreshLobby(host));
    host.append(retry);
  }
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

  // 이웃 방 (D-343 2.2 — 이 기기가 대신 찾아 준 이웃. 주소는 현재 origin 으로만 연다)
  const lobby = el("div", null, {"data-lobby-list": ""});
  root.append(lobby);
  refreshLobby(lobby);

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

// --- 연동 코드 보여주기 (D-193 §5 등록 코드) ---
// 화면이 없는 상대 기기와 연동할 때: 이 태블릿이 코드를 보여 주고 상대 기기에서
// 입력한다. 반대 방향(상대 화면 코드 → 이 태블릿 입력)은 접속 폼의 pairWithCode.
// 발급은 관리자만(CORE 403), 표시 역할은 운전자(operator) 고정.
function mountShowCode(root) {
  const section = el("div", null, {"data-enroll-section": ""});
  section.append(el("ui-text", "연동 코드 보여주기", {scale: "label"}));
  section.append(el("p", "입력 화면이 있는 상대 기기는 이 코드를 보고 그 화면에서 입력합니다. " +
    "입력 수단이 없는 로봇은 로봇 화면의 코드를 이 태블릿 접속 폼에 입력하세요.",
    {"data-enroll-guidance": ""}));
  const button = el("ui-button", "코드 발급", {type: "button", "data-show-code": ""});
  button.setAttribute("kind", "segment");
  const status = el("ui-status", "", {role: "status", "data-enroll-status": ""});
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "코드 발급 중…";
    section.querySelector("[data-enroll-code]")?.remove();
    let result = null;
    try { result = await requestEnrollmentCode("operator"); }
    catch { result = null; }
    button.disabled = false;
    if (!result || result.status !== 201 || typeof result.body?.code !== "string") {
      status.textContent = result?.status === 403
        ? "관리자 권한이 필요합니다."
        : "코드를 발급할 수 없습니다. 연결을 확인하세요.";
      return;
    }
    const minutes = Math.max(1, Math.round((result.body.expires_in_s ?? 300) / 60));
    const code = el("ui-text", result.body.code, {scale: "display", "data-enroll-code": ""});
    status.textContent = `운전자용 코드입니다. 약 ${minutes}분 안에 상대 기기에서 입력하세요.`;
    section.append(code);
  });
  section.append(button, status);
  root.append(section);
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
  root.__pilotPreviewClose?.();
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
  const state = await api("/api/v1/robot/state").catch(() => null);
  const emergency = state?.body?.mode === "EMERGENCY";
  if (emergency) {
    enter.disabled = true;
    enter.reason = "비상 정지 중에는 주행을 시작할 수 없습니다";
    setTag("비상 정지 중"); notice("로봇에 연결됐습니다 · 비상 정지 중");
  }
  const camera = el("ui-button", "카메라 보기", {type: "button", kind: "primary", "data-camera-preview": ""});
  camera.setAttribute("kind", "primary");
  actionIcon(camera, "fit");
  camera.addEventListener("click", () => showCamera(root, () => check(root, onReady, onEnter)));
  const actions = el("ui-actions"); actions.append(camera, enter);
  const roleLabel = {operator: "운영자", administrator: "관리자", viewer: "조회 전용"};
  const summary = readoutPair([["로봇 연결", "확인됨"], ["사용 권한", roleLabel[me.body?.role] ?? "확인 필요"]]);
  summary.dataset.gateState = emergency ? "BLOCK" : "READY";
  root.replaceChildren(
    el("ui-head", "로봇에 연결됐습니다", {id: "pilot-gate-heading"}),
    summary,
    el("p", emergency ? "비상 정지 중입니다. 카메라는 조종을 시작하지 않고 볼 수 있습니다."
      : "먼저 카메라를 확인하세요. 주행을 시작하면 누르는 동안만 로봇을 조종합니다.", {"data-ready-guidance": ""}),
    actions,
  );
  if (me.body?.role === "administrator") mountShowCode(root);
  onReady?.({role: me.body?.role});
}

function showCamera(root, onBack) {
  setTag("영상 보기"); notice("조종하지 않는 카메라 보기");
  document.body.dataset.pilotScreen = "preview";
  const arena = el("div", null, {class: "pilot-drive", "data-readonly-camera": ""});
  const stage = el("div", null, {"data-drive-stage": ""});
  const hud = el("div", null, {"data-drive-hud": ""});
  const description = el("span", "카메라 · 조종하지 않는 보기", {"data-camera-description": ""});
  const zoomFact = el("span", "", {"data-drive-fact": "zoom", hidden: ""});
  const view = el("div", null, {"data-drive-view": ""});
  const frame = el("img", null, {alt: "로봇 전방 카메라 전체 영상", "data-drive-frame": "", hidden: ""});
  const empty = el("ui-empty", "카메라 프레임 수신 대기", {"data-drive-empty": ""});
  view.append(frame, empty); stage.append(hud, view); arena.append(stage);
  root.replaceChildren(arena);
  const elements = {frame, hud, view, zoomFact};
  const layout = mountDriveView(arena, elements);
  const actions = el("ui-actions");
  const fitButton = el("ui-button", "전체 영상", {kind: "segment", type: "button", "data-drive-fit": ""});
  fitButton.setAttribute("kind", "segment");
  actionIcon(fitButton, "fit");
  elements.fitButton = fitButton;
  const fillButton = el("ui-button", "화면 채우기", {kind: "segment", type: "button", "data-drive-fill": ""});
  fillButton.setAttribute("kind", "segment");
  actionIcon(fillButton, "expand");
  elements.fillButton = fillButton;
  elements.fitButton.addEventListener("click", () => layout.setZoom(1));
  elements.fillButton.addEventListener("click", () => layout.setZoom("full"));
  const back = el("ui-button", "접속 화면으로", {kind: "quiet", type: "button", "data-camera-back": ""});
  back.setAttribute("kind", "quiet");
  actionIcon(back, "back");
  back.addEventListener("click", onBack);
  actions.append(elements.fitButton, elements.fillButton, back);
  hud.append(description, zoomFact, actions);
  layout.setZoom(1);
  const preview = createVisionPreview({
    apiGet: api,
    fetchFrame: async (path) => {
      const response = await fetch(path, {headers: authHeaders(), cache: "no-store"});
      if (!response.ok) throw new Error("camera frame unavailable");
      return response;
    },
    onFrame: (url, meta) => {
      frame.src = url; frame.hidden = false; empty.hidden = true;
      description.textContent = `카메라 · ${meta.width ?? "—"}×${meta.height ?? "—"} · 조종하지 않는 보기`;
    },
    onUnavailable: (message) => { frame.hidden = true; empty.hidden = false; empty.textContent = message; },
  });
  const visibility = () => { document.hidden ? preview.stop() : preview.start(); };
  document.addEventListener("visibilitychange", visibility);
  root.__pilotPreviewClose = () => {
    preview.stop(); layout.close(); document.removeEventListener("visibilitychange", visibility);
    document.body.dataset.pilotScreen = "connect"; delete root.__pilotPreviewClose;
  };
  preview.start();
}

export function mountConnect(root, {onReady, onEnter} = {}) {
  root.__pilotPreviewClose?.();
  const run = () => check(root, onReady, onEnter);
  root.__pilotRunCheck = run;
  root.__pilotForm = () => renderTokenForm(root, run);
  if (!token()) {
    renderTokenForm(root, run);
    return;
  }
  run();
}
