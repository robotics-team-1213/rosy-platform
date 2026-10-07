// 명렬 카드 + 큐 채우기 (Fleet 분해 3). 로봇 한 대의 상태·증거·조작과
// 주의/개입 큐를 그린다. formation/signals 팩토리와 같은 모양이다.

// D-359 §5.2 — 카드의 짧은 값은 공용 <ui-tag>다. 주행(nav)·도착(ok)은 색이 아니라
// ink인 active, 나머지는 태그의 warn/crit 어휘 그대로다.
import { MODE_LABEL, NAVIGATION_LABEL, enumLabel, EVIDENCE_LABEL } from "/common/core_ui_logic.js";
import { actionIcon } from "/common/ui.js";
import { addressReason } from "./address-drift.js";
import { linkTag } from "./link-tag.js";
import { localizationTag, localizationUrgent, untrustedQueuedReason } from "./localization-badge.js";
import { capabilityReason } from "./motion-readiness.js";
import { staleAgeS } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";

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

function blockWith(button, reason) {
  button.disabled = Boolean(reason);
  if (reason) button.setAttribute("reason", reason);
  else button.removeAttribute("reason");
}

export function createRoster({ scope, el, view, log, call, render, streamEvidence, isOperator,
  moveAddress = null, moveAddressBlocked = () => "", confirmedAction }) {
  // D-493 — 예외 큐와 로봇 카드의 "주의" 보기는 이 한 규칙을 쓴다. 카드에 빨간 표지가 붙은
  // 로봇이 큐에 없으면 "예외가 먼저"(D-201)가 거짓말이 된다(2026-10-07 회차: 릴레이 끊김).
  function attentionItems(robot) {
    const state = robot.state;
    // 2026-10-02 관제 회차 — 로봇 전원이 닿지 않아도 큐는 비어 있었다. 가장 흔한 예외부터 말한다.
    if (!robot.online) return [{ severity: "warn", text: `: ${EVIDENCE_LABEL.disconnected}` }];
    if (!state) return [{ severity: "warn", text: ": 상태 확인 불가" }];
    const items = [];
    const power = powerHealthView(robot, view.receivedAtMs, Date.now());
    if ("power_health" in robot && power.problem)
      items.push({ severity: "warn", text: `: ${power.problem}` });
    // D-407: 막힌 로봇이 답을 기다린다. 답하는 자리는 큐 아래 판단 요청이다.
    const staleS = staleAgeS(robot, view.receivedAtMs, Date.now());
    const staleNote = staleS === null ? "" : ` (상태 ${staleS}초 전 값)`;
    if (robot.line_stuck) items.push({ severity: "crit", text: `: 판단 요청 — 차선 추종이 막혔습니다${staleNote}` });
    if (localizationUrgent(robot.localization)) {
      // D-395 사다리 끝: Fleet이 스스로 위치를 못 잡았다. 사람만 풀 수 있다.
      items.push({ severity: "crit", text: ": 위치 확인 필요 — 로봇 위치를 직접 지정하세요" });
    } else if (state.hitl_requested === true) {
      // 개입 요청은 이름으로 알린다(Law 0). 원격 조종은 이 서버에 없는 능력이다 — 못 하는
      // 조작을 모의 버튼으로 걸면 경보가 거짓말을 한다(D-218, F-20). 진짜 개입은 로봇 화면에서.
      items.push({ severity: "crit", text: ": 개입 필요 — 로봇 화면에서 확인" });
    } else if (state.capabilities_degraded?.length) {
      items.push({ severity: "warn", text: `: 성능 저하 [${state.capabilities_degraded.join(", ")}]` });
    }
    const relay = streamEvidence(view.formation, robot.robot_id);
    if (relay && relay.cls) items.push({ severity: relay.cls === "crit" ? "crit" : "warn", text: `: ${relay.text}` });
    if (state.safety?.estop === true) items.push({ severity: "warn", text: ": 비상 정지 걸림 — 관리자가 해제해야 움직입니다" });
    else if (state.safety?.estop !== false) items.push({ severity: "warn", text: ": 정지 상태 미확인" });
    if (state.navigation === "FAILED") items.push({ severity: "warn", text: ": 목표 실패" });
    // D-511 M0: Fleet이 Rosy Cam 지도 자세로 본 차로 여유. 움직이는 로봇만 알린다(D-511 §2).
    // 알리기만 한다(보정·정지는 M1/M2). 여유가 음수면 몸체가 가장자리를 넘은 것이다.
    const lane = robot.lane_compliance;
    if (lane?.moving === true && typeof lane.margin_m === "number" && (lane.level === "WARN" || lane.level === "ACT")) {
      const cm = Math.round(Math.abs(lane.margin_m) * 100);
      const text = lane.margin_m < 0 ? `몸체가 가장자리를 ${cm} cm 넘음` : `여유 ${cm} cm`;
      items.push(lane.level === "ACT"
        ? { severity: "crit", text: `: 차로 이탈 — ${text}` }
        : { severity: "warn", text: `: 차로 가장자리 접근 — ${text}` });
    }
    if (robot.queued) items.push({ severity: "warn", text: ": 교통 대기" });
    if (robot.yielding) items.push({ severity: "warn", text: ": 양보 중" });
    if (staleS !== null) items.push({ severity: "warn", text: `: 상태 오래됨 — ${staleS}초 전 값` });
    return items;
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
    return { text: enumLabel(NAVIGATION_LABEL, nav), cls: "" };
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
    // D-82 로봇 사다리 — 지도 삼각형과 같은 색 순서(view.robots 인덱스)로 카드의
    // 정체 띠가 돈다. CSS 의 .s0/.s1/.s2 가 --robot-1..3 을 붙인다. 표시 순서가
    // 예외 우선으로 바뀌어도 색은 로봇에 붙어 있다.
    node.className = `robot s${index % view.colors.length}`;
    node.dataset.robotId = robot.robot_id;
    if (!view.stateUnavailable && !robot.online) node.classList.add("offline");
    if (view.selected === robot.robot_id) node.classList.add("selected");
    // D-224 — ↑/↓ 순회의 착지점. tabindex -1 은 프로그램 포커스만 허용한다
    // (탭 순서를 더럽히지 않는다).
    node.tabIndex = -1;

    const state = view.stateUnavailable ? {} : (robot.state || {});
    const pose = state.pose;
    const nav = navTag(state);
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
    robotName.textContent = robot.robot_id;
    const spacer = nodeWithText("span", "spacer");
    head.append(robotName, spacer);
    // D-359 US-009 — 모드 글은 공용 MODE_LABEL, 열거값은 title에만 둔다.
    const modeTag = tag(
      view.stateUnavailable ? "상태 확인 불가" : robot.online ? enumLabel(MODE_LABEL, state.mode) : "오프라인",
      view.stateUnavailable || !robot.online ? "crit" : "");
    if (!view.stateUnavailable && robot.online && state.mode) modeTag.title = state.mode;
    else if (!view.stateUnavailable && !robot.online) modeTag.title = "OFFLINE";
    head.appendChild(modeTag);
    const link = view.stateUnavailable ? null : linkTag(robot.link);
    if (link) {
      const linkNode = tag(link.word, link.kind);
      linkNode.dataset.link = robot.link;
      head.appendChild(linkNode);
    }
    const blocked = !view.stateUnavailable && robot.queued && robot.queued.reason === "NO_YIELD_SPACE";
    // 비켜서는 중인 로봇은 "주행 중"이 맞다 — 다만 제 미션을 가는 것이 아니라서 따로 적는다.
    head.appendChild(tag(
      view.stateUnavailable ? "—" : robot.yielding ? "비켜서는 중" : robot.queued ? "대기" : nav.text,
      blocked ? "crit" : robot.queued ? "warn" : nav.cls));
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
    node.appendChild(head);

    const facts = nodeWithText("div", "facts");
    const power = powerHealthView(robot, view.receivedAtMs, Date.now());
    const battery = power.battery;
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
      }
      cellEl.append(labelEl, valueEl);
      facts.appendChild(cellEl);
    });
    node.appendChild(facts);

    if (!view.stateUnavailable) {
      const when = typeof power.observedAgeS === "number" ? ` · 전원 근거 ${power.observedAgeS}초 전` : "";
      const charging = nodeWithText("p", "hint", `충전: ${power.charging}${when}`);
      charging.dataset.fact = "charging";
      node.appendChild(charging);
      if (power.problem) node.appendChild(nodeWithText("p", "hint", power.problem));
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
    blockWith(aim, view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online ? (offlineWhyId ? "위 사유" : "로봇 오프라인")
        : capabilityReason(robot.capabilities, "navigation.goal_navigation")
          || (!view.map ? "지도 없음"
          : estop === true ? "비상정지 중"
            : estop !== false ? "안전 상태 확인 불가"
              : lineFollowActive ? "라인 추종 중" : ""));
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
    const cancel = document.createElement("ui-button");
    cancel.setAttribute("kind", "quiet");
    cancel.type = "button";
    cancel.textContent = "취소";
    blockWith(cancel, view.stateUnavailable ? "Fleet 상태 확인 불가"
      : !robot.online ? (offlineWhyId ? "위 사유" : "로봇 오프라인") : "");
    if (offlineWhyId) cancel.setAttribute("aria-describedby", offlineWhyId);
    cancel.addEventListener("click", scope.guard(async () => {
      const life = scope.capture();
      life.check();
      try {
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
        log(`${robot.robot_id} 항법 취소`, "good");
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
      fallback.textContent = lineFollow.mode === "IR_LINE" ? "IR 추적 중지" : "IR 추적 선택";
      blockWith(fallback, view.stateUnavailable ? "Fleet 상태 확인 불가"
        : !robot.online ? "로봇 오프라인"
          : !isOperator() ? "운영자 권한이 필요합니다" : "");
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
          log(`${robot.robot_id} ${mode === "IR_LINE" ? "IR 추적 요청" : "IR 추적 중지"} · ${result.result?.state || "CORE 응답 확인"}`, "good");
        };
        const fail = err => log(`${robot.robot_id} IR 추적 거부 · ${err.message}`, "bad");
        if (mode === "OFF") {
          confirmedAction.cancel(kind);
          try { await send(life); } catch (err) { if (life.current() && err.name !== "AbortError") fail(err); }
          return;
        }
        await confirmedAction.run({kind, message: `${robot.robot_id}의 카메라 고장이 확인되었습니다. CORE 안전 조건을 다시 확인하고 IR 추적을 요청할까요?`, opener: fallback,
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
    actions.append(aim, cancel, identify);
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
    if (goalSafetyReason) {
      const why = nodeWithText("p", "hint", goalSafetyReason);
      node.appendChild(why);
    }
    if (lineFollowActive) {
      const why = nodeWithText("p", "hint", "선택된 line-follow가 CORE motion을 소유합니다. 먼저 중지해야 Nav2 목표를 받을 수 있습니다.");
      node.appendChild(why);
    }
    return node;
  }

  // D-252: 큐 머리는 ui-triage. <b>는 범주+개수, <small>은 이름들이다. 행은 그대로 둔다.
  function setTriageHead(id, label, list) {
    const head = el(id);
    if (!head) return;
    const names = [...new Set([...list.querySelectorAll("li b")].map((b) => b.textContent))];
    head.querySelector("b").textContent = `${label} ${names.length}`;
    head.querySelector("small").textContent = names.join(" · ");
  }

  function fillQueues() {
    // ADR-1000: Populate Queues
    const warnList = el("warning-list");
    const critList = el("critical-list");
    warnList.innerHTML = "";
    critList.innerHTML = "";

    let warningCount = 0;
    let criticalCount = 0;

    const queueItem = (robotId, text) => {
      const li = document.createElement("li");
      const name = document.createElement("b");
      name.textContent = robotId;
      li.append(name, document.createTextNode(text));
      return li;
    };

    for (const r of view.stateUnavailable ? [] : view.robots) {
      for (const item of attentionItems(r)) {
        if (item.severity === "crit") {
          critList.appendChild(queueItem(r.robot_id, item.text));
          criticalCount++;
        } else {
          warnList.appendChild(queueItem(r.robot_id, item.text));
          warningCount++;
        }
      }
    }
    setTriageHead("warning-head", "주의 요망", warnList);
    setTriageHead("critical-head", "최우선 개입 요망", critList);

    // ADR-1000 & UX Law 1: Hide empty queues to prevent alarm colors in normal state.
    // CSP `style-src 'self'` 는 style 속성을 막으므로 hidden 속성으로 토글한다
    // (D-201 회차 계측에서 style.display 토글이 실서버에서는 무시됨을 확인).
    warnList.parentElement.hidden = warningCount === 0;
    critList.parentElement.hidden = criticalCount === 0;
    document.querySelector(".queues-panel").hidden = (warningCount + criticalCount) === 0;
  }

  return { card, fillQueues, queuedReason, needsAttention, attentionItems };
}
