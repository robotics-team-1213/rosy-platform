// 세션과 인증된 fetch. 토큰이 사는 유일한 곳이다.

import { elements } from "./dom.js";

// D-193 6 storage rule. A token without an expiry (card, manual) lives only in
// sessionStorage. A paired token may go to localStorage, and only when the
// operator ticks "keep me logged in"; it is dropped there once it expires.
// Tokens never go into a URL, a cookie or the console.
const SESSION_KEY = "rosy.dashboard.token";
const PAIRED_KEY = "rosy.dashboard.paired";
// "로그인 유지(최대 7일)" is a promise: a token that would outlive it stays in this tab only.
export const REMEMBER_MAX_MS = 7 * 24 * 60 * 60 * 1000;

export const PAIRED_SOURCES = new Set(["pair-physical", "pair-admin"]);

function storageRemove(storage, key) {
  try { storage.removeItem(key); } catch (_error) { /* storage may be blocked */ }
}

function persistedPairedToken() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(PAIRED_KEY) || "null"); } catch (_error) { saved = null; }
  if (!saved) return "";
  const left = Date.parse(saved.expires_at || "") - Date.now();
  if (typeof saved.token !== "string" || !saved.token || !(left > 0 && left <= REMEMBER_MAX_MS)) {
    storageRemove(localStorage, PAIRED_KEY);
    return "";
  }
  return saved.token;
}

function storedToken() {
  try {
    const current = sessionStorage.getItem(SESSION_KEY);
    if (current) return current;
  } catch (_error) {
    // Fall through to a remembered paired token.
  }
  return persistedPairedToken();
}

export const session = {
  token: storedToken(),
  identity: null,
  socket: null,
  socketLive: false,
  reconnectTimer: null,
  stableTimer: null,
  reconnectDelayMs: 1000,
  fallbackTimer: null,
  refreshTimer: null,
  capabilities: null,
  robotState: null,
  waypoints: [],
  docks: [],
  dockingSupported: false,
  role: "",
  modeChangePending: false,
  teleopPending: null,
  teleopIntervalMs: 100,
  networkHistory: { rx: [], tx: [] },
};

export const authHeaders = () => ({
  "Content-Type": "application/json",
  Authorization: `Bearer ${session.token}`,
});

export function setConnection(kind, label) {
  const badge = elements["connection-badge"];
  badge.className = `status-badge status-${kind}`;
  badge.querySelector("span").textContent = label;
}

/** Keep `token` for this browser. `persist` applies only to a token that expires within 7 days. */
export function rememberToken(token, { expiresAt = null, persist = false } = {}) {
  session.token = token;
  const left = expiresAt ? Date.parse(expiresAt) - Date.now() : NaN;
  if (persist && left > 0 && left <= REMEMBER_MAX_MS) {
    try {
      localStorage.setItem(PAIRED_KEY, JSON.stringify({ token, expires_at: expiresAt }));
      storageRemove(sessionStorage, SESSION_KEY);
      return;
    } catch (_error) {
      // Blocked storage: fall back to this tab only.
    }
  }
  storageRemove(localStorage, PAIRED_KEY);
  try { sessionStorage.setItem(SESSION_KEY, token); } catch (_error) { /* memory only */ }
}

export function forgetToken() {
  session.token = "";
  session.identity = null;
  session.role = "";
  storageRemove(sessionStorage, SESSION_KEY);
  storageRemove(localStorage, PAIRED_KEY);
}

// D-193: the login code alphabet (no 0, 1, I, L, O). Must match
// core_api_web/api/v1/auth.py ALPHABET and rosy-login-code.
export const LOGIN_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";
export const LOGIN_CODE_LENGTH = 8;

/** Typed code -> {value} (8 upper-case characters) or {error}. Spaces and hyphens are ignored. */
export function normalizeLoginCode(text) {
  const value = String(text || "").replace(/[\s-]/g, "").toUpperCase();
  if (!value) return { error: "로봇 화면에 보이는 8자 코드를 입력하세요." };
  const foreign = [...new Set([...value].filter((ch) => !LOGIN_CODE_ALPHABET.includes(ch)))];
  if (foreign.length) {
    return { error: `코드에 없는 글자: ${foreign.join(" ")} — 로그인 코드에는 0·1·I·L·O가 없습니다.` };
  }
  if (value.length !== LOGIN_CODE_LENGTH) {
    return { error: `코드는 ${LOGIN_CODE_LENGTH}자입니다 (지금 ${value.length}자). 예: ABCD-EFGH` };
  }
  return { value };
}

/** Why a pairing failed, in words that do not claim more than the server said. */
function pairFailure(status, body, retryAfter) {
  if (status === 401 && body?.error?.detail?.burned === true) {
    // The flag does not say which kind of code burned, so name both ways out.
    return "틀린 시도가 5번 쌓여 이 코드는 폐기되었습니다. 로봇 화면의 코드였다면 로봇을 다시 켜거나 "
      + "SSH에서 sudo rosy-login-code 로 새 코드를 받으세요. 관리자가 준 등록 코드였다면 관리자에게 새 코드를 요청하세요.";
  }
  if (status === 401) {
    // CORE answers every other miss the same way on purpose (D-193 4).
    return "코드가 맞지 않습니다. 잘못 쳤거나, 이미 쓰였거나, 10분이 지났거나, 발급된 코드가 없습니다. "
      + "로봇 화면의 코드를 확인하세요. 한 코드에 5번 틀리면 폐기됩니다.";
  }
  if (status === 429) {
    const seconds = Number.parseInt(retryAfter || "", 10);
    return Number.isFinite(seconds) && seconds > 0
      ? `시도가 너무 많습니다. ${seconds}초 뒤에 다시 하세요.`
      : "시도가 너무 많습니다. 1분 뒤에 다시 하세요.";
  }
  if (status === 403) return "로봇 LAN(사설 대역·로봇 AP) 밖에서는 코드로 로그인할 수 없습니다.";
  if (status === 400) return "코드 형식이 아닙니다. 8자, 예: ABCD-EFGH";
  return `로그인 실패: ${body?.error?.message || status}`;
}

/**
 * D-193 4: exchange a login code for this browser's own expiring token.
 * Resolves to the paired identity (without the token) or rejects with an Error
 * whose `message` is operator-facing and whose `retryAfter` is seconds or 0.
 */
export async function pairWithCode(code, { label = "", persist = false } = {}) {
  let response;
  try {
    response = await fetch("/api/v1/auth/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(label ? { code, label } : { code }),
    });
  } catch (_error) {
    throw new Error("로봇에 닿지 못했습니다. 로봇과 같은 네트워크인지 확인하세요.");
  }
  let body = null;
  try { body = await response.json(); } catch (_error) { body = null; }
  if (response.status !== 201 || typeof body?.token !== "string") {
    const retryAfter = response.headers.get("Retry-After");
    const error = new Error(pairFailure(response.status, body, retryAfter));
    error.status = response.status;
    error.retryAfter = response.status === 429 ? Math.max(1, Number.parseInt(retryAfter || "60", 10) || 60) : 0;
    throw error;
  }
  rememberToken(body.token, { expiresAt: body.expires_at, persist });
  const { token: _token, ...identity } = body;
  return identity;
}

/**
 * Always asks CORE to log this token out; CORE decides what may be deleted.
 * Resolves true when the token no longer works on the robot, false when CORE
 * keeps it (409: card or manual tokens are revoked in settings) and it is only
 * forgotten here.
 */
export async function logout() {
  let deleted = false;
  if (session.token) {
    try {
      await api("/api/v1/auth/logout", { method: "POST" });
      deleted = true;
    } catch (error) {
      // 401: already gone on the robot. 409: not a paired token, forget it locally.
      if (error.status === 401) deleted = true;
      else if (error.status !== 409) throw error;
    }
  }
  forgetToken();
  return deleted;
}

const SOURCE_LABELS = {
  card: "카드",
  manual: "수동",
  "pair-physical": "로봇 화면 코드",
  "pair-admin": "관리자 등록 코드",
  legacy: "설정 파일",
};

export function sourceLabel(source) {
  return SOURCE_LABELS[source] || source || "알 수 없음";
}

export function expiryLabel(expiresAt) {
  if (!expiresAt) return "만료 없음";
  const stamp = new Date(expiresAt);
  if (Number.isNaN(stamp.getTime())) return "만료 알 수 없음";
  return `만료 ${stamp.toLocaleString("ko-KR", { hour12: false })}`;
}

export async function api(path, options = {}) {
  if (!session.token) throw new Error("접속 키가 필요합니다.");
  const response = await fetch(path, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.error?.message || body.detail || message;
    } catch (_error) {
      // The HTTP status remains the safest fallback.
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function apiMaybe(path) {
  if (!session.token) return null;
  const response = await fetch(path, { headers: authHeaders() });
  if (response.status === 404) return null;
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.error?.message || message;
    } catch (_error) {
      // Keep the status text.
    }
    throw new Error(message);
  }
  return response.json();
}

export function isAdmin() {
  return session.role === "administrator";
}
