// D-494 5 / D-540 3 — a trip held at a place for a changed route asks the operator. The answer lives in
// the queue row's slot: `바뀐 경로로 계속` (POST /trips/{id}/confirm-replan, named operator on the server)
// or `운행 취소` (a stop: quiet, no confirm, D-540 6). Fleet decides and refuses; the screen says why.
import { tripErrorText } from "/console/assets/site-map-model.js";

/** What the slot shows for one held trip: the changed route, or why there is none. */
export function replanView(trip, { operator, busy = false }) {
  const hold = trip.hold || {};
  const plan = hold.plan;
  const facts = plan
    ? [Number.isFinite(hold.length_m) ? `바뀐 경로 ${hold.length_m.toFixed(1)} m` : "바뀐 경로",
      Number.isFinite(hold.eta_s) ? `약 ${Math.round(hold.eta_s)}초` : "",
      `장소 ${(plan.places || []).length}곳`].filter(Boolean).join(" · ")
    : `다시 계산한 경로가 없습니다${hold.code ? ` (${hold.code})` : ""} · 운행을 취소하세요`;
  const lock = !operator ? "운영자 권한이 필요합니다" : busy ? "답을 보내는 중" : "";
  return { facts, confirmReason: lock || (plan ? "" : "다시 계산한 경로가 없습니다"), cancelReason: lock };
}

function button(kind, text, reason) {
  const node = document.createElement("ui-button");
  if (kind === "primary") node.setAttribute("kind", "primary");
  else node.setAttribute("kind", "quiet");
  node.type = "button";
  node.textContent = text;
  node.disabled = Boolean(reason);
  if (reason) node.setAttribute("reason", reason);
  return node;
}

export function createTripReplan({ scope, view, call, log, isOperator }) {
  const busy = new Set();     // trip ids with an answer in flight
  const results = new Map();  // trip id -> { text, kind }
  const signatures = new Map();

  async function send(trip, verb, done) {
    if (busy.has(trip.trip_id)) return;
    const life = scope.capture();
    busy.add(trip.trip_id);
    render();
    try {
      await call(`/api/fleet/trips/${encodeURIComponent(trip.trip_id)}/${verb}`, { method: "POST" });
      life.check();
      results.set(trip.trip_id, { text: `${trip.robot_id} ${done}`, kind: "good" });
      log(`${trip.robot_id} ${done}`, "good");
    } catch (err) {
      if (err.name === "AbortError") return;
      const why = err.code ? tripErrorText(err.code, err.detail) : err.message;
      results.set(trip.trip_id, { text: `${trip.robot_id} 거절 · ${why}`, kind: "bad" });
      log(`${trip.robot_id} 운행 거절 · ${why}`, "bad");
    } finally {
      if (life.current()) {
        busy.delete(trip.trip_id);
        render();
      }
    }
  }

  function body(trip) {
    const box = document.createElement("div");
    box.className = "stuck-item replan-item";
    box.dataset.tripId = trip.trip_id;
    const spec = replanView(trip, { operator: isOperator(), busy: busy.has(trip.trip_id) });
    const facts = document.createElement("p");
    facts.className = "stuck-resolver";
    facts.textContent = spec.facts;
    const actions = document.createElement("div");
    actions.className = "stuck-actions";
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", `${trip.robot_id} 바뀐 경로 확인`);
    const go = button("primary", "바뀐 경로로 계속", spec.confirmReason);
    go.dataset.replan = "confirm";
    go.addEventListener("click", scope.guard(() => send(trip, "confirm-replan", "바뀐 경로로 계속합니다")));
    const stop = button("quiet", "운행 취소", spec.cancelReason);
    stop.dataset.replan = "cancel";
    stop.addEventListener("click", scope.guard(() => send(trip, "cancel", "운행을 취소했습니다")));
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
    for (const trip of view.stateUnavailable ? [] : view.trafficTrips || []) {
      if (!trip.hold) continue;
      const slot = document.querySelector(`[data-decision-slot="${CSS.escape(`${trip.robot_id}|replan`)}"]`);
      if (!slot) continue;
      const signature = JSON.stringify([trip.trip_id, trip.hold, busy.has(trip.trip_id),
        results.get(trip.trip_id) || null, isOperator()]);
      if (slot.firstElementChild && signatures.get(trip.robot_id) === signature) continue;
      const focusKey = slot.contains(document.activeElement) ? document.activeElement.dataset.replan : null;
      slot.replaceChildren(body(trip));
      signatures.set(trip.robot_id, signature);
      if (focusKey) slot.querySelector(`[data-replan="${focusKey}"]`)?.focus({ preventScroll: true });
    }
  }

  return { render };
}
