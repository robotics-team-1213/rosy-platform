import { createFleetClient } from "/common/fleet-client.js";

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
  const session = await request("/api/fleet/auth/development-session", { method: "POST" });
  sessionStorage.setItem("rosy-console-token", session.token);
  return session.token;
}
