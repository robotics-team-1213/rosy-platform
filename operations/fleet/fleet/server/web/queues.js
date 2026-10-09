// 예외 큐 (Fleet 분해 3에서 roster.js로부터 옮김, D-540 단계 (d) 크기 재판정). 주의/개입 큐의
// 규칙(attentionItems, D-493 한 규칙)과 행 채우기, 큐 펼침의 버튼 헬퍼를 가진다. 카드는 roster.js다.
import { BATTERY_LEVEL_LABEL, DOCK_STATE_LABEL, EVIDENCE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { localizationUrgent } from "./localization-badge.js";
import { staleAgeS } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { trafficAttention, tripEndText } from "/console/assets/site-map-model.js";
import { guideAttention } from "/console/assets/guide-layer.js";

function nodeWithText(tagName, className = "", text) {
  const node = document.createElement(tagName);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** A row's text after its robot name. Rows read "<b>rosy_41</b>: …"; a later row of the same robot hides the
 * name, so it drops the leading ": " (field check 2026-10-10: ": Rosy Cam이 …" with no name). */
export function queueRowText(text, named) {
  return named ? text : text.replace(/^:\s*/, "");
}

/** D-540 3: the queue row open on its decision. The operator's last pick holds while that row lives;
 * otherwise the most urgent decision row (critical first) is open. */
export function openDecisionKey(keys, choice) {
  if (choice && keys.includes(choice.key)) return choice.open ? choice.key : null;
  return keys[0] ?? null;
}

// D-540 3 — a disclosure (queue row, folded card line, fold) shows and hides; it never moves a robot.
export function disclosure(className, expanded, onClick) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  node.setAttribute("aria-expanded", String(expanded));
  node.addEventListener("click", onClick);
  return node;
}

// 계약(D-359 §5.2)은 버튼마다 글자 kind 를 요구한다 — 변수 kind 헬퍼는 정적 검사가
// 못 본다. 종류별 헬퍼가 리터럴을 담는다.
export function quietButton(text) {
  const node = document.createElement("ui-button");
  node.setAttribute("kind", "quiet");
  node.type = "button";
  node.textContent = text;
  return node;
}

export function primaryButton(text) {
  const node = document.createElement("ui-button");
  node.setAttribute("kind", "primary");
  node.type = "button";
  node.textContent = text;
  return node;
}

export function setReason(node, reason) {
  node.disabled = Boolean(reason);
  if (reason) node.setAttribute("reason", reason);
  else node.removeAttribute("reason");
}

/** The robot's open trip as the console last read it, or null. */
export function openTrip(view, robotId) {
  return (view.trafficTrips || []).find((trip) => trip.robot_id === robotId) || null;
}

/** Why the robot's last trip stopped or failed ('' while a trip is open or the last one arrived or was canceled). */
export function endedTripText(view, robotId) {
  if (openTrip(view, robotId)) return "";
  return tripEndText((view.endedTrips || []).find((trip) => trip.robot_id === robotId));
}

// D-577 8: an escalated stuck nobody answered within this many seconds rises to the top. The robot
// keeps holding; nothing moves on silence. Console only — no phone or messenger alert (user, 2026-10-09).
const HUMAN_DEADLINE_S = 30;

function stuckOverdue(stuck) {
  const note = stuck && stuck.resolver;
  return Boolean(note && note.escalated && note.escalated !== "human_claimed"
    && typeof note.age_s === "number" && note.age_s >= HUMAN_DEADLINE_S);
}

export function createQueues({ scope, el, view, render, streamEvidence }) {
  // D-493 — 예외 큐와 로봇 카드의 "주의" 보기는 이 한 규칙을 쓴다. 카드에 빨간 표지가 붙은
  // 로봇이 큐에 없으면 "예외가 먼저"(D-201)가 거짓말이 된다(2026-10-07 회차: 릴레이 끊김).
  function attentionItems(robot) {
    const state = robot.state;
    // D-407 / D-540 3: a stuck robot waits for an answer; the row opens into its decision. An offline
    // robot keeps the row (last value, answers locked) so the question does not vanish with the link.
    const staleS = staleAgeS(robot, view.receivedAtMs, Date.now());
    const staleNote = staleS === null ? "" : ` (상태 ${staleS}초 전 값)`;
    const overdue = stuckOverdue(robot.line_stuck);
    const stuck = robot.line_stuck
      ? [{ severity: "crit", decision: "stuck", overdue,
           text: overdue ? `: 판단 요청 — 30초 넘게 답 없음, 로봇은 멈춰 기다립니다${staleNote}`
             : `: 판단 요청 — 차선 추종이 막혔습니다${staleNote}` }] : [];
    // 2026-10-02 관제 회차 — 로봇 전원이 닿지 않아도 큐는 비어 있었다. 가장 흔한 예외부터 말한다.
    if (!robot.online && robot.link === "degraded") return [{ severity: "warn", text: ": 응답 지연" }, ...stuck];
    if (!robot.online) return [{ severity: "warn", text: `: ${EVIDENCE_LABEL.disconnected}` }, ...stuck];
    if (!state) return [{ severity: "warn", text: ": 상태 확인 불가" }, ...stuck];
    const items = [];
    const level = state.battery_status?.level;
    if (level && level !== "ok") {
      const severe = level === "critical" || level === "deep";
      items.push({ severity: severe ? "crit" : "warn", text: `: ${enumLabel(BATTERY_LEVEL_LABEL, level)}` });
    }
    if (state.docking?.state === "DOCK_FAILED")
      items.push({ severity: "warn", text: `: ${enumLabel(DOCK_STATE_LABEL, "DOCK_FAILED")}` });
    const power = powerHealthView(robot, view.receivedAtMs, Date.now());
    if ("power_health" in robot && power.problem)
      items.push({ severity: "warn", text: `: ${power.problem}` });
    items.push(...stuck);
    // D-494 5 / D-540 3: a trip held at a place for a changed route waits for the operator's confirm.
    if ((view.trafficTrips || []).some((trip) => trip.robot_id === robot.robot_id && trip.hold)) {
      items.push({ severity: "crit", text: ": 바뀐 경로 확인 — 운행이 장소에서 기다립니다", decision: "replan" });
    }
    // D-540 (d): a trip Fleet stopped (lease lost, stall, junction …) until the robot's next trip; not arrive/cancel.
    const ended = endedTripText(view, robot.robot_id);
    if (ended) items.push({ severity: "warn", text: `: ${ended}` });
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
    // D-517 10: 교착·30 s 넘는 위치 불명·긴 합류 대기·고리 수용 초과. 블록 대기 자체는 정상이라 행이 아니다.
    items.push(...trafficAttention(view.traffic, robot.robot_id, view.trafficClock, Date.now()));
    items.push(...guideAttention(view.guide, robot.robot_id));  // D-536 coordinate guides
    if (robot.queued) items.push({ severity: "warn", text: ": 교통 대기" });
    if (robot.yielding) items.push({ severity: "warn", text: ": 양보 중" });
    if (staleS !== null) items.push({ severity: "warn", text: `: 상태 오래됨 — ${staleS}초 전 값` });
    return items;
  }
  // Clock-like digits ("3초 전") are not a new exception.
  function attentionKey(robot) {
    return view.stateUnavailable ? "" : attentionItems(robot).map((item) => item.text.replace(/\d+/g, "#")).join("|");
  }
  // D-252: 큐 머리는 ui-triage. <b>는 범주+개수, <small>은 이름들이다. 행은 그대로 둔다.
  function setTriageHead(id, label, list) {
    const head = el(id);
    if (!head) return;
    const names = [...new Set([...list.querySelectorAll("li b")].map((b) => b.textContent))];
    head.querySelector("b").textContent = `${label} ${names.length}`;
    head.querySelector("small").textContent = names.join(" · ");
  }

  // D-540 3 — a row with a decision opens in place, one at a time: the operator's pick, else the most
  // urgent decision row. Rows are kept by key so a 1 s poll never drops focus or a confirm step.
  function syncRows(list, rows, open) {
    const old = new Map([...list.children].map((node) => [node.dataset.key, node]));
    const nodes = rows.map((row, index) => {
      const named = index === 0 || rows[index - 1].robotId !== row.robotId;  // the name once per robot
      let li = old.get(row.key);
      if (!li || li.dataset.decision !== (row.decision || "")) {
        li = document.createElement("li");
        li.dataset.key = row.key;
        li.dataset.decision = row.decision || "";
        const line = row.decision ? disclosure("queue-row", false, scope.guard(() => {
          view.queueChoice = { key: row.key, open: line.getAttribute("aria-expanded") !== "true" };
          render();
        })) : li;
        if (row.decision) {
          const body = nodeWithText("div", "queue-decision");
          body.id = `decision-${row.key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
          body.dataset.decisionSlot = row.key;
          line.setAttribute("aria-controls", body.id);
          li.append(line, body);
        }
        line.append(document.createElement("b"), nodeWithText("span", "queue-text"));
      }
      const line = row.decision ? li.firstElementChild : li;
      const name = line.querySelector("b");
      name.textContent = row.robotId;
      name.className = named ? "" : "sr-only";
      const text = line.querySelector(".queue-text");
      const shown = queueRowText(row.text, named);
      if (text.textContent !== shown) text.textContent = shown;
      if (row.decision) {
        line.setAttribute("aria-expanded", String(open === row.key));
        li.lastElementChild.hidden = open !== row.key;
      }
      return li;
    });
    if (nodes.length !== list.children.length || nodes.some((node, i) => list.children[i] !== node)) {
      list.replaceChildren(...nodes);
    }
  }

  function fillQueues() {
    // ADR-1000: Populate Queues
    const warnList = el("warning-list");
    const critList = el("critical-list");
    const rows = { crit: [], warn: [] };
    for (const r of view.stateUnavailable ? [] : view.robots) {
      for (const item of attentionItems(r)) {
        const list = item.severity === "crit" ? rows.crit : rows.warn;
        const key = `${r.robot_id}|${item.decision || list.length}`;
        list.push({ ...item, robotId: r.robot_id, key });
      }
    }
    rows.crit.sort((a, b) => Number(Boolean(b.overdue)) - Number(Boolean(a.overdue)));   // stable: overdue first
    const decisions = [...rows.crit, ...rows.warn].filter((row) => row.decision).map((row) => row.key);
    const open = openDecisionKey(decisions, view.queueChoice);
    syncRows(critList, rows.crit, open);
    syncRows(warnList, rows.warn, open);
    setTriageHead("warning-head", "주의 요망", warnList);
    setTriageHead("critical-head", "최우선 개입 요망", critList);

    // ADR-1000 & UX Law 1: Hide empty queues to prevent alarm colors in normal state.
    // CSP `style-src 'self'` 는 style 속성을 막으므로 hidden 속성으로 토글한다
    // (D-201 회차 계측에서 style.display 토글이 실서버에서는 무시됨을 확인).
    warnList.parentElement.hidden = rows.warn.length === 0;
    critList.parentElement.hidden = rows.crit.length === 0;
    document.querySelector(".queues-panel").hidden = (rows.warn.length + rows.crit.length) === 0;
  }

  return { attentionItems, attentionKey, fillQueues };
}
