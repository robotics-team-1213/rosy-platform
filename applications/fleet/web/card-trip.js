// D-540 (d) — trips from the 관제 screen. The robot card's `운행…` opens a form on that card: destination
// from the active site map, `경로 보기` (a preview, nothing moves), `운행 시작`; or `반복 운행 시작` from a
// start place with the loop's capacity line. The `대형·대열` block starts a D-517 9 convoy: a follower laps
// behind a leader's open repeat trip. Every request goes through the site map's own trip path
// (shared/site-map-model.js) to the unchanged D-494 routes. Moving controls need a named operator (D-540 9).
// `운행 취소` stays on roster.js: it is a stop, open to every operator.
import {convoyLeaders, loopCapacityText, oneLapBody, oneLapReason, planSummaryText, planTrip, repeatTripBody, repeatTripReason, startTrip, trafficCardLine, tripRefusalText, tripStartReason, tripPoseReason} from "/console/assets/site-map-model.js";
import {tripWaitText} from "/console/assets/trip-display.js";
import { POSE_REFUSALS, enqueuePoseStart } from "/console/assets/localization-view.js";
import { chooseConvoyLeader, estopText, motionCommandReason } from "./motion-readiness.js";
import { robotMapPose } from "./localization-badge.js";
import { endedTripText, openTrip, primaryButton, quietButton, setReason } from "./queues.js";
import { ruleJudgeSection } from "./site-rules-judge.js";
import {getAnnouncer} from "/common/announcer.js";

export { endedTripText, openTrip };

/** D-517 10 card line: lap, waits, resolver for an open trip; else why the last trip ended (D-541 7). */
export function cardTripLine(view, robotId) {
  return tripWaitText(openTrip(view, robotId)) || trafficCardLine(view.traffic, robotId) || endedTripText(view, robotId);
}

/** '' when this robot may be sent on a trip from here; otherwise the first reason that holds (D-359 §5.3). */
export function tripReason(robot, { view, operator, named }) {
  const estop = robot?.state?.safety?.estop;
  return view.stateUnavailable ? "Fleet 상태 확인 불가"
    : !operator ? "운영자 권한이 필요합니다"
      : named || (!robot ? "로봇을 고르세요"
        : !robot.online ? "로봇 오프라인"
          : estop === true ? estopText(robot.state)
            : estop !== false ? "안전 상태 확인 불가"
              : motionCommandReason(view, robot.robot_id, 'trip')
                || (view.activeSiteMap ? "" : "활성 현장 지도 없음"));
}

/** What `운행 취소` stops: the open trip if there is one, else the goal; `lane` (lane driving is on) also
 * guards a failed trip cancel — OFF makes Fleet's trip guard end the trip server-side. */
export function cancelScope(trip, lineFollowMode) {
  const lane = lineFollowMode === "CAMERA_LINE" || lineFollowMode === "IR_LINE";
  if (trip) return { trip: trip.trip_id, lane, text: "진행 중인 운행을 취소합니다" };
  return { trip: null, lane, text: lane ? "목표와 차선 추종을 취소합니다" : "목표를 취소합니다" };
}

// Options change only when the list does, so a poll keeps the operator's choice.
export function placeOptions(select, places, chosen, label = (place) => `${place.name} (${place.id})`) {
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

/** Pure: what the open form draws right now — roster-presentation compares this on each paint to decide a
 * redraw, so it is computed from the live form, never stored, and covers every shown value: busy, both
 * plans (id, expiry crossing, start check), the picks, the rule judge and the error notes. '' when closed. */
export function cardTripSig(form, now = Date.now() / 1000) {
  const planKey = (plan) => plan && [plan.plan_id ?? null, plan.expires_at ?? null,
    plan.start_check?.code ?? null, Boolean(plan.expires_at && now > plan.expires_at)];
  return form ? JSON.stringify([form.robotId, form.kind || "route", Boolean(form.busy),
    planKey(form.plan), planKey(form.lapPlan), form.to || "", form.start || "", form.lapStart || "",
    form.via || "", form.note || "",
    form.rule && { kind: form.rule.kind, values: form.rule.values, answer: form.rule.answer ?? null,
      note: form.rule.note ?? null, busy: Boolean(form.rule.busy), draft: Boolean(form.rule.draft) }]) : "";
}

export function createCardTrip({ scope, el, view, call, log, render, isOperator, namedReason = () => "" }) {
  let form = null;  // { robotId, kind, to, start, lapStart, via, plan, lapPlan, busy, note, rule }: one form at a time
  // D-1117 — 경로 계산 거절은 이 양식에만 보이는 실패다(log를 거치지 않는다). 낭독은 공용 방송기 한 곳이 담당한다.
  const noteAnnounce = (text) => { if (text && globalThis.document?.body) getAnnouncer().announce(text, {urgent: true}); };
  // The panel computes its redraw signature from the live form (cardTripSig), so only the reference is kept.
  function syncTripForm() { view.cardTripForm = form; }
  const gate = (robot) => tripReason(robot, { view, operator: isOperator(), named: namedReason() });
  const ready = (robot) => gate(robot) || (view.guideUnavailable ? "현장 지도 위치 확인 불가"
    : tripPoseReason(view.guide, robot?.robot_id, view.activeSiteMap, robotMapPose(robot)));
  const places = () => view.activeSiteMap?.map?.places || [];
  function checkReady(robotId) {
    const reason = ready(view.robots.find(row => row.robot_id === robotId));
    if (reason) throw new Error(reason);
  }
  function checkedStart(robotId, plan) {
    checkReady(robotId);
    const reason = tripStartReason({ role: isOperator() ? "operator" : "viewer", plan,
      active: view.activeSiteMap, running: openTrip(view, robotId) });
    if (reason) throw new Error(reason);
    return startTrip(call, plan.plan_id);
  }

  // Plan then start, or start a plan already previewed; the opened trip shows before the next poll.
  async function send(robotId, holder, work, done) {
    if (holder.busy) return;
    const life = scope.capture();
    holder.busy = true;
    holder.note = null;
    render();
    try {
      checkReady(robotId);
      const trip = await work();
      life.check();
      view.trafficTrips = [...(view.trafficTrips || []).filter((row) => row.robot_id !== robotId), trip];
      delete view.tripRefusalByRobot?.[robotId];
      log(`${robotId} ${done}`, "good");
      if (holder === form) { form = null; syncTripForm(); }
    } catch (err) {
      if (err.name === "AbortError") return;
      holder.note = `운행 거절 · ${tripRefusalText(err)}`;
      const code = err?.code || err?.detail?.code;
      view.tripRefusalByRobot ??= {};
      view.tripRefusalByRobot[robotId] = { code: code || "", text: holder.note };
      if (POSE_REFUSALS.has(code)) {
        enqueuePoseStart({ view, robotId, code, request: () => send(robotId, holder, work, done) });
      }
      log(`${robotId} ${holder.note}`, "bad", { code: code || undefined, status: err?.status });
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
      form = open ? null : { robotId: robot.robot_id, kind: "route", to: "", start: "", lapStart: "", via: "", plan: null,
        lapPlan: null, busy: false, note: null };
      syncTripForm();
      render();
    }));
    return button;
  }

  /** The open form for this card, or null. */
  function section(robot) {
    if (form?.robotId !== robot.robot_id) return null;
    const mine = form, id = robot.robot_id, active = view.activeSiteMap, running = openTrip(view, id);
    const lock = ready(robot) || (mine.busy ? "보내는 중" : "");
    const box = document.createElement("div");
    box.className = "card-trip";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", `${id} 운행`);
    const kind = pick("작업 종류", value => {
      mine.kind = value;
      syncTripForm();
      for (const panel of box.querySelectorAll(".trip-mode")) panel.hidden = panel.dataset.tripMode !== value;
    });
    kind.select.dataset.tripKind = id;
    for (const [value, name] of [["route", "목적지로 이동"], ["lap", "한 바퀴"], ["repeat", "반복 운행"]]) {
      const option = document.createElement("option"); option.value = value; option.textContent = name;
      kind.select.append(option);
    }
    kind.select.value = mine.kind || "route";
    setReason(kind.select, mine.busy ? "요청 처리 중" : "");
    if (mine.busy) {
      const reason = line("hint", "요청 처리 중 · 완료 후 작업 종류를 바꿀 수 있습니다");
      reason.id = `${id}-trip-kind-reason`;
      kind.select.setAttribute("aria-describedby", reason.id);
      kind.wrap.append(reason);
    }

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
        checkReady(id);
        const to = mine.to;
        const plan = await planTrip(call, id, { to });
        life.check();
        if (form === mine && mine.to === to) mine.plan = plan;
      } catch (err) {
        if (err.name === "AbortError") return;
        mine.note = `경로 계산 거절 · ${tripRefusalText(err)}`;
        noteAnnounce(mine.note);
      } finally {
        if (life.current()) { mine.busy = false; render(); }
      }
    }));
    const go = primaryButton("운행 시작");
    go.dataset.tripStart = id;
    setReason(go, lock || tripStartReason({ role: "operator", plan: mine.plan, active, running }));
    go.addEventListener("click", scope.guard(() => {
      const plan = mine.plan;
      if (plan) send(id, mine, () => checkedStart(id, plan), "운행을 시작했습니다");
    }));
    const once = document.createElement("div");
    once.className = "robot-actions";
    once.append(preview, go);
    const summary = line("hint", mine.plan ? `${planSummaryText(mine.plan)} · 실행하지 않음` : "계산 전 · 실행은 하지 않습니다");

    const starts = places().filter((place) => place.kind === "start");
    const start = pick("반복 출발 자리", (value) => { mine.start = value; render(); });
    mine.start = placeOptions(start.select, starts, mine.start);
    const repeat = primaryButton("반복 운행 시작");
    repeat.dataset.tripRepeat = id;
    setReason(repeat, lock || repeatTripReason({ active, running, start: mine.start }));
    repeat.addEventListener("click", scope.guard(() => send(id, mine, async () => {
      const plan = await planTrip(call, id, repeatTripBody(active?.map, mine.start, ""));
      return checkedStart(id, plan);
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
        checkReady(id);
        const start = mine.lapStart, via = mine.via;
        const plan = await planTrip(call, id, oneLapBody(active?.map, start, via));
        life.check();
        if (form === mine && mine.lapStart === start && mine.via === via) mine.lapPlan = plan;
      } catch (err) {
        if (err.name === "AbortError") return;
        mine.note = `한 바퀴 계획 거절 · ${tripRefusalText(err)}`;
        noteAnnounce(mine.note);
      } finally {
        if (life.current()) { mine.busy = false; render(); }
      }
    }));
    const lapGo = primaryButton("한 바퀴 시작");
    lapGo.dataset.tripLapOnce = id;
    setReason(lapGo, lapReason || tripStartReason({ role: "operator", plan: mine.lapPlan, active, running }));
    lapGo.addEventListener("click", scope.guard(() => {
      const plan = mine.lapPlan;
      if (plan) send(id, mine, () => checkedStart(id, plan), "한 바퀴를 시작했습니다");
    }));
    const lapActions = document.createElement("div");
    lapActions.className = "robot-actions";
    lapActions.append(lapPreview, lapGo);
    const lapSummary = line("hint", mine.lapPlan ? `${planSummaryText(mine.lapPlan)} · 실행하지 않음`
      : "출발 장소에 있는 로봇만 계획할 수 있습니다");

    box.append(kind.wrap);
    for (const [mode, children] of [["route", [to.wrap, once, summary]],
      ["lap", [lapStart.wrap, lapVia.wrap, lapActions, lapSummary]], ["repeat", [start.wrap, laps]]]) {
      const panel = document.createElement("div");
      panel.className = "trip-mode"; panel.dataset.tripMode = mode;
      panel.hidden = mode !== (mine.kind || "route"); panel.append(...children); box.append(panel);
    }
    box.append(ruleJudgeSection({ mine, robot, call, scope, render }));  // D-982: what the site rules say, not sent
    const loops = loopCapacityText(view.traffic);  // D-517 3: "고리 2/3대"
    if (loops) box.append(line("hint", loops));
    if (mine.note) {
      // D-1117 — 거절 문구는 양식 안 글자다. 낭독은 noteAnnounce가 이미 한 번 했다.
      const note = line("stuck-result", mine.note);
      note.dataset.kind = "bad";
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
    const choice = chooseConvoyLeader(view.robots, leaders, view.guide, view.activeSiteMap?.version);
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
      || ready(robot)
      || repeatTripReason({ active: view.activeSiteMap, running: openTrip(view, chosen), start });
    setReason(el("convoy-go"), reason);
    el("convoy-detail").textContent = convoy.note || (reason ? "" : `팔로워 ${chosen} · 리더 ${lead} 뒤에서 반복 운행 · 출발 ${start}`);
  }

  function bindConvoy() {
    scope.listen(el("convoy-leader"), "change", () => {
      const leaders = convoyLeaders(view.trafficTrips, null);
      const choice = chooseConvoyLeader(view.robots, leaders, view.guide, view.activeSiteMap?.version);
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
        return checkedStart(id, plan);
      }, `대열 반복 운행을 시작했습니다 · ${leader} 뒤 · ${start}`);
    });
  }

  function focus(robotId) {
    form = {
      robotId, kind: "route", to: "", start: "", lapStart: "", via: "", plan: null, lapPlan: null, busy: false, note: null,
    };
    syncTripForm();
  }

  return { toggle, section, syncConvoy, focus, close: () => { form = null; syncTripForm(); } };
}

// D-763 6·9 — 새 작업의 이동은 로봇 카드의 운행 폼(card-trip.js) 그 자체다: 같은 계획·시작 요청, 같은 거절.
// 이동이 종류 목록에 서는지는 서버의 종류 목록이 정한다(work-view.js showKinds, D-763 9). 꺼진 단추로 보이지 않는다.
export function createMovePanel({ scope, el, view, getRoster, render }) {
  scope.listen(el("work-new-move"), "click", ({currentTarget: button}) => {
    for (const name of ["aria-pressed", "aria-expanded"]) button.setAttribute(name, String(button.getAttribute(name) !== "true"));
    render();
  });
  scope.listen(el("work-move-robot"), "change", () => render());
  return function paintMove() {
    const pick = el("work-move-robot"), box = el("work-move-form");
    el("work-move").hidden = el("work-new-move-item").hidden || el("work-new-move").getAttribute("aria-pressed") !== "true";
    // 오프라인 로봇도 이유와 함께 올라야 한다 — 선택은 읽기이고, 시작 단추가 잠긴 이유를 보여준다.
    const id = placeOptions(pick, view.robots.map(row => ({id: row.robot_id})), pick.value, row => view.robotNames?.[row.id] || row.id);
    const robot = view.stateUnavailable ? null : view.robots.find(row => row.robot_id === id);  // as roster.js
    el("work-move-state").textContent = robot ? cardTripLine(view, id) : "";
    if (!el("work-move").hidden) getRoster().paintTrip(box, id);
  };
}
