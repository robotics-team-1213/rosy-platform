// 토큰 세션과 API 래퍼(D-193 6 준수). pilot v1 은 만료 없는 토큰을
// sessionStorage 에만 둔다 — localStorage 영구 저장(로그인 유지)은 제공하지
// 않는다. 토큰을 URL·쿠키·콘솔에 남기지 않는다.

import { accountKey as sharedAccountKey, createAccountSession } from "/common/account-session.js";
import {createAlertCenter} from "/common/alert-center.js";
import {getAnnouncer} from "/common/announcer.js";

const KEY = "rosy.pilot.token";
export let account = null;
export const authenticated = () => Boolean(account?.authenticated || token());
const accountKey = () => account?.authenticated ? sharedAccountKey(account) : token();
const kit = createAccountSession({
  current: () => account,
  apply: value => { account = value; if (value?.authenticated) sessionStorage.removeItem(KEY); },
  changed: () => { clearToken(); document.body.hidden = true; window.location.reload(); },
});

export async function restoreAccount() {
  if (inPilotApp() && document.documentElement.dataset.pilotAccount !== 'managed') return null;
  return kit.restore();
}

export const accountLogout = () => kit.logout(clearToken);

export function token() {
  return sessionStorage.getItem(KEY) ?? "";
}

// Rosy Pilot 앱이 이 화면을 연 경우. 로봇 선택과 세션은 앱이 소유한다.
// 번들 화면은 그 세션만 쓰고, 개발 연결·코드·다른 표면으로 다시 나가지 않는다.
export function inPilotApp() {
  return document.documentElement.dataset.pilotShell === "android";
}

export function setToken(value) {
  kit.invalidate();
  account = null;
  sessionStorage.setItem(KEY, String(value ?? "").trim());
}

export function clearToken() {
  sessionStorage.removeItem(KEY);
  kit.invalidate();
  account = null;
}

export function prepareConsoleSession() {
  const current = token();
  if (current) sessionStorage.setItem("rosy.dashboard.token", current);
}

export function authHeaders() {
  const value = token();
  return value ? {Authorization: `Bearer ${value}`} : {};
}

export async function api(path, options = {}) {
  const identity = accountKey();
  const {timeoutMs, ...init} = options;
  const headers = {...(init.headers ?? {})};
  if (init.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  // 시한이 있으면 그 안에 못 끝난 요청을 끊는다(AbortError 로 거부된다).
  const controller = timeoutMs ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(path, {
      cache: "no-store",
      ...init,
      ...(controller ? {signal: controller.signal} : {}),
      headers: {...headers, ...authHeaders()},
    });
    const body = await response.json().catch(() => ({}));
    if (identity !== accountKey()) throw new Error('계정이 변경되었습니다. 화면을 다시 여세요.');
    return {status: response.status, ok: response.ok, body};
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export async function postJson(path, body, {timeoutMs} = {}) {
  return api(path, {method: "POST", body: JSON.stringify(body ?? {}), timeoutMs});
}

// D-411: 같은 Bearer 머리로 바이너리를 받는다(토큰은 URL 에 넣지 않는다). length 는
// Content-Length — 본문이 그보다 짧으면 서버가 도중에 끊은 것이다(실패).
// signal 로 호출자가 끊을 수 있다(취소·화면 나가기); timeoutMs 가 지나도 끊는다.
export async function apiBlob(path, {timeoutMs, signal} = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, {once: true});
  const timer = timeoutMs ? setTimeout(abort, timeoutMs) : null;
  try {
    const response = await fetch(path, {cache: "no-store", headers: authHeaders(), signal: controller.signal});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      return {status: response.status, ok: false, body, blob: null, length: null};
    }
    const header = response.headers.get("Content-Length");
    return {status: response.status, ok: true, body: null, blob: await response.blob(),
            length: header == null ? null : Number(header)};
  } finally {
    if (timer) clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function whoami() {
  return api("/api/v1/auth/whoami");
}

export function fetchCapabilities() {
  return api("/api/v1/system/capabilities");
}

// 로그인 코드(ABCD-EFGH, D-193) → 이 기기 전용 만료 토큰. 코드는 로봇 화면·운영자가 발급한다.
// 로봇은 코드를 늘 하이픈과 함께 보여 준다. 하이픈 없는 8 글자는 토큰일 수 있어 코드로 보지 않는다.
export const LOGIN_CODE = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/i;

export async function pairWithCode(code, label = "Rosy Pilot") {
  const response = await fetch("/api/v1/auth/pair", {
    method: "POST",
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({code: code.trim().toUpperCase(), label}),
  });
  const body = await response.json().catch(() => ({}));
  if (response.status === 201 && body.token) setToken(body.token);
  return {status: response.status, body};
}

// D-432 연결 방식. 인증 없음. 이 화면이 붙어 있는 로봇과 paired/development 만 돌려준다.
// 실패·다른 모양은 null — 코드 입력은 그대로 둔다.
const ROBOT_ID = /^[A-Za-z0-9_-]{1,64}$/;

export async function connectionOffer() {
  try {
    const result = await api("/api/v1/auth/connection");
    const body = result.body ?? {};
    if (!result.ok || (body.mode !== "paired" && body.mode !== "development")) return null;
    if (typeof body.robot_id !== "string" || !ROBOT_ID.test(body.robot_id)) return null;
    return {mode: body.mode, robotId: body.robot_id};
  } catch {
    return null;
  }
}

// D-432 개발 연결. 로봇이 development 일 때만 CORE 가 201 로 1시간 운전자 세션을 준다.
export async function developmentSession() {
  const result = await postJson("/api/v1/auth/development-session", {});
  if (result.status === 201 && typeof result.body?.token === "string") setToken(result.body.token);
  return result;
}

// --- 알림 한 표면(D-1117 A3) ---
// 한 줄(#pilot-notice)은 일반 안내만 쓴다. 지속 알림(비상 정지 해제 보류 등)은 앱당 목록 하나(#pilot-alerts, C25)에 둔다.
// 켜진 안전·위험·경고(또는 정지 결과)가 있으면 일반 안내는 그것을 덮지 못한다. 낭독은 공용 announcer 한 곳이다.
const STICKY = new Set(["safety", "crit", "warn"]);
const STOP_RESULTS = new Set(["received", "refused", "unknown"]);

export function createNotice({line, center}) {
  const blocked = () => center.getItems().some((item) => STICKY.has(item.kind))
    || STOP_RESULTS.has(line?.dataset?.stopState);
  return {
    blocked,
    // 일반 안내. 빈 글자는 줄을 비운다(화면 전환). 값이 같으면 다시 쓰지 않는다.
    say(text) {
      if (!line) return false;
      if (text && blocked()) return false;
      line.removeAttribute("data-stop-state");
      if (line.textContent !== text) line.textContent = text;
      return true;
    },
    alert(key, kind, message, title = "") { center.publish({kind, key, message, title}); },
    clear(key) { center.resolve(key); },
  };
}

let shared = null;
export function pilotNotice() {
  return shared ??= createNotice({
    line: document.querySelector("#pilot-notice"),
    center: createAlertCenter({listEl: document.querySelector("#pilot-alerts"), toastEl: null,
      announcer: getAnnouncer(document), isOnScreen: () => true}),
  });
}

// 한 사건 한 번 낭독: 폴링이 같은 글을 다시 써도 announcer 가 바뀔 때만 읽는다.
export const announce = (text, options) => getAnnouncer(document).announce(text, options);
