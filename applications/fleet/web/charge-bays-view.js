// D-941 5/7: the charge-bay plan remains display-only; robot/arm inspection and actions live in C23/C24 (robot-dock-binding.js).
import { isRouteAbsent } from "/console/assets/poll-gate.js";
import { chargeBayRows, inspectorTargetsFromRows, formatArmLiveJointText } from "/console/assets/charge-bays-model.js";

export { chargeBayRows, inspectorTargetsFromRows, formatArmLiveJointText };

export function createChargeBaysView({ scope, el, call, auth, onPlan = null }) {
  const state = el("charge-bays-state");
  const list = el("charge-bay-rows");
  const hint = el("charge-bays-hint");
  let inFlight = false;
  let unavailable = false;

  scope.listen(document, "visibilitychange", () => {
    if (!document.hidden) void refresh();
  });

  function tag(text, status) {
    const t = document.createElement("ui-tag");
    t.setAttribute("status", status);
    t.textContent = text;
    return t;
  }

  function show(rows, note) {
    if (!list) return;
    list.replaceChildren();
    for (const b of rows?.bays || []) {
      const li = document.createElement("li");
      li.append(`${b.id} `, tag(b.text, b.status));
      list.append(li);
    }
    for (const c of rows?.cells || []) {
      const li = document.createElement("li");
      li.append(`${c.id} `, tag(c.text, c.status));
      list.append(li);
    }
    for (const a of rows?.actions || []) {
      const li = document.createElement("li");
      li.textContent = `${a.robot}: ${a.text}`;
      list.append(li);
    }
    if (hint) {
      hint.textContent = note;
      hint.hidden = !note;
    }
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable || auth.locked || document.hidden) return;
    inFlight = true;
    try {
      const plan = await call("/api/fleet/charge-bays", { signals: [life.signal] });
      life.check();
      onPlan?.(plan);
      const rows = chargeBayRows(plan);
      if (state) state.textContent = `칸 ${rows.bays.length}`;
      show(rows, rows.bays.length ? rows.summary : "활성 지도에 충전 칸(charge)이 없습니다");
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
      if (state) state.textContent = "—";
      show(null, error.code === "NO_ACTIVE_MAP" ? "활성 지도가 없습니다" : "충전 칸 계획을 읽지 못했습니다");
    } finally {
      inFlight = false;
    }
  }

  return { refresh };
}
