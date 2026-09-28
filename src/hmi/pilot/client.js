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
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: {...(options.headers ?? {}), ...authHeaders()},
  });
  const body = await response.json().catch(() => ({}));
  return {status: response.status, ok: response.ok, body};
}

export async function postJson(path, body) {
  return api(path, {method: "POST", body: JSON.stringify(body ?? {})});
}

export function whoami() {
  return api("/api/v1/auth/whoami");
}

export function fetchCapabilities() {
  return api("/api/v1/system/capabilities");
}
