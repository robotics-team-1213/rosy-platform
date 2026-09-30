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
