import { createFleetClient } from "/common/fleet-client.js";

// Field check 2026-10-10: pages that minted a session on every 401 evicted each other's
// sessions (D-473 keeps eight), so each then minted again. A page tries its stored token
// first and issues at most one new session per minute.
export const ISSUE_GAP_MS = 60000;
let issuedAtMs = -Infinity;

/** POST a development session through `request`, or null inside the page's issue gap. */
export async function issueDevelopmentSession(request, nowMs = Date.now()) {
  if (nowMs - issuedAtMs < ISSUE_GAP_MS) return null;
  issuedAtMs = nowMs;
  const session = await request("/api/fleet/auth/development-session", { method: "POST" });
  sessionStorage.setItem("rosy-console-token", session.token);
  return session.token;
}

// Only an explicitly enabled development console may issue a browser session.
export async function developmentToken(token) {
  const request = createFleetClient({ credential: () => token });
  if ((await request("/api/fleet/auth/connection")).mode !== "development") return null;
  if (token) {
    try {
      await request("/api/fleet/session");
      return token;
    } catch (error) {
      if (error.status !== 401) throw error;
    }
  }
  return issueDevelopmentSession(request);
}
