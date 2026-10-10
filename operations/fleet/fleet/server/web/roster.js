// 명렬 카드 (Fleet 분해 3). 로봇 한 대의 상태·증거·조작을 그린다. 주의/개입 큐는 queues.js가
// 가지고, 이 팩토리가 그 규칙(attentionItems)을 카드 펼침에 같이 쓴다. formation/signals 팩토리와 같은 모양이다.

// D-359 §5.2 — 카드의 짧은 값은 공용 <ui-tag>다. 주행(nav)·도착(ok)은 색이 아니라
// ink인 active, 나머지는 태그의 warn/crit 어휘 그대로다.
import { NAVIGATION_LABEL, DOCK_STATE_LABEL, POWER_MODE_LABEL, LINE_FOLLOW_MODE_LABEL, LINE_STATE_LABEL,
  enumLabel, operatorModeLabel, EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { actionIcon } from "/common/ui.js";
import { addressReason } from "/console/assets/address-drift.js";
import { linkTag } from "./link-tag.js";
import { localizationTag, untrustedQueuedReason } from "./localization-badge.js";
import { capabilityReason } from "./motion-readiness.js";
import { staleAgeS } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { createQueues, disclosure } from "./queues.js";
import { cancelScope, cardTripLine, createCardTrip, openTrip } from "./card-trip.js";

const TAG_STATUS = { nav: "active", ok: "active", warn: "warn", crit: "crit" };

// console_view._error_of 는 닿지 못한 예외를 클래스 이름(code)으로 싣는다. 운영자 말은
// 한국어 평문이다 — 아는 코드만 옮기고 모르는 값은 받은 그대로 보인다(2026-10-02 회차).
const REACH_LABEL = Object.freeze({
  ConnectError: "접속 실패",
  ConnectTimeout: "접속 시간 초과",
  TimeoutException: "응답 시간 초과",
  ReadTimeout: "응답 시간 초과",
});

function nodeWithText(tagName, className = "", text) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function tag(text, cls) {
  const node = document.createElement("ui-tag");
  node.setAttribute("status", TAG_STATUS[cls] || "neutral");
  node.textContent = text;
  return node;
}

/** D-540 3: a card stays open whatever the operator chose while the robot is offline (no link or no
 * state), its E-stop is latched, its safety state is not nominal, or a calibration lease holds it. */
export function mustExpand(robot) {
  const estop = robot.state?.safety?.estop;
  return !robot.online || !robot.state || estop !== false || Boolean(robot.calibration);
}

/** D-540 3: open on an exception or selection, one line when nominal; the operator's fold or unfold
 * holds until the robot's exceptions change. `attention` is the exception key ("" when nominal). */
export function cardExpanded({ must, selected, attention, choice }) {
  if (must || selected) return true;
  if (choice && choice.attention === attention) return choice.open;
  return attention !== "";
}

function blockWith(button, reason) {
  button.disabled = Boolean(reason);
  if (reason) button.setAttribute("reason", reason);
  else button.removeAttribute("reason");
}

export function createRoster({ scope, el, view, log, call, render, streamEvidence, isOperator, namedReason = () => "",
  moveAddress = null, moveAddressBlocked = () => "", confirmedAction }) {
  const { attentionItems, attentionKey, fillQueues } = createQueues({ scope, el, view, render, streamEvidence });
  const trip = createCardTrip({ scope, el, view, call, log, render, isOperator, namedReason });
  function openCard(robotId) {
    const robot = view.robots.find((row) => row.robot_id === robotId);
    if (robot) view.cardChoice = { ...view.cardChoice, [robotId]: { open: true, attention: attentionKey(robot) } };
  }
  function needsAttention(robot) {
    return view.stateUnavailable || attentionItems(robot).length > 0;
  }
  function navTag(state) {
    const nav = state && state.navigation;
    if (!nav) return { text: "—", cls: "" };
    if (nav === "NAVIGATING") {
      return { text: state.safety?.estop === false ? "목표 활성" : "목표 남음", cls: "nav" };
    }
    if (nav === "ARRIVED") return { text: enumLabel(NAVIGATION_LABEL, nav), cls: "ok" };
    if (nav === "FAILED") return { text: enumLabel(NAVIGATION_LABEL, nav), cls: "crit" };
    // IDLE 항법은 "대기"라서 모드 태그의 "대기"와 겹친다. 카드에서는 목표가 없다고 말한다.
    return { text: nav === "IDLE" ? "목표 없음" : enumLabel(NAVIGATION_LABEL, nav), cls: "" };
  }

  // 대기에는 세 가지 이유가 있고, 운영자가 할 일이 저마다 다르다. "대기 중" 한 마디로
  // 뭉뜽그리면, 손대야 풀리는 상황에서도 사람이 저절로 풀리기를 기다린다.
  function queuedReason(queued) {
    const who = queued.blocked_by;
    if (queued.reason === "NO_YIELD_SPACE") {
      return `${who} 가 길을 막았는데 비켜설 자리가 없습니다 — 맵이 좁습니다. `
        + `${who} 를 직접 다른 곳으로 보내 주세요`;
    }
    if (queued.reason === "YIELDING") {
      return `${who} 가 비켜서기를 기다리는 중 — 물러나면 자동 출발합니다`;
    }
    if (queued.reason === "LOCALIZATION_UNTRUSTED") return untrustedQueuedReason(who);
    if (queued.reason === "YIELDED") {
      return `${who} 가 지나가기를 기다리는 중 — 지나가면 제 미션으로 돌아갑니다`;
    }
    return `${who} 경로와 겹쳐 대기 중 — 앞이 비면 자동 출발합니다`;
  }

  function card(robot, index) {
    const node = document.createElement("article");
    const displayName = view.robotNames?.[robot.robot_id] || robot.robot_id;
    // D-82 로봇 사다리 — 지도 삼각형과 같은 색 순서(view.robots 인덱스)로 카드의
    // 정체 띠가 돈다. CSS 의 .s0/.s1/.s2 가 --robot-1..3 을 붙인다. 표시 순서가
    // 예외 우선으로 바뀌어도 색은 로봇에 붙어 있다.
    node.className = `robot s${index % view.colors.length}`;
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
    // D-540 3: one line when nominal; the four must-expand states keep the card open.
    const attention = attentionKey(robot);
    const must = view.stateUnavailable || mustExpand(robot);
    const selected = view.selected === robot.robot_id;
    const fold = (open) => scope.guard(() => {
      view.cardChoice = { ...view.cardChoice, [robot.robot_id]: { open, attention } };
      render();
    });
    const tripLine = view.stateUnavailable ? "" : cardTripLine(view, robot.robot_id);
    if (!cardExpanded({ must, selected, attention, choice: view.cardChoice?.[robot.robot_id] })) {
      node.dataset.collapsed = "";
      const line = disclosure("robot-line", false, fold(true));
      line.title = "카드 펼치기";
      const battery = nodeWithText("span", "robot-line-battery");
      battery.dataset.fact = "battery";
      battery.append(nodeWithText("span", "sr-only", "배터리 "),
        nodeWithText("strong", "", powerHealthView(robot, view.receivedAtMs, Date.now()).battery));
      line.append(nodeWithText("b", "", displayName),
        nodeWithText("span", "trip-line", tripLine || (robot.yielding ? "비켜서는 중" : nav.text)), battery);
      if (displayName !== robot.robot_id) line.title = `Fleet ID ${robot.robot_id}`;
      node.appendChild(line);
      return node;
    }
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
    // D-359 US-009 / D-540 6 — 모드 글은 공용 표, 열거값은 title에만 둔다. 차선 추종이 켜져 있으면 그것이
    // 로봇을 움직이는 모드라서 CORE 모드(대개 IDLE "대기") 대신 차선 추종 방식을 말한다.
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
        const powerTag = tag(enumLabel(POWER_MODE_LABEL, powerMode), "");
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
    const loc = view.stateUnavailable ? null : localizationTag(robot.localization);
    if (loc) {
      // D-395: 위치 확정 상태. 서버 문구를 그대로 쓰고 열거값은 title에만 둔다.
      const locTag = tag(loc.text, loc.cls);
      locTag.title = loc.title;
      locTag.dataset.localization = "";
      head.appendChild(locTag);
    }
    if (!must && !selected) {
      const shut = disclosure("robot-fold", true, fold(false));
      shut.textContent = "접기";
      shut.setAttribute("aria-label", `${robot.robot_id} 카드 접기`);
      head.appendChild(shut);
    }
    node.appendChild(head);
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
      ["pose", "위치", pose ? `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}` : "—"],
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
      facts.appendChild(cellEl);
    });
    node.appendChild(facts);

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
        const next = document.createElement("button");
        next.type = "button";
        next.textContent = link.next;
        next.addEventListener("click", scope.guard(() => {
          document.getElementById("console-token")?.focus();
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
        : capabilityReason(robot.capabilities, "navigation.goal_navigation")
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
      else [...document.querySelectorAll("#roster ui-button[data-goal-robot-id]")]
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
        : !view.map ? "지도 없음" : openTrip(view, robot.robot_id) ? "운행 중" : ""));
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
      try {
        const sortedIds = view.robots.map((row) => row.robot_id).sort();
        const color = sortedIds.indexOf(robot.robot_id) % 2 === 0 ? "blue" : "amber";
        await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/identify`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ color }),
        });
        // The robot face says CALL <id> for the same window. The map chip names who was called.
        view.call = { robot_id: robot.robot_id, until: Date.now() + 6000 };
        render();
        log(`${robot.robot_id} 호출 · ${color === "blue" ? "파랑" : "주황"} LED · 얼굴에 이름 표시`, "info");
      } catch (error) { log(`${robot.robot_id} LED 시험 거부 · ${error.message}`, "bad"); }
    }));
    actions.append(aim, pin, trip.toggle(robot), cancel, identify);
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

  // D-540 (d): a card whose picker has focus stays where it is — a rebuilt <select> closes its list mid-pick.
  function place(box, cards) {
    const keep = document.activeElement?.tagName === "SELECT" ? document.activeElement.closest("#roster article") : null;
    const nodes = cards.map((node) => (keep && node.dataset.robotId === keep.dataset.robotId ? keep : node));
    if (!nodes.includes(keep)) { box.replaceChildren(...nodes); return; }
    for (const node of [...box.children]) if (node !== keep) node.remove();
    nodes.forEach((node, i) => { if (box.children[i] !== node) box.insertBefore(node, box.children[i] || null); });
  }

  return { card, place, trip, fillQueues, queuedReason, needsAttention, attentionItems, openCard };
}
