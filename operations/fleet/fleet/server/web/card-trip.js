// D-540 (d) — trips from the 관제 screen. The robot card's `운행…` opens a form on that card: destination
// from the active site map, `경로 보기` (a preview, nothing moves), `운행 시작`; or `반복 운행 시작` from a
// start place with the loop's capacity line. The `대형·대열` block starts a D-517 9 convoy: a follower laps
// behind a leader's open repeat trip. Every request goes through the site map's own trip path
// (shared/site-map-model.js) to the unchanged D-494 routes. Moving controls need a named operator (D-540 9).
// `운행 취소` stays on roster.js: it is a stop, open to every operator.
import {
  convoyLeaders, loopCapacityText, oneLapBody, oneLapReason, planSummaryText, planTrip, repeatTripBody,
  repeatTripReason, startTrip,
  trafficCardLine, tripRefusalText, tripStartReason,
} from "/console/assets/site-map-model.js";
import { chooseConvoyLeader } from "./motion-readiness.js";
import { endedTripText, openTrip, primaryButton, quietButton, setReason } from "./queues.js";

export { endedTripText, openTrip };

/** D-517 10 card line: lap, waits, resolver for an open trip; else why the last trip ended (D-541 7). */
export function cardTripLine(view, robotId) {
  return trafficCardLine(view.traffic, robotId) || endedTripText(view, robotId);
}

/** '' when this robot may be sent on a trip from here; otherwise the first reason that holds (D-359 §5.3). */
export function tripReason(robot, { view, operator, named }) {
  const estop = robot?.state?.safety?.estop;
  return view.stateUnavailable ? "Fleet 상태 확인 불가"
    : !operator ? "운영자 권한이 필요합니다"
      : named || (!robot ? "로봇을 고르세요"
        : !robot.online ? "로봇 오프라인"
          : estop === true ? "비상정지 중"
            : estop !== false ? "안전 상태 확인 불가"
              : view.activeSiteMap ? "" : "활성 현장 지도 없음");
}

/** What `운행 취소` stops: the open trip if there is one, else the goal; `lane` (lane driving is on) also
 * guards a failed trip cancel — OFF makes Fleet's trip guard end the trip server-side. */
export function cancelScope(trip, lineFollowMode) {
  const lane = lineFollowMode === "CAMERA_LINE" || lineFollowMode === "IR_LINE";
  if (trip) return { trip: trip.trip_id, lane, text: "진행 중인 운행을 취소합니다" };
  return { trip: null, lane, text: lane ? "목표와 차선 추종을 취소합니다" : "목표를 취소합니다" };
}

// Options change only when the list does, so a poll keeps the operator's choice.
function placeOptions(select, places, chosen, label = (place) => `${place.name} (${place.id})`) {
  const ids = places.map((place) => place.id).join(",");
  if (select.dataset.ids !== ids) {
    select.dataset.ids = ids;
    select.replaceChildren(...places.map((place) => new Option(label(place), place.id)));
  }
  if (places.some((place) => place.id === chosen)) select.value = chosen;
  return select.value;
}

function pick(label, onChange) {
  const wrap = document.createElement("label");
  const select = document.createElement("select");
  select.className = "ui-field";
  select.addEventListener("change", () => onChange(select.value));
  wrap.append(label, select);
  return { wrap, select };
}

function line(className, text) {
  const node = document.createElement("p");
  node.className = className;
  node.textContent = text;
  return node;
}

export function createCardTrip({ scope, el, view, call, log, render, isOperator, namedReason = () => "" }) {
  let form = null;  // { robotId, to, start, plan, busy, note }: one form open at a time
  const gate = (robot) => tripReason(robot, { view, operator: isOperator(), named: namedReason() });
  const places = () => view.activeSiteMap?.map?.places || [];

  // Plan then start, or start a plan already previewed; the opened trip shows before the next poll.
  async function send(robotId, holder, work, done) {
    if (holder.busy) return;
    const life = scope.capture();
    holder.busy = true;
    holder.note = null;
    render();
    try {
      const trip = await work();
      life.check();
      view.trafficTrips = [...(view.trafficTrips || []).filter((row) => row.robot_id !== robotId), trip];
      log(`${robotId} ${done}`, "good");
      if (holder === form) form = null;
    } catch (err) {
      if (err.name === "AbortError") return;
      holder.note = `운행 거절 · ${tripRefusalText(err)}`;
      log(`${robotId} ${holder.note}`, "bad");
    } finally {
      if (life.current()) { holder.busy = false; render(); }
    }
  }

  /** The card's `운행…` disclosure. */
  function toggle(robot) {
    const open = form?.robotId === robot.robot_id;
    // Like 목표 지정, a toggle: pressed while the form is open on this card.
    const button = document.createElement("ui-button");
    button.setAttribute("kind", "toggle");
    button.type = "button";
    button.textContent = "운행…";
    button.dataset.tripOpen = robot.robot_id;
    button.setAttribute("aria-pressed", String(open));
    button.setAttribute("aria-expanded", String(open));
    setReason(button, open ? "" : gate(robot));
    button.addEventListener("click", scope.guard(() => {
      form = open ? null : { robotId: robot.robot_id, to: "", start: "", lapStart: "", via: "", plan: null,
        lapPlan: null, busy: false, note: null };
      render();
    }));
    return button;
  }

  /** The open form for this card, or null. */
  function section(robot) {
    if (form?.robotId !== robot.robot_id) return null;
    const mine = form, id = robot.robot_id, active = view.activeSiteMap, running = openTrip(view, id);
    const lock = gate(robot) || (mine.busy ? "보내는 중" : "");
    const box = document.createElement("div");
    box.className = "card-trip";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", `${id} 운행`);

    // A card whose picker has focus is kept across polls (roster.place), so a new destination also
    // drops the previewed plan from the buttons on screen now.
    const to = pick("목적지", (value) => {
      mine.to = value;
      mine.plan = null;
      setReason(go, lock || "먼저 경로를 계산하세요");
      summary.textContent = "계산 전 · 실행은 하지 않습니다";
      render();
    });
    mine.to = placeOptions(to.select, places(), mine.to);
    const preview = quietButton("경로 보기");
    setReason(preview, lock || (running ? "이 로봇은 이미 운행 중입니다" : mine.to ? "" : "목적지를 고르세요"));
    preview.addEventListener("click", scope.guard(async () => {
      const life = scope.capture();
      mine.busy = true;
      mine.plan = null;
      mine.note = null;
      render();
      try {
        mine.plan = await planTrip(call, id, { to: mine.to });
        life.check();
      } catch (err) {
        if (err.name === "AbortError") return;
        mine.note = `경로 계산 거절 · ${tripRefusalText(err)}`;
      } finally {
        if (life.current()) { mine.busy = false; render(); }
      }
    }));
    const go = primaryButton("운행 시작");
    go.dataset.tripStart = id;
    setReason(go, lock || tripStartReason({ role: "operator", plan: mine.plan, active, running }));
    go.addEventListener("click", scope.guard(() => {
      const plan = mine.plan;
      if (plan) send(id, mine, () => startTrip(call, plan.plan_id), "운행을 시작했습니다");
    }));
    const once = document.createElement("div");
    once.className = "robot-actions";
    once.append(preview, go);
    const summary = line("hint", mine.plan ? `${planSummaryText(mine.plan)} · 실행하지 않음` : "계산 전 · 실행은 하지 않습니다");
    summary.setAttribute("role", "status");

    const starts = places().filter((place) => place.kind === "start");
    const start = pick("반복 출발 자리", (value) => { mine.start = value; render(); });
    mine.start = placeOptions(start.select, starts, mine.start);
    const repeat = primaryButton("반복 운행 시작");
    repeat.dataset.tripRepeat = id;
    setReason(repeat, lock || repeatTripReason({ active, running, start: mine.start }));
    repeat.addEventListener("click", scope.guard(() => send(id, mine, async () => {
      const plan = await planTrip(call, id, repeatTripBody(active?.map, mine.start, ""));
      return startTrip(call, plan.plan_id);
    }, `반복 운행을 시작했습니다 · ${mine.start}`)));
    const laps = document.createElement("div");
    laps.className = "robot-actions";
    laps.append(repeat);

    const stops = places().filter(place => place.kind === "start" || place.kind === "stop");
    const lapStart = pick("한 바퀴 출발·복귀", (value) => { mine.lapStart = value; mine.lapPlan = null; render(); });
    mine.lapStart = placeOptions(lapStart.select, stops, mine.lapStart);
    const lapVia = pick("한 바퀴 경유", (value) => { mine.via = value; mine.lapPlan = null; render(); });
    mine.via = placeOptions(lapVia.select, stops, mine.via);
    const lapReason = lock || oneLapReason({ active, running, start: mine.lapStart, via: mine.via });
    const lapPreview = quietButton("한 바퀴 경로 보기");
    setReason(lapPreview, lapReason);
    lapPreview.addEventListener("click", scope.guard(async () => {
      const life = scope.capture();
      mine.busy = true;
      mine.lapPlan = null;
      mine.note = null;
      render();
      try {
        mine.lapPlan = await planTrip(call, id, oneLapBody(active?.map, mine.lapStart, mine.via));
        life.check();
      } catch (err) {
        if (err.name === "AbortError") return;
        mine.note = `한 바퀴 계획 거절 · ${tripRefusalText(err)}`;
      } finally {
        if (life.current()) { mine.busy = false; render(); }
      }
    }));
    const lapGo = primaryButton("한 바퀴 시작");
    lapGo.dataset.tripLapOnce = id;
    setReason(lapGo, lapReason || tripStartReason({ role: "operator", plan: mine.lapPlan, active, running }));
    lapGo.addEventListener("click", scope.guard(() => {
      const plan = mine.lapPlan;
      if (plan) send(id, mine, () => startTrip(call, plan.plan_id), "한 바퀴를 시작했습니다");
    }));
    const lapActions = document.createElement("div");
    lapActions.className = "robot-actions";
    lapActions.append(lapPreview, lapGo);
    const lapSummary = line("hint", mine.lapPlan ? `${planSummaryText(mine.lapPlan)} · 실행하지 않음`
      : "출발 장소에 있는 로봇만 계획할 수 있습니다");
    lapSummary.setAttribute("role", "status");

    box.append(to.wrap, once, summary, lapStart.wrap, lapVia.wrap, lapActions, lapSummary, start.wrap, laps);
    const loops = loopCapacityText(view.traffic);  // D-517 3: "고리 2/3대"
    if (loops) box.append(line("hint", loops));
    if (mine.note) {
      const note = line("stuck-result", mine.note);
      note.dataset.kind = "bad";
      note.setAttribute("role", "alert");
      box.append(note);
    }
    return box;
  }

  // D-540 3 `대형·대열`: pick the leader (a robot on an open repeat trip), then the follower (a robot with no
  // open trip); the follower plans a repeat trip from its start place with `convoy.leader`.
  const convoy = { busy: false, note: null };
  let bound = false;
  function syncConvoy() {
    if (!bound) { bound = true; bindConvoy(); }
    const follower = el("convoy-follower"), leader = el("convoy-leader");
    const leaders = convoyLeaders(view.trafficTrips, null);
    const choice = chooseConvoyLeader(view.robots, leaders, view.guide, view.activeSiteMap?.map?.map_id);
    if (leader.dataset.leaderOverride && !leaders.includes(leader.dataset.leaderOverride)) {
      delete leader.dataset.leaderOverride;
    }
    const preferred = leader.dataset.leaderOverride || choice.id || leader.value;
    const lead = placeOptions(leader, leaders.map((id) => ({ id })), preferred, (row) => row.id);
    const free = view.robots.map((robot) => robot.robot_id).filter((id) => id !== lead && !openTrip(view, id));
    const chosen = placeOptions(follower, free.map((id) => ({ id })), follower.value, (row) => row.id);
    const starts = places().filter((place) => place.kind === "start");
    const start = placeOptions(el("convoy-start"), starts, el("convoy-start").value);
    const robot = view.robots.find((row) => row.robot_id === chosen);
    const reason = (convoy.busy ? "보내는 중" : "")
      || (leaders.length ? "" : "반복 운행 중인 리더가 없습니다 · 리더 카드의 운행…에서 반복 운행을 먼저 시작하세요")
      || (free.length ? "" : "따라갈 로봇이 없습니다 · 운행 중이 아닌 로봇이 필요합니다")
      || gate(robot)
      || repeatTripReason({ active: view.activeSiteMap, running: openTrip(view, chosen), start });
    setReason(el("convoy-go"), reason);
    el("convoy-detail").textContent = convoy.note || (reason ? "" : `팔로워 ${chosen} · 리더 ${lead} 뒤에서 반복 운행 · 출발 ${start}`);
  }

  function bindConvoy() {
    scope.listen(el("convoy-leader"), "change", () => {
      const leaders = convoyLeaders(view.trafficTrips, null);
      const choice = chooseConvoyLeader(view.robots, leaders, view.guide, view.activeSiteMap?.map?.map_id);
      const leader = el("convoy-leader");
      if (leader.value && leader.value !== choice.id) leader.dataset.leaderOverride = leader.value;
      else delete leader.dataset.leaderOverride;
      syncConvoy();
    });
    for (const id of ["convoy-follower", "convoy-start"]) scope.listen(el(id), "change", syncConvoy);
    scope.listen(el("convoy-go"), "click", () => {
      const id = el("convoy-follower").value, leader = el("convoy-leader").value, start = el("convoy-start").value;
      send(id, convoy, async () => {
        const plan = await planTrip(call, id, repeatTripBody(view.activeSiteMap?.map, start, leader));
        return startTrip(call, plan.plan_id);
      }, `대열 반복 운행을 시작했습니다 · ${leader} 뒤 · ${start}`);
    });
  }

  function focus(robotId) {
    form = {
      robotId, to: "", start: "", lapStart: "", via: "", plan: null, lapPlan: null, busy: false, note: null,
    };
  }

  return { toggle, section, syncConvoy, focus };
}
