// 명렬 카드 (Fleet 분해 3). 로봇 한 대의 상태·증거·조작을 그린다. 주의/개입 큐는 queues.js가
// 가지고, 이 팩토리가 그 규칙(attentionItems)을 카드 펼침에 같이 쓴다. formation/signals 팩토리와 같은 모양이다.

// D-359 §5.2 — 카드의 짧은 값은 공용 <ui-tag>다. 주행(nav)·도착(ok)은 색이 아니라
// ink인 active, 나머지는 태그의 warn/crit 어휘 그대로다.
import { DOCK_STATE_LABEL, POWER_MODE_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL,
  enumLabel, operatorModeLabel, EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { actionIcon } from "/common/ui.js";
import { createPowerButton } from "/console/assets/power-action.js";
import { createRobotAppActions } from "/console/assets/device-discovery.js";
import { addressReason } from "/console/assets/address-drift.js";
import { linkTag, ruleMTag } from "./link-tag.js";
import { positionTag, robotPoseText, sitePoseText } from "./localization-badge.js";
import { capabilityReason, motionCommandReason } from "./motion-readiness.js";
import { staleAgeS } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { createQueues } from "./queues.js";
import { createFleetMotorHealth } from "./motor-health-view.js";
import { placeRosterCards as place } from "./roster-cards.js";
import { cancelScope, cardTripLine, createCardTrip, openTrip } from "./card-trip.js";
import { createRosterSummary, nodeWithText, tag, blockWith, navTag, queuedReason, REACH_LABEL,
  IDENTIFY_REASON, LAMP_REASON } from "./roster-presentation.js";

/** D-651: all four safety exceptions remain visible in the compact list, ahead of nominal robots. */
export function mustExpand(robot) {
  const estop = robot.state?.safety?.estop;
  return !robot.online || !robot.state || estop !== false || Boolean(robot.calibration);
}

/** Inspection is UI-only. Switching robots withdraws every pending map interaction. */
export function selectRobot(view, robotId) {
  if (robotId && !view.robots.some(robot => robot.robot_id === robotId)) return false;
  if (view.focusRobot === robotId) return false;
  view.focusRobot = robotId || null;
  view.selected = null;
  view.pinning = null;
  view.cursor = null;
  return true;
}

export function createRoster({ scope, el, view, log, call, render, streamEvidence, isOperator, namedReason = () => "",
  moveAddress = null, moveAddressBlocked = () => "", confirmedAction, onSelectionChanged = () => {} }) {
  const { attentionItems, fillQueues } = createQueues({ scope, el, view, render, streamEvidence });
  const trip = createCardTrip({ scope, el, view, call, log, render, isOperator, namedReason });
  const motorHealth = createFleetMotorHealth({view, scope});
  const summary = createRosterSummary({scope, view, openCard, render, attentionItems, motorHealth});
  function openCard(robotId) {
    if (selectRobot(view, robotId)) {
      confirmedAction?.cancel();
      trip.close();
      onSelectionChanged();
      const canvas = el("map-canvas");
      canvas.classList.add("idle");
      canvas.tabIndex = -1;
    }
  }
  function needsAttention(robot) {
    return view.stateUnavailable || mustExpand(robot) || attentionItems(robot).length > 0;
  }

  function workspace() {
    const box = el("robot-workspace"), choice = el("robot-choice"), empty = el("robot-workspace-empty");
    if (!box) return;
    if (view.focusRobot && !view.robots.some(robot => robot.robot_id === view.focusRobot)) openCard(null);
    if (choice) {
      const options = view.robots.map(robot => [robot.robot_id, view.robotNames?.[robot.robot_id] || robot.robot_id]);
      const key = JSON.stringify(options);
      if (choice.dataset.options !== key) {
        const first = nodeWithText("option", "", "로봇을 선택하세요"); first.value = "";
        choice.replaceChildren(first, ...options.map(([id, name]) => { const option = nodeWithText("option", "", name); option.value = id; return option; }));
        choice.dataset.options = key;
      }
      choice.value = view.focusRobot || "";
    }
    const index = view.robots.findIndex(robot => robot.robot_id === view.focusRobot);
    if (empty) empty.hidden = index >= 0;
    place(box, index >= 0 ? [card(view.robots[index], index)] : []);
  }

  function card(robot, index) {
    const node = document.createElement("article");
    const displayName = view.robotNames?.[robot.robot_id] || robot.robot_id;
    // D-82 로봇 사다리 — 지도 삼각형과 같은 색 순서(view.robots 인덱스)로 카드의
    // 정체 띠가 돈다. CSS 의 .s0/.s1/.s2 가 --robot-1..3 을 붙인다. 표시 순서가
    // 예외 우선으로 바뀌어도 색은 로봇에 붙어 있다.
    node.className = `robot robot-workspace-card s${index % view.colors.length}`;
    node.dataset.robotId = robot.robot_id;
    // A late answer (link "degraded", server grace) is not shown as offline; decisions still see online=false.
    const lagging = !robot.online && robot.link === "degraded";
    if (!view.stateUnavailable && !robot.online && !lagging) node.classList.add("offline");
    if (view.selected === robot.robot_id) node.classList.add("selected");
    // D-224 — ↑/↓ 순회의 착지점. tabindex -1 은 프로그램 포커스만 허용한다
    // (탭 순서를 더럽히지 않는다).
    node.tabIndex = -1;

    const state = view.stateUnavailable ? {} : (robot.state || {});
    const pose = state.pose;
    const power = powerHealthView(robot, view.receivedAtMs, Date.now());
    const nav = navTag(state);
    const tripLine = view.stateUnavailable ? "" : cardTripLine(view, robot.robot_id);
    const estop = state.safety?.estop;
    const stateStale = staleAgeS(robot, view.receivedAtMs, Date.now()) !== null;
    const safetyLabel = !robot.online ? "—" : view.stateUnavailable || stateStale ? EVIDENCE_LABEL.unavailable : estop === true ? "비상 정지"
      : estop === false ? "정상" : EVIDENCE_LABEL.unavailable;
    const goalSafetyReason = view.stateUnavailable
      ? "Fleet 상태를 확인할 수 없어 목표를 보낼 수 없습니다."
      : estop === true
      ? "비상정지가 활성화되어 목표를 보낼 수 없습니다."
      : estop !== false && robot.online
        ? "안전 상태를 확인할 수 없어 목표를 보낼 수 없습니다." : "";

    const head = nodeWithText("div", "robot-head");
    const robotName = document.createElement("b");
    robotName.textContent = displayName;
    const spacer = nodeWithText("span", "spacer");
    head.append(robotName);
    if (displayName !== robot.robot_id) head.append(nodeWithText("small", "hint", `Fleet ID ${robot.robot_id}`));
    head.append(spacer);
    // D-540 6: mode words from the shared table (enum in title); lane following, when on, is the mode shown.
    const lane = state.line_follow || {};
    const laneOn = lane.mode === "CAMERA_LINE" || lane.mode === "IR_LINE";
    const modeTag = tag(
      view.stateUnavailable ? "상태 확인 불가" : !robot.online ? "오프라인"
        : laneOn ? `${enumLabel(LINE_FOLLOW_MODE_LABEL, lane.mode)} · ${enumLabel(LINE_STATE_LABEL, lane.state)}`
          : operatorModeLabel(state.mode),
      view.stateUnavailable || !robot.online ? "crit" : laneOn && lane.state === "LOST" ? "warn" : "");
    if (!view.stateUnavailable && robot.online && state.mode) {
      modeTag.title = laneOn ? `${state.mode} · ${lane.mode} ${lane.state || ""}`.trim() : state.mode;
    } else if (!view.stateUnavailable && !robot.online) modeTag.title = "OFFLINE";
    if (laneOn) modeTag.dataset.lineFollow = lane.mode;
    head.appendChild(modeTag);
    if (!view.stateUnavailable && robot.online) {
      const powerMode = state.power?.mode;
      if (powerMode) {
        // D-440: after a wake the wheels stay at zero until the LiDAR confirms (motion_ready false).
        const waking = state.power.motion_ready === false && powerMode === "ACTIVE";
        const powerTag = tag(enumLabel(POWER_MODE_LABEL, powerMode) + (waking ? " · 준비 중" : ""), "");
        powerTag.title = String(powerMode);
        powerTag.dataset.power = String(powerMode);
        head.appendChild(powerTag);
      }
      const dock = state.docking?.state;
      if (dock) {
        const dockTag = tag(enumLabel(DOCK_STATE_LABEL, dock), dock === "DOCK_FAILED" ? "crit" : "");
        dockTag.title = String(dock);
        dockTag.dataset.dock = String(dock);
        head.appendChild(dockTag);
      }
      const chargeTag = tag(power.charging === "확인 불가" ? "충전 확인 불가" : power.charging, "");
      chargeTag.dataset.charging = power.charging;
      const chargeState = robot.power_health?.battery?.charging_state;
      if (typeof chargeState === "string") chargeTag.title = chargeState;
      head.appendChild(chargeTag);
    }
    const link = view.stateUnavailable ? null : linkTag(robot.link);
    // D-535: the server's reason (code, message, action) for a failed robot read.
    const reason = view.stateUnavailable ? null : robot.link_reason;
    if (link || reason) {
      const linkNode = tag(link ? link.word : reason.message, link ? link.kind : "warn");
      if (link) linkNode.dataset.link = robot.link;
      if (reason) {
        linkNode.dataset.reason = reason.code;
        linkNode.title = `${reason.message} ${reason.action}`;
      }
      head.appendChild(linkNode);
    }
    const unbounded = view.stateUnavailable ? null : ruleMTag(robot.rule_m);
    if (unbounded) {
      const boundNode = tag(unbounded.word, unbounded.kind);
      boundNode.title = unbounded.text;
      head.appendChild(boundNode);
    }
    const blocked = !view.stateUnavailable && robot.queued && robot.queued.reason === "NO_YIELD_SPACE";
    // 비켜서는 중인 로봇은 "주행 중"이 맞다 — 다만 제 미션을 가는 것이 아니라서 따로 적는다.
    head.appendChild(tag(
      view.stateUnavailable ? "—" : robot.yielding ? "비켜서는 중" : robot.queued ? "출발 대기" : nav.text,
      blocked ? "crit" : robot.queued ? "warn" : nav.cls));
    const formation = view.stateUnavailable ? null : view.formation;
    const role = formation?.active ? (formation.leader === robot.robot_id ? "대형 리더"
      : Object.hasOwn(formation.assignment || {}, robot.robot_id) ? "대형 팔로워" : "") : "";
    if (role) {
      const roleTag = tag(role, "nav");
      roleTag.dataset.formationRole = role === "대형 리더" ? "leader" : "follower";
      head.appendChild(roleTag);
    }
    const evidence = view.stateUnavailable ? null : streamEvidence(view.formation, robot.robot_id);
    if (evidence) {
      // 릴레이 건강은 증거다(D-72). fresh 는 아무것도 붙지 않는다 — 붙는 것은 문제뿐이다.
      const relay = tag(evidence.text, evidence.cls);
      relay.dataset.evidence = evidence.evidence;
      head.appendChild(relay);
    }
    const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === robot.robot_id);
    const loc = view.stateUnavailable ? null : positionTag(robot.localization, guideRow);
    if (loc) {
      // 위치 칩 하나: Fleet 지도 위치가 먼저, CORE 위치 상태는 보고할 때만(D-395). 열거값은 title에만.
      const locTag = tag(loc.text, loc.cls);
      locTag.title = loc.title;
      locTag.dataset.localization = "";
      head.appendChild(locTag);
    }
    node.appendChild(head);
    const context = createRobotAppActions(robot.robot_id, view.robotPeers, nodeWithText);
    const group = nodeWithText('ui-button', '', '대형·대열 관리');
    group.setAttribute('kind', 'quiet'); group.type = 'button'; group.dataset.openFormation = '';
    group.addEventListener('click', scope.guard(() => view.openFormationWorkspace?.()));
    context.append(group); node.appendChild(context);
    if (role) node.appendChild(nodeWithText('p', 'hint',
      `목적지는 리더 ${formation.leader}에게 배정합니다 · 팔로워 ${Object.keys(formation.assignment || {}).filter(id => id !== formation.leader).join(', ') || '없음'}`));
    // D-517 10: 운행 상태 한 줄("반복 운행 3바퀴째", "앞 블록 대기 · rosy_02"), 끝난 운행은 그 이유(D-541 7).
    if (tripLine) {
      const line = nodeWithText("p", "trip-line", tripLine);
      line.dataset.fact = "trip";
      node.appendChild(line);
    }

    const facts = nodeWithText("div", "facts");
    const battery = power.battery.endsWith("%") && typeof power.voltage === "number"
      ? `${power.battery} · ${power.voltage.toFixed(2)} V` : power.battery;
    const rows = [
      ["pose", "위치", robotPoseText(state, robot.localization)],
      ["yaw", "방향", pose ? `${(pose.yaw * 180 / Math.PI).toFixed(0)}°` : "—"],
      ["battery", "배터리", battery],
      ["safety", "안전", safetyLabel],
    ];
    rows.forEach(([key, label, value]) => {
      const cellEl = document.createElement("div");
      // D-409 — 컴팩트에서 위치·방향은 지도가 말한다. 칸에 이름을 달아 표면이 접는다.
      cellEl.dataset.fact = key;
      const labelEl = document.createElement("span");
      // D-405 — 라벨의 얼굴은 actionIcon, 한국어 이름은 스크린리더와 title에 남는다.
      labelEl.title = label;
      const srLabel = nodeWithText("span", "sr-only", label);
      labelEl.appendChild(srLabel);
      actionIcon(labelEl, key);
      let valueEl;
      if (label === "안전" && value === "비상 정지") {
        // D-202 — 위험은 채움이다. 정지 사실은 카드의 다른 측정값과 같은
        // 무게로 읽히면 안 된다. 공용 어휘인 crit 태그를 재사용한다.
        valueEl = tag(value, "crit");
      } else {
        valueEl = document.createElement("strong");
        valueEl.textContent = value;
        if (key === "battery" && typeof power.observedAgeS === "number")
          valueEl.title = `${power.observedAgeS}초 전`;
      }
      cellEl.append(labelEl, valueEl);
      const sitePose = key === "pose" && !view.stateUnavailable
        ? sitePoseText((view.guide?.robots || []).find((row) => row.robot_id === robot.robot_id)) : null;
      if (sitePose) cellEl.append(nodeWithText("small", "fact-detail", sitePose));
      facts.appendChild(cellEl);
    });
    node.appendChild(facts);
    node.appendChild(motorHealth.detail(robot));

    if (!view.stateUnavailable) {
      if (power.safetyRelease) node.appendChild(nodeWithText("p", "hint", power.safetyRelease));
      const diagnostics = Object.entries(stateStale ? {} : state.diagnostics_summary || {})
        .filter(([, status]) => status === "WARNING" || status === "ERROR" || status === "UNKNOWN")
        .map(([name, status]) => `${name}: ${status}`);
      if (diagnostics.length) node.appendChild(nodeWithText("p", "hint",
        `진단: ${diagnostics.join(" · ")} — 로봇 진단 확인`));
    }

    if (!view.stateUnavailable && robot.yielding) {
      // 운영자가 보내지 않은 좌표로 로봇이 움직인다. 이유를 적지 않으면 오작동으로 읽힌다.
      const why = nodeWithText("p", "hint");
      why.textContent = `${robot.yielding.for} 가 지나가도록 비켜서는 중 — `
        + `(${robot.yielding.bay.x.toFixed(2)}, ${robot.yielding.bay.y.toFixed(2)}) 로 물러납니다`;
      node.appendChild(why);
    }

    if (!view.stateUnavailable && robot.queued) {
      // 왜 안 가는지 화면이 말하지 않으면 운영자는 미션이 사라졌다고 읽는다.
      const why = nodeWithText("p", "hint", queuedReason(robot.queued));
      node.appendChild(why);
    }

    // 한 원인은 한 번 말한다(D-359 §5.3) — 카드 상태 줄이 원인을 이미 말하면
    // 버튼 사유는 "위 사유"로 이 줄을 가리킨다.
    const offlineWhyId = !view.stateUnavailable && !robot.online && robot.error && !link
      ? `robot-why-${robot.robot_id}` : null;
    if (!view.stateUnavailable && !robot.online && robot.error && !link) {
      const why = nodeWithText("p", "hint");
      why.textContent = robot.error.reachable
        ? `로봇이 거절: ${robot.error.code}`
        : `닿지 않음: ${REACH_LABEL[robot.error.code] ?? robot.error.code}`;
      why.id = offlineWhyId;
      node.appendChild(why);
    }

    // 점검 2026-10-01 — 사이트 망이 바뀌면 오프라인만으로는 까닭을 모른다. 고정 주소가
    // 지금 망에 있는지는 서버가 판정하고(GET /api/fleet/discovery/addresses), 여기는 옮겨 적는다.
    const address = !view.stateUnavailable && !robot.online
      ? addressReason(view.addresses?.[robot.robot_id]) : null;
    if (address) {
      const why = nodeWithText("p", "hint");
      why.dataset.addressReason = view.addresses[robot.robot_id].status;
      why.textContent = address.text;
      node.appendChild(why);
    }

    if (link?.text) node.appendChild(nodeWithText("p", "hint", link.text));
    if (link?.next) {
      if (link.focus === "console-token") {
        const next = document.createElement("ui-button");
        next.setAttribute("kind", "quiet");
        next.dataset.authFocus = "";
        next.type = "button";
        next.textContent = link.next;
        next.addEventListener("click", scope.guard(() => {
          const token = document.getElementById("console-token");
          const access = document.getElementById("token-access");
          if (access) { access.hidden = false; access.open = true; }
          const more = document.getElementById("topbar-more");
          if (more?.getAttribute("aria-expanded") === "false") more.click();
          token?.focus();
        }));
        node.appendChild(next);
      } else {
        node.appendChild(nodeWithText("p", "hint", link.next));
      }
    }

    // D-416 — 오프라인 로봇의 마지막 응답 시각: "언제부터 안 됐지?"에 바로 답한다.
    if (!view.stateUnavailable && !robot.online) {
      const seen = nodeWithText("p", "hint");
      seen.dataset.fact = "last-seen";
      const ts = robot.state?.ts;
      if (typeof ts === "number" && ts > 0) {
        const age = Math.max(0, Math.floor((Date.now() / 1000) - ts));
        seen.textContent = age < 60 ? `마지막 응답: ${age}초 전`
          : age < 3600 ? `마지막 응답: ${Math.floor(age / 60)}분 전`
          : `마지막 응답: ${Math.floor(age / 3600)}시간 전`;
      } else {
        seen.textContent = "응답 없음";
      }
      node.appendChild(seen);
    }

    const actions = nodeWithText("div", "robot-actions");
    const aim = document.createElement("ui-button");
    // D-406 — 목표 받기는 토글이다. 눌림(aria-pressed)이 계열 파랑 채움으로 보여
    // "지금 지도를 찍으면 이 로봇이 움직인다"가 색으로 말해진다.
    aim.setAttribute("kind", "toggle");
    aim.type = "button";
    aim.dataset.goalRobotId = robot.robot_id;
    aim.textContent = view.selected === robot.robot_id ? "지도를 찍으세요" : "목표 지정";
    aim.setAttribute("aria-pressed", view.selected === robot.robot_id ? "true" : "false");
    const currentLineFollow = state.line_follow || {};
    const lineFollowActive = currentLineFollow.mode === "CAMERA_LINE" || currentLineFollow.mode === "IR_LINE";
    // D-359 §5.3 — 사유는 비활성과 같은 조건에서 첫 번째로 걸린 것을 말한다.
    blockWith(aim, namedReason() || (view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online ? (offlineWhyId ? "위 사유" : "로봇 오프라인")
        : motionCommandReason(view, robot.robot_id, 'goal')
          || capabilityReason(robot.capabilities, "navigation.goal_navigation")
          || (!view.map ? "지도 없음"
          : estop === true ? "비상정지 중"
            : estop !== false ? "안전 상태 확인 불가"
              : lineFollowActive ? "차선 추종 중" : "")));
    if (offlineWhyId) aim.setAttribute("aria-describedby", offlineWhyId);
    aim.addEventListener("click", scope.guard(() => {
      view.selected = view.selected === robot.robot_id ? null : robot.robot_id;
      view.cursor = view.selected && view.map
        ? { col: Math.floor(view.map.width / 2), row: Math.floor(view.map.height / 2) }
        : null;
      const canvas = el("map-canvas");
      // D-493: a goal pick needs the map, so the large camera view yields.
      if (view.selected) { el("map-stage").dataset.view = "map"; el("birdseye-toggle").setAttribute("aria-pressed", "false"); }
      canvas.classList.toggle("idle", view.selected === null);
      canvas.tabIndex = view.selected ? 0 : -1;
      render();
      if (view.selected) canvas.focus({preventScroll: true});
      else [...document.querySelectorAll("#robot-workspace ui-button[data-goal-robot-id]")]
        .find(button => button.dataset.goalRobotId === robot.robot_id)?.focus({preventScroll: true});
    }));
    // D-593 운영자 핀: 지도에서 이 로봇의 위치(누른 점)와 방향(끈 방향)을 찍어 Fleet 지도 자세의 앵커로 둔다.
    // 로봇에 아무것도 보내지 않는다. 이름 있는 운영자만, 운행 중이 아닐 때만.
    const pin = document.createElement("ui-button");
    pin.setAttribute("kind", "toggle");
    pin.type = "button";
    pin.dataset.pinRobotId = robot.robot_id;
    pin.textContent = view.pinning === robot.robot_id ? "위치를 찍고 방향으로 끄세요" : "위치 찍기";
    pin.setAttribute("aria-pressed", view.pinning === robot.robot_id ? "true" : "false");
    blockWith(pin, namedReason() || (view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online ? (offlineWhyId ? "위 사유" : "로봇 오프라인")
        : !view.map && !view.siteMap ? "지도 없음" : openTrip(view, robot.robot_id) ? "운행 중" : ""));
    pin.addEventListener("click", scope.guard(() => {
      view.pinning = view.pinning === robot.robot_id ? null : robot.robot_id;
      if (view.pinning) {
        view.selected = null; view.cursor = null;
        el("map-stage").dataset.view = "map"; el("birdseye-toggle").setAttribute("aria-pressed", "false");
      }
      el("map-canvas").classList.toggle("idle", !view.pinning);
      render();
    }));
    // D-540 1/3: 이 로봇 정지 = 운행 취소 한 자리. 열린 trip이면 trip을, 없으면 목표(와 켜진 차선 주행)를
    // 멈춘다. 멈춤이라 quiet·확인 없음이고 이름 없는 운영자에게도 열려 있다(D-540 9). Fleet의 trip은
    // 로봇이 오프라인이어도 취소할 수 있다.
    const shown = cancelScope(openTrip(view, robot.robot_id), state.line_follow?.mode);
    const cancel = document.createElement("ui-button");
    cancel.setAttribute("kind", "quiet");
    cancel.type = "button";
    cancel.textContent = "운행 취소";
    cancel.title = shown.text;
    cancel.dataset.cancelScope = shown.trip ? "trip" : shown.lane ? "goal-lane" : "goal";
    blockWith(cancel, view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online && !shown.trip ? (offlineWhyId ? "위 사유" : "로봇 오프라인") : "");
    if (offlineWhyId) cancel.setAttribute("aria-describedby", offlineWhyId);
    cancel.addEventListener("click", scope.guard(async () => {
      const life = scope.capture();
      life.check();
      // Decide at click time: a card kept across polls (roster.place) may predate the trip.
      const now = view.robots.find((row) => row.robot_id === robot.robot_id) || robot;
      const stop = cancelScope(openTrip(view, robot.robot_id), now.state?.line_follow?.mode);
      try {
        if (stop.trip) {
          try {
            await call(`/api/fleet/trips/${encodeURIComponent(stop.trip)}/cancel`, { method: "POST" });
            life.check();
            view.trafficTrips = (view.trafficTrips || []).filter((row) => row.trip_id !== stop.trip);
            render();
            log(`${robot.robot_id} 운행 취소`, "good");
            return;
          } catch (err) {  // the trip may have just ended: the goal cancel below still stops the robot
            if (err.name === "AbortError") return;
            log(`${robot.robot_id} 운행 취소 실패 — ${err.message} · 목표 취소를 보냅니다`, "bad");
          }
        }
        const pending = view.pendingTasks[robot.robot_id];
        if (pending) {
          const readback = await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}`);
          life.check();
          if (readback.task?.status === "QUEUED") {
            await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}/cancel`, { method: "POST" });
            life.check();
            delete view.pendingTasks[robot.robot_id];
            render();
            log(`${robot.robot_id} task ${pending.task_id} QUEUED 취소`, "good");
            return;
          }
          delete view.pendingTasks[robot.robot_id];
        }
        await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/cancel`, { method: "POST" });
        life.check();
        if (stop.lane) {
          await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/line-follow`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "OFF" }) });
          life.check();
        }
        log(`${robot.robot_id} ${stop.lane ? "목표·차선 추종 취소" : "항법 취소"}`, "good");
      } catch (err) {
        if (err.name === "AbortError") return;
        log(`${robot.robot_id} 취소 실패 — ${err.message}`, "bad");
      }
    }));
    const lineFollow = state.line_follow || {};
    const cameraFaultLatched = lineFollow.mode === "CAMERA_LINE"
      && lineFollow.state === "LOST"
      && lineFollow.reason === "camera_reselection_required";
    if (cameraFaultLatched || lineFollow.mode === "IR_LINE") {
      const fallback = document.createElement("ui-button");
      fallback.setAttribute("kind", "quiet");
      fallback.type = "button";
      fallback.textContent = lineFollow.mode === "IR_LINE" ? "IR 차선 추종 끄기" : "IR 차선 추종으로 전환…";
      blockWith(fallback, view.stateUnavailable ? "Fleet 상태 확인 불가"
        : !robot.online ? "로봇 오프라인"
          : !isOperator() ? "운영자 권한이 필요합니다"
            // D-540 9: IR 추적 선택은 움직임, 중지(OFF)는 멈춤이다.
            : lineFollow.mode !== "IR_LINE" ? namedReason() : "");
      fallback.addEventListener("click", scope.guard(async () => {
        const life = scope.capture();
        life.check();
        const mode = lineFollow.mode === "IR_LINE" ? "OFF" : "IR_LINE";
        const kind = `IR:${robot.robot_id}`;
        const send = async owner => {
          const result = await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/line-follow`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode }), signals: [owner.signal],
          });
          owner.check();
          const now = result.result?.state;
          log(`${robot.robot_id} ${mode === "IR_LINE" ? "IR 차선 추종 요청" : "IR 차선 추종 끔"} · ${now ? enumLabel(LINE_STATE_LABEL, now) : "CORE 응답 확인"}`, "good");
        };
        const fail = err => log(`${robot.robot_id} IR 차선 추종 거절 · ${err.message}`, "bad");
        if (mode === "OFF") {
          confirmedAction.cancel(kind);
          try { await send(life); } catch (err) { if (life.current() && err.name !== "AbortError") fail(err); }
          return;
        }
        await confirmedAction.run({kind, message: `${robot.robot_id}의 카메라 고장이 확인되었습니다. CORE 안전 조건을 다시 확인하고 IR 차선 추종을 요청할까요?`, opener: fallback,
          eligible: () => !view.stateUnavailable && isOperator() && view.robots.some(current => current.robot_id === robot.robot_id && current.online
            && current.state?.line_follow?.mode === "CAMERA_LINE" && current.state.line_follow.state === "LOST" && current.state.line_follow.reason === "camera_reselection_required"),
          request: send, onError: fail});
      }));
      actions.append(fallback);
    }
    const identify = document.createElement("ui-button");
    identify.setAttribute("kind", "quiet");
    identify.type = "button";
    identify.textContent = "LED로 찾기";
    blockWith(identify, !isOperator() ? "운영자 권한이 필요합니다"
      : namedReason() ? namedReason()
      : !robot.online || view.stateUnavailable ? "로봇 연결을 확인하세요"
        : estop !== false ? "안전 상태 확인이 필요합니다" : "");
    identify.addEventListener("click", scope.guard(async () => {
      const life = scope.capture();
      try {
        // D-596: Fleet picks the colour (the robot's own, or the one still free on its camera) and asks
        // a standing robot too; the robot is never moved.
        const started = await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/identify`, { method: "POST" });
        // The robot face says CALL <id> for the same window. The map chip names who was called.
        view.call = { robot_id: robot.robot_id, until: Date.now() + 6000 };
        render();
        log(`${robot.robot_id} LED 확인 중 · ${started.color === "blue" ? "파랑" : "주황"} 식별 조명 · 얼굴에 이름 표시`, "info");
        await new Promise((done) => setTimeout(done, 8500));  // 6 s window + Vision's verdict
        if (!life.current()) return;
        const readback = await call("/api/fleet/tracking/identity", { signals: [life.signal] });
        const row = (readback.robots || []).find((item) => item.robot_id === robot.robot_id);
        if (row?.state === "CONFIRMED") log(`${robot.robot_id} LED 확인됨 · 카메라 트랙에 이름을 붙였습니다`, "good");
        else {
          const lamp = row?.last?.lamp_reason;
          const why = lamp ? ` · ${LAMP_REASON[lamp] || lamp}` : "";
          log(`${robot.robot_id} LED 확인 실패 · ${IDENTIFY_REASON[row?.reason] || row?.reason || "판정 없음"}${why}`, "bad");
        }
      } catch (error) {
        if (error.name !== "AbortError") log(`${robot.robot_id} LED 확인 거부 · ${error.message}`, "bad");
      }
    }));
    const powerButton = createPowerButton({ robot, state, view, scope, call, log, isOperator, namedReason, blockWith });
    actions.append(aim, pin, trip.toggle(robot), cancel, identify, powerButton);
    if (address?.action === "move" && moveAddress) {
      // 기존 로봇별 "새 주소로 옮기기"를 그대로 부른다 — 확인 뒤 서버가 토큰으로 신원을 다시 읽는다.
      const move = document.createElement("ui-button");
      move.setAttribute("kind", "quiet");
      move.type = "button";
      move.dataset.moveRobotId = robot.robot_id;
      move.textContent = "새 주소로 옮기기…";
      blockWith(move, moveAddressBlocked());
      move.addEventListener("click", scope.guard(() => moveAddress(robot.robot_id)));
      actions.append(move);
    }
    node.appendChild(actions);
    const tripForm = view.stateUnavailable ? null : trip.section(robot);
    if (tripForm) node.appendChild(tripForm);
    if (goalSafetyReason) {
      const why = nodeWithText("p", "hint", goalSafetyReason);
      node.appendChild(why);
    }
    if (lineFollowActive) {
      const why = nodeWithText("p", "hint", "차선 추종 중에는 목표를 받지 않습니다 · 운행 취소로 차선 추종을 끈 뒤 목표를 지정하세요.");
      node.appendChild(why);
    }
    return node;
  }

  function openTripForm(robotId) {
    openCard(robotId);
    trip.focus(robotId);
  }

  function paintTrip(box, robotId) {
    const focused = document.activeElement;
    if (focused?.tagName === "SELECT" && box.contains(focused)) return;
    const robot = view.stateUnavailable ? null : view.robots.find(row => row.robot_id === robotId);
    const controls = () => [...box.querySelectorAll("ui-button, select")], at = controls().indexOf(focused);
    let section = robot ? trip.section(robot) : null;
    if (robot && !section) {
      trip.focus(robotId);
      section = trip.section(robot);
    }
    box.replaceChildren(...(section ? [section] : []));
    controls()[at]?.focus({preventScroll: true});
  }

  return { card, summary, workspace, place, fillQueues, queuedReason, needsAttention, attentionItems, openCard,
    syncConvoy: trip.syncConvoy, closeTrip: trip.close, openTrip: openTripForm, paintTrip };
}
