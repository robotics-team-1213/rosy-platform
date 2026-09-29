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
