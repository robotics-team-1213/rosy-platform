// D-494 5 / D-540 3 — a trip held at a place for a changed route asks the operator in its queue row:
// `바뀐 경로로 계속` (confirm-replan, a move: named operator, D-540 9) or `운행 취소` (a stop: quiet, no confirm).
// D-577 (d): the wait-cycle row opens on Fleet's resolver decision, the AI facts (shadow) and the same two
// trip routes plus the robot card. No new motion route.
import { OPERATOR_REASON } from "/console/assets/authorization.js";
import {AI_FACT_LABEL, RESOLVER_DECISION_LABEL, tripErrorText} from "/console/assets/trip-display.js";
import { buildDecisionBox, createDecisionSlotFiller } from "./decision-slot.js";

/** What the slot shows for one held trip: the changed route, pause/failure hold, or why there is none. */
export function replanView(trip, { operator, named = "", busy = false }) {
  const hold = trip.hold || {};
  const plan = hold.plan;
  const paused = hold.reason === "fleet_hold" || hold.reason === "nav2_problem";
  const pending = hold.stop?.confirmed === false;
  const facts = pending ? tripErrorText("TRIP_PAUSE_STOP_UNCONFIRMED") : paused
    ? (hold.reason === "fleet_hold"
      ? "Fleet 일시 정지 대기 중 · 재개 지시를 기다립니다"
      : "Nav2 주행 문제로 정지 중 · 확인 후 재개하세요")
    : plan
      ? [Number.isFinite(hold.length_m) ? `바뀐 경로 ${hold.length_m.toFixed(1)} m` : "바뀐 경로",
        Number.isFinite(hold.eta_s) ? `약 ${Math.round(hold.eta_s)}초` : "",
        `장소 ${(plan.places || []).length}곳`].filter(Boolean).join(" · ")
      : `다시 계산한 경로가 없습니다${hold.code ? ` (${hold.code})` : ""} · 운행을 취소하세요`;
  const lock = !operator ? OPERATOR_REASON : busy ? "답을 보내는 중" : "";
  return { facts, confirmReason: paused ? (lock || named || (pending ? facts : "")) : (lock || named || (plan ? "" : "다시 계산한 경로가 없습니다")), cancelReason: lock };
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
  lines.push(...(facts.length ? facts.map((fact) => `AI 참고 · ${AI_FACT_LABEL[fact.kind] || fact.kind}`
    + `${fact.kind === "wait_cycle_confirmed" && fact.value?.fleet_agrees === false ? " (Fleet 순환과 불일치)" : ""}`
    + ` · ${fact.robot_ids.join(", ")} · 신뢰도 ${Math.round(fact.confidence * 100)}%`) : ["AI 사실 없음"]));
  const lock = !operator ? OPERATOR_REASON : busy ? "답을 보내는 중" : "";
  const held = trip?.hold?.reason === "replan" && trip.hold.plan;
  return { lines, confirmReason: lock || named || (!trip ? "열린 운행이 없습니다" : held ? "" : "확인할 바뀐 경로가 없습니다"),
    cancelReason: lock || (trip ? "" : "열린 운행이 없습니다") };
}

export function createTripReplan({ scope, view, call, log, isOperator, namedReason = () => "", openCard = () => {} }) {
  const busy = new Set(), results = new Map();  // by trip id
  const fill = createDecisionSlotFiller({ focusAttr: "replan" });

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

  function render() {
    const operator = isOperator(), named = namedReason();
    for (const trip of view.stateUnavailable ? [] : (view.trafficTrips || []).filter((row) => row.hold)) {
      const spec = replanView(trip, { operator, named, busy: busy.has(trip.trip_id) });
      const paused = trip.hold?.reason === "fleet_hold" || trip.hold?.reason === "nav2_problem";
      const confirmLabel = paused ? "운행 재개" : "바뀐 경로로 계속";
      const verb = paused ? "resume" : "confirm-replan";
      const confirmDone = paused ? "운행을 재개합니다" : "바뀐 경로로 계속합니다";
      const result = results.get(trip.trip_id) || null;
      fill(`${trip.robot_id}|replan`, JSON.stringify([trip.trip_id, trip.hold, spec, result]), () => buildDecisionBox({
        scope,
        lines: [spec.facts],
        groupLabel: `${trip.robot_id} 바뀐 경로 확인`,
        buttons: [
          { label: confirmLabel, primary: true, reason: spec.confirmReason, dataset: { replan: "confirm" }, onClick: () => send(trip, verb, confirmDone) },
          { label: "운행 취소", reason: spec.cancelReason, dataset: { replan: "cancel" }, onClick: () => send(trip, "cancel", "운행을 취소했습니다") },
        ],
        result,
      }));
    }
    for (const robotId of view.stateUnavailable ? [] : (view.traffic?.wait_cycle || []).filter((id) => !id.startsWith("signal:"))) {
      const trip = (view.trafficTrips || []).find((row) => row.robot_id === robotId) || null;
      const spec = deadlockView(view.traffic, trip, view.trafficAi, robotId,
        { operator, named, busy: Boolean(trip && busy.has(trip.trip_id)) });
      const result = (trip && results.get(trip.trip_id)) || null;
      fill(`${robotId}|deadlock`, JSON.stringify([trip?.trip_id, spec, result]), () => buildDecisionBox({
        scope,
        lines: spec.lines,
        groupLabel: `${robotId} 교착 조치`,
        buttons: [
          { label: "바뀐 경로로 계속", primary: true, reason: spec.confirmReason, dataset: { replan: "confirm" }, onClick: () => send(trip, "confirm-replan", "바뀐 경로로 계속합니다") },
          { label: "운행 취소", reason: spec.cancelReason, dataset: { replan: "cancel" }, onClick: () => send(trip, "cancel", "운행을 취소했습니다") },
          { label: "로봇 카드 열기", reason: "", dataset: { replan: "card" }, onClick: () => {
            openCard(robotId);
            document.querySelector(`article[data-robot-id="${CSS.escape(robotId)}"]`)?.scrollIntoView({ block: "nearest" });
          } },
        ],
        result,
      }));
    }
  }

  return { render };
}
