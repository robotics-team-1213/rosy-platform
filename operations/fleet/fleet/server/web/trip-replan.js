// D-494 5 / D-540 3 — a trip held at a place for a changed route asks the operator in its queue row:
// `바뀐 경로로 계속` (confirm-replan, a move: named operator, D-540 9) or `운행 취소` (a stop: quiet, no confirm).
import { tripErrorText } from "/console/assets/site-map-model.js";
import { primaryButton, quietButton, setReason } from "./queues.js";

/** What the slot shows for one held trip: the changed route, or why there is none. */
export function replanView(trip, { operator, named = "", busy = false }) {
  const hold = trip.hold || {};
  const plan = hold.plan;
  const facts = plan
    ? [Number.isFinite(hold.length_m) ? `바뀐 경로 ${hold.length_m.toFixed(1)} m` : "바뀐 경로",
      Number.isFinite(hold.eta_s) ? `약 ${Math.round(hold.eta_s)}초` : "",
      `장소 ${(plan.places || []).length}곳`].filter(Boolean).join(" · ")
    : `다시 계산한 경로가 없습니다${hold.code ? ` (${hold.code})` : ""} · 운행을 취소하세요`;
  const lock = !operator ? "운영자 권한이 필요합니다" : busy ? "답을 보내는 중" : "";
  return { facts, confirmReason: lock || named || (plan ? "" : "다시 계산한 경로가 없습니다"), cancelReason: lock };
}

export function createTripReplan({ scope, view, call, log, isOperator, namedReason = () => "" }) {
  const busy = new Set(), results = new Map(), signatures = new Map();  // by trip id / robot id

  async function send(trip, verb, done) {
    if (busy.has(trip.trip_id)) return;
    const life = scope.capture();
    busy.add(trip.trip_id);
    render();
    try {
      await call(`/api/fleet/trips/${encodeURIComponent(trip.trip_id)}/${verb}`, { method: "POST" });
      life.check();
      results.set(trip.trip_id, { text: `${trip.robot_id} ${done}`, kind: "good" });
    } catch (err) {
      if (err.name === "AbortError") return;
      const why = err.code ? tripErrorText(err.code, err.detail) : err.message;
      results.set(trip.trip_id, { text: `${trip.robot_id} 운행 거절 · ${why}`, kind: "bad" });
    } finally {
      if (life.current()) {
        const last = results.get(trip.trip_id);
        if (last) log(last.text, last.kind);
        busy.delete(trip.trip_id);
        render();
      }
    }
  }

  function body(trip) {
    const spec = replanView(trip, { operator: isOperator(), named: namedReason(), busy: busy.has(trip.trip_id) });
    const box = document.createElement("div");
    box.className = "stuck-item";
    const facts = document.createElement("p");
    facts.className = "stuck-resolver";
    facts.textContent = spec.facts;
    const actions = document.createElement("div");
    actions.className = "stuck-actions";
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", `${trip.robot_id} 바뀐 경로 확인`);
    const go = primaryButton("바뀐 경로로 계속");
    const stop = quietButton("운행 취소");
    for (const [node, key, reason, verb, done] of [[go, "confirm", spec.confirmReason, "confirm-replan", "바뀐 경로로 계속합니다"],
      [stop, "cancel", spec.cancelReason, "cancel", "운행을 취소했습니다"]]) {
      node.dataset.replan = key;
      setReason(node, reason);
      node.addEventListener("click", scope.guard(() => send(trip, verb, done)));
    }
    actions.append(go, stop);
    box.append(facts, actions);
    const last = results.get(trip.trip_id);
    if (last) {
      const line = document.createElement("p");
      line.className = "stuck-result";
      line.dataset.kind = last.kind;
      line.setAttribute("role", last.kind === "bad" ? "alert" : "status");
      line.textContent = last.text;
      box.append(line);
    }
    return box;
  }

  function render() {
    for (const trip of view.stateUnavailable ? [] : (view.trafficTrips || []).filter((row) => row.hold)) {
      const slot = document.querySelector(`[data-decision-slot="${CSS.escape(`${trip.robot_id}|replan`)}"]`);
      const signature = JSON.stringify([trip.trip_id, trip.hold, busy.has(trip.trip_id),
        results.get(trip.trip_id) || null, isOperator(), namedReason()]);
      if (!slot || (slot.firstElementChild && signatures.get(trip.robot_id) === signature)) continue;
      const focusKey = slot.contains(document.activeElement) ? document.activeElement.dataset.replan : null;
      slot.replaceChildren(body(trip));
      signatures.set(trip.robot_id, signature);
      if (focusKey) slot.querySelector(`[data-replan="${focusKey}"]`)?.focus({ preventScroll: true });
    }
  }

  return { render };
}
