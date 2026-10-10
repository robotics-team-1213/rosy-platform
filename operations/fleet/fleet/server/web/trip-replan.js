// D-494 5 / D-540 3 — a trip held at a place for a changed route asks the operator in its queue row:
// `바뀐 경로로 계속` (confirm-replan, a move: named operator, D-540 9) or `운행 취소` (a stop: quiet, no confirm).
// D-577 (d): the wait-cycle row opens on Fleet's resolver decision, the AI facts (shadow) and the same two
// trip routes plus the robot card. No new motion route.
import { AI_FACT_LABEL, RESOLVER_DECISION_LABEL, tripErrorText } from "/console/assets/site-map-model.js";
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

/** D-577 (d) wait-cycle row for one robot: Fleet's decision per cycle robot, the AI facts naming it. */
export function deadlockView(traffic, trip, aiFacts, robotId, { operator, named = "", busy = false }) {
  const resolver = traffic?.resolver || [];
  const lines = (traffic?.wait_cycle || []).filter((id) => !id.startsWith("signal:")).map((id) => {
    const row = resolver.find((item) => item.robot_id === id && item.trigger === "wait_cycle");
    return `${id} · 해결기 ${row ? RESOLVER_DECISION_LABEL[row.decision] || row.decision : "판단 전"}`;
  });
  const newest = new Map();  // Fleet keeps every post within its ttl: one line per kind and robots, the newest
  for (const fact of aiFacts || []) {
    const key = `${fact.kind}|${(fact.robot_ids || []).join(",")}`;
    if ((fact.robot_ids || []).includes(robotId) && !(newest.get(key)?.observed_at > fact.observed_at)) newest.set(key, fact);
  }
  const facts = [...newest.values()];
  lines.push(...(facts.length ? facts.map((fact) => `AI 참고 · ${AI_FACT_LABEL[fact.kind] || fact.kind} · `
    + `${fact.robot_ids.join(", ")} · 신뢰도 ${Math.round(fact.confidence * 100)}%`) : ["AI 사실 없음"]));
  const lock = !operator ? "운영자 권한이 필요합니다" : busy ? "답을 보내는 중" : "";
  const held = trip?.hold?.reason === "replan" && trip.hold.plan;
  return { lines, confirmReason: lock || named || (!trip ? "열린 운행이 없습니다" : held ? "" : "확인할 바뀐 경로가 없습니다"),
    cancelReason: lock || (trip ? "" : "열린 운행이 없습니다") };
}

export function createTripReplan({ scope, view, call, log, isOperator, namedReason = () => "", openCard = () => {} }) {
  const busy = new Set(), results = new Map(), signatures = new Map();  // by trip id / slot key

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

  // buttons: [node, data-replan key, disabled reason, click]
  function body(robotId, trip, lines, label, buttons) {
    const box = document.createElement("div");
    box.className = "stuck-item";
    for (const text of lines) {
      const line = document.createElement("p");
      line.className = "stuck-resolver";
      line.textContent = text;
      box.append(line);
    }
    const actions = document.createElement("div");
    actions.className = "stuck-actions";
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", `${robotId} ${label}`);
    for (const [node, key, reason, click] of buttons) {
      node.dataset.replan = key;
      setReason(node, reason);
      node.addEventListener("click", scope.guard(click));
      actions.append(node);
    }
    box.append(actions);
    const last = trip && results.get(trip.trip_id);
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

  function fill(key, signature, make) {
    const slot = document.querySelector(`[data-decision-slot="${CSS.escape(key)}"]`);
    if (!slot || (slot.firstElementChild && signatures.get(key) === signature)) return;
    const focusKey = slot.contains(document.activeElement) ? document.activeElement.dataset.replan : null;
    slot.replaceChildren(make());
    signatures.set(key, signature);
    if (focusKey) slot.querySelector(`[data-replan="${focusKey}"]`)?.focus({ preventScroll: true });
  }

  function render() {
    const operator = isOperator(), named = namedReason();
    for (const trip of view.stateUnavailable ? [] : (view.trafficTrips || []).filter((row) => row.hold)) {
      const spec = replanView(trip, { operator, named, busy: busy.has(trip.trip_id) });
      fill(`${trip.robot_id}|replan`, JSON.stringify([trip.trip_id, trip.hold, spec, results.get(trip.trip_id) || null]),
        () => body(trip.robot_id, trip, [spec.facts], "바뀐 경로 확인", [
          [primaryButton("바뀐 경로로 계속"), "confirm", spec.confirmReason, () => send(trip, "confirm-replan", "바뀐 경로로 계속합니다")],
          [quietButton("운행 취소"), "cancel", spec.cancelReason, () => send(trip, "cancel", "운행을 취소했습니다")]]));
    }
    for (const robotId of view.stateUnavailable ? [] : (view.traffic?.wait_cycle || []).filter((id) => !id.startsWith("signal:"))) {
      const trip = (view.trafficTrips || []).find((row) => row.robot_id === robotId) || null;
      const spec = deadlockView(view.traffic, trip, view.trafficAi, robotId,
        { operator, named, busy: Boolean(trip && busy.has(trip.trip_id)) });
      fill(`${robotId}|deadlock`, JSON.stringify([trip?.trip_id, spec, (trip && results.get(trip.trip_id)) || null]),
        () => body(robotId, trip, spec.lines, "교착 조치", [
          [primaryButton("바뀐 경로로 계속"), "confirm", spec.confirmReason, () => send(trip, "confirm-replan", "바뀐 경로로 계속합니다")],
          [quietButton("운행 취소"), "cancel", spec.cancelReason, () => send(trip, "cancel", "운행을 취소했습니다")],
          [quietButton("로봇 카드 열기"), "card", "", () => {
            openCard(robotId);
            document.querySelector(`article[data-robot-id="${CSS.escape(robotId)}"]`)?.scrollIntoView({ block: "nearest" });
          }]]));
    }
  }

  return { render };
}
