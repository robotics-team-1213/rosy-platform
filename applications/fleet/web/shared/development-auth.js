import { createFleetClient } from "/common/fleet-client.js";

// Reuse a configured credential only; development mode never supplies an identity.
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
  return null;
}
