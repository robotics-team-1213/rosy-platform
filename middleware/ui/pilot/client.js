// 토큰 세션과 API 래퍼(D-193 6 준수). pilot v1 은 만료 없는 토큰을
// sessionStorage 에만 둔다 — localStorage 영구 저장(로그인 유지)은 제공하지
// 않는다. 토큰을 URL·쿠키·콘솔에 남기지 않는다.

const KEY = "rosy.pilot.token";

export function token() {
  return sessionStorage.getItem(KEY) ?? "";
}

export function setToken(value) {
  sessionStorage.setItem(KEY, String(value ?? "").trim());
}

export function clearToken() {
  sessionStorage.removeItem(KEY);
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

// 등록 코드 발급(D-193 §5, 관리자만). 화면이 없는 상대 기기와 연동할 때
// 이 태블릿에 코드를 크게 보여 주고 상대 기기에서 입력한다.
// 입력 방향(상대 화면 코드 → 이 태블릿 입력)은 pairWithCode 가 맡는다.
export async function requestEnrollmentCode(role = "operator") {
  return postJson("/api/v1/auth/enrollment-codes", {role});
}
