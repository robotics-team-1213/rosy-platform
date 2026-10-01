// SIM-only OMX transport. It never uses Pinky teleop, CORE tokens, or /ws/state.
const API = "/api/v1/sim/omx";

export const omxSim = {
  kind: "omx_sim",
  async discover() {
    const response = await fetch(`${API}/target`, {cache: "no-store"});
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`target ${response.status}`);
    const target = await response.json();
    if (target.kind !== "omx_sim" || target.simulation !== true || !target.instance_id ||
        !Array.isArray(target.joints) || !target.joints.length || !target.gripper) {
      throw new Error("invalid simulation target");
    }
    return target;
  },
  async request(path, {token = "", format = "json", ...options} = {}) {
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers: {"Content-Type": "application/json", ...(token ? {Authorization: `Bearer ${token}`} : {}), ...options.headers},
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
    return response.status === 204 ? null : format === "blob" ? response.blob() : response.json();
  },
};
